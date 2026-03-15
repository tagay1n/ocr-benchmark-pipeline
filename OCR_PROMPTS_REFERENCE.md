# OCR Prompts Reference

This file shows the final default prompts sent to Gemini per layout class (no image bytes).

## section_header

- Output format: `markdown`

```text
You are given one cropped image region from a document page.
HARD REQUIREMENTS:
- Return output as JSON only: {"content":"..."}
- Return exactly one top-level key: "content".
- The value of "content" must be a string.
- Do not add any other keys.
- Do not wrap output in markdown/code fences.
- Do not add explanations, comments, or metadata outside JSON.
- Do not add content that is not visible.
- Do not translate, paraphrase, summarize, or alter meaning.
- Do not intentionally omit readable legitimate content.
- When rules conflict: preserve visible content semantics first, then source fidelity, then formatting.
SOURCE FIDELITY:
- Extract only content visible inside this crop.
- Do not dehyphenate words split by line breaks.
- Preserve visible punctuation exactly.
CLASS-SPECIFIC REQUIREMENTS:
- Treat this crop as heading-like text.
- Preserve visible heading markers/tokens when present.
- Primary script is Tatar Cyrillic; preserve original characters exactly. Words from other languages may appear and must be preserved.
- Keep text as normal Markdown paragraphs.
- Do not convert into headings, lists, or tables unless those markers are clearly visible.
- Apply emphasis only when clearly visible: **bold**, *italic*, ***bold italic***.
- Do not guess or apply formatting arbitrarily.
- Inline formulas inside text must use LaTeX inline syntax: $...$.
- Keep formulas inline with surrounding sentence text.
- Do not turn regular words into formulas.
- Do not convert the whole text block into a standalone formula block.
- If formula notation is unclear, keep the visible text as-is.
- Preserve visible superscript/subscript formatting.
- Encode superscripts/subscripts as inline HTML in Markdown: <sup>...</sup> and <sub>...</sub>.
- Do not invent superscript/subscript where it is not clearly visible.
- One-shot example (text-like crop):
  EXAMPLE INPUT START
  Без съезддагы фикер алышуларның һәм тавыш бирүләрнең
  анализын тәмам иттек; бу анализ съезддан соң булган хәл-
  ләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм
  EXAMPLE INPUT END
  EXAMPLE OUTPUT START
  {"content":"Без съезддагы фикер алышуларның һәм тавыш бирүләрнең\nанализын тәмам иттек; бу анализ съезддан соң булган хәл-\nләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм"}
  EXAMPLE OUTPUT END
OUTPUT FORMAT REQUIREMENTS:
The "content" string must be valid Markdown.
- Preserve line breaks exactly as shown in the crop.
IF UNSURE:
- Prefer conservative extraction over guessing.
- Keep visible text/tokens as-is rather than normalizing aggressively.
- Leave ambiguous or unreadable fragments empty instead of inventing content.
```

## text

- Output format: `markdown`

