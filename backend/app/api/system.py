"""Health and runtime status (used by the UI's model badge and by deploy checks)."""

from fastapi import APIRouter

from app.core.config import get_settings
from app.llm import get_llm

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "app": get_settings().app_name}


@router.get("/system/llm")
def llm_status() -> dict:
    return get_llm().status()
