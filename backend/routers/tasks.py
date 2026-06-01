from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from backend.models import TaskStatusResponse
from backend.services.docker import TaskNotFoundError, get_task_status

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task(task_id: str) -> TaskStatusResponse:
    try:
        return get_task_status(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' was not found.",
        ) from exc
