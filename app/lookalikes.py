from __future__ import annotations

from typing import Any
import re
import unicodedata

FENCE_RE = re.compile(r"^(?P<fence>`{3,}|~{3,})")
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
WORD_RE = re.compile(r"\w+", flags=re.UNICODE)

LOOKALIKE_TO_TATAR: dict[str, str] = {}
for _chars, _target in (
    ("ə", "ә"),
    ("Ə", "Ә"),
    ("eėĕẹéèêëēěęẽẻȅȇếềểễệ", "е"),
    ("EĖĔẸÉÈÊËĒĚĘẼẺȄȆẾỀỂỄỆ", "Е"),
    ("oọőôöòóõøōŏȯȱỏốồổỗộ", "о"),
    ("OỌŐÔÖÒÓÕØŌŎȮȰỎỐỒỔỖỘ", "О"),
    ("aàáâãäåāăąȁȃȧȩǎǟǡǻ", "а"),
    ("AÀÁÂÃÄÅĀĂĄȀȂȦȨǍǞǠǺ", "А"),
    ("yýỳỹỷỵȳÿ", "у"),
    ("YÝỲỸỶỴȲŸ", "У"),
    ("cƈċ", "с"),
    ("CƇĊ", "С"),
    ("xẋẍҳӽӿ", "х"),
    ("XẊẌҲӼӾ", "Х"),
    ("pṗṕ", "р"),
    ("PṖṔ", "Р"),
    ("hħḥḧḩḫḣ", "һ"),
    ("HĦḤḦḨḪḢ", "Һ"),
    ("kķĸқҡҟҝќ", "к"),
    ("KĶҚҠҞҜЌ", "К"),
    ("ґғ", "г"),
    ("ҐҒ", "Г"),
):
    for _ch in _chars:
        LOOKALIKE_TO_TATAR[_ch] = _target


def normalize_text_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", str(text or ""))


def detect_suspicious_lookalikes(
    text: str,
    *,
    markdown_code_aware: bool = True,
    max_warnings: int = 200,
) -> list[dict[str, Any]]:
    if max_warnings <= 0:
        return []

    normalized = normalize_text_nfc(text)
    warnings: list[dict[str, Any]] = []
    in_fence = False
    fence_char: str | None = None
    fence_len = 0

    for line_index, line in enumerate(normalized.splitlines()):
        if markdown_code_aware:
            fence_match = FENCE_RE.match(line)
            if fence_match:
                fence = fence_match.group("fence")
                if not in_fence:
                    in_fence = True
                    fence_char = fence[0]
                    fence_len = len(fence)
                elif fence_char and line.startswith(fence_char * fence_len):
                    in_fence = False
                    fence_char = None
                    fence_len = 0
                continue
            if in_fence:
                continue
            segments = _non_code_segments(line)
        else:
            segments = [(line, 0)]

        for segment_text, segment_offset in segments:
            segment_has_cyrillic = bool(CYRILLIC_RE.search(segment_text))
            for match in WORD_RE.finditer(segment_text):
                token = match.group(0)
                token_has_cyrillic = bool(CYRILLIC_RE.search(token))
                token_letter_count = sum(1 for char in token if str(char).isalpha())
                normalized_token_chars: list[str] = []
                replacements: list[dict[str, str]] = []
                for char in token:
                    mapped = LOOKALIKE_TO_TATAR.get(char, char)
                    normalized_token_chars.append(mapped)
                    if mapped != char:
                        replacements.append({"from": char, "to": mapped})
                if not replacements:
                    continue
                if not token_has_cyrillic:
                    if not segment_has_cyrillic:
                        continue
                    if token_letter_count != 1:
                        continue
                token_start = int(segment_offset + match.start())
                token_end = int(segment_offset + match.end())
                warnings.append(
                    {
                        "line_index": int(line_index),
                        "line_number": int(line_index + 1),
                        "token": token,
                        "normalized_token": "".join(normalized_token_chars),
                        "token_start": token_start,
                        "token_end": token_end,
                        "replacements": replacements,
                    }
                )
                if len(warnings) >= max_warnings:
                    return warnings
    return warnings


def _non_code_segments(line: str) -> list[tuple[str, int]]:
    segments: list[tuple[str, int]] = []
    start = 0
    index = 0
    length = len(line)

    while index < length:
        backtick = line.find("`", index)
        if backtick < 0:
            if start < length:
                segments.append((line[start:], start))
            break

        if backtick > start:
            segments.append((line[start:backtick], start))

        run_end = backtick
        while run_end < length and line[run_end] == "`":
            run_end += 1
        delimiter = line[backtick:run_end]
        closing_index = line.find(delimiter, run_end)
        if closing_index < 0:
            start = run_end
            index = run_end
            continue

        start = closing_index + len(delimiter)
        index = start

    return segments
