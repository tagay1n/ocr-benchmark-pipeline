from __future__ import annotations

from .layout_classes import normalize_class_name
from .ocr_prompts import resolve_prompt_spec


def normalize_output_format(value: str | None) -> str:
    return str(value or "").strip().lower()


def expected_output_format_for_layout_class(class_name: str) -> str:
    return normalize_output_format(str(resolve_prompt_spec(class_name).output_format))


def layout_class_requires_ocr(class_name: str) -> bool:
    return expected_output_format_for_layout_class(class_name) != "skip"


def output_matches_layout_class(
    *,
    output_class_name: str | None,
    output_format: str | None,
    layout_class_name: str | None,
) -> bool:
    expected_format = expected_output_format_for_layout_class(str(layout_class_name or ""))
    normalized_output_format = normalize_output_format(output_format)
    if expected_format == "skip":
        return False
    if normalized_output_format != expected_format:
        return False
    return normalize_class_name(str(output_class_name or "")) == normalize_class_name(str(layout_class_name or ""))


def can_preserve_output_for_class_transition(
    *,
    previous_class_name: str | None,
    next_class_name: str | None,
    output_format: str | None,
) -> bool:
    previous_format = expected_output_format_for_layout_class(str(previous_class_name or ""))
    next_format = expected_output_format_for_layout_class(str(next_class_name or ""))
    if next_format != "markdown":
        return False
    if previous_format != next_format:
        return False
    return normalize_output_format(output_format) == next_format
