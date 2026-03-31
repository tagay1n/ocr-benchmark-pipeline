from __future__ import annotations

from datetime import UTC, datetime
from html import escape, unescape
from html.parser import HTMLParser
from io import BytesIO
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
import unicodedata

from sqlalchemy import select

from .config import settings
from .db import get_session
from .models import CaptionBinding, Layout, OcrOutput, Page
from .statuses import STATUS_OCR_REVIEWED, to_api_status

_CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    "section_header": (53, 95, 168),
    "text": (79, 93, 105),
    "list_item": (47, 111, 95),
    "table": (111, 125, 47),
    "picture": (138, 104, 49),
    "picture_text": (154, 111, 86),
    "caption": (73, 111, 152),
    "footnote": (122, 96, 48),
    "formula": (123, 90, 149),
    "page_header": (63, 110, 105),
    "page_footer": (139, 89, 73),
}
_FALLBACK_COLORS: tuple[tuple[int, int, int], ...] = (
    (78, 111, 143),
    (124, 95, 144),
    (63, 123, 105),
    (141, 106, 59),
    (130, 96, 91),
    (83, 121, 135),
    (110, 107, 63),
)
_CAPTION_TARGET_CLASSES = frozenset({"table", "picture", "formula"})
_SOURCE_CROP_CLASSES = frozenset({"table", "picture"})
_HTML_TABLE_ALLOWED_TAGS = frozenset({"table", "thead", "tbody", "tr", "th", "td", "br"})
_HTML_TABLE_ALLOWED_ATTRIBUTES = frozenset({"rowspan", "colspan"})


def _timestamp_folder_name() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")


