from __future__ import annotations

import asyncio
import os
import re
import shutil
from asyncio.subprocess import PIPE
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from backend.config import ensure_images_dir, settings
from backend.models import (
    PullImageAcceptedResponse,
    TaskState,
    TaskStatusResponse,
)

TASKS: dict[str, "TaskRecord"] = {}

IMAGE_NAME_RE = re.compile(
    r"^(?=.{1,255}$)"
    r"(?:[a-zA-Z0-9.-]+(?::[0-9]+)?/)?"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
    r"(?::[\w][\w.-]{0,127})?"
    r"(?:@sha256:[A-Fa-f0-9]{64})?$"
)


class InvalidImageNameError(ValueError):
    """Raised when the requested Docker image reference is malformed."""


class TaskNotFoundError(KeyError):
    """Raised when a task ID does not exist in memory."""


class DiskSpaceError(RuntimeError):
    """Raised when there is not enough disk space to save an image."""


class DockerCommandError(RuntimeError):
    def __init__(
        self,
        command: Iterable[str],
        return_code: int,
        stdout: str,
        stderr: str,
    ) -> None:
        self.command = list(command)
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr

        output = stderr.strip() or stdout.strip() or "No output captured."
        super().__init__(output)


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    image: str
    status: TaskState
    filename: str | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)


def submit_pull_task(image: str) -> PullImageAcceptedResponse:
    normalized_image = image.strip()
    if not IMAGE_NAME_RE.fullmatch(normalized_image):
        raise InvalidImageNameError(
            "Invalid Docker image name. Example format: nginx:latest"
        )

    task_id = uuid4().hex
    task = TaskRecord(task_id=task_id, image=normalized_image, status="pending")
    _append_log(task, f"Task accepted for image '{normalized_image}'.")
    TASKS[task_id] = task
    asyncio.create_task(_pull_and_save_image(task))

    return PullImageAcceptedResponse(
        task_id=task_id,
        status="pending",
        image=normalized_image,
    )


def get_task_status(task_id: str) -> TaskStatusResponse:
    task = TASKS.get(task_id)
    if task is None:
        raise TaskNotFoundError(task_id)

    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        image=task.image,
        filename=task.filename,
        error=task.error,
        logs=list(task.logs),
    )


async def _pull_and_save_image(task: TaskRecord) -> None:
    task.status = "running"
    output_path: Path | None = None

    try:
        _append_log(task, "Running docker pull.")
        await _run_command(
            [settings.docker_binary, "pull", task.image],
            task=task,
            step_name="pull",
        )

        output_path = _reserve_output_path(task.image, task.task_id)
        await _ensure_sufficient_disk_space(task.image, task)

        _append_log(task, f"Saving image archive to '{output_path.name}'.")
        await _run_command(
            [settings.docker_binary, "save", "-o", str(output_path), task.image],
            task=task,
            step_name="save",
        )

        task.filename = output_path.name
        task.status = "success"
        _append_log(task, f"Image saved successfully as '{output_path.name}'.")
    except InvalidImageNameError as exc:
        task.status = "failed"
        task.error = str(exc)
        _append_log(task, task.error)
    except DiskSpaceError as exc:
        task.status = "failed"
        task.error = str(exc)
        _append_log(task, task.error)
    except DockerCommandError as exc:
        task.status = "failed"
        task.error = _format_docker_command_error(task.image, exc)
        _append_log(task, task.error)
    except FileNotFoundError:
        task.status = "failed"
        task.error = (
            f"Docker executable '{settings.docker_binary}' was not found on the server."
        )
        _append_log(task, task.error)
    except Exception as exc:  # pragma: no cover - defensive fallback
        import traceback
        task.status = "failed"
        task.error = f"Unexpected error while processing image '{task.image}': {exc}"
        task.logs.append(traceback.format_exc())
        _append_log(task, task.error)
    finally:
        if task.status != "success" and output_path is not None:
            output_path.unlink(missing_ok=True)


async def _ensure_sufficient_disk_space(image: str, task: TaskRecord) -> None:
    size_bytes = await _inspect_image_size(image, task)
    free_bytes = shutil.disk_usage(ensure_images_dir()).free
    safety_buffer = 50 * 1024 * 1024
    required_bytes = size_bytes + safety_buffer

    if free_bytes < required_bytes:
        raise DiskSpaceError(
            "Insufficient disk space to save the Docker image. "
            f"Required about {_format_bytes(required_bytes)}, "
            f"available {_format_bytes(free_bytes)}."
        )

    _append_log(
        task,
        "Disk space check passed: "
        f"{_format_bytes(free_bytes)} free, archive estimate {_format_bytes(size_bytes)}.",
    )


