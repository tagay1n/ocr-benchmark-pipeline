from __future__ import annotations

import base64
import json
import re
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

GEMINI_MODEL = "gemini-3-flash-preview"
DEFAULT_GEMINI_TEMPERATURE = 0.0


def key_alias(api_key: str) -> str:
    if len(api_key) <= 8:
        return api_key
    return f"{api_key[:4]}...{api_key[-4:]}"


def extract_text_from_response(payload: dict[str, Any]) -> str:
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


def extract_content_from_json_response(raw_text: str) -> str:
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


def gemini_generate_content(
    api_key: str,
    prompt: str,
    image_bytes: bytes,
    *,
    temperature: float = DEFAULT_GEMINI_TEMPERATURE,
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

    raw_output = extract_text_from_response(response_payload)
    if not raw_output:
        raise RuntimeError("Gemini request returned an empty response.")
    return extract_content_from_json_response(raw_output)


def is_quota_error(message: str) -> bool:
    normalized = message.lower()
    return (
        "http 429" in normalized
        or "resource_exhausted" in normalized
        or "quota" in normalized
        or "rate limit" in normalized
    )


def is_gemini_server_error(message: str) -> bool:
    normalized = str(message).strip().lower()
    if not normalized:
        return False
    if re.search(r"http\s+5\d\d", normalized):
        return True
    server_error_markers = (
        "timed out",
        "timeout",
        "connection reset",
        "connection aborted",
        "connection refused",
        "temporarily unavailable",
        "service unavailable",
        "internal error",
        "internal server error",
        "bad gateway",
        "gateway timeout",
    )
    return any(marker in normalized for marker in server_error_markers)

