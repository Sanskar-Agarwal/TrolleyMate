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
from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.seed import seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.seed_on_startup:
        with SessionLocal() as db:
            if seed_if_empty(db):
                logging.getLogger("trolleymate").info("Loaded demo data")
    yield


app = FastAPI(title="Trolley Mate API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)
app.include_router(api_router)

@app.exception_handler(ValueError)
async def domain_error(_: Request, exc: ValueError) -> JSONResponse:
    # Workflow errors (IntakeError, BuildError, EscalationError, ...) subclass ValueError
    # and carry user-facing messages such as "Confirm your constraints first".
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# Serve the built React app (production / single-container deploy).
dist = (Path(__file__).resolve().parents[1] / settings.frontend_dist).resolve()
if (dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        target = dist / path
        return FileResponse(target if path and target.is_file() else dist / "index.html")