```text
You are given one cropped image region from a document page.
HARD REQUIREMENTS:
- Return output as JSON only: {"content":"..."}
- Return exactly one top-level key: "content".
- The value of "content" must be a string.
- Do not add any other keys.
- Do not wrap output in markdown/code fences.
- Do not add explanations, comments, or metadata outside JSON.
- Do not add content that is not visible.
- Do not translate, paraphrase, summarize, or alter meaning.
- Do not intentionally omit readable legitimate content.
- When rules conflict: preserve visible content semantics first, then source fidelity, then formatting.
SOURCE FIDELITY:
- Extract only content visible inside this crop.
- Do not dehyphenate words split by line breaks.
- Preserve visible punctuation exactly.
CLASS-SPECIFIC REQUIREMENTS:
- Primary script is Tatar Cyrillic; preserve original characters exactly. Words from other languages may appear and must be preserved.
- Keep text as normal Markdown paragraphs.
- Do not convert into headings, lists, or tables unless those markers are clearly visible.
- Apply emphasis only when clearly visible: **bold**, *italic*, ***bold italic***.
- Do not guess or apply formatting arbitrarily.
- Inline formulas inside text must use LaTeX inline syntax: $...$.
- Keep formulas inline with surrounding sentence text.
- Do not turn regular words into formulas.
- Do not convert the whole text block into a standalone formula block.
- If formula notation is unclear, keep the visible text as-is.
- Preserve visible superscript/subscript formatting.
- Encode superscripts/subscripts as inline HTML in Markdown: <sup>...</sup> and <sub>...</sub>.
- Do not invent superscript/subscript where it is not clearly visible.
- One-shot example (text-like crop):
  EXAMPLE INPUT START
  Без съезддагы фикер алышуларның һәм тавыш бирүләрнең
  анализын тәмам иттек; бу анализ съезддан соң булган хәл-
  ләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм
  EXAMPLE INPUT END
  EXAMPLE OUTPUT START
  {"content":"Без съезддагы фикер алышуларның һәм тавыш бирүләрнең\nанализын тәмам иттек; бу анализ съезддан соң булган хәл-\nләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм"}
  EXAMPLE OUTPUT END
OUTPUT FORMAT REQUIREMENTS:
The "content" string must be valid Markdown.
- Preserve line breaks exactly as shown in the crop.
IF UNSURE:
- Prefer conservative extraction over guessing.
- Keep visible text/tokens as-is rather than normalizing aggressively.
- Leave ambiguous or unreadable fragments empty instead of inventing content.
```

## list_item

- Output format: `markdown`

```text
You are given one cropped image region from a document page.
HARD REQUIREMENTS:
- Return output as JSON only: {"content":"..."}
- Return exactly one top-level key: "content".
- The value of "content" must be a string.
- Do not add any other keys.
- Do not wrap output in markdown/code fences.
- Do not add explanations, comments, or metadata outside JSON.
- Do not add content that is not visible.
- Do not translate, paraphrase, summarize, or alter meaning.
- Do not intentionally omit readable legitimate content.
- When rules conflict: preserve visible content semantics first, then source fidelity, then formatting.
SOURCE FIDELITY:
- Extract only content visible inside this crop.
- Do not dehyphenate words split by line breaks.
- Preserve visible punctuation exactly.
CLASS-SPECIFIC REQUIREMENTS:
- Treat this crop as exactly one list item.
- Preserve the visible list marker exactly when present (for example: -, *, •, 1., 2), a), б)).
- If no explicit marker is visible, return only the item text; do not invent marker symbols or numbering.
- If marker visibility is ambiguous, keep item text conservative; downstream normalization may apply marker formatting.
- Do not merge this item with neighboring items and do not split it into multiple items.
- Preserve visible indentation/alignment cues as much as possible within one-item output.
- Do not convert into heading, paragraph prose, or table.
- Keep punctuation and line breaks exactly as visible.
- If any fragment is visible but unreadable, keep it empty rather than inventing text.
OUTPUT FORMAT REQUIREMENTS:
The "content" string must be valid Markdown.
- Preserve line breaks exactly as shown in the crop.
IF UNSURE:
- Prefer conservative extraction over guessing.
- Keep visible text/tokens as-is rather than normalizing aggressively.
- Leave ambiguous or unreadable fragments empty instead of inventing content.
```

## table

- Output format: `html`

