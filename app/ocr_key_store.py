from __future__ import annotations

import json
from pathlib import Path

from .config import settings


class GeminiQuotaExhaustedError(RuntimeError):
    pass


def usage_path() -> Path:
    configured = settings.gemini_usage_path
    if configured is None:
        return (settings.project_root / "_artifacts" / "gemini_usage.json").resolve()
    return configured


def load_usage_state() -> list[str]:
    path = usage_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    exhausted_keys: list[str] = []
    seen: set[str] = set()
    for value in payload:
        key = str(value).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        exhausted_keys.append(key)
    return exhausted_keys


def save_usage_state(exhausted_keys: list[str]) -> None:
    path = usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(exhausted_keys, ensure_ascii=True, indent=2), encoding="utf-8")


def next_available_key(exhausted_keys: list[str]) -> str:
    configured = list(settings.gemini_keys)
    if not configured:
        raise GeminiQuotaExhaustedError("No Gemini API keys configured.")
    exhausted_set = set(exhausted_keys)
    candidates = [key for key in configured if key not in exhausted_set]
    if not candidates:
        raise GeminiQuotaExhaustedError("All configured Gemini keys are exhausted for today.")
    return candidates[0]


def mark_key_exhausted(exhausted_keys: list[str], key: str) -> None:
    if key in exhausted_keys:
        return
    exhausted_keys.append(key)
    save_usage_state(exhausted_keys)

