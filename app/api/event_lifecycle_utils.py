from __future__ import annotations

from typing import Any

from ..pipeline_runtime import emit_event


def emit_lifecycle_started(
    *,
    stage: str,
    event_type: str,
    message: str,
    page_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    emit_event(
        stage=stage,
        event_type=event_type,
        page_id=page_id,
        message=message,
        data=data,
    )


def emit_lifecycle_failed(
    *,
    stage: str,
    event_type: str,
    error: Exception | str,
    message_prefix: str,
    page_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    emit_event(
        stage=stage,
        event_type=event_type,
        page_id=page_id,
        message=f"{message_prefix}: {error}",
        data=data,
    )


def emit_lifecycle_completed(
    *,
    stage: str,
    event_type: str,
    message: str,
    page_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    emit_event(
        stage=stage,
        event_type=event_type,
        page_id=page_id,
        message=message,
        data=data,
    )
