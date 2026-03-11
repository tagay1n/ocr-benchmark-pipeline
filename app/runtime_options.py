from __future__ import annotations

from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class RuntimeOptionsSnapshot:
    enable_background_jobs: bool


def reset_runtime_options_from_settings() -> RuntimeOptionsSnapshot:
    return RuntimeOptionsSnapshot(enable_background_jobs=bool(settings.enable_background_jobs))


def get_runtime_options() -> RuntimeOptionsSnapshot:
    return RuntimeOptionsSnapshot(enable_background_jobs=bool(settings.enable_background_jobs))
