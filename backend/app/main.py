"""Trolley Mate API.

    uvicorn app.main:app --reload            # dev, from the backend/ folder
    http://localhost:8000/docs               # interactive API docs
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.core import tracing
from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.core.request_security import RequestSecurityMiddleware, init_limits
from app.seed import seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    init_limits()
    if settings.seed_on_startup:
        with SessionLocal() as db:
            if seed_if_empty(db):
                logging.getLogger("trolleymate").info("Loaded demo data")
    tracing.initialise(settings)
    try:
        yield
    finally:
        tracing.shutdown()


app = FastAPI(title="Trolley Mate API", version="0.2.0", lifespan=lifespan)
app.add_middleware(RequestSecurityMiddleware)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False, allow_methods=["*"], allow_headers=["*"]
)
app.add_middleware(tracing.TracingMiddleware)
app.include_router(api_router)

@app.exception_handler(ValueError)
async def domain_error(_: Request, exc: ValueError) -> JSONResponse:
    # Workflow errors (IntakeError, BuildError, EscalationError, ...) subclass ValueError
    # and carry user-facing messages such as "Confirm your constraints first".
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def spa_file(dist: Path, path: str) -> Path:
    """The file to serve for a frontend URL: a real file inside dist/, else index.html.
    Resolved first, so an encoded "../" can never reach files outside dist/."""
    target = (dist / path).resolve()
    if path and target.is_relative_to(dist) and target.is_file():
        return target
    return dist / "index.html"


# Serve the built React app (production / single-container deploy).
dist = (Path(__file__).resolve().parents[1] / settings.frontend_dist).resolve()
if (dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        return FileResponse(spa_file(dist, path))
