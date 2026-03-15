#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.layout_classes import KNOWN_LAYOUT_CLASSES
from app.ocr_prompts import render_prompt_for_layout_class


def build_reference_markdown() -> str:
    lines: list[str] = []
    lines.append("# OCR Prompts Reference")
    lines.append("")
    lines.append("This file shows the final default prompts sent to Gemini per layout class (no image bytes).")
    lines.append("")
    for class_name in KNOWN_LAYOUT_CLASSES:
        rendered = render_prompt_for_layout_class(class_name)
        lines.append(f"## {class_name}")
        lines.append("")
        lines.append(f"- Output format: `{rendered.output_format}`")
        if rendered.output_format == "skip":
            lines.append("- Prompt: _not sent (class is skipped)_")
            lines.append("")
            continue
        lines.append("")
        lines.append("```text")
        lines.append(rendered.prompt)
        lines.append("```")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate OCR prompt reference markdown.")
    parser.add_argument(
        "--output",
        default="OCR_PROMPTS_REFERENCE.md",
        help="Output markdown path (default: OCR_PROMPTS_REFERENCE.md).",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.write_text(build_reference_markdown(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
