"""FastAPI application entry point."""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from routers.summarize import router as summarize_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)

app = FastAPI(
    title="Repo Summarizer",
    description="Summarize GitHub repositories using an LLM.",
    version="1.0.0",
)


@app.middleware("http")
async def request_timing(request: Request, call_next):
    t0 = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - t0
    response.headers["X-Process-Time"] = f"{elapsed:.3f}"
    logging.getLogger("timing").info(
        "%s %s — %.3fs (%d)",
        request.method,
        request.url.path,
        elapsed,
        response.status_code,
    )
    return response


app.include_router(summarize_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
