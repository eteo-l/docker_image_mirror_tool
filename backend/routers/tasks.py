from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from backend.models import DeleteTaskResponse, TaskStatusResponse
from backend.services.docker import (
    TaskDeleteNotAllowedError,
    TaskNotCancellableError,
    TaskNotFoundError,
    cancel_task as cancel_task_record,
    delete_cancelled_task,
    get_task_status,
)

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


@router.post("/{task_id}/cancel", response_model=TaskStatusResponse)
async def cancel_task_route(task_id: str) -> TaskStatusResponse:
    try:
        return await cancel_task_record(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' was not found.",
        ) from exc
    except TaskNotCancellableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.delete("/{task_id}", response_model=DeleteTaskResponse)
async def delete_task(task_id: str) -> DeleteTaskResponse:
    try:
        delete_cancelled_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' was not found.",
        ) from exc
    except TaskDeleteNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return DeleteTaskResponse(task_id=task_id, deleted=True)
