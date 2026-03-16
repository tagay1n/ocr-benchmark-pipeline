from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def resolve_main_callable(attr_name: str, fallback: F) -> F:
    from .. import main as main_module

    resolved = getattr(main_module, str(attr_name), fallback)
    return resolved if callable(resolved) else fallback


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_json_object(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def coerce_int(
    value: Any,
    *,
    default: int = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = int(default)
    if minimum is not None:
        numeric = max(int(minimum), numeric)
    if maximum is not None:
        numeric = min(int(maximum), numeric)
    return numeric
