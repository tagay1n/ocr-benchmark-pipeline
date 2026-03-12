from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select

from ..db import get_session
from ..discovery import discover_images
from ..layouts import get_page
from ..models import DuplicateFile, Page
from ..pipeline_constants import (
    EVENT_SCAN_FINISHED,
    EVENT_SCAN_STARTED,
    STAGE_DISCOVERY,
)
from ..pipeline_runtime import emit_event


LAYOUT_REVIEW_QUEUE_STATUS = "layout_detected"
LAYOUT_REVIEW_QUEUE_STATUSES = ("layout_detected", "new")
OCR_REVIEW_QUEUE_STATUS = "ocr_done"


def _settings():
    from .. import main as main_module
    from ..config import settings as default_settings

    return getattr(main_module, "settings", default_settings)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _discovery_source_info() -> tuple[str, list[str]]:
    current = _settings()
    return str(current.source_dir), list(current.allowed_extensions)


def _pipeline_stats_snapshot() -> dict[str, int]:
    with get_session() as session:
        total_pages = int(session.query(Page).count())
        missing_pages = int(session.query(Page).filter(Page.is_missing.is_(True)).count())
        active_duplicate_files = int(
            session.query(DuplicateFile).filter(DuplicateFile.active.is_(True)).count()
        )
    return {
        "total_pages": total_pages,
        "missing_pages": missing_pages,
        "active_duplicate_files": active_duplicate_files,
    }


def _scan_finished_message(prefix: str, payload: dict[str, object]) -> str:
    return (
        f"{prefix} "
        f"Scanned: {payload['scanned_files']}, new: {payload['new_pages']}, updated: {payload['updated_pages']}, "
        f"missing marked: {payload['missing_marked']}, duplicates: {payload['duplicate_files']}. "
        f"Total Indexed Pages: {payload['total_pages']}, Missing Pages: {payload['missing_pages']}, "
        f"Active Duplicate Files: {payload['active_duplicate_files']}."
    )


def run_discovery_scan_with_events(
    *,
    trigger: str,
    started_message: str,
    finished_prefix: str,
) -> dict[str, int | str]:
    source_dir, allowed_extensions = _discovery_source_info()
    allowed_text = ", ".join(allowed_extensions)
    emit_event(
        stage=STAGE_DISCOVERY,
        event_type=EVENT_SCAN_STARTED,
        message=f"{started_message} for folder {source_dir} (formats: {allowed_text}).",
        data={
            "trigger": trigger,
            "source_dir": source_dir,
            "allowed_extensions": allowed_extensions,
        },
    )
    summary = discover_images()
    stats_snapshot = _pipeline_stats_snapshot()
    payload: dict[str, int | str] = {
        "source_dir": summary.source_dir,
        "scanned_files": summary.scanned_files,
        "new_pages": summary.new_pages,
        "updated_pages": summary.updated_pages,
        "missing_marked": summary.missing_marked,
        "duplicate_files": summary.duplicate_files,
        **stats_snapshot,
    }
    emit_event(
        stage=STAGE_DISCOVERY,
        event_type=EVENT_SCAN_FINISHED,
        message=_scan_finished_message(finished_prefix, payload),
        data={"trigger": trigger, **payload},
    )
    return payload


def run_startup_scan() -> None:
    run_discovery_scan_with_events(
        trigger="startup",
        started_message="Startup discovery scan started",
        finished_prefix="Startup discovery scan finished.",
    )


def _next_page_response_from_row(row: tuple[object, ...] | None) -> dict[str, object]:
    if row is None:
        return {
            "has_next": False,
            "next_page_id": None,
            "next_page_rel_path": None,
        }
    return {
        "has_next": True,
        "next_page_id": int(row[0]),
        "next_page_rel_path": row[1],
    }


def next_page_for_status(
    *,
    status: str,
    current_page_id: int | None = None,
) -> dict[str, object]:
    with get_session() as session:
        base_query = (
            select(Page.id, Page.rel_path)
            .where(Page.is_missing.is_(False))
            .where(Page.status == status)
        )
        if current_page_id is None:
            row = session.execute(base_query.order_by(Page.id.asc()).limit(1)).first()
            return _next_page_response_from_row(row)

        row = session.execute(
            base_query.where(Page.id > current_page_id).order_by(Page.id.asc()).limit(1)
        ).first()
        if row is None:
            row = session.execute(
                base_query.where(Page.id < current_page_id).order_by(Page.id.asc()).limit(1)
            ).first()
    return _next_page_response_from_row(row)


def next_page_for_statuses(
    *,
    statuses: list[str] | tuple[str, ...],
    current_page_id: int | None = None,
) -> dict[str, object]:
    normalized_statuses = tuple(
        str(status).strip()
        for status in (statuses or [])
        if str(status).strip()
    )
    if not normalized_statuses:
        return _next_page_response_from_row(None)

    with get_session() as session:
        base_query = (
            select(Page.id, Page.rel_path)
            .where(Page.is_missing.is_(False))
            .where(Page.status.in_(normalized_statuses))
        )
        if current_page_id is None:
            row = session.execute(base_query.order_by(Page.id.asc()).limit(1)).first()
            return _next_page_response_from_row(row)

        row = session.execute(
            base_query.where(Page.id > current_page_id).order_by(Page.id.asc()).limit(1)
        ).first()
        if row is None:
            row = session.execute(
                base_query.where(Page.id < current_page_id).order_by(Page.id.asc()).limit(1)
            ).first()
    return _next_page_response_from_row(row)


def ensure_page_exists_or_404(page_id: int) -> None:
    if get_page(page_id) is None:
        raise HTTPException(status_code=404, detail="Page not found.")
