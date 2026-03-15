from __future__ import annotations

import base64
from datetime import UTC, datetime
from io import BytesIO
import json
from pathlib import Path
import re
import statistics
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from sqlalchemy import delete, select

from .config import settings
from .db import get_session
from .layout_classes import (
    MARKDOWN_LAYOUT_CLASSES as MARKDOWN_CLASSES,
    normalize_class_name,
)
from .lookalikes import detect_suspicious_lookalikes, normalize_text_nfc
from .models import Layout, OcrOutput, Page
from .ocr_prompts import (
    DEFAULT_PROMPT_TEMPLATE,
    render_prompt_for_layout_class,
)

GEMINI_MODEL = "gemini-3-flash-preview"
MAX_RETRIES_PER_LAYOUT = 3
DEFAULT_GEMINI_TEMPERATURE = 0.0

class GeminiQuotaExhaustedError(RuntimeError):
    pass


_SECTION_HEADER_LEVEL_H2 = 2
_SECTION_HEADER_LEVEL_H3 = 3
_SECTION_HEADER_LEVEL_H4 = 4
_LIST_INDENT_EPSILON = 0.03
_ORDERED_LIST_PREFIX_RE = re.compile(r"^\s*((?:\d+|[A-Za-zА-Яа-яЁё])[.)])\s+")
_UNORDERED_LIST_PREFIX_RE = re.compile(r"^\s*([-*•‣▪◦])\s+")


def _layout_height_ratio(layout: dict[str, Any]) -> float:
    bbox = layout.get("bbox")
    if not isinstance(bbox, dict):
        return 0.0
    try:
        y1 = float(bbox.get("y1", 0.0))
        y2 = float(bbox.get("y2", 0.0))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, y2 - y1)


def _median(values: list[float]) -> float:
    cleaned = [float(value) for value in values if float(value) > 0.0]
    if not cleaned:
        return 0.0
    return float(statistics.median(cleaned))


def _section_header_baseline_text_height(layouts: list[dict[str, Any]]) -> float:
    text_heights = [
        _layout_height_ratio(layout)
        for layout in layouts
        if normalize_class_name(str(layout.get("class_name", ""))) == "text"
    ]
    baseline = _median(text_heights)
    if baseline > 0:
        return baseline

    fallback_heights = [
        _layout_height_ratio(layout)
        for layout in layouts
        if normalize_class_name(str(layout.get("class_name", ""))) in {"list_item", "footnote", "picture_text"}
    ]
    baseline = _median(fallback_heights)
    if baseline > 0:
        return baseline

    any_markdown_heights = [
        _layout_height_ratio(layout)
        for layout in layouts
        if normalize_class_name(str(layout.get("class_name", ""))) in MARKDOWN_CLASSES
        and normalize_class_name(str(layout.get("class_name", ""))) != "section_header"
    ]
    return _median(any_markdown_heights)


def _section_header_level_from_ratio(height_ratio: float, baseline_text_height: float) -> int:
    if baseline_text_height <= 0:
        return _SECTION_HEADER_LEVEL_H3
    ratio = float(height_ratio) / float(baseline_text_height)
    if ratio >= 2.2:
        return _SECTION_HEADER_LEVEL_H2
    if ratio >= 1.6:
        return _SECTION_HEADER_LEVEL_H3
    return _SECTION_HEADER_LEVEL_H4


def _section_header_levels_by_layout_id(layouts: list[dict[str, Any]]) -> dict[int, int]:
    baseline_text_height = _section_header_baseline_text_height(layouts)
    levels: dict[int, int] = {}
    for layout in layouts:
        class_name = normalize_class_name(str(layout.get("class_name", "")))
        if class_name != "section_header":
            continue
        layout_id_raw = layout.get("id")
        try:
            layout_id = int(layout_id_raw)
        except (TypeError, ValueError):
            continue
        levels[layout_id] = _section_header_level_from_ratio(
            _layout_height_ratio(layout),
            baseline_text_height,
        )
    return levels


