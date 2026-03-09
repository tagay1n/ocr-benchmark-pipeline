from __future__ import annotations

from typing import Final

# Canonical layout classes used by review UI and persisted records.
KNOWN_LAYOUT_CLASSES: Final[tuple[str, ...]] = (
    "section_header",
    "text",
    "list_item",
    "table",
    "picture",
    "caption",
    "footnote",
    "formula",
    "page_header",
    "page_footer",
)

CAPTION_CLASS_NAME: Final[str] = "caption"
CAPTION_TARGET_CLASS_NAMES: Final[frozenset[str]] = frozenset({"table", "picture", "formula"})

DETECTED_CLASS_REMAP: Final[dict[str, str]] = {
    "title": "section_header",
    "list_item": "text",
}

PERSISTED_CLASS_REMAP: Final[dict[str, str]] = {
    "title": "section_header",
}

# OCR format routing by normalized class.
MARKDOWN_LAYOUT_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "caption",
        "footnote",
        "list_item",
        "page_footer",
        "page_header",
        "section_header",
        "text",
    }
)
HTML_LAYOUT_CLASSES: Final[frozenset[str]] = frozenset({"table"})
LATEX_LAYOUT_CLASSES: Final[frozenset[str]] = frozenset({"formula"})
SKIP_LAYOUT_CLASSES: Final[frozenset[str]] = frozenset({"picture"})


def normalize_class_name(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace("/", "_")
    return "_".join(normalized.split())


def normalize_detected_class_name(value: str) -> str:
    class_name = normalize_class_name(value)
    return DETECTED_CLASS_REMAP.get(class_name, class_name)


def normalize_persisted_class_name(value: str) -> str:
    class_name = normalize_class_name(value)
    return PERSISTED_CLASS_REMAP.get(class_name, class_name)
