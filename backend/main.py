from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import ensure_images_dir
from backend.routers.images import router as images_router
from backend.routers.tasks import router as tasks_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_images_dir()
    yield


app = FastAPI(
    title="Docker Image Mirror Tool API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(images_router)
app.include_router(tasks_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Docker Image Mirror Tool API is running."}