def _strip_markdown_heading_prefix(line: str) -> str:
    return re.sub(r"^\s{0,3}#{1,6}\s*", "", str(line)).strip()


def _apply_section_header_heading_level(content: str, level: int) -> str:
    text = str(content).strip()
    if not text:
        return text
    safe_level = max(1, min(6, int(level)))
    lines = text.splitlines()
    first_content_idx = -1
    for idx, line in enumerate(lines):
        if line.strip():
            first_content_idx = idx
            break
    if first_content_idx < 0:
        return text
    heading_text = _strip_markdown_heading_prefix(lines[first_content_idx])
    if not heading_text:
        heading_text = lines[first_content_idx].strip()
    lines[first_content_idx] = f"{'#' * safe_level} {heading_text}".strip()
    return "\n".join(lines).strip()


def _normalize_formula_latex_content(content: str) -> str:
    text = str(content).strip()
    if not text:
        return text

    lines = text.splitlines()
    if len(lines) >= 2:
        opening = lines[0].strip()
        closing = lines[-1].strip()
        if (
            (opening.startswith("```") and closing == "```")
            or (opening.startswith("~~~") and closing == "~~~")
        ):
            text = "\n".join(lines[1:-1]).strip()
            lines = text.splitlines()

    if text.startswith("\\[") and text.endswith("\\]") and len(text) > 4:
        text = text[2:-2].strip()
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        text = text[2:-2].strip()
    if text.startswith("$") and text.endswith("$") and len(text) > 2:
        text = text[1:-1].strip()
    return text


def _list_item_indent_level_from_x1(x1: float, baseline_x1: float) -> int:
    delta = max(0.0, float(x1) - float(baseline_x1))
    return int(delta / _LIST_INDENT_EPSILON)


def _normalize_list_item_line(
    content: str,
    *,
    indent_level: int,
    fallback_marker: str = "-",
) -> str:
    text = str(content).strip()
    if not text:
        return text
    ordered_match = _ORDERED_LIST_PREFIX_RE.match(text)
    unordered_match = _UNORDERED_LIST_PREFIX_RE.match(text)
    marker = ""
    body = text
    if ordered_match is not None:
        marker = ordered_match.group(1).strip()
        body = text[ordered_match.end() :].strip()
    elif unordered_match is not None:
        marker = fallback_marker
        body = text[unordered_match.end() :].strip()
    else:
        marker = fallback_marker
        body = text
    if not body:
        body = text
    indent = "  " * max(0, int(indent_level))
    return f"{indent}{marker} {body}".rstrip()


def _list_item_indent_levels_by_layout_id(layouts: list[dict[str, Any]]) -> dict[int, int]:
    list_items: list[tuple[int, float]] = []
    for layout in layouts:
        if normalize_class_name(str(layout.get("class_name", ""))) != "list_item":
            continue
        try:
            layout_id = int(layout.get("id"))
            x1 = float(layout.get("bbox", {}).get("x1", 0.0))
        except (TypeError, ValueError, AttributeError):
            continue
        list_items.append((layout_id, x1))
    if not list_items:
        return {}
    baseline_x1 = min(x1 for _, x1 in list_items)
    return {
        layout_id: _list_item_indent_level_from_x1(x1, baseline_x1)
        for layout_id, x1 in list_items
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _key_alias(api_key: str) -> str:
    if len(api_key) <= 8:
        return api_key
    return f"{api_key[:4]}...{api_key[-4:]}"


def _usage_path() -> Path:
    usage_path = settings.gemini_usage_path
    if usage_path is None:
        return (settings.project_root / "_artifacts" / "gemini_usage.json").resolve()
    return usage_path


def _load_usage_state() -> list[str]:
    path = _usage_path()
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


def _save_usage_state(exhausted_keys: list[str]) -> None:
    path = _usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(exhausted_keys, ensure_ascii=True, indent=2), encoding="utf-8")