```text
You are given one cropped image region from a document page.
HARD REQUIREMENTS:
- Return output as JSON only: {"content":"..."}
- Return exactly one top-level key: "content".
- The value of "content" must be a string.
- Do not add any other keys.
- Do not wrap output in markdown/code fences.
- Do not add explanations, comments, or metadata outside JSON.
- Do not add content that is not visible.
- Do not translate, paraphrase, summarize, or alter meaning.
- Do not intentionally omit readable legitimate content.
- When rules conflict: preserve visible content semantics first, then source fidelity, then formatting.
SOURCE FIDELITY:
- Extract only content visible inside this crop.
- Do not dehyphenate words split by line breaks.
- Preserve visible punctuation exactly.
CLASS-SPECIFIC REQUIREMENTS:
- Treat this crop as a table extraction task.
- Treat tabular alignment as table structure even when grid lines are faint, partial, or absent.
- Infer rows and columns from alignment/spacing only when clearly supported by visual layout.
- Infer structure conservatively and never invent unseen text.
- If structure is ambiguous, prefer conservative segmentation and do not invent extra rows or columns.
- Preserve table structure exactly as visible: row order, column order, and cell boundaries.
- Use semantic HTML tags: <table>, <thead>, <tbody>, <tr>, <th>, <td>.
- Use <thead> and <tbody> only when clearly inferable.
- Use <th> only when header role is clearly visible; otherwise use <td>.
- Preserve merged cells using rowspan/colspan when clearly visible.
- If a cell is visibly empty, output it as an empty cell.
- If cell text is unreadable, keep the cell and leave its content empty; do not invent text.
- Preserve visible line breaks inside a cell using <br> only when clearly visible.
- Do not infer or reconstruct hidden rows/columns outside crop boundaries.
- Do not add CSS, classes, style attributes, wrapper tags, or Markdown table syntax.
OUTPUT FORMAT REQUIREMENTS:
The "content" string must be only one HTML <table>...</table> block.
- Preserve visible line breaks inside a table cell using <br> only when clearly visible.
IF UNSURE:
- Prefer conservative extraction over guessing.
- Keep visible text/tokens as-is rather than normalizing aggressively.
- Leave ambiguous or unreadable fragments empty instead of inventing content.
```

## picture

- Output format: `skip`
- Prompt: _not sent (class is skipped)_

## picture_text

- Output format: `markdown`

```text
You are given one cropped image region from a document page.
HARD REQUIREMENTS:
- Return output as JSON only: {"content":"..."}
- Return exactly one top-level key: "content".
- The value of "content" must be a string.
- Do not add any other keys.
- Do not wrap output in markdown/code fences.
- Do not add explanations, comments, or metadata outside JSON.
- Do not add content that is not visible.
- Do not translate, paraphrase, summarize, or alter meaning.
- Do not intentionally omit readable legitimate content.
- When rules conflict: preserve visible content semantics first, then source fidelity, then formatting.
SOURCE FIDELITY:
- Extract only content visible inside this crop.
- Do not dehyphenate words split by line breaks.
- Preserve visible punctuation exactly.
CLASS-SPECIFIC REQUIREMENTS:
- Primary script is Tatar Cyrillic; preserve original characters exactly. Words from other languages may appear and must be preserved.
- Keep text as normal Markdown paragraphs.
- Do not convert into headings, lists, or tables unless those markers are clearly visible.
- Apply emphasis only when clearly visible: **bold**, *italic*, ***bold italic***.
- Do not guess or apply formatting arbitrarily.
- Inline formulas inside text must use LaTeX inline syntax: $...$.
- Keep formulas inline with surrounding sentence text.
- Do not turn regular words into formulas.
- Do not convert the whole text block into a standalone formula block.
- If formula notation is unclear, keep the visible text as-is.
- Preserve visible superscript/subscript formatting.
- Encode superscripts/subscripts as inline HTML in Markdown: <sup>...</sup> and <sub>...</sub>.
- Do not invent superscript/subscript where it is not clearly visible.
- One-shot example (text-like crop):
  EXAMPLE INPUT START
  Без съезддагы фикер алышуларның һәм тавыш бирүләрнең
  анализын тәмам иттек; бу анализ съезддан соң булган хәл-
  ләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм
  EXAMPLE INPUT END
  EXAMPLE OUTPUT START
  {"content":"Без съезддагы фикер алышуларның һәм тавыш бирүләрнең\nанализын тәмам иттек; бу анализ съезддан соң булган хәл-\nләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм"}
  EXAMPLE OUTPUT END
OUTPUT FORMAT REQUIREMENTS:
The "content" string must be valid Markdown.
- Preserve line breaks exactly as shown in the crop.
IF UNSURE:
- Prefer conservative extraction over guessing.
- Keep visible text/tokens as-is rather than normalizing aggressively.
- Leave ambiguous or unreadable fragments empty instead of inventing content.
```