async def _inspect_image_size(image: str, task: TaskRecord) -> int:
    stdout, _ = await _run_command(
        [settings.docker_binary, "image", "inspect", "--format={{.Size}}", image],
        task=task,
        step_name="inspect",
    )
    inspected_size = stdout.strip()

    try:
        return int(inspected_size)
    except ValueError as exc:
        raise RuntimeError(
            f"Could not determine image size for '{image}'. Docker returned: {inspected_size}"
        ) from exc


async def _run_command(
    command: list[str],
    *,
    task: TaskRecord,
    step_name: str,
) -> tuple[str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=PIPE,
        stderr=PIPE,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    await asyncio.gather(
        _read_stream(process.stdout, stdout_lines, task, step_name),
        _read_stream(process.stderr, stderr_lines, task, step_name),
    )
    return_code = await process.wait()

    stdout = "\n".join(stdout_lines).strip()
    stderr = "\n".join(stderr_lines).strip()

    if return_code != 0:
        raise DockerCommandError(command, return_code, stdout, stderr)

    return stdout, stderr


async def _read_stream(
    stream: asyncio.StreamReader | None,
    sink: list[str],
    task: TaskRecord,
    step_name: str,
) -> None:
    if stream is None:
        return

    while True:
        line = await stream.readline()
        if not line:
            break

        text = line.decode("utf-8", errors="replace").rstrip()
        if not text:
            continue

        sink.append(text)
        _append_log(task, f"[{step_name}] {text}")


def _format_docker_command_error(image: str, error: DockerCommandError) -> str:
    output = error.stderr.lower() or error.stdout.lower()

    if "no space left on device" in output or "not enough space" in output:
        return (
            "Insufficient disk space while saving the Docker image. "
            "Free up space and try again."
        )

    if "not found" in output or "pull access denied" in output:
        return (
            f"Docker could not pull image '{image}'. "
            "Check that the image exists and is accessible."
        )

    return (
        f"Docker command failed for image '{image}' "
        f"with exit code {error.return_code}: {error}"
    )


def _reserve_output_path(image: str, task_id: str) -> Path:
    image_dir = ensure_images_dir()
    base_name = _image_to_filename_base(image)
    candidates = [
        image_dir / f"{base_name}.tar",
        image_dir / f"{base_name}_{task_id[:8]}.tar",
    ]

    for candidate in candidates:
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return candidate
        except FileExistsError:
            continue

    counter = 1
    while True:
        candidate = image_dir / f"{base_name}_{task_id[:8]}_{counter}.tar"
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return candidate
        except FileExistsError:
            counter += 1


def list_saved_images() -> list[dict[str, object]]:
    image_dir = ensure_images_dir()
    items: list[dict[str, object]] = []

    archives = sorted(
        image_dir.glob("*.tar"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )

    for path in archives:
        stat = path.stat()
        items.append(
            {
                "filename": path.name,
                "size_bytes": stat.st_size,
                "saved_at": stat.st_mtime,
            }
        )

    return items


def resolve_image_archive(filename: str) -> Path:
    if Path(filename).name != filename or not filename.endswith(".tar"):
        raise FileNotFoundError("Only .tar archive filenames are allowed.")

    image_dir = ensure_images_dir()
    candidate = (image_dir / filename).resolve()

    if candidate.parent != image_dir:
        raise FileNotFoundError("Invalid archive path.")

    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Image archive '{filename}' does not exist.")

    return candidate


def delete_image_archive(filename: str) -> None:
    archive_path = resolve_image_archive(filename)
    archive_path.unlink(missing_ok=False)


def _image_to_filename_base(image: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", image)
    sanitized = re.sub(r"_+", "_", sanitized).strip("._")
    return sanitized or "image"


def _append_log(task: TaskRecord, message: str) -> None:
    task.logs.append(message)
    overflow = len(task.logs) - settings.max_task_log_lines
    if overflow > 0:
        del task.logs[:overflow]


def _format_bytes(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)

    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024

    return f"{size_bytes} B"
