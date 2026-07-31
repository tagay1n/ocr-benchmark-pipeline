from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import random
from threading import RLock
from typing import Iterator
from zoneinfo import ZoneInfo


class GeminiQuotaExhaustedError(RuntimeError):
    pass


_STATE_LOCK = RLock()
_PACIFIC_TIME = ZoneInfo("America/Los_Angeles")


def _quota_day() -> str:
    return datetime.now(_PACIFIC_TIME).date().isoformat()


def _normalize_values(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _normalize_model_name(model_name: str) -> str:
    normalized = str(model_name or "").strip()
    if not normalized:
        raise ValueError("Gemini model name is required for quota accounting.")
    return normalized


@contextmanager
def _locked_state(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with _STATE_LOCK:
        with lock_path.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _read_state_unlocked(path: Path, *, legacy_model_name: str) -> tuple[dict[str, list[str]], bool]:
    if not path.exists():
        return {}, False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, False

    if isinstance(payload, list):
        legacy_keys = _normalize_values(payload)
        return ({legacy_model_name: legacy_keys} if legacy_keys else {}), True
    if not isinstance(payload, dict):
        return {}, False
    if str(payload.get("quota_day") or "").strip() != _quota_day():
        return {}, True

    raw_models = payload.get("models")
    if not isinstance(raw_models, dict):
        return {}, False
    models: dict[str, list[str]] = {}
    for raw_model_name, raw_keys in raw_models.items():
        model_name = str(raw_model_name or "").strip()
        keys = _normalize_values(raw_keys)
        if model_name and keys:
            models[model_name] = keys
    return models, False


def _write_state_unlocked(path: Path, models: dict[str, list[str]]) -> None:
    payload = {
        "quota_day": _quota_day(),
        "models": {
            model_name: _normalize_values(keys)
            for model_name, keys in models.items()
            if str(model_name).strip() and _normalize_values(keys)
        },
    }
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def load_usage_state(path: Path, *, model_name: str) -> list[str]:
    resolved_model_name = _normalize_model_name(model_name)
    with _locked_state(path):
        models, rewrite = _read_state_unlocked(path, legacy_model_name=resolved_model_name)
        if rewrite:
            _write_state_unlocked(path, models)
        return list(models.get(resolved_model_name, []))


def save_usage_state(path: Path, exhausted_keys: list[str], *, model_name: str) -> None:
    resolved_model_name = _normalize_model_name(model_name)
    with _locked_state(path):
        models, _rewrite = _read_state_unlocked(path, legacy_model_name=resolved_model_name)
        normalized_keys = _normalize_values(exhausted_keys)
        if normalized_keys:
            models[resolved_model_name] = normalized_keys
        else:
            models.pop(resolved_model_name, None)
        _write_state_unlocked(path, models)


def next_available_key(
    path: Path,
    configured_keys: tuple[str, ...],
    exhausted_keys: list[str],
    *,
    model_name: str,
    exclude_keys: set[str] | None = None,
) -> str:
    resolved_model_name = _normalize_model_name(model_name)
    configured = _normalize_values(list(configured_keys))
    if not configured:
        raise GeminiQuotaExhaustedError("No Gemini API keys configured.")

    with _locked_state(path):
        models, rewrite = _read_state_unlocked(path, legacy_model_name=resolved_model_name)
        if rewrite:
            _write_state_unlocked(path, models)
        persisted = models.get(resolved_model_name, [])
        merged_exhausted = _normalize_values([*persisted, *exhausted_keys])
        exhausted_keys[:] = merged_exhausted

        exhausted_set = set(merged_exhausted)
        daily_candidates = [key for key in configured if key not in exhausted_set]
        if not daily_candidates:
            raise GeminiQuotaExhaustedError(
                f"All configured Gemini keys are exhausted for today for model {resolved_model_name}."
            )

        excluded = exclude_keys or set()
        candidates = [key for key in daily_candidates if key not in excluded]
        if not candidates:
            raise GeminiQuotaExhaustedError(
                "All non-exhausted Gemini keys have already been tried for this layout."
            )
        random.shuffle(candidates)
        return candidates[0]


def mark_key_exhausted(
    path: Path,
    exhausted_keys: list[str],
    key: str,
    *,
    model_name: str,
) -> None:
    resolved_model_name = _normalize_model_name(model_name)
    normalized_key = str(key or "").strip()
    if not normalized_key:
        return
    with _locked_state(path):
        models, _rewrite = _read_state_unlocked(path, legacy_model_name=resolved_model_name)
        merged = _normalize_values(
            [*models.get(resolved_model_name, []), *exhausted_keys, normalized_key]
        )
        models[resolved_model_name] = merged
        _write_state_unlocked(path, models)
        exhausted_keys[:] = merged
