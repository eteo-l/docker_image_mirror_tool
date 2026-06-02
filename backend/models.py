from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TaskState = Literal["pending", "running", "success", "failed", "cancelled"]


class PullImageRequest(BaseModel):
    image: str = Field(..., min_length=1, examples=["nginx:latest"])


class PullImageAcceptedResponse(BaseModel):
    task_id: str
    status: Literal["pending"]
    image: str


class ImageFileInfo(BaseModel):
    filename: str
    size_bytes: int
    saved_at: datetime


class ImageListResponse(BaseModel):
    images: list[ImageFileInfo]


class DeleteImageResponse(BaseModel):
    filename: str
    deleted: bool


class DeleteTaskResponse(BaseModel):
    task_id: str
    deleted: bool


class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskState
    image: str
    filename: str | None = None
    error: str | None = None
    logs: list[str] = Field(default_factory=list)
