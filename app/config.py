from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import yaml

DEFAULT_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp")


@dataclass(frozen=True)
class Settings:
    project_root: Path
    source_dir: Path
    db_path: Path
    result_dir: Path
    allowed_extensions: tuple[str, ...]
    enable_background_jobs: bool
    auto_detect_layouts_after_discovery: bool = False
    auto_extract_text_after_layout_review: bool = False
    gemini_keys: tuple[str, ...] = ()
    gemini_usage_path: Path | None = None


def _resolve_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


def _parse_extensions(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_EXTENSIONS

    extensions: list[str] = []
    for ext in raw.split(","):
        normalized = ext.strip().lower()
        if not normalized:
            continue
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        extensions.append(normalized)

    return tuple(extensions) if extensions else DEFAULT_EXTENSIONS


def _read_config_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        if path.suffix.lower() in {".yaml", ".yml"}:
            payload = yaml.safe_load(handle)
        elif path.suffix.lower() == ".json":
            payload = json.load(handle)
        else:
            # Default to YAML for unknown extensions.
            payload = yaml.safe_load(handle)

    if not isinstance(payload, dict):
        return {}

    return payload


def _coerce_extensions(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        items = [str(value) for value in raw]
        return ",".join(items)
    return None


def _parse_bool(raw: object, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_gemini_keys(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()

    flattened: list[str] = []
    if isinstance(raw, str):
        flattened = [raw]
    elif isinstance(raw, list):
        flattened = [str(value) for value in raw]
    elif isinstance(raw, dict):
        for value in raw.values():
            if isinstance(value, list):
                flattened.extend(str(item) for item in value)
            elif isinstance(value, str):
                flattened.append(value)
    else:
        return ()

    deduplicated: list[str] = []
    seen: set[str] = set()
    for key in flattened:
        normalized = key.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(normalized)
    return tuple(deduplicated)


def load_settings() -> Settings:
    project_root = Path(os.getenv("PROJECT_ROOT", ".")).resolve()
    config_path = _resolve_path(project_root, os.getenv("APP_CONFIG_PATH", "config.yaml"))
    config = _read_config_file(config_path)

    source_dir_value = os.getenv("SOURCE_DIR", str(config.get("source_dir", "input")))
    db_path_value = os.getenv("DB_PATH", str(config.get("db_path", "data/ocr_dataset.db")))
    result_dir_value = os.getenv("RESULT_DIR", str(config.get("result_dir", "result")))
    ext_env = os.getenv("ALLOWED_IMAGE_EXTENSIONS")
    ext_value = ext_env if ext_env is not None else _coerce_extensions(config.get("allowed_image_extensions"))
    jobs_env = os.getenv("ENABLE_BACKGROUND_JOBS")
    jobs_value = jobs_env if jobs_env is not None else config.get("enable_background_jobs")
    auto_detect_layouts_value = config.get("auto_detect_layouts_after_discovery")
    auto_extract_text_value = config.get("auto_extract_text_after_layout_review")
    gemini_keys_env = os.getenv("GEMINI_KEYS")
    gemini_keys_value = (
        _coerce_gemini_keys(gemini_keys_env.split(",")) if gemini_keys_env is not None else _coerce_gemini_keys(config.get("gemini_keys"))
    )
    gemini_usage_path_value = os.getenv("GEMINI_USAGE_PATH", "_artifacts/gemini_usage.json")

    source_dir = _resolve_path(project_root, source_dir_value)
    db_path = _resolve_path(project_root, db_path_value)
    result_dir = _resolve_path(project_root, result_dir_value)
    allowed_extensions = _parse_extensions(ext_value)
    enable_background_jobs = _parse_bool(jobs_value, default=True)
    auto_detect_layouts_after_discovery = _parse_bool(auto_detect_layouts_value, default=False)
    auto_extract_text_after_layout_review = _parse_bool(auto_extract_text_value, default=False)
    gemini_usage_path = _resolve_path(project_root, gemini_usage_path_value)

    return Settings(
        project_root=project_root,
        source_dir=source_dir,
        db_path=db_path,
        result_dir=result_dir,
        allowed_extensions=allowed_extensions,
        enable_background_jobs=enable_background_jobs,
        auto_detect_layouts_after_discovery=auto_detect_layouts_after_discovery,
        auto_extract_text_after_layout_review=auto_extract_text_after_layout_review,
        gemini_keys=gemini_keys_value,
        gemini_usage_path=gemini_usage_path,
    )


settings = load_settings()
