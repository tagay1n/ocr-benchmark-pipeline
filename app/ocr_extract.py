from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import delete, select

from .config import settings
from .db import get_session
from .layout_classes import normalize_class_name
from .layout_orientation import is_effective_vertical
from .lookalikes import detect_suspicious_lookalikes, normalize_text_nfc
from .models import Layout, OcrOutput, Page
from .ocr_content_postprocess import (
    SECTION_HEADER_LEVEL_H3,
    apply_section_header_heading_level,
    list_item_indent_level_from_x1,
    list_item_indent_levels_by_layout_id,
    normalize_formula_latex_content,
    normalize_list_item_line,
    section_header_levels_by_layout_id,
)
from .ocr_gemini_client import (
    DEFAULT_GEMINI_TEMPERATURE,
    GEMINI_MODEL,
    extract_content_from_json_response,
    extract_text_from_response,
    gemini_generate_content,
    gemini_generate_content_with_model,
    is_daily_quota_exhausted_error,
    is_gemini_server_error,
    is_quota_error,
    key_alias,
)
from .ocr_key_store import (
    GeminiQuotaExhaustedError,
)
from .ocr_prompts import (
    DEFAULT_PROMPT_TEMPLATE,
    render_prompt_for_layout_class,
)

MAX_RETRIES_PER_LAYOUT = 2


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _usage_path() -> Path:
    configured = settings.gemini_usage_path
    if configured is None:
        return (settings.project_root / "_artifacts" / "gemini_usage.json").resolve()
    return configured


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


def _next_available_key(exhausted_keys: list[str], *, exclude_keys: set[str] | None = None) -> str:
    configured = list(settings.gemini_keys)
    if not configured:
        raise GeminiQuotaExhaustedError("No Gemini API keys configured.")
    excluded = exclude_keys or set()
    exhausted_set = set(exhausted_keys)
    candidates = [key for key in configured if key not in exhausted_set and key not in excluded]
    if not candidates:
        raise GeminiQuotaExhaustedError("All configured Gemini keys are exhausted for today.")
    return candidates[0]


def _mark_key_exhausted(exhausted_keys: list[str], key: str) -> None:
    if key in exhausted_keys:
        return
    exhausted_keys.append(key)
    _save_usage_state(exhausted_keys)


# Backward-compatible aliases for tests and existing call sites.
_SECTION_HEADER_LEVEL_H3 = SECTION_HEADER_LEVEL_H3
_section_header_levels_by_layout_id = section_header_levels_by_layout_id
_apply_section_header_heading_level = apply_section_header_heading_level
_list_item_indent_level_from_x1 = list_item_indent_level_from_x1
_list_item_indent_levels_by_layout_id = list_item_indent_levels_by_layout_id
_normalize_list_item_line = normalize_list_item_line
_normalize_formula_latex_content = normalize_formula_latex_content
_extract_text_from_response = extract_text_from_response
_extract_content_from_json_response = extract_content_from_json_response
_gemini_generate_content = gemini_generate_content
_gemini_generate_content_with_model = gemini_generate_content_with_model
_is_quota_error = is_quota_error
_is_daily_quota_exhausted_error = is_daily_quota_exhausted_error
_is_gemini_server_error = is_gemini_server_error
_key_alias = key_alias


def supported_ocr_models() -> tuple[str, ...]:
    configured = tuple(str(value).strip() for value in settings.supported_ocr_models if str(value).strip())
    if not configured:
        return (GEMINI_MODEL,)
    deduplicated: list[str] = []
    seen: set[str] = set()
    for model_name in configured:
        if model_name in seen:
            continue
        seen.add(model_name)
        deduplicated.append(model_name)
    return tuple(deduplicated) if deduplicated else (GEMINI_MODEL,)


def default_ocr_model() -> str:
    return GEMINI_MODEL


def _prompt_for_layout(layout: dict[str, Any], *, prompt_template: str) -> tuple[str, str]:
    class_name = normalize_class_name(str(layout["class_name"]))
    rendered_prompt = render_prompt_for_layout_class(
        class_name,
        prompt_template=prompt_template,
    )
    return (rendered_prompt.prompt, rendered_prompt.output_format)


def _crop_layout_png_bytes(
    image_path: Path,
    bbox: dict[str, float],
    *,
    rotate_for_vertical: bool = False,
) -> bytes:
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
        if rotate_for_vertical:
            clip = clip.rotate(-90, expand=True)
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
            "orientation": str(getattr(layout, "orientation", "horizontal")),
            "effective_orientation": (
                "vertical"
                if is_effective_vertical(
                    orientation=str(getattr(layout, "orientation", "horizontal")),
                    bbox={
                        "x1": float(layout.x1),
                        "y1": float(layout.y1),
                        "x2": float(layout.x2),
                        "y2": float(layout.y2),
                    },
                )
                else "horizontal"
            ),
        }
        for layout in layouts
    ]