## caption

- Output format: `markdown`

```text
You are given one cropped image region from a document page.
HARD REQUIREMENTS:
- Return output as JSON only: {"content":"..."}
- Return exactly one top-level key: "content".
- The value of "content" must be a string.
- Do not add any other keys.
- Do not wrap output in markdown/code fences.
- Do not add explanations, comments, or metadata outside JSON.
- Do not add content that is not visible.
- Do not translate, paraphrase, summarize, or alter meaning.
- Do not intentionally omit readable legitimate content.
- When rules conflict: preserve visible content semantics first, then source fidelity, then formatting.
SOURCE FIDELITY:
- Extract only content visible inside this crop.
- Do not dehyphenate words split by line breaks.
- Preserve visible punctuation exactly.
CLASS-SPECIFIC REQUIREMENTS:
- Keep this content as caption text only.
- Do not convert caption text into heading, list, or table.
- Preserve caption labels/prefixes exactly when visible (for example: Figure, Fig., Table, Рис.).
- Preserve caption numbering/indexes exactly as visible.
- Preserve references to targets exactly as written; do not invent new target identifiers.
- Preserve punctuation and separators exactly as visible.
- If caption spans multiple lines, preserve line breaks exactly as shown.
OUTPUT FORMAT REQUIREMENTS:
The "content" string must be valid Markdown.
- Preserve line breaks exactly as shown in the crop.
IF UNSURE:
- Prefer conservative extraction over guessing.
- Keep visible text/tokens as-is rather than normalizing aggressively.
- Leave ambiguous or unreadable fragments empty instead of inventing content.
```

## footnote

- Output format: `markdown`

```text
You are given one cropped image region from a document page.
HARD REQUIREMENTS:
- Return output as JSON only: {"content":"..."}
- Return exactly one top-level key: "content".
- The value of "content" must be a string.
- Do not add any other keys.
- Do not wrap output in markdown/code fences.
- Do not add explanations, comments, or metadata outside JSON.
- Do not add content that is not visible.
- Do not translate, paraphrase, summarize, or alter meaning.
- Do not intentionally omit readable legitimate content.
- When rules conflict: preserve visible content semantics first, then source fidelity, then formatting.
SOURCE FIDELITY:
- Extract only content visible inside this crop.
- Do not dehyphenate words split by line breaks.
- Preserve visible punctuation exactly.
CLASS-SPECIFIC REQUIREMENTS:
- Primary script is Tatar Cyrillic; preserve original characters exactly. Words from other languages may appear and must be preserved.
- Keep text as normal Markdown paragraphs.
- Do not convert into headings, lists, or tables unless those markers are clearly visible.
- Apply emphasis only when clearly visible: **bold**, *italic*, ***bold italic***.
- Do not guess or apply formatting arbitrarily.
- Inline formulas inside text must use LaTeX inline syntax: $...$.
- Keep formulas inline with surrounding sentence text.
- Do not turn regular words into formulas.
- Do not convert the whole text block into a standalone formula block.
- If formula notation is unclear, keep the visible text as-is.
- Preserve visible superscript/subscript formatting.
- Encode superscripts/subscripts as inline HTML in Markdown: <sup>...</sup> and <sub>...</sub>.
- Do not invent superscript/subscript where it is not clearly visible.
- One-shot example (text-like crop):
  EXAMPLE INPUT START
  Без съезддагы фикер алышуларның һәм тавыш бирүләрнең
  анализын тәмам иттек; бу анализ съезддан соң булган хәл-
  ләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм
  EXAMPLE INPUT END
  EXAMPLE OUTPUT START
  {"content":"Без съезддагы фикер алышуларның һәм тавыш бирүләрнең\nанализын тәмам иттек; бу анализ съезддан соң булган хәл-\nләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм"}
  EXAMPLE OUTPUT END
- Keep content as literal footnote text.
- Do not convert output to Markdown footnote syntax (for example: [^1] or [^1]: ...).
OUTPUT FORMAT REQUIREMENTS:
The "content" string must be valid Markdown.
- Preserve line breaks exactly as shown in the crop.
IF UNSURE:
- Prefer conservative extraction over guessing.
- Keep visible text/tokens as-is rather than normalizing aggressively.
- Leave ambiguous or unreadable fragments empty instead of inventing content.
```

