from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from .config import settings


@dataclass(frozen=True)
class RuntimeOptionsSnapshot:
    enable_background_jobs: bool
    auto_detect_layouts_after_discovery: bool
    auto_extract_text_after_layout_review: bool


_OPTIONS_LOCK = Lock()
_AUTO_DETECT_LAYOUTS_AFTER_DISCOVERY = bool(settings.auto_detect_layouts_after_discovery)
_AUTO_EXTRACT_TEXT_AFTER_LAYOUT_REVIEW = bool(settings.auto_extract_text_after_layout_review)


def reset_runtime_options_from_settings() -> RuntimeOptionsSnapshot:
    global _AUTO_DETECT_LAYOUTS_AFTER_DISCOVERY, _AUTO_EXTRACT_TEXT_AFTER_LAYOUT_REVIEW
    with _OPTIONS_LOCK:
        _AUTO_DETECT_LAYOUTS_AFTER_DISCOVERY = bool(settings.auto_detect_layouts_after_discovery)
        _AUTO_EXTRACT_TEXT_AFTER_LAYOUT_REVIEW = bool(settings.auto_extract_text_after_layout_review)
        return RuntimeOptionsSnapshot(
            enable_background_jobs=bool(settings.enable_background_jobs),
            auto_detect_layouts_after_discovery=_AUTO_DETECT_LAYOUTS_AFTER_DISCOVERY,
            auto_extract_text_after_layout_review=_AUTO_EXTRACT_TEXT_AFTER_LAYOUT_REVIEW,
        )


def get_runtime_options() -> RuntimeOptionsSnapshot:
    with _OPTIONS_LOCK:
        return RuntimeOptionsSnapshot(
            enable_background_jobs=bool(settings.enable_background_jobs),
            auto_detect_layouts_after_discovery=_AUTO_DETECT_LAYOUTS_AFTER_DISCOVERY,
            auto_extract_text_after_layout_review=_AUTO_EXTRACT_TEXT_AFTER_LAYOUT_REVIEW,
        )


def update_runtime_options(
    *,
    auto_detect_layouts_after_discovery: bool | None = None,
    auto_extract_text_after_layout_review: bool | None = None,
) -> RuntimeOptionsSnapshot:
    global _AUTO_DETECT_LAYOUTS_AFTER_DISCOVERY, _AUTO_EXTRACT_TEXT_AFTER_LAYOUT_REVIEW
    with _OPTIONS_LOCK:
        if auto_detect_layouts_after_discovery is not None:
            _AUTO_DETECT_LAYOUTS_AFTER_DISCOVERY = bool(auto_detect_layouts_after_discovery)
        if auto_extract_text_after_layout_review is not None:
            _AUTO_EXTRACT_TEXT_AFTER_LAYOUT_REVIEW = bool(auto_extract_text_after_layout_review)
        return RuntimeOptionsSnapshot(
            enable_background_jobs=bool(settings.enable_background_jobs),
            auto_detect_layouts_after_discovery=_AUTO_DETECT_LAYOUTS_AFTER_DISCOVERY,
            auto_extract_text_after_layout_review=_AUTO_EXTRACT_TEXT_AFTER_LAYOUT_REVIEW,
        )


def should_auto_detect_layouts_after_discovery() -> bool:
    options = get_runtime_options()
    return options.enable_background_jobs and options.auto_detect_layouts_after_discovery


def should_auto_extract_text_after_layout_review() -> bool:
    options = get_runtime_options()
    return options.enable_background_jobs and options.auto_extract_text_after_layout_review