def extract_ocr_for_page(
    page_id: int,
    *,
    layout_ids: list[int] | None = None,
    model_name: str | None = None,
    prompt_template: str | None = None,
    temperature: float | None = None,
    max_retries_per_layout: int | None = None,
    progress_callback: Callable[[dict[str, int]], None] | None = None,
    continue_on_server_error: bool = False,
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
    resolved_model_name = (
        default_ocr_model()
        if model_name is None or not str(model_name).strip()
        else str(model_name).strip()
    )
    supported_models = supported_ocr_models()
    if resolved_model_name not in supported_models:
        raise ValueError(
            "Unsupported OCR model. "
            f"model_name must be one of: {', '.join(supported_models)}."
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
    revalidated_exhausted_pool = False

    pending_outputs: list[dict[str, Any]] = []
    prompt_debug_rows: list[dict[str, Any]] = []
    extracted_count = 0
    skipped_count = 0
    failed_count = 0
    failed_layout_ids: list[int] = []
    request_count = 0
    processed_count = 0
    total_selected = len(layouts_to_process)
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
                    "extraction_status": "skip",
                    "error_message": None,
                }
            )
            skipped_count += 1
            processed_count += 1
            if callable(progress_callback):
                progress_callback(
                    {
                        "processed_layouts": int(processed_count),
                        "total_layouts": int(total_selected),
                    }
                )
            continue

        rotate_for_vertical = (
            output_format == "markdown"
            and str(layout.get("effective_orientation") or "").strip().lower() == "vertical"
        )
        image_bytes = _crop_layout_png_bytes(
            image_path,
            layout["bbox"],
            rotate_for_vertical=rotate_for_vertical,
        )
        last_error: str | None = None
        response_text = ""
        used_key = ""
        retry_excluded_keys: set[str] = set()
        non_quota_attempts = 0
        while True:
            try:
                key = _next_available_key(exhausted_keys, exclude_keys=retry_excluded_keys)
            except GeminiQuotaExhaustedError as error:
                if not revalidated_exhausted_pool and exhausted_keys:
                    exhausted_keys = []
                    _save_usage_state(exhausted_keys)
                    retry_excluded_keys.clear()
                    revalidated_exhausted_pool = True
                    continue
                last_error = str(error)
                break
            try:
                if resolved_model_name == default_ocr_model():
                    response_text = _gemini_generate_content(
                        key,
                        prompt,
                        image_bytes,
                        temperature=resolved_temperature,
                    )
                else:
                    response_text = _gemini_generate_content_with_model(
                        key,
                        prompt,
                        image_bytes,
                        model_name=resolved_model_name,
                        temperature=resolved_temperature,
                    )
                request_count += 1
                used_key = key
                last_error = None
                break
            except Exception as error:
                error_text = str(error)
                if _is_quota_error(error_text):
                    retry_excluded_keys.add(key)
                    if _is_daily_quota_exhausted_error(error_text):
                        _mark_key_exhausted(exhausted_keys, key)
                    last_error = error_text
                    continue
                last_error = error_text
                non_quota_attempts += 1
                if non_quota_attempts >= resolved_max_retries:
                    break
        if last_error is not None:
            layout_id = int(layout["id"])
            failed_count += 1
            failed_layout_ids.append(layout_id)
            pending_outputs.append(
                {
                    "layout_id": int(layout["id"]),
                    "class_name": str(layout["class_name"]),
                    "output_format": output_format,
                    "content": "",
                    "key_alias": None,
                    "extraction_status": "failed",
                    "error_message": str(last_error),
                }
            )
            processed_count += 1
            if callable(progress_callback):
                progress_callback(
                    {
                        "processed_layouts": int(processed_count),
                        "total_layouts": int(total_selected),
                        "failed_layout_id": int(layout_id),
                        "failed_count": int(failed_count),
                    }
                )
            continue

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
                "extraction_status": "ok",
                "error_message": None,
            }
        )
        extracted_count += 1
        processed_count += 1
        if callable(progress_callback):
            progress_callback(
                {
                    "processed_layouts": int(processed_count),
                    "total_layouts": int(total_selected),
                }
            )

    now = _utc_now()
    final_status = "ocr_done"
    with get_session() as session:
        output_layout_ids = [int(output["layout_id"]) for output in pending_outputs]
        if output_layout_ids:
            session.execute(
                delete(OcrOutput).where(
                    OcrOutput.page_id == page_id,
                    OcrOutput.layout_id.in_(output_layout_ids),
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
                    model_name=resolved_model_name,
                    key_alias=output["key_alias"],
                    extraction_status=str(output.get("extraction_status") or "ok"),
                    error_message=None
                    if output.get("error_message") is None
                    else str(output.get("error_message")),
                    created_at=now,
                    updated_at=now,
                )
            )
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        page_row.status = final_status
        page_row.updated_at = now

    prompt_debug_path = _write_prompt_debug_dump(page_id, prompt_debug_rows)

    return {
        "page_id": page_id,
        "status": final_status,
        "model": resolved_model_name,
        "layouts_total": len(layouts),
        "layouts_selected": len(layouts_to_process),
        "extracted_count": extracted_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "failed_layout_ids": failed_layout_ids,
        "requests_count": request_count,
        "prompt_debug_path": None if prompt_debug_path is None else str(prompt_debug_path),
        "inference_params": {
            "temperature": resolved_temperature,
            "max_retries_per_layout": resolved_max_retries,
            "prompt_template": resolved_prompt_template,
        },
    }
