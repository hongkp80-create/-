"""로컬 작업 디렉터리 및 설정 저장소."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import find_capcut_draft_folder

BASE_DIR = Path.home() / ".capcut_agent"
UPLOAD_DIR = BASE_DIR / "uploads"
ASR_CACHE_DIR = BASE_DIR / "cache" / "asr"
PIPELINE_CACHE_DIR = BASE_DIR / "cache" / "pipeline"
STATE_PATH = BASE_DIR / "state.json"

for d in (UPLOAD_DIR, ASR_CACHE_DIR, PIPELINE_CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {
    "draft_folder": None,
    "model_size": "small",
    "language": "ko",
}


def load_settings() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}
    settings = {**DEFAULT_SETTINGS, **data}
    if not settings.get("draft_folder"):
        settings["draft_folder"] = find_capcut_draft_folder()
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
