from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from backend.config import settings
from backend.models import (
    DeleteImageResponse,
    ImageFileInfo,
    ImageListResponse,
    PullImageAcceptedResponse,
    PullImageRequest,
)
from backend.services.docker import (
    InvalidImageNameError,
    delete_image_archive,
    list_saved_images,
    resolve_image_archive,
    submit_pull_task,
)

router = APIRouter(prefix="/images", tags=["images"])


@router.post(
    "/pull",
    response_model=PullImageAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def pull_image(request: PullImageRequest) -> PullImageAcceptedResponse:
    try:
        return submit_pull_task(request.image)
    except InvalidImageNameError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=ImageListResponse)
async def get_images() -> ImageListResponse:
    images = [
        ImageFileInfo(
            filename=item["filename"],
            size_bytes=item["size_bytes"],
            saved_at=datetime.fromtimestamp(item["saved_at"], tz=timezone.utc),
        )
        for item in list_saved_images()
    ]
    return ImageListResponse(images=images)


@router.get("/{filename}/download")
async def download_image(filename: str, request: Request) -> Response:
    try:
        archive_path = resolve_image_archive(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    file_size = archive_path.stat().st_size
    common_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'attachment; filename="{archive_path.name}"',
    }
    range_header = request.headers.get("range")

    if not range_header:
        return FileResponse(
            path=archive_path,
            media_type="application/x-tar",
            filename=archive_path.name,
            headers=common_headers,
        )

    try:
        start, end = _parse_range_header(range_header, file_size)
    except ValueError as exc:
        return JSONResponse(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={**common_headers, "Content-Range": f"bytes */{file_size}"},
            content={"detail": str(exc)},
        )

    headers = {
        **common_headers,
        "Content-Length": str(end - start + 1),
        "Content-Range": f"bytes {start}-{end}/{file_size}",
    }
    return StreamingResponse(
        _stream_file_range(archive_path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type="application/x-tar",
        headers=headers,
    )


@router.delete("/{filename}", response_model=DeleteImageResponse)
async def delete_image(filename: str) -> DeleteImageResponse:
    try:
        delete_image_archive(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return DeleteImageResponse(filename=filename, deleted=True)


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    if not range_header.startswith("bytes="):
        raise ValueError("Only byte ranges are supported.")

    range_spec = range_header[len("bytes=") :].strip()
    if "," in range_spec:
        raise ValueError("Multiple ranges are not supported.")

    if "-" not in range_spec:
        raise ValueError("Invalid Range header format.")

    start_text, end_text = range_spec.split("-", 1)

    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise ValueError("Range suffix must be greater than zero.")
        start = max(file_size - suffix_length, 0)
        end = file_size - 1
        return start, end

    start = int(start_text)
    end = int(end_text) if end_text else file_size - 1

    if start < 0 or end < start or start >= file_size:
        raise ValueError("Requested range is outside the file size.")

    return start, min(end, file_size - 1)


async def _stream_file_range(path: Path, start: int, end: int):
    remaining = end - start + 1

    with path.open("rb") as file_obj:
        file_obj.seek(start)

        while remaining > 0:
            chunk_size = min(settings.download_chunk_size, remaining)
            chunk = await asyncio.to_thread(file_obj.read, chunk_size)
            if not chunk:
                break

            remaining -= len(chunk)
            yield chunk
