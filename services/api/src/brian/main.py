"""FastAPI application. Run with `brian-api` (or `uv run brian-api`)."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from brian.config import get_settings
from brian.db import get_engine
from brian.logs import configure_logging
from brian.routers import chat, devices, goals, insights, me, nudges, system


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    if not logging.getLogger().handlers:  # e.g. the server process uvicorn's reloader starts
        configure_logging(get_settings().log_level)
    app = FastAPI(
        title="Brian API",
        version="0.1.0",
        summary="Goal coaching agent with proactive, self-optimizing nudges.",
        lifespan=lifespan,
    )
    for module in (system, me, devices, goals, nudges, chat, insights):
        app.include_router(module.router)
    origins = get_settings().cors_origins
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )
    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        "brian.main:app",
        host="0.0.0.0",  # noqa: S104 - container entrypoint
        port=int(os.environ.get("PORT", "8000")),
        reload=settings.environment == "local",
        log_config=None,
    )