def _safe_relative_path(rel_path: str) -> Path:
    normalized = Path(rel_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError("Invalid relative path for export.")
    return normalized


def _copy_source_image(page_rel_path: str, destination_root: Path) -> tuple[Path, int, int]:
    try:
        from PIL import Image
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    rel_path = _safe_relative_path(page_rel_path)
    src = (settings.source_dir / rel_path).resolve()
    if settings.source_dir.resolve() not in src.parents:
        raise ValueError("Invalid source image path during export.")
    if not src.exists() or not src.is_file():
        raise ValueError(f"Source image missing for export: {page_rel_path}")

    dst = destination_root / "images" / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

    with Image.open(src) as image:
        width, height = image.size
    return dst, int(width), int(height)


def _normalize_class_name(value: str) -> str:
    return "_".join(str(value or "").strip().lower().replace("-", " ").replace("/", " ").split())


def _color_for_class(class_name: str) -> tuple[int, int, int]:
    normalized = _normalize_class_name(class_name)
    if normalized in _CLASS_COLORS:
        return _CLASS_COLORS[normalized]
    if not normalized:
        return _FALLBACK_COLORS[0]
    rolling = 0
    for char in normalized:
        rolling = ((rolling << 5) - rolling) + ord(char)
    return _FALLBACK_COLORS[abs(rolling) % len(_FALLBACK_COLORS)]


def _bbox_pixels(bbox: dict[str, Any], *, width: int, height: int) -> tuple[int, int, int, int]:
    x1 = max(0, min(width - 1, int(round(float(bbox["x1"]) * width))))
    y1 = max(0, min(height - 1, int(round(float(bbox["y1"]) * height))))
    x2 = max(x1 + 1, min(width, int(round(float(bbox["x2"]) * width))))
    y2 = max(y1 + 1, min(height, int(round(float(bbox["y2"]) * height))))
    return x1, y1, x2, y2


def _load_font(size: int) -> Any:
    try:
        from PIL import ImageFont
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    requested_size = max(6, int(size))
    for family in ("DejaVuSans.ttf", "Arial.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(family, requested_size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_size(draw: Any, text: str, font: Any, *, spacing: int = 0) -> tuple[int, int]:
    if "\n" in text:
        left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
    else:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return int(max(0, right - left)), int(max(0, bottom - top))


def _font_text_size(font: Any, text: str) -> tuple[int, int]:
    if not text:
        return (0, 0)
    left, top, right, bottom = font.getbbox(text)
    return int(max(0, right - left)), int(max(0, bottom - top))


def _split_chunk_to_width(draw: Any, chunk: str, font: Any, max_width: int) -> list[str]:
    if not chunk:
        return [""]
    width, _ = _text_size(draw, chunk, font)
    if width <= max_width:
        return [chunk]
    lines: list[str] = []
    current = ""
    for char in chunk:
        candidate = char if not current else f"{current}{char}"
        candidate_width, _ = _text_size(draw, candidate, font)
        if candidate_width <= max_width or not current:
            current = candidate
            continue
        lines.append(current)
        current = char
    if current:
        lines.append(current)
    return lines or [chunk]


def _wrap_text_to_width(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    raw_lines = str(text or "").splitlines() or [""]
    wrapped: list[str] = []
    for raw in raw_lines:
        if not raw:
            wrapped.append("")
            continue
        words = raw.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            width, _ = _text_size(draw, candidate, font)
            if width <= max_width:
                current = candidate
                continue
            if current:
                wrapped.append(current)
            for split_chunk in _split_chunk_to_width(draw, word, font, max_width):
                wrapped.append(split_chunk)
            current = ""
        if current:
            wrapped.append(current)
    return wrapped or [""]


def _line_height_ratio_for_output_format(output_format: str | None) -> float:
    normalized = str(output_format or "").strip().lower()
    if normalized == "latex":
        return 1.02
    if normalized == "html":
        return 1.08
    return 1.1


def _format_class_label(class_name: str) -> str:
    normalized = _normalize_class_name(class_name).replace("_", " ").strip()
    if not normalized:
        return ""
    return normalized[:1].upper() + normalized[1:]


def _normalized_rect_from_bbox(bbox: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(bbox, dict):
        return None
    try:
        x1 = float(bbox.get("x1", 0.0))
        y1 = float(bbox.get("y1", 0.0))
        x2 = float(bbox.get("x2", 0.0))
        y2 = float(bbox.get("y2", 0.0))
    except (TypeError, ValueError):
        return None
    return {
        "left": max(0.0, min(1.0, min(x1, x2))),
        "right": max(0.0, min(1.0, max(x1, x2))),
        "top": max(0.0, min(1.0, min(y1, y2))),
        "bottom": max(0.0, min(1.0, max(y1, y2))),
    }


def _shortest_connector_between_rects(
    source_rect: dict[str, float],
    target_rect: dict[str, float],
) -> dict[str, dict[str, float]]:
    if source_rect["right"] < target_rect["left"]:
        source_x = source_rect["right"]
        target_x = target_rect["left"]
    elif target_rect["right"] < source_rect["left"]:
        source_x = source_rect["left"]
        target_x = target_rect["right"]
    else:
        overlap_left = max(source_rect["left"], target_rect["left"])
        overlap_right = min(source_rect["right"], target_rect["right"])
        overlap_mid_x = (overlap_left + overlap_right) / 2.0
        source_x = overlap_mid_x
        target_x = overlap_mid_x

    if source_rect["bottom"] < target_rect["top"]:
        source_y = source_rect["bottom"]
        target_y = target_rect["top"]
    elif target_rect["bottom"] < source_rect["top"]:
        source_y = source_rect["top"]
        target_y = target_rect["bottom"]
    else:
        overlap_top = max(source_rect["top"], target_rect["top"])
        overlap_bottom = min(source_rect["bottom"], target_rect["bottom"])
        overlap_mid_y = (overlap_top + overlap_bottom) / 2.0
        source_y = overlap_mid_y
        target_y = overlap_mid_y

    return {
        "source": {"x": source_x, "y": source_y},
        "target": {"x": target_x, "y": target_y},
    }


def _content_text_for_render(item: dict[str, Any]) -> str:
    raw_content = item.get("content")
    if raw_content is None:
        return ""
    text = str(raw_content)
    output_format = str(item.get("content_format") or "").strip().lower()
    if output_format == "html":
        # Preserve readable table/text signal without exposing raw tags.
        text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</\s*(p|tr|li|div|h[1-6])\s*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text, flags=re.DOTALL)
        text = unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" ?\n ?", "\n", text)
        text = text.strip()
    if len(text) > 4000:
        text = text[:4000]
    return text


class _StructuredTableHtmlSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = str(tag or "").strip().lower()
        if normalized not in _HTML_TABLE_ALLOWED_TAGS:
            return
        if normalized == "br":
            self._parts.append("<br>")
            return
        safe_attrs: list[str] = []
        for name_raw, value_raw in attrs:
            name = str(name_raw or "").strip().lower()
            if name not in _HTML_TABLE_ALLOWED_ATTRIBUTES:
                continue
            value = "" if value_raw is None else str(value_raw).strip()
            if not value:
                continue
            if not value.isdigit():
                continue
            numeric_value = max(1, min(200, int(value)))
            safe_attrs.append(f' {name}="{numeric_value}"')
        self._parts.append(f"<{normalized}{''.join(safe_attrs)}>")
        self._stack.append(normalized)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        normalized = str(tag or "").strip().lower()
        if normalized == "br" or normalized not in _HTML_TABLE_ALLOWED_TAGS:
            return
        if not self._stack:
            return
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index] != normalized:
                continue
            for close_tag in reversed(self._stack[index:]):
                self._parts.append(f"</{close_tag}>")
            self._stack = self._stack[:index]
            return

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self._parts.append(escape(data))

    def html(self) -> str:
        while self._stack:
            self._parts.append(f"</{self._stack.pop()}>")
        return "".join(self._parts)


def _extract_first_table_fragment(raw_html: str) -> str:
    text = str(raw_html or "")
    if not text:
        return ""
    match = re.search(r"<table\b[\s\S]*?</table>", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return str(match.group(0))


def _sanitize_table_html(raw_html: str) -> str:
    fragment = _extract_first_table_fragment(raw_html)
    if not fragment:
        return ""
    parser = _StructuredTableHtmlSanitizer()
    try:
        parser.feed(fragment)
        parser.close()
    except Exception:
        return ""
    safe_html = parser.html().strip()
    if "<table" not in safe_html.lower() or "</table>" not in safe_html.lower():
        return ""
    return safe_html


def _find_headless_browser_binary() -> str:
    for candidate in ("google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(candidate)
        if path:
            return path
    return ""


def _render_html_document_via_browser(
    *,
    document_html: str,
    target_width: int,
    target_height: int,
) -> Any | None:
    browser_binary = _find_headless_browser_binary()
    if not browser_binary:
        return None
    safe_width = max(16, int(target_width))
    safe_height = max(16, int(target_height))
    try:
        from PIL import Image
    except ImportError:
        return None

    with tempfile.TemporaryDirectory(prefix="ocr-table-render-") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        html_path = temp_dir / "table.html"
        screenshot_path = temp_dir / "table.png"
        html_path.write_text(str(document_html or ""), encoding="utf-8")
        command = [
            browser_binary,
            "--headless",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-software-rasterizer",
            "--disable-crash-reporter",
            "--disable-breakpad",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-sandbox",
            "--force-device-scale-factor=1",
            "--virtual-time-budget=2500",
            f"--window-size={safe_width},{safe_height}",
            f"--screenshot={str(screenshot_path)}",
            str(html_path.resolve().as_uri()),
        ]
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=25,
            )
        except Exception:
            return None
        if completed.returncode != 0 or not screenshot_path.exists():
            return None
        try:
            with Image.open(screenshot_path) as image:
                rendered = image.convert("RGBA")
        except Exception:
            return None
        if rendered.size != (safe_width, safe_height):
            rendered = rendered.resize((safe_width, safe_height), Image.Resampling.LANCZOS)
        return rendered


def _render_html_table_image(
    *,
    html_source: str,
    target_width: int,
    target_height: int,
) -> Any | None:
    safe_table_html = _sanitize_table_html(html_source)
    if not safe_table_html:
        return None
    safe_width = max(8, int(target_width))
    safe_height = max(8, int(target_height))
    document_html = (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'>"
        "<style>"
        f"html, body {{ margin:0; padding:0; width:{safe_width}px; height:{safe_height}px; background:#fff; }}"
        "#root { width:100%; height:100%; overflow:hidden; display:flex; align-items:stretch; justify-content:stretch; }"
        "#content { width:100%; height:100%; font-family:'DejaVu Sans','Arial','Liberation Sans',sans-serif; "
        "line-height:1.1; color:#2d3230; }"
        "#content table { width:100%; border-collapse:collapse; margin:0 auto; table-layout:auto; "
        "border:2px solid #9f9686; }"
        "#content th, #content td { border:1.5px solid #9f9686; padding:2px 4px; font-size:inherit; text-align:left; "
        "vertical-align:top; white-space:normal; word-break:break-word; overflow-wrap:anywhere; }"
        "</style></head><body>"
        f"<div id='root'><div id='content'>{safe_table_html}</div></div>"
        "<script>"
        "(function(){"
        "const root=document.getElementById('root');"
        "const content=document.getElementById('content');"
        "if(!root||!content){return;}"
        "const fits=()=>content.scrollWidth<=root.clientWidth+1&&content.scrollHeight<=root.clientHeight+1;"
        "let low=6,high=72,best=6;"
        "while(low<=high){"
        "const mid=(low+high)>>1;"
        "content.style.fontSize=String(mid)+'px';"
        "if(fits()){best=mid;low=mid+1;}else{high=mid-1;}"
        "}"
        "content.style.fontSize=String(best)+'px';"
        "})();"
        "</script>"
        "</body></html>"
    )
    return _render_html_document_via_browser(
        document_html=document_html,
        target_width=safe_width,
        target_height=safe_height,
    )


def _formula_render_candidates(raw_value: str) -> list[str]:
    text = str(raw_value or "").strip()
    if not text:
        return []
    candidates: list[str] = [text]
    if text.startswith("$$") and text.endswith("$$") and len(text) >= 4:
        candidates.append(text[2:-2].strip())
    if text.startswith("$") and text.endswith("$") and len(text) >= 2:
        candidates.append(text[1:-1].strip())
    if "\n" in text:
        candidates.append(text.replace("\n", r"\\"))
        candidates.append(" ".join(part.strip() for part in text.splitlines() if part.strip()))
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _render_formula_latex_image(latex_source: str) -> Any | None:
    try:
        from matplotlib.mathtext import math_to_image
        from PIL import Image
    except ImportError:
        return None

    for candidate in _formula_render_candidates(latex_source):
        output = BytesIO()
        try:
            math_to_image(candidate, output, dpi=220, format="png")
            output.seek(0)
            with Image.open(output) as image:
                rendered = image.convert("RGBA")
            if rendered.width <= 0 or rendered.height <= 0:
                continue
            return rendered
        except Exception:
            continue
    return None


def _draw_formula_into_bbox(
    *,
    canvas: Any,
    formula_image: Any,
    left: int,
    top: int,
    width: int,
    height: int,
) -> None:
    try:
        from PIL import Image
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    target_width = max(1, int(width))
    target_height = max(1, int(height))
    source_width = max(1, int(formula_image.width))
    source_height = max(1, int(formula_image.height))

    fit_scale = min(target_width / source_width, target_height / source_height)
    if not math.isfinite(fit_scale) or fit_scale <= 0:
        return
    rendered_width = max(1, int(round(source_width * fit_scale)))
    rendered_height = max(1, int(round(source_height * fit_scale)))
    resized = formula_image.resize((rendered_width, rendered_height), Image.Resampling.LANCZOS)
    offset_x = int(left + max(0, (target_width - rendered_width) // 2))
    offset_y = int(top + max(0, (target_height - rendered_height) // 2))
    canvas.alpha_composite(resized, (offset_x, offset_y))


def _control_render_lines(text: str) -> list[str]:
    normalized = str(text or "").replace("\r\n", "\n")
    lines = normalized.split("\n")
    return lines if lines else [""]


def _contains_combining_marks(value: str) -> bool:
    for char in str(value or ""):
        if unicodedata.combining(char):
            return True
    return False


def _count_stretchable_spaces(value: str) -> int:
    count = 0
    for char in str(value or ""):
        if char == " ":
            count += 1
    return count


def _count_stretchable_glyphs(value: str) -> int:
    count = 0
    for char in str(value or ""):
        if char in {" ", "\n", "\r", "\t"}:
            continue
        count += 1
    return count


def _line_width_with_spacing(
    *,
    line: str,
    font: Any,
    word_spacing: float,
    letter_spacing: float,
) -> float:
    text = str(line or "")
    if not text:
        return 0.0
    last_stretchable_index = -1
    for index, char in enumerate(text):
        if char not in {" ", "\n", "\r", "\t"}:
            last_stretchable_index = index
    width = 0.0
    for index, char in enumerate(text):
        char_width, _ = _font_text_size(font, char)
        width += float(char_width)
        if char == " ":
            width += max(0.0, float(word_spacing))
        if index != last_stretchable_index and char not in {" ", "\n", "\r", "\t"}:
            width += max(0.0, float(letter_spacing))
    return max(0.0, width)


def _render_line_image(
    *,
    line: str,
    font: Any,
    fill_rgba: tuple[int, int, int, int],
    word_spacing: float,
    letter_spacing: float,
) -> Any:
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    text = str(line or "")
    line_width = max(1, int(math.ceil(_line_width_with_spacing(
        line=text,
        font=font,
        word_spacing=word_spacing,
        letter_spacing=letter_spacing,
    ))))
    ascent, descent = font.getmetrics()
    base_height = max(1, int(ascent + descent))
    image = Image.new("RGBA", (line_width + 2, base_height + 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    last_stretchable_index = -1
    for index, char in enumerate(text):
        if char not in {" ", "\n", "\r", "\t"}:
            last_stretchable_index = index

    cursor_x = 0.0
    for index, char in enumerate(text):
        draw.text((cursor_x, 1), char, fill=fill_rgba, font=font)
        char_width, _ = _font_text_size(font, char)
        cursor_x += float(char_width)
        if char == " ":
            cursor_x += max(0.0, float(word_spacing))
        if index != last_stretchable_index and char not in {" ", "\n", "\r", "\t"}:
            cursor_x += max(0.0, float(letter_spacing))
    return image


def _fit_plan_for_single_line(
    *,
    line: str,
    font: Any,
    output_format: str | None,
    target_width: int,
    max_word_spacing: float = 3.5,
    max_letter_spacing: float = 0.8,
) -> dict[str, float]:
    safe_target_width = max(1, int(target_width))
    text = str(line or "")
    normalized_format = str(output_format or "").strip().lower()
    has_combining_marks = _contains_combining_marks(text)

    word_spacing = 0.0
    letter_spacing = 0.0
    measured_base = _line_width_with_spacing(
        line=text,
        font=font,
        word_spacing=0.0,
        letter_spacing=0.0,
    )

    if normalized_format == "markdown" and not has_combining_marks and measured_base > 0:
        spaces_count = _count_stretchable_spaces(text)
        if spaces_count > 0:
            gap = safe_target_width - measured_base
            gain_threshold = safe_target_width * 0.01
            if gap > gain_threshold:
                word_spacing = min(float(max_word_spacing), gap / spaces_count)

        measured_after_word_spacing = _line_width_with_spacing(
            line=text,
            font=font,
            word_spacing=word_spacing,
            letter_spacing=0.0,
        )
        glyphs_count = _count_stretchable_glyphs(text)
        if glyphs_count > 1:
            gap = safe_target_width - measured_after_word_spacing
            gain_threshold = safe_target_width * 0.004
            if gap > gain_threshold:
                letter_spacing = min(float(max_letter_spacing), gap / max(1, glyphs_count - 1))

    measured = _line_width_with_spacing(
        line=text,
        font=font,
        word_spacing=word_spacing,
        letter_spacing=letter_spacing,
    )
    horizontal_scale = 1.0
    if normalized_format != "html" and measured > 0:
        horizontal_scale = safe_target_width / measured
        if normalized_format == "markdown" and has_combining_marks:
            horizontal_scale = min(1.0, horizontal_scale)
        horizontal_scale = max(0.18, min(8.0, horizontal_scale))
    return {
        "word_spacing": float(max(0.0, word_spacing)),
        "letter_spacing": float(max(0.0, letter_spacing)),
        "horizontal_scale": float(max(0.18, min(8.0, horizontal_scale))),
    }


def _median(values: list[float], fallback: float = 0.0) -> float:
    sorted_values = sorted(
        [
            float(value)
            for value in values
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        ]
    )
    if not sorted_values:
        return float(fallback)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return float(sorted_values[mid])
    return float((sorted_values[mid - 1] + sorted_values[mid]) / 2.0)


def _line_fit_plans_for_lines(
    *,
    lines: list[str],
    font: Any,
    output_format: str | None,
    target_width: int,
) -> list[dict[str, float]]:
    safe_lines = [str(line or "") for line in list(lines)]
    if not safe_lines:
        return []
    normalized_format = str(output_format or "").strip().lower()
    is_multiline = len(safe_lines) > 1
    max_word_spacing = 6.0 if (normalized_format == "markdown" and is_multiline) else 3.5
    max_letter_spacing = 1.2 if (normalized_format == "markdown" and is_multiline) else 0.8
    plans = [
        _fit_plan_for_single_line(
            line=line,
            font=font,
            output_format=normalized_format,
            target_width=target_width,
            max_word_spacing=max_word_spacing,
            max_letter_spacing=max_letter_spacing,
        )
        for line in safe_lines
    ]
    if normalized_format != "markdown" or len(plans) <= 1:
        return plans

    non_last = plans[:-1]
    last_idx = len(plans) - 1
    last_line = safe_lines[last_idx]
    has_combining_marks = _contains_combining_marks(last_line)
    median_word_spacing = 0.0 if has_combining_marks else max(0.0, _median([p["word_spacing"] for p in non_last], 0.0))
    median_letter_spacing = 0.0 if has_combining_marks else max(
        0.0,
        _median([p["letter_spacing"] for p in non_last], 0.0),
    )
    measured_last = _line_width_with_spacing(
        line=last_line,
        font=font,
        word_spacing=median_word_spacing,
        letter_spacing=median_letter_spacing,
    )
    if not math.isfinite(measured_last) or measured_last <= 0:
        return plans

    fit_scale = max(0.18, min(8.0, float(max(1, target_width)) / measured_last))
    if fit_scale < 1:
        applied_scale = fit_scale
    elif has_combining_marks:
        applied_scale = 1.0
    else:
        median_scale = max(0.18, _median([p["horizontal_scale"] for p in non_last], 1.0))
        applied_scale = max(1.0, min(median_scale, fit_scale))

    if not last_line.strip() or not math.isfinite(applied_scale) or applied_scale <= 0:
        return plans

    plans[last_idx] = {
        "word_spacing": float(median_word_spacing),
        "letter_spacing": float(median_letter_spacing),
        "horizontal_scale": float(max(0.18, min(8.0, applied_scale))),
    }
    return plans


def _draw_fitted_line_on_canvas(
    *,
    canvas: Any,
    line: str,
    font: Any,
    output_format: str | None,
    target_left: int,
    target_top: int,
    target_width: int,
    target_height: int,
    fit_plan: dict[str, float] | None = None,
) -> None:
    try:
        from PIL import Image
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    safe_target_width = max(1, int(target_width))
    safe_target_height = max(1, int(target_height))
    text = str(line or "")
    if not text:
        return

    effective_fit_plan = fit_plan or _fit_plan_for_single_line(
        line=text,
        font=font,
        output_format=output_format,
        target_width=safe_target_width,
    )
    word_spacing = float(effective_fit_plan.get("word_spacing", 0.0))
    letter_spacing = float(effective_fit_plan.get("letter_spacing", 0.0))
    horizontal_scale = float(effective_fit_plan.get("horizontal_scale", 1.0))
    horizontal_scale = max(0.18, min(8.0, horizontal_scale))

    line_image = _render_line_image(
        line=text,
        font=font,
        fill_rgba=(45, 50, 48, 255),
        word_spacing=word_spacing,
        letter_spacing=letter_spacing,
    )
    if abs(horizontal_scale - 1.0) > 1e-3:
        scaled_width = max(1, int(round(line_image.width * horizontal_scale)))
        line_image = line_image.resize((scaled_width, line_image.height), Image.Resampling.BICUBIC)

    if line_image.width > safe_target_width:
        line_image = line_image.crop((0, 0, safe_target_width, line_image.height))

    paste_y = int(target_top + max(0, (safe_target_height - line_image.height) // 2))
    canvas.alpha_composite(line_image, (int(target_left), paste_y))


def _draw_arrow_line(
    draw: Any,
    *,
    source_x: float,
    source_y: float,
    target_x: float,
    target_y: float,
    color_rgba: tuple[int, int, int, int],
) -> None:
    dx = target_x - source_x
    dy = target_y - source_y
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= 1e-4:
        return
    unit_x = dx / length
    unit_y = dy / length
    arrow_length = 8.0
    arrow_half_width = 4.0

    base_x = target_x - (unit_x * arrow_length)
    base_y = target_y - (unit_y * arrow_length)
    perp_x = -unit_y
    perp_y = unit_x

    draw.line([(source_x, source_y), (base_x, base_y)], fill=color_rgba, width=2)
    draw.polygon(
        [
            (target_x, target_y),
            (base_x + (perp_x * arrow_half_width), base_y + (perp_y * arrow_half_width)),
            (base_x - (perp_x * arrow_half_width), base_y - (perp_y * arrow_half_width)),
        ],
        fill=color_rgba,
    )


def _draw_caption_binding_arrows(
    draw: Any,
    *,
    items: list[dict[str, Any]],
    width: int,
    height: int,
) -> None:
    by_layout_id: dict[int, dict[str, Any]] = {}
    for item in items:
        try:
            layout_id = int(item.get("layout_id", 0))
        except (TypeError, ValueError):
            continue
        if layout_id > 0:
            by_layout_id[layout_id] = item

    for caption_item in items:
        if _normalize_class_name(str(caption_item.get("class_name") or "")) != "caption":
            continue
        source_rect = _normalized_rect_from_bbox(caption_item.get("bbox"))
        if source_rect is None:
            continue
        target_ids = caption_item.get("caption_targets")
        if not isinstance(target_ids, list):
            continue
        for target_layout_id_raw in target_ids:
            try:
                target_layout_id = int(target_layout_id_raw)
            except (TypeError, ValueError):
                continue
            target_item = by_layout_id.get(target_layout_id)
            if not target_item:
                continue
            target_class_name = _normalize_class_name(str(target_item.get("class_name") or ""))
            if target_class_name not in _CAPTION_TARGET_CLASSES:
                continue
            target_rect = _normalized_rect_from_bbox(target_item.get("bbox"))
            if target_rect is None:
                continue

            connector = _shortest_connector_between_rects(source_rect, target_rect)
            source_x = max(0, min(width - 1, float(connector["source"]["x"]) * width))
            source_y = max(0, min(height - 1, float(connector["source"]["y"]) * height))
            target_x = max(0, min(width - 1, float(connector["target"]["x"]) * width))
            target_y = max(0, min(height - 1, float(connector["target"]["y"]) * height))
            _draw_arrow_line(
                draw,
                source_x=source_x,
                source_y=source_y,
                target_x=target_x,
                target_y=target_y,
                color_rgba=(73, 111, 152, 190),
            )


def _fit_wrapped_lines(
    draw: Any,
    text: str,
    *,
    output_format: str | None,
    max_width: int,
    max_height: int,
) -> tuple[Any, list[str], int]:
    min_font_size = 6
    max_font_size = max(min_font_size, min(72, max_width, max_height))
    ratio = _line_height_ratio_for_output_format(output_format)
    best_font = _load_font(min_font_size)
    best_lines = _wrap_text_to_width(draw, text, best_font, max_width)
    best_line_height = max(1, int(round(min_font_size * ratio)))

    low = min_font_size
    high = max_font_size
    while low <= high:
        mid = (low + high) // 2
        font = _load_font(mid)
        lines = _wrap_text_to_width(draw, text, font, max_width)
        line_height = max(1, int(round(mid * ratio)))
        total_height = line_height * max(1, len(lines))
        fits_height = total_height <= max_height
        fits_width = True
        for line in lines:
            line_width, _ = _text_size(draw, line, font)
            if line_width > max_width:
                fits_width = False
                break
        if fits_height and fits_width:
            best_font = font
            best_lines = lines
            best_line_height = line_height
            low = mid + 1
        else:
            high = mid - 1
    return best_font, best_lines, best_line_height


def _draw_reconstructed_canvas(
    *,
    width: int,
    height: int,
    items: list[dict[str, Any]],
    source_image: Any,
) -> Any:
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")
    ordered_items = sorted(
        list(items),
        key=lambda item: (
            int(item.get("order", 0)),
            int(item.get("layout_id", 0)),
        ),
    )

    for item in ordered_items:
        bbox = item.get("bbox") or {}
        x1, y1, x2, y2 = _bbox_pixels(bbox, width=width, height=height)
        class_name = str(item.get("class_name") or "")
        normalized_class_name = _normalize_class_name(class_name)
        color = _color_for_class(class_name)
        if normalized_class_name in _SOURCE_CROP_CLASSES:
            crop = source_image.crop((x1, y1, x2, y2)).convert("RGBA")
            canvas.paste(crop, (x1, y1))

        draw.rectangle([(x1, y1), (x2, y2)], outline=(color[0], color[1], color[2], 200), width=1)

        order_label = json.dumps(int(item.get("order", 0)), ensure_ascii=False)
        label_text = f"{order_label}. {_format_class_label(class_name)}"
        label_font = _load_font(10)
        label_width, label_height = _text_size(draw, label_text, label_font)
        label_box_x1 = max(0, x1)
        label_box_x2 = min(width - 1, label_box_x1 + label_width + 4)
        label_box_y2 = max(0, y1 - 1)
        label_box_y1 = max(0, label_box_y2 - (label_height + 4))
        draw.rectangle(
            [(label_box_x1, label_box_y1), (label_box_x2, label_box_y2)],
            fill=(255, 255, 255, 236),
            outline=(color[0], color[1], color[2], 180),
            width=1,
        )
        draw.text(
            (label_box_x1 + 2, label_box_y1 + 2),
            label_text,
            fill=(color[0], color[1], color[2], 255),
            font=label_font,
        )

        if normalized_class_name == "picture":
            continue

        content_box_x1 = min(width - 1, max(0, x1 + 2))
        content_box_y1 = min(height - 1, max(0, y1 + 2))
        content_box_x2 = max(content_box_x1 + 1, min(width, x2 - 2))
        content_box_y2 = max(content_box_y1 + 1, min(height, y2 - 2))
        available_width = max(1, content_box_x2 - content_box_x1)
        available_height = max(1, content_box_y2 - content_box_y1)
        output_format = None if item.get("content_format") is None else str(item["content_format"])
        normalized_output_format = str(output_format or "").strip().lower()
        raw_content = "" if item.get("content") is None else str(item.get("content"))

        if normalized_class_name == "table" and normalized_output_format == "html":
            table_image = _render_html_table_image(
                html_source=raw_content,
                target_width=available_width,
                target_height=available_height,
            )
            if table_image is not None:
                canvas.alpha_composite(table_image, (content_box_x1, content_box_y1))
                continue

        text = _content_text_for_render(item)
        if not text:
            continue

        if normalized_class_name == "formula":
            formula_image = _render_formula_latex_image(text)
            if formula_image is not None:
                _draw_formula_into_bbox(
                    canvas=canvas,
                    formula_image=formula_image,
                    left=content_box_x1,
                    top=content_box_y1,
                    width=available_width,
                    height=available_height,
                )
                continue
        visible_lines = _control_render_lines(text)
        line_count = max(1, len(visible_lines))
        slot_height = max(1.0, available_height / line_count)
        line_height_ratio = _line_height_ratio_for_output_format(output_format)
        max_font_size = max(2, min(72, int(round(available_height * 2.2))))
        low_font = 2
        high_font = max_font_size
        best_font_size = low_font
        while low_font <= high_font:
            mid_font = (low_font + high_font) // 2
            candidate_line_height = max(1.0, float(mid_font) * float(line_height_ratio))
            if candidate_line_height <= slot_height + 0.5:
                best_font_size = mid_font
                low_font = mid_font + 1
            else:
                high_font = mid_font - 1

        font = _load_font(best_font_size)
        line_fit_plans = _line_fit_plans_for_lines(
            lines=visible_lines,
            font=font,
            output_format=output_format,
            target_width=available_width,
        )
        for line_index, line in enumerate(visible_lines):
            slot_top = content_box_y1 + int(round((line_index * available_height) / line_count))
            if line_index >= line_count - 1:
                slot_bottom = content_box_y2
            else:
                slot_bottom = content_box_y1 + int(round(((line_index + 1) * available_height) / line_count))
            slot_top = max(content_box_y1, min(content_box_y2 - 1, slot_top))
            slot_bottom = max(slot_top + 1, min(content_box_y2, slot_bottom))
            line_fit_plan = line_fit_plans[line_index] if line_index < len(line_fit_plans) else None
            _draw_fitted_line_on_canvas(
                canvas=canvas,
                line=line,
                font=font,
                output_format=output_format,
                target_left=content_box_x1,
                target_top=slot_top,
                target_width=available_width,
                target_height=slot_bottom - slot_top,
                fit_plan=line_fit_plan,
            )

    _draw_caption_binding_arrows(draw, items=ordered_items, width=width, height=height)
    return canvas.convert("RGB")


def _draw_control_image(
    *,
    source_image_path: Path,
    width: int,
    height: int,
    items: list[dict[str, Any]],
    destination_path: Path,
) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise ValueError("Pillow is required for final export.") from error

    with Image.open(source_image_path) as source_image:
        source = source_image.convert("RGB")
        if source.size != (width, height):
            source = source.resize((width, height))
        reconstructed = _draw_reconstructed_canvas(
            width=width,
            height=height,
            items=items,
            source_image=source,
        )
    control = Image.new("RGB", (width * 2, height), (248, 248, 248))
    control.paste(source, (0, 0))
    control.paste(reconstructed, (width, 0))
    divider = ImageDraw.Draw(control)
    divider.line([(width, 0), (width, height)], fill=(170, 170, 170), width=1)

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    control.save(destination_path)


def _load_export_rows() -> list[dict[str, Any]]:
    reviewed_status_values = (STATUS_OCR_REVIEWED, to_api_status(STATUS_OCR_REVIEWED))
    with get_session() as session:
        rows = session.execute(
            select(
                Page.id,
                Page.rel_path,
                Layout.id,
                Layout.reading_order,
                Layout.class_name,
                Layout.x1,
                Layout.y1,
                Layout.x2,
                Layout.y2,
                OcrOutput.output_format,
                OcrOutput.content,
            )
            .join(Layout, Layout.page_id == Page.id)
            .outerjoin(OcrOutput, OcrOutput.layout_id == Layout.id)
            .where(Page.is_missing.is_(False))
            .where(Page.status.in_(reviewed_status_values))
            .order_by(Page.id.asc(), Layout.reading_order.asc(), Layout.id.asc())
        ).all()

        caption_binding_rows = session.execute(
            select(Layout.page_id, CaptionBinding.caption_layout_id, CaptionBinding.target_layout_id)
            .join(Layout, Layout.id == CaptionBinding.caption_layout_id)
            .join(Page, Page.id == Layout.page_id)
            .where(Page.is_missing.is_(False))
            .where(Page.status.in_(reviewed_status_values))
            .order_by(Layout.page_id.asc(), CaptionBinding.caption_layout_id.asc(), CaptionBinding.target_layout_id.asc())
        ).all()

    caption_targets_by_page_and_layout: dict[tuple[int, int], list[int]] = {}
    for page_id_raw, caption_layout_id_raw, target_layout_id_raw in caption_binding_rows:
        key = (int(page_id_raw), int(caption_layout_id_raw))
        caption_targets_by_page_and_layout.setdefault(key, []).append(int(target_layout_id_raw))

    by_page: dict[int, dict[str, Any]] = {}
    for (
        page_id_raw,
        rel_path_raw,
        layout_id_raw,
        reading_order_raw,
        class_name_raw,
        x1_raw,
        y1_raw,
        x2_raw,
        y2_raw,
        output_format_raw,
        content_raw,
    ) in rows:
        page_id = int(page_id_raw)
        page = by_page.setdefault(
            page_id,
            {
                "page_id": page_id,
                "rel_path": str(rel_path_raw),
                "items": [],
            },
        )
        class_name = str(class_name_raw)
        output_format = None if output_format_raw is None else str(output_format_raw)
        content = None if content_raw is None else str(content_raw)

        item: dict[str, Any] = {
            "order": int(reading_order_raw),
            "layout_id": int(layout_id_raw),
            "bbox": {
                "x1": float(x1_raw),
                "y1": float(y1_raw),
                "x2": float(x2_raw),
                "y2": float(y2_raw),
            },
            "class_name": class_name,
        }

        if class_name != "picture":
            if output_format is not None:
                item["content_format"] = output_format
            if content is not None:
                item["content"] = content

        if class_name == "caption":
            targets = caption_targets_by_page_and_layout.get((page_id, int(layout_id_raw)), [])
            item["caption_targets"] = sorted(set(targets))

        page["items"].append(item)

    return [by_page[key] for key in sorted(by_page.keys())]


def export_final_dataset() -> dict[str, Any]:
    export_rows = _load_export_rows()
    if not export_rows:
        raise ValueError("No OCR reviewed pages available for export.")

    root = settings.result_dir / _timestamp_folder_name()
    images_root = root / "images"
    control_root = root / "control"
    images_root.mkdir(parents=True, exist_ok=True)
    control_root.mkdir(parents=True, exist_ok=True)

    metadata_rows: list[dict[str, Any]] = []
    for row in export_rows:
        rel_path = str(row["rel_path"])
        copied_image_path, width, height = _copy_source_image(rel_path, root)
        rel = _safe_relative_path(rel_path)
        control_path = control_root / rel.with_suffix(".png")

        metadata_row = {
            "page_id": int(row["page_id"]),
            "image": str(copied_image_path.relative_to(root).as_posix()),
            "control": str(control_path.relative_to(root).as_posix()),
            "width": width,
            "height": height,
            "items": row["items"],
        }
        _draw_control_image(
            source_image_path=copied_image_path,
            width=width,
            height=height,
            items=metadata_row["items"],
            destination_path=control_path,
        )
        metadata_rows.append(metadata_row)

    dataset_path = root / "dataset.jsonl"
    with dataset_path.open("w", encoding="utf-8") as handle:
        for row in metadata_rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    return {
        "export_dir": str(root),
        "dataset_file": str(dataset_path),
        "metadata_file": str(dataset_path),
        "page_count": len(metadata_rows),
        "image_count": len(metadata_rows),
        "reconstructed_count": len(metadata_rows),
        "control_count": len(metadata_rows),
    }
