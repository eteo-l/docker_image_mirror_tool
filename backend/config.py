from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class Settings:
    images_dir: Path
    docker_binary: str
    download_chunk_size: int
    max_task_log_lines: int


def _build_settings() -> Settings:
    images_dir = Path(os.getenv("IMAGE_STORAGE_DIR", "./images")).resolve()
    docker_binary = os.getenv("DOCKER_BIN", "docker")
    download_chunk_size = int(os.getenv("DOWNLOAD_CHUNK_SIZE", str(1024 * 1024)))
    max_task_log_lines = int(os.getenv("MAX_TASK_LOG_LINES", "500"))

    return Settings(
        images_dir=images_dir,
        docker_binary=docker_binary,
        download_chunk_size=download_chunk_size,
        max_task_log_lines=max_task_log_lines,
    )


settings = _build_settings()


def ensure_images_dir() -> Path:
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    return settings.images_dir
