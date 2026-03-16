from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, Callable, TypeVar

from sqlalchemy import select, update

from ..db import get_session
from ..models import PipelineJob

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


def stop_stage_jobs(
    stage: str,
    *,
    payload_matcher: Callable[[dict[str, Any]], bool] | None = None,
    now_iso: str | None = None,
    stop_error: str = "Stopped by user request.",
) -> dict[str, int | bool]:
    queued_ids: list[int] = []
    running_found = False
    now = str(now_iso or utc_now_iso())

    with get_session() as session:
        rows = session.execute(
            select(PipelineJob.id, PipelineJob.status, PipelineJob.payload_json)
            .where(PipelineJob.stage == str(stage))
            .where(PipelineJob.status.in_(("queued", "running")))
        ).all()

        for row_id, status, payload_json in rows:
            if payload_matcher is not None:
                payload = parse_json_object(payload_json)
                if not payload_matcher(payload):
                    continue
            status_text = str(status)
            if status_text == "queued":
                queued_ids.append(int(row_id))
            elif status_text == "running":
                running_found = True

        if queued_ids:
            session.execute(
                update(PipelineJob)
                .where(PipelineJob.id.in_(queued_ids))
                .values(
                    status="failed",
                    error=str(stop_error),
                    finished_at=now,
                    updated_at=now,
                )
            )

    return {
        "running_found": bool(running_found),
        "queued_cancelled": int(len(queued_ids)),
    }