## formula

- Output format: `latex`

```text
You are given one cropped image region from a document page.
HARD REQUIREMENTS:
- Return output as JSON only: {"content":"..."}
- Return exactly one top-level key: "content".
- The value of "content" must be a string.
- Do not add any other keys.
- Do not wrap output in markdown/code fences.
- Do not add explanations, comments, or metadata outside JSON.
- Do not add content that is not visible.
- Do not translate, paraphrase, summarize, or alter meaning.
- Do not intentionally omit readable legitimate content.
- When rules conflict: preserve visible content semantics first, then source fidelity, then formatting.
SOURCE FIDELITY:
- Extract only content visible inside this crop.
- Do not dehyphenate words split by line breaks.
- Preserve visible punctuation exactly.
CLASS-SPECIFIC REQUIREMENTS:
- Your task is to extract a standalone display formula from this crop.
- The output must be LaTeX formula text only.
- Represent the formula in LaTeX as faithfully as possible.
- Preserve symbols, operators, and structure exactly as visible.
- If exact LaTeX mapping is unclear, preserve visible tokens conservatively and do not invent missing parts.
- Preserve line breaks when they are part of the visible formula layout.
- Do not include prose, labels, or explanations.
- Do not wrap output in $...$ or $$...$$.
- Do not output Markdown formatting.
OUTPUT FORMAT REQUIREMENTS:
The "content" string must be only LaTeX expression text, without Markdown wrappers.
- Preserve line breaks only when they are part of the visible formula layout.
IF UNSURE:
- Prefer conservative extraction over guessing.
- Keep visible text/tokens as-is rather than normalizing aggressively.
- Leave ambiguous or unreadable fragments empty instead of inventing content.
```

## page_header

- Output format: `markdown`

```text
You are given one cropped image region from a document page.
HARD REQUIREMENTS:
- Return output as JSON only: {"content":"..."}
- Return exactly one top-level key: "content".
- The value of "content" must be a string.
- Do not add any other keys.
- Do not wrap output in markdown/code fences.
- Do not add explanations, comments, or metadata outside JSON.
- Do not add content that is not visible.
- Do not translate, paraphrase, summarize, or alter meaning.
- Do not intentionally omit readable legitimate content.
- When rules conflict: preserve visible content semantics first, then source fidelity, then formatting.
SOURCE FIDELITY:
- Extract only content visible inside this crop.
- Do not dehyphenate words split by line breaks.
- Preserve visible punctuation exactly.
CLASS-SPECIFIC REQUIREMENTS:
- Primary script is Tatar Cyrillic; preserve original characters exactly. Words from other languages may appear and must be preserved.
- Keep text as normal Markdown paragraphs.
- Do not convert into headings, lists, or tables unless those markers are clearly visible.
- Apply emphasis only when clearly visible: **bold**, *italic*, ***bold italic***.
- Do not guess or apply formatting arbitrarily.
- Inline formulas inside text must use LaTeX inline syntax: $...$.
- Keep formulas inline with surrounding sentence text.
- Do not turn regular words into formulas.
- Do not convert the whole text block into a standalone formula block.
- If formula notation is unclear, keep the visible text as-is.
- Preserve visible superscript/subscript formatting.
- Encode superscripts/subscripts as inline HTML in Markdown: <sup>...</sup> and <sub>...</sub>.
- Do not invent superscript/subscript where it is not clearly visible.
- One-shot example (text-like crop):
  EXAMPLE INPUT START
  Без съезддагы фикер алышуларның һәм тавыш бирүләрнең
  анализын тәмам иттек; бу анализ съезддан соң булган хәл-
  ләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм
  EXAMPLE INPUT END
  EXAMPLE OUTPUT START
  {"content":"Без съезддагы фикер алышуларның һәм тавыш бирүләрнең\nанализын тәмам иттек; бу анализ съезддан соң булган хәл-\nләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм"}
  EXAMPLE OUTPUT END
OUTPUT FORMAT REQUIREMENTS:
The "content" string must be valid Markdown.
- Preserve line breaks exactly as shown in the crop.
IF UNSURE:
- Prefer conservative extraction over guessing.
- Keep visible text/tokens as-is rather than normalizing aggressively.
- Leave ambiguous or unreadable fragments empty instead of inventing content.
```