def _next_available_key(exhausted_keys: list[str]) -> str:
    configured = list(settings.gemini_keys)
    if not configured:
        raise GeminiQuotaExhaustedError("No Gemini API keys configured.")

    exhausted_set = set(exhausted_keys)
    candidates = [key for key in configured if key not in exhausted_set]
    if not candidates:
        raise GeminiQuotaExhaustedError("All configured Gemini keys are exhausted for today.")
    return candidates[0]


def _mark_key_exhausted(exhausted_keys: list[str], key: str) -> None:
    if key not in exhausted_keys:
        exhausted_keys.append(key)
        _save_usage_state(exhausted_keys)


def _extract_text_from_response(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return ""
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        fragments: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                fragments.append(text)
        joined = "".join(fragments).strip()
        if joined:
            return joined
    return ""


def _extract_content_from_json_response(raw_text: str) -> str:
    text = str(raw_text).strip()
    if not text:
        raise RuntimeError("Gemini response text is empty.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Gemini response is not valid JSON: {error.msg}.") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Gemini response JSON must be an object.")
    if set(payload.keys()) != {"content"}:
        raise RuntimeError('Gemini response JSON must contain exactly one key: "content".')
    content = payload.get("content")
    if not isinstance(content, str):
        raise RuntimeError('Gemini response JSON field "content" must be a string.')
    return content


def _gemini_generate_content(
    api_key: str, prompt: str, image_bytes: bytes, *, temperature: float = DEFAULT_GEMINI_TEMPERATURE
) -> str:
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib_parse.quote(GEMINI_MODEL)}:generateContent?key={urllib_parse.quote(api_key)}"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(image_bytes).decode("ascii")}},
                ],
            }
        ],
        "generationConfig": {
            "temperature": float(temperature),
            "responseMimeType": "application/json",
        },
    }
    request_payload = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = urllib_request.Request(
        endpoint,
        data=request_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=120) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini request failed with HTTP {error.code}: {body}") from error
    except urllib_error.URLError as error:
        raise RuntimeError(f"Gemini request failed: {error}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("Gemini request returned invalid JSON.") from error

    raw_output = _extract_text_from_response(response_payload)
    if not raw_output:
        raise RuntimeError("Gemini request returned an empty response.")
    return _extract_content_from_json_response(raw_output)


def _is_quota_error(message: str) -> bool:
    normalized = message.lower()
    return (
        "http 429" in normalized
        or "resource_exhausted" in normalized
        or "quota" in normalized
        or "rate limit" in normalized
    )


def _prompt_for_layout(layout: dict[str, Any], *, prompt_template: str) -> tuple[str, str]:
    class_name = normalize_class_name(str(layout["class_name"]))
    rendered_prompt = render_prompt_for_layout_class(
        class_name,
        prompt_template=prompt_template,
    )
    return (rendered_prompt.prompt, rendered_prompt.output_format)


def _crop_layout_png_bytes(image_path: Path, bbox: dict[str, float]) -> bytes:
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError("Pillow is required for OCR crop extraction.") from error

    with Image.open(image_path) as image:
        width, height = image.size
        x1 = max(0.0, min(1.0, float(bbox["x1"])))
        y1 = max(0.0, min(1.0, float(bbox["y1"])))
        x2 = max(0.0, min(1.0, float(bbox["x2"])))
        y2 = max(0.0, min(1.0, float(bbox["y2"])))
        left = min(width - 1, max(0, int(round(x1 * width))))
        top = min(height - 1, max(0, int(round(y1 * height))))
        right = min(width, max(left + 1, int(round(x2 * width))))
        bottom = min(height, max(top + 1, int(round(y2 * height))))

        clip = image.crop((left, top, right, bottom))
        output = BytesIO()
        clip.save(output, format="PNG")
        return output.getvalue()


def _write_prompt_debug_dump(page_id: int, prompt_rows: list[dict[str, Any]]) -> Path | None:
    if not prompt_rows:
        return None
    try:
        prompts_dir = (settings.project_root / "_artifacts" / "ocr_prompts").resolve()
        prompts_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        output_path = prompts_dir / f"{timestamp}_page_{int(page_id)}.jsonl"
        lines = [json.dumps(row, ensure_ascii=False) for row in prompt_rows]
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output_path
    except OSError:
        return None


def _fetch_page_layouts(page_id: int) -> list[dict[str, Any]]:
    with get_session() as session:
        layouts = session.execute(
            select(Layout)
            .where(Layout.page_id == page_id)
            .order_by(Layout.reading_order.asc(), Layout.id.asc())
        ).scalars().all()

    return [
        {
            "id": int(layout.id),
            "class_name": normalize_class_name(str(layout.class_name)),
            "bbox": {
                "x1": float(layout.x1),
                "y1": float(layout.y1),
                "x2": float(layout.x2),
                "y2": float(layout.y2),
            },
            "reading_order": int(layout.reading_order),
        }
        for layout in layouts
    ]


def extract_ocr_for_page(
    page_id: int,
    *,
    layout_ids: list[int] | None = None,
    prompt_template: str | None = None,
    temperature: float | None = None,
    max_retries_per_layout: int | None = None,
) -> dict[str, Any]:
    with get_session() as session:
        page = session.get(Page, page_id)
        if page is None:
            raise ValueError("Page not found.")
        if bool(page.is_missing):
            raise ValueError("Page is marked as missing.")

    image_path = (settings.source_dir / str(page.rel_path)).resolve()
    source_root = settings.source_dir.resolve()
    if source_root not in image_path.parents:
        raise ValueError("Invalid page image path for OCR extraction.")
    if not image_path.exists() or not image_path.is_file():
        raise ValueError("Image file not found on disk.")

    layouts = _fetch_page_layouts(page_id)
    if not layouts:
        raise ValueError("No layouts found for OCR extraction.")

    selected_layout_ids: list[int] | None = None
    layouts_to_process = list(layouts)
    if layout_ids is not None:
        normalized_ids: list[int] = []
        seen_ids: set[int] = set()
        for raw_layout_id in layout_ids:
            layout_id = int(raw_layout_id)
            if layout_id <= 0 or layout_id in seen_ids:
                continue
            seen_ids.add(layout_id)
            normalized_ids.append(layout_id)
        if not normalized_ids:
            raise ValueError("layout_ids must contain at least one positive layout id.")

        page_layout_ids = {int(layout["id"]) for layout in layouts}
        missing_layout_ids = [layout_id for layout_id in normalized_ids if layout_id not in page_layout_ids]
        if missing_layout_ids:
            raise ValueError(
                f"Selected layout ids are not present on this page: {', '.join(str(value) for value in missing_layout_ids)}."
            )

        selected_layout_ids = normalized_ids
        selected_layout_id_set = set(selected_layout_ids)
        layouts_to_process = [
            layout for layout in layouts if int(layout["id"]) in selected_layout_id_set
        ]
        if not layouts_to_process:
            raise ValueError("No selected layouts available for OCR extraction.")

    resolved_prompt_template = (
        DEFAULT_PROMPT_TEMPLATE
        if prompt_template is None or not str(prompt_template).strip()
        else str(prompt_template)
    )
    resolved_temperature = DEFAULT_GEMINI_TEMPERATURE if temperature is None else float(temperature)
    if resolved_temperature < 0 or resolved_temperature > 2:
        raise ValueError("temperature must be between 0 and 2.")
    resolved_max_retries = (
        MAX_RETRIES_PER_LAYOUT if max_retries_per_layout is None else int(max_retries_per_layout)
    )
    if resolved_max_retries < 1:
        raise ValueError("max_retries_per_layout must be >= 1.")

    exhausted_keys = _load_usage_state()
    section_header_levels = _section_header_levels_by_layout_id(layouts)
    list_item_indent_levels = _list_item_indent_levels_by_layout_id(layouts)

    pending_outputs: list[dict[str, Any]] = []
    prompt_debug_rows: list[dict[str, Any]] = []
    extracted_count = 0
    skipped_count = 0
    request_count = 0
    for layout in layouts_to_process:
        prompt, output_format = _prompt_for_layout(
            layout,
            prompt_template=resolved_prompt_template,
        )
        prompt_debug_rows.append(
            {
                "page_id": int(page_id),
                "layout_id": int(layout["id"]),
                "class_name": str(layout["class_name"]),
                "reading_order": int(layout["reading_order"]),
                "output_format": output_format,
                "prompt": prompt,
            }
        )
        if output_format == "skip":
            pending_outputs.append(
                {
                    "layout_id": int(layout["id"]),
                    "class_name": str(layout["class_name"]),
                    "output_format": "skip",
                    "content": "",
                    "key_alias": None,
                }
            )
            skipped_count += 1
            continue

        image_bytes = _crop_layout_png_bytes(image_path, layout["bbox"])
        last_error: str | None = None
        response_text = ""
        used_key = ""
        for _ in range(resolved_max_retries):
            key = _next_available_key(exhausted_keys)
            try:
                response_text = _gemini_generate_content(
                    key,
                    prompt,
                    image_bytes,
                    temperature=resolved_temperature,
                )
                request_count += 1
                used_key = key
                last_error = None
                break
            except Exception as error:
                error_text = str(error)
                if _is_quota_error(error_text):
                    _mark_key_exhausted(exhausted_keys, key)
                    last_error = error_text
                    continue
                last_error = error_text
        if last_error is not None:
            _write_prompt_debug_dump(page_id, prompt_debug_rows)
            raise RuntimeError(f"OCR extraction failed for layout {layout['id']}: {last_error}")

        response_text = normalize_text_nfc(response_text)
        class_name = str(layout["class_name"])
        if class_name == "section_header":
            target_level = section_header_levels.get(int(layout["id"]), _SECTION_HEADER_LEVEL_H3)
            response_text = _apply_section_header_heading_level(response_text, target_level)
        elif class_name == "list_item":
            indent_level = list_item_indent_levels.get(int(layout["id"]), 0)
            response_text = _normalize_list_item_line(response_text, indent_level=indent_level, fallback_marker="-")
        elif class_name == "formula":
            response_text = _normalize_formula_latex_content(response_text)
        lookalike_warnings = (
            detect_suspicious_lookalikes(response_text, markdown_code_aware=True)
            if output_format == "markdown"
            else []
        )

        pending_outputs.append(
            {
                "layout_id": int(layout["id"]),
                "class_name": str(layout["class_name"]),
                "output_format": output_format,
                "content": response_text,
                "key_alias": _key_alias(used_key),
                "lookalike_warning_count": len(lookalike_warnings),
            }
        )
        extracted_count += 1

    now = _utc_now()
    with get_session() as session:
        if selected_layout_ids is None:
            session.execute(delete(OcrOutput).where(OcrOutput.page_id == page_id))
        else:
            session.execute(
                delete(OcrOutput).where(
                    OcrOutput.page_id == page_id,
                    OcrOutput.layout_id.in_(selected_layout_ids),
                )
            )
        for output in pending_outputs:
            session.add(
                OcrOutput(
                    page_id=page_id,
                    layout_id=int(output["layout_id"]),
                    class_name=str(output["class_name"]),
                    output_format=str(output["output_format"]),
                    content=str(output["content"]),
                    model_name=GEMINI_MODEL,
                    key_alias=output["key_alias"],
                    created_at=now,
                    updated_at=now,
                )
            )
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        page_row.status = "ocr_done"
        page_row.updated_at = now

    prompt_debug_path = _write_prompt_debug_dump(page_id, prompt_debug_rows)

    return {
        "page_id": page_id,
        "status": "ocr_done",
        "model": GEMINI_MODEL,
        "layouts_total": len(layouts),
        "layouts_selected": len(layouts_to_process),
        "extracted_count": extracted_count,
        "skipped_count": skipped_count,
        "requests_count": request_count,
        "prompt_debug_path": None if prompt_debug_path is None else str(prompt_debug_path),
        "inference_params": {
            "temperature": resolved_temperature,
            "max_retries_per_layout": resolved_max_retries,
            "prompt_template": resolved_prompt_template,
        },
    }
