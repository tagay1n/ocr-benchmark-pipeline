from __future__ import annotations

import base64
from datetime import UTC, datetime
from io import BytesIO
import json
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .config import settings
from .db import get_connection

GEMINI_MODEL = "gemini-3-flash-preview"
MAX_RETRIES_PER_LAYOUT = 3

MARKDOWN_CLASSES = {
    "caption",
    "footnote",
    "list_item",
    "page_footer",
    "page_header",
    "section_header",
    "text",
    "title",
}
HTML_CLASSES = {"table"}
LATEX_CLASSES = {"formula"}
SKIP_CLASSES = {"picture"}


class GeminiQuotaExhaustedError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_class_name(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace("/", "_")
    return "_".join(normalized.split())


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

    exhausted_keys_raw: list[object]
    if isinstance(payload, list):
        exhausted_keys_raw = payload
    elif isinstance(payload, dict):
        exhausted_keys_raw = payload.get("exhausted_keys", [])
        if not isinstance(exhausted_keys_raw, list):
            return []
    else:
        return []

    exhausted_keys: list[str] = []
    seen: set[str] = set()
    for value in exhausted_keys_raw:
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
    fragments: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                fragments.append(text.strip())
    return "\n".join(fragments).strip()


def _gemini_generate_content(api_key: str, prompt: str, image_bytes: bytes) -> str:
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
        "generationConfig": {"temperature": 0.0},
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

    output = _extract_text_from_response(response_payload)
    if not output:
        raise RuntimeError("Gemini request returned an empty response.")
    return output


def _is_quota_error(message: str) -> bool:
    normalized = message.lower()
    return (
        "http 429" in normalized
        or "resource_exhausted" in normalized
        or "quota" in normalized
        or "rate limit" in normalized
    )


def _prompt_for_layout(layout: dict[str, Any], caption_targets: list[str]) -> tuple[str, str]:
    class_name = _normalize_class_name(str(layout["class_name"]))
    if class_name in MARKDOWN_CLASSES:
        output_format = "markdown"
    elif class_name in HTML_CLASSES:
        output_format = "html"
    elif class_name in LATEX_CLASSES:
        output_format = "latex"
    elif class_name in SKIP_CLASSES:
        output_format = "skip"
    else:
        output_format = "markdown"

    if output_format == "skip":
        return ("", "skip")

    rules = [
        "Extract only the content inside this crop.",
        "Return only extracted content, without explanations.",
        "Preserve line breaks exactly as shown in the crop.",
        "Do not dehyphenate words split by line breaks.",
    ]
    if output_format == "markdown":
        rules.append("Output must be valid Markdown and preserve visible emphasis like bold/italic.")
    elif output_format == "html":
        rules.append("Output must be only one HTML <table>...</table> block.")
    elif output_format == "latex":
        rules.append("Output must be only LaTeX expression(s), no markdown wrapper.")

    class_line = f"Layout class: {class_name}."
    caption_line = ""
    if class_name == "caption" and caption_targets:
        caption_line = f" Caption targets: {', '.join(caption_targets)}."

    prompt = " ".join([class_line + caption_line, *rules]).strip()
    return (prompt, output_format)


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


def _fetch_page_layouts(page_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, class_name, x1, y1, x2, y2, reading_order
            FROM layouts
            WHERE page_id = ?
            ORDER BY reading_order ASC, id ASC
            """,
            (page_id,),
        ).fetchall()

        binding_rows = conn.execute(
            """
            SELECT cb.caption_layout_id, cb.target_layout_id, target.class_name
            FROM caption_bindings cb
            JOIN layouts target ON target.id = cb.target_layout_id
            JOIN layouts caption ON caption.id = cb.caption_layout_id
            WHERE caption.page_id = ?
              AND target.page_id = ?
            ORDER BY cb.caption_layout_id ASC, cb.target_layout_id ASC
            """,
            (page_id, page_id),
        ).fetchall()

    caption_targets_by_layout_id: dict[int, list[str]] = {}
    for row in binding_rows:
        caption_layout_id = int(row["caption_layout_id"])
        target_layout_id = int(row["target_layout_id"])
        target_class_name = _normalize_class_name(str(row["class_name"]))
        label = f"{target_class_name} [id:{target_layout_id}]"
        caption_targets_by_layout_id.setdefault(caption_layout_id, []).append(label)

    return [
        {
            "id": int(row["id"]),
            "class_name": _normalize_class_name(str(row["class_name"])),
            "bbox": {
                "x1": float(row["x1"]),
                "y1": float(row["y1"]),
                "x2": float(row["x2"]),
                "y2": float(row["y2"]),
            },
            "reading_order": int(row["reading_order"]),
            "caption_targets": caption_targets_by_layout_id.get(int(row["id"]), []),
        }
        for row in rows
    ]


def _store_ocr_output(
    *,
    page_id: int,
    layout_id: int,
    class_name: str,
    output_format: str,
    content: str,
    key_alias: str | None,
) -> None:
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO ocr_outputs(
                page_id, layout_id, class_name, output_format, content, model_name, key_alias, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(layout_id) DO UPDATE SET
                class_name = excluded.class_name,
                output_format = excluded.output_format,
                content = excluded.content,
                model_name = excluded.model_name,
                key_alias = excluded.key_alias,
                updated_at = excluded.updated_at
            """,
            (page_id, layout_id, class_name, output_format, content, GEMINI_MODEL, key_alias, now, now),
        )


def extract_ocr_for_page(page_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        page = conn.execute(
            "SELECT id, rel_path, status, is_missing FROM pages WHERE id = ?",
            (page_id,),
        ).fetchone()
        if page is None:
            raise ValueError("Page not found.")
        if int(page["is_missing"]) == 1:
            raise ValueError("Page is marked as missing.")

        conn.execute("DELETE FROM ocr_outputs WHERE page_id = ?", (page_id,))

    image_path = (settings.source_dir / str(page["rel_path"])).resolve()
    source_root = settings.source_dir.resolve()
    if source_root not in image_path.parents:
        raise ValueError("Invalid page image path for OCR extraction.")
    if not image_path.exists() or not image_path.is_file():
        raise ValueError("Image file not found on disk.")

    layouts = _fetch_page_layouts(page_id)
    if not layouts:
        raise ValueError("No layouts found for OCR extraction.")

    exhausted_keys = _load_usage_state()

    extracted_count = 0
    skipped_count = 0
    request_count = 0
    for layout in layouts:
        prompt, output_format = _prompt_for_layout(layout, layout["caption_targets"])
        if output_format == "skip":
            _store_ocr_output(
                page_id=page_id,
                layout_id=int(layout["id"]),
                class_name=str(layout["class_name"]),
                output_format="skip",
                content="",
                key_alias=None,
            )
            skipped_count += 1
            continue

        image_bytes = _crop_layout_png_bytes(image_path, layout["bbox"])
        last_error: str | None = None
        response_text = ""
        used_key = ""
        for _ in range(MAX_RETRIES_PER_LAYOUT):
            key = _next_available_key(exhausted_keys)
            try:
                response_text = _gemini_generate_content(key, prompt, image_bytes)
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
            raise RuntimeError(f"OCR extraction failed for layout {layout['id']}: {last_error}")

        _store_ocr_output(
            page_id=page_id,
            layout_id=int(layout["id"]),
            class_name=str(layout["class_name"]),
            output_format=output_format,
            content=response_text,
            key_alias=_key_alias(used_key),
        )
        extracted_count += 1

    with get_connection() as conn:
        conn.execute(
            "UPDATE pages SET status = 'ocr_done', updated_at = ? WHERE id = ?",
            (_utc_now(), page_id),
        )

    return {
        "page_id": page_id,
        "status": "ocr_done",
        "model": GEMINI_MODEL,
        "layouts_total": len(layouts),
        "extracted_count": extracted_count,
        "skipped_count": skipped_count,
        "requests_count": request_count,
    }
