from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class Settings:
    images_dir: Path
    docker_binary: str
    cleanup_local_image_on_cancel: bool
    download_chunk_size: int
    max_task_log_lines: int
    archive_storage_limit_bytes: int


def _get_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized_value = raw_value.strip().lower()
    if normalized_value in {"1", "true", "yes", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "off"}:
        return False

    return default


def _build_settings() -> Settings:
    images_dir = Path(os.getenv("IMAGE_STORAGE_DIR", "./images")).resolve()
    docker_binary = os.getenv("DOCKER_BIN", "docker")
    cleanup_local_image_on_cancel = _get_bool_env(
        "CLEANUP_LOCAL_IMAGE_ON_CANCEL",
        True,
    )
    download_chunk_size = int(os.getenv("DOWNLOAD_CHUNK_SIZE", str(1024 * 1024)))
    max_task_log_lines = int(os.getenv("MAX_TASK_LOG_LINES", "500"))
    archive_storage_limit_bytes = int(
        os.getenv("ARCHIVE_STORAGE_LIMIT_BYTES", str(10 * 1024 * 1024 * 1024))
    )

    return Settings(
        images_dir=images_dir,
        docker_binary=docker_binary,
        cleanup_local_image_on_cancel=cleanup_local_image_on_cancel,
        download_chunk_size=download_chunk_size,
        max_task_log_lines=max_task_log_lines,
        archive_storage_limit_bytes=archive_storage_limit_bytes,
    )


settings = _build_settings()


def ensure_images_dir() -> Path:
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    return settings.images_dir
