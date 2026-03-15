from __future__ import annotations

from typing import Final, Sequence

PROMPT_PART_LAYOUT_CLASS: Final[str] = "Layout class: {class_name}.{caption_line}"
PROMPT_PART_EXTRACT_SCOPE: Final[str] = "Extract only the content inside this crop."
PROMPT_PART_OUTPUT_ONLY: Final[str] = "Return only extracted content, without explanations."
PROMPT_PART_KEEP_LINE_BREAKS: Final[str] = "Preserve line breaks exactly as shown in the crop."
PROMPT_PART_NO_DEHYPHENATION: Final[str] = "Do not dehyphenate words split by line breaks."
PROMPT_PART_FORMAT_RULE: Final[str] = "{format_rule}"

DEFAULT_PROMPT_PARTS: Final[tuple[str, ...]] = (
    PROMPT_PART_LAYOUT_CLASS,
    PROMPT_PART_EXTRACT_SCOPE,
    PROMPT_PART_OUTPUT_ONLY,
    PROMPT_PART_KEEP_LINE_BREAKS,
    PROMPT_PART_NO_DEHYPHENATION,
    PROMPT_PART_FORMAT_RULE,
)

DEFAULT_PROMPT_TEMPLATE: Final[str] = "\n".join(DEFAULT_PROMPT_PARTS)

FORMAT_RULE_MARKDOWN: Final[str] = (
    "Output must be valid Markdown and preserve visible emphasis like bold/italic."
)
FORMAT_RULE_HTML: Final[str] = "Output must be only one HTML <table>...</table> block."
FORMAT_RULE_LATEX: Final[str] = "Output must be only LaTeX expression(s), no markdown wrapper."

FORMAT_RULES_BY_OUTPUT_FORMAT: Final[dict[str, str]] = {
    "markdown": FORMAT_RULE_MARKDOWN,
    "html": FORMAT_RULE_HTML,
    "latex": FORMAT_RULE_LATEX,
}


def caption_line_for_layout(class_name: str, caption_targets: Sequence[str]) -> str:
    if class_name != "caption":
        return ""
    targets = [str(value).strip() for value in caption_targets if str(value).strip()]
    if not targets:
        return ""
    return f" Caption targets: {', '.join(targets)}."


def format_rule_for_output_format(output_format: str) -> str:
    return FORMAT_RULES_BY_OUTPUT_FORMAT.get(output_format, "")


def render_prompt_template(
    prompt_template: str,
    *,
    class_name: str,
    caption_targets: Sequence[str],
    format_rule: str,
) -> str:
    normalized_targets = [str(value).strip() for value in caption_targets if str(value).strip()]
    prompt = str(prompt_template)
    prompt = prompt.replace("{class_name}", class_name)
    prompt = prompt.replace("{caption_line}", caption_line_for_layout(class_name, normalized_targets))
    prompt = prompt.replace("{caption_targets}", ", ".join(normalized_targets))
    prompt = prompt.replace("{format_rule}", format_rule)
    prompt = prompt.strip()
    if not prompt:
        raise RuntimeError("OCR prompt template produced an empty prompt.")
    return prompt