## page_footer

- Output format: `markdown`

```text
You are given one cropped image region from a document page.
HARD REQUIREMENTS:
- Return output as JSON only: {"content":"..."}
- Return exactly one top-level key: "content".
- The value of "content" must be a string.
- Do not add any other keys.
- Do not wrap output in markdown/code fences.
- Do not add explanations, comments, or metadata outside JSON.
- Do not add content that is not visible.
- Do not translate, paraphrase, summarize, or alter meaning.
- Do not intentionally omit readable legitimate content.
- When rules conflict: preserve visible content semantics first, then source fidelity, then formatting.
SOURCE FIDELITY:
- Extract only content visible inside this crop.
- Do not dehyphenate words split by line breaks.
- Preserve visible punctuation exactly.
CLASS-SPECIFIC REQUIREMENTS:
- Primary script is Tatar Cyrillic; preserve original characters exactly. Words from other languages may appear and must be preserved.
- Keep text as normal Markdown paragraphs.
- Do not convert into headings, lists, or tables unless those markers are clearly visible.
- Apply emphasis only when clearly visible: **bold**, *italic*, ***bold italic***.
- Do not guess or apply formatting arbitrarily.
- Inline formulas inside text must use LaTeX inline syntax: $...$.
- Keep formulas inline with surrounding sentence text.
- Do not turn regular words into formulas.
- Do not convert the whole text block into a standalone formula block.
- If formula notation is unclear, keep the visible text as-is.
- Preserve visible superscript/subscript formatting.
- Encode superscripts/subscripts as inline HTML in Markdown: <sup>...</sup> and <sub>...</sub>.
- Do not invent superscript/subscript where it is not clearly visible.
- One-shot example (text-like crop):
  EXAMPLE INPUT START
  Без съезддагы фикер алышуларның һәм тавыш бирүләрнең
  анализын тәмам иттек; бу анализ съезддан соң булган хәл-
  ләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм
  EXAMPLE INPUT END
  EXAMPLE OUTPUT START
  {"content":"Без съезддагы фикер алышуларның һәм тавыш бирүләрнең\nанализын тәмам иттек; бу анализ съезддан соң булган хәл-\nләрнең бөтенесен in nuce (яралгы хәлендә) аңлатып бирә, һәм"}
  EXAMPLE OUTPUT END
OUTPUT FORMAT REQUIREMENTS:
The "content" string must be valid Markdown.
- Preserve line breaks exactly as shown in the crop.
IF UNSURE:
- Prefer conservative extraction over guessing.
- Keep visible text/tokens as-is rather than normalizing aggressively.
- Leave ambiguous or unreadable fragments empty instead of inventing content.
```

