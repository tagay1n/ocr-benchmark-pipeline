from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp")


@dataclass(frozen=True)
class Settings:
    project_root: Path
    source_dir: Path
    db_path: Path
    allowed_extensions: tuple[str, ...]


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
        payload = json.load(handle)

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


def load_settings() -> Settings:
    project_root = Path(os.getenv("PROJECT_ROOT", ".")).resolve()
    config_path = _resolve_path(project_root, os.getenv("APP_CONFIG_PATH", "config.json"))
    config = _read_config_file(config_path)

    source_dir_value = os.getenv("SOURCE_DIR", str(config.get("source_dir", "input")))
    db_path_value = os.getenv("DB_PATH", str(config.get("db_path", "data/ocr_dataset.db")))
    ext_env = os.getenv("ALLOWED_IMAGE_EXTENSIONS")
    ext_value = ext_env if ext_env is not None else _coerce_extensions(config.get("allowed_image_extensions"))

    source_dir = _resolve_path(project_root, source_dir_value)
    db_path = _resolve_path(project_root, db_path_value)
    allowed_extensions = _parse_extensions(ext_value)

    return Settings(
        project_root=project_root,
        source_dir=source_dir,
        db_path=db_path,
        allowed_extensions=allowed_extensions,
    )


settings = load_settings()
