from __future__ import annotations

from typing import Final

PROMPT_BLOCK_TASK_CONTEXT: Final[str] = "You are given one cropped image region from a document page."
PROMPT_BLOCK_RESPONSE_CONTRACT: Final[str] = (
    'Return output as JSON only: {"content":"..."}\n'
    'Return exactly one top-level key: "content".\n'
    'The value of "content" must be a string.\n'
    "Do not add any other keys.\n"
    "Do not wrap output in markdown/code fences.\n"
    "Do not add explanations, comments, or metadata outside JSON."
)
PROMPT_BLOCK_GENERAL_RULES: Final[str] = (
    "Extract only content visible inside this crop.\n"
    "Do not add content that is not visible.\n"
    "Do not translate, paraphrase, rewrite, summarize, or omit legitimate content.\n"
    "Preserve line breaks exactly as shown in the crop.\n"
    "Do not dehyphenate words split by line breaks.\n"
    "Preserve visible punctuation exactly."
)
PROMPT_BLOCK_CLASS_RULES: Final[str] = "{class_rule}"
PROMPT_BLOCK_OUTPUT_RULE: Final[str] = "{format_rule}"

DEFAULT_PROMPT_PARTS: Final[tuple[str, ...]] = (
    PROMPT_BLOCK_TASK_CONTEXT,
    PROMPT_BLOCK_RESPONSE_CONTRACT,
    PROMPT_BLOCK_GENERAL_RULES,
    PROMPT_BLOCK_CLASS_RULES,
    PROMPT_BLOCK_OUTPUT_RULE,
)

DEFAULT_PROMPT_TEMPLATE: Final[str] = "\n".join(DEFAULT_PROMPT_PARTS)

FORMAT_RULE_MARKDOWN: Final[str] = 'The "content" string must be valid Markdown.'
FORMAT_RULE_HTML: Final[str] = 'The "content" string must be only one HTML <table>...</table> block.'
FORMAT_RULE_LATEX: Final[str] = (
    'The "content" string must be only LaTeX expression text, without Markdown wrappers.'
)

FORMAT_RULES_BY_OUTPUT_FORMAT: Final[dict[str, str]] = {
    "markdown": FORMAT_RULE_MARKDOWN,
    "html": FORMAT_RULE_HTML,
    "latex": FORMAT_RULE_LATEX,
}

CLASS_RULE_TEXT: Final[str] = (
    "- Primary script is Tatar Cyrillic; preserve original characters exactly. Words from other languages may appear and must be preserved.\n"
    "- Keep text as normal Markdown paragraphs.\n"
    "- Do not convert into headings, lists, or tables unless those markers are clearly visible.\n"
    "- Apply emphasis only when clearly visible: **bold**, *italic*, ***bold italic***.\n"
    "- Do not guess or apply formatting arbitrarily.\n"
    "- Inline formulas inside text must use LaTeX inline syntax: $...$.\n"
    "- Keep formulas inline with surrounding sentence text.\n"
    "- Do not turn regular words into formulas.\n"
    "- Do not convert the whole text block into a standalone formula block.\n"
    "- If formula notation is unclear, keep the visible text as-is.\n"
    "- Preserve visible superscript/subscript formatting.\n"
    "- Encode superscripts/subscripts as inline HTML in Markdown: <sup>...</sup> and <sub>...</sub>.\n"
    "- Do not invent superscript/subscript where it is not clearly visible."
)

CLASS_RULE_CAPTION: Final[str] = (
    "- Keep this content as caption text only.\n"
    "- Do not convert caption text into heading, list, or table.\n"
    "- Preserve caption labels/prefixes exactly when visible (for example: Figure, Fig., Table, Рис.).\n"
    "- Preserve caption numbering/indexes exactly as visible.\n"
    "- Preserve references to targets exactly as written; do not invent new target identifiers.\n"
    "- Preserve punctuation and separators exactly as visible.\n"
    "- If caption spans multiple lines, preserve line breaks exactly as shown."
)

CLASS_RULE_FOOTNOTE: Final[str] = (
    f"{CLASS_RULE_TEXT}\n"
    "- Keep content as literal footnote text.\n"
    "- Do not convert output to Markdown footnote syntax (for example: [^1] or [^1]: ...)."
)

CLASS_RULE_FORMULA: Final[str] = (
    "- Your task is to extract a standalone display formula from this crop.\n"
    "- The output must be LaTeX formula text only.\n"
    "- Represent the formula in LaTeX as faithfully as possible.\n"
    "- Preserve symbols, operators, and structure exactly as visible.\n"
    "- If exact LaTeX mapping is unclear, preserve visible tokens conservatively and do not invent missing parts.\n"
    "- Preserve line breaks exactly as shown in the crop.\n"
    "- Do not include prose, labels, or explanations.\n"
    "- Do not wrap output in $...$ or $$...$$.\n"
    "- Do not output Markdown formatting."
)

CLASS_RULE_TABLE: Final[str] = (
    "- Treat this crop as a table extraction task.\n"
    "- Treat tabular alignment as table structure even when grid lines are faint, partial, or absent.\n"
    "- Infer rows and columns from alignment/spacing only when clearly supported by visual layout.\n"
    "- If structure is ambiguous, prefer conservative segmentation and do not invent extra rows or columns.\n"
    "- Preserve table structure exactly as visible: row order, column order, and cell boundaries.\n"
    "- Use semantic HTML tags: <table>, <thead>, <tbody>, <tr>, <th>, <td>.\n"
    "- Use <thead> and <tbody> only when clearly inferable.\n"
    "- Use <th> only when header role is clearly visible; otherwise use <td>.\n"
    "- Preserve merged cells using rowspan/colspan when clearly visible.\n"
    "- If a cell is visibly empty, output it as an empty cell.\n"
    "- If cell text is unreadable, keep the cell and leave its content empty; do not invent text.\n"
    "- Preserve visible line breaks inside a cell using <br> only when clearly visible.\n"
    "- Do not infer or reconstruct hidden rows/columns outside crop boundaries.\n"
    "- Do not add CSS, classes, style attributes, wrapper tags, or Markdown table syntax."
)

CLASS_RULES_BY_LAYOUT_CLASS: Final[dict[str, str]] = {
    "text": CLASS_RULE_TEXT,
    "section_header": CLASS_RULE_TEXT,
    "picture_text": CLASS_RULE_TEXT,
    "page_header": CLASS_RULE_TEXT,
    "page_footer": CLASS_RULE_TEXT,
    "footnote": CLASS_RULE_FOOTNOTE,
    "caption": CLASS_RULE_CAPTION,
    "formula": CLASS_RULE_FORMULA,
    "table": CLASS_RULE_TABLE,
}


def format_rule_for_output_format(output_format: str) -> str:
    return FORMAT_RULES_BY_OUTPUT_FORMAT.get(output_format, "")


def class_rule_for_layout_class(class_name: str) -> str:
    return CLASS_RULES_BY_LAYOUT_CLASS.get(class_name, "")


def render_prompt_template(
    prompt_template: str,
    *,
    class_rule: str,
    format_rule: str,
) -> str:
    prompt = str(prompt_template)
    prompt = prompt.replace("{class_rule}", class_rule)
    prompt = prompt.replace("{format_rule}", format_rule)
    prompt = prompt.strip()
    if not prompt:
        raise RuntimeError("OCR prompt template produced an empty prompt.")
    return prompt
