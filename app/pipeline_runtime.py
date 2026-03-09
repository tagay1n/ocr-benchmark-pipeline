from __future__ import annotations

from datetime import UTC, datetime
import json
from threading import Lock, Thread
from typing import Any, Callable

from sqlalchemy import and_, func, or_, select, update

from .db import get_session
from .layouts import detect_layouts_for_page
from .models import Page, PipelineEvent, PipelineJob
from .ocr_extract import extract_ocr_for_page
from .pipeline_constants import (
    EVENT_JOB_COMPLETED,
    EVENT_JOB_FAILED,
    EVENT_JOB_QUEUED,
    EVENT_JOB_STARTED,
    STAGE_LAYOUT_DETECT,
    STAGE_OCR_EXTRACT,
    stage_display_name,
)

JobHandler = Callable[[dict[str, Any]], dict[str, Any] | None]

_HANDLERS: dict[str, JobHandler] = {}
_HANDLERS_LOCK = Lock()
_ENQUEUE_LOCK = Lock()

_WORKER_THREAD: Thread | None = None
_WORKER_LOCK = Lock()

_DEFAULT_HANDLERS_REGISTERED = False


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def register_stage_handler(stage: str, handler: JobHandler) -> None:
    with _HANDLERS_LOCK:
        _HANDLERS[stage] = handler


def emit_event(
    *,
    stage: str,
    event_type: str,
    message: str,
    page_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    with get_session() as session:
        session.add(
            PipelineEvent(
                ts=_utc_now(),
                stage=stage,
                event_type=event_type,
                page_id=page_id,
                message=message,
                data_json=None if data is None else _json_dumps(data),
            )
        )


def register_default_handlers() -> None:
    global _DEFAULT_HANDLERS_REGISTERED
    if _DEFAULT_HANDLERS_REGISTERED:
        return
    register_stage_handler(STAGE_LAYOUT_DETECT, _layout_detect_handler)
    register_stage_handler(STAGE_OCR_EXTRACT, _ocr_extract_handler)
    _DEFAULT_HANDLERS_REGISTERED = True


def _ensure_worker_running() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return
        _WORKER_THREAD = Thread(target=_worker_loop, name="pipeline-worker", daemon=True)
        _WORKER_THREAD.start()


def _claim_next_job() -> dict[str, Any] | None:
    while True:
        with get_session() as session:
            row = session.execute(
                select(PipelineJob)
                .where(PipelineJob.status == "queued")
                .order_by(PipelineJob.id.asc())
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None

            now = _utc_now()
            updated = session.execute(
                update(PipelineJob)
                .where(PipelineJob.id == row.id)
                .where(PipelineJob.status == "queued")
                .values(
                    status="running",
                    attempts=int(row.attempts) + 1,
                    started_at=row.started_at or now,
                    updated_at=now,
                )
            )
            if int(updated.rowcount or 0) == 1:
                return {
                    "id": int(row.id),
                    "stage": row.stage,
                    "page_id": None if row.page_id is None else int(row.page_id),
                    "payload": _json_loads(row.payload_json),
                }


def _finalize_job_success(job_id: int, result: dict[str, Any] | None) -> None:
    now = _utc_now()
    with get_session() as session:
        session.execute(
            update(PipelineJob)
            .where(PipelineJob.id == job_id)
            .values(
                status="completed",
                result_json=None if result is None else _json_dumps(result),
                error=None,
                finished_at=now,
                updated_at=now,
            )
        )


def _finalize_job_failure(job_id: int, error: str) -> None:
    now = _utc_now()
    with get_session() as session:
        session.execute(
            update(PipelineJob)
            .where(PipelineJob.id == job_id)
            .values(
                status="failed",
                error=error,
                finished_at=now,
                updated_at=now,
            )
        )


def _completion_message(stage: str, result: dict[str, Any] | None) -> str:
    if not result:
        return f"Completed {stage_display_name(stage)}."
    if result.get("skipped"):
        reason = str(result.get("reason") or "not applicable")
        return f"Skipped {stage_display_name(stage)}: {reason}."
    if stage == STAGE_LAYOUT_DETECT:
        created = int(result.get("created", 0))
        return f"Completed layout detection, created {created} regions."
    if stage == STAGE_OCR_EXTRACT:
        extracted = int(result.get("extracted_count", 0))
        skipped = int(result.get("skipped_count", 0))
        requests = int(result.get("requests_count", 0))
        return f"Completed OCR extraction, extracted {extracted}, skipped {skipped}, Gemini requests {requests}."
    return f"Completed {stage_display_name(stage)}."


def _worker_loop() -> None:
    global _WORKER_THREAD
    while True:
        job = _claim_next_job()
        if job is None:
            with _WORKER_LOCK:
                _WORKER_THREAD = None
            return

        stage = job["stage"]
        page_id = job["page_id"]
        emit_event(
            stage=stage,
            event_type=EVENT_JOB_STARTED,
            page_id=page_id,
            message=f"Started {stage_display_name(stage)}.",
            data={"job_id": job["id"]},
        )

        with _HANDLERS_LOCK:
            handler = _HANDLERS.get(stage)
        if handler is None:
            error = f"No handler registered for stage '{stage}'."
            _finalize_job_failure(job["id"], error)
            emit_event(
                stage=stage,
                event_type=EVENT_JOB_FAILED,
                page_id=page_id,
                message=error,
                data={"job_id": job["id"]},
            )
            continue

        try:
            result = handler(job) or {}
            _finalize_job_success(job["id"], result)
            emit_event(
                stage=stage,
                event_type=EVENT_JOB_COMPLETED,
                page_id=page_id,
                message=_completion_message(stage, result),
                data={"job_id": job["id"], "result": result},
            )
        except Exception as error:
            error_text = str(error)
            _finalize_job_failure(job["id"], error_text)
            emit_event(
                stage=stage,
                event_type=EVENT_JOB_FAILED,
                page_id=page_id,
                message=error_text,
                data={"job_id": job["id"]},
            )


def enqueue_job(stage: str, *, page_id: int | None, payload: dict[str, Any] | None = None) -> bool:
    payload_json = None if payload is None else _json_dumps(payload)
    # Serialize enqueue dedup checks and inserts to avoid duplicate queued jobs under concurrent requests.
    with _ENQUEUE_LOCK:
        with get_session() as session:
            existing_query = select(PipelineJob.id).where(PipelineJob.stage == stage).where(
                PipelineJob.status.in_(("queued", "running"))
            )
            if page_id is None:
                existing_query = existing_query.where(PipelineJob.page_id.is_(None))
            else:
                existing_query = existing_query.where(PipelineJob.page_id == page_id)
            existing = session.execute(existing_query.limit(1)).scalar_one_or_none()
            if existing is not None:
                return False

            now = _utc_now()
            session.add(
                PipelineJob(
                    stage=stage,
                    page_id=page_id,
                    status="queued",
                    payload_json=payload_json,
                    created_at=now,
                    updated_at=now,
                    attempts=0,
                )
            )

    emit_event(
        stage=stage,
        event_type=EVENT_JOB_QUEUED,
        page_id=page_id,
        message=f"Queued {stage_display_name(stage)}.",
    )
    _ensure_worker_running()
    return True


def enqueue_stage_for_pages(
    stage: str,
    *,
    page_ids: list[int],
    payload_factory: Callable[[int], dict[str, Any]] | None = None,
) -> dict[str, int]:
    queued = 0
    already_queued = 0
    for page_id in page_ids:
        payload = None if payload_factory is None else payload_factory(page_id)
        if enqueue_job(stage, page_id=page_id, payload=payload):
            queued += 1
        else:
            already_queued += 1
    return {
        "considered": len(page_ids),
        "queued": queued,
        "already_queued_or_running": already_queued,
    }


def enqueue_layout_detection_for_new_pages() -> dict[str, int]:
    with get_session() as session:
        rows = session.execute(
            select(Page.id)
            .where(Page.is_missing.is_(False))
            .where(Page.status == "new")
            .order_by(Page.id.asc())
        ).scalars().all()

    page_ids = [int(row) for row in rows]
    return enqueue_stage_for_pages(
        STAGE_LAYOUT_DETECT,
        page_ids=page_ids,
        payload_factory=lambda _page_id: {"trigger": "auto"},
    )


def _layout_detect_handler(job: dict[str, Any]) -> dict[str, Any]:
    page_id = job["page_id"]
    if page_id is None:
        raise ValueError(f"{STAGE_LAYOUT_DETECT} job requires page_id.")

    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if bool(page_row.is_missing):
            return {"skipped": True, "reason": "page is missing"}

        current_status = str(page_row.status)
        if current_status not in {"new", "layout_detecting"}:
            return {"skipped": True, "reason": f"page status is {current_status}"}

        now = _utc_now()
        page_row.status = "layout_detecting"
        page_row.updated_at = now

    try:
        return detect_layouts_for_page(
            page_id,
            replace_existing=True,
            confidence_threshold=None,
            iou_threshold=None,
        )
    except Exception:
        with get_session() as session:
            page_row = session.get(Page, page_id)
            if page_row is not None and not bool(page_row.is_missing):
                page_row.status = "new"
                page_row.updated_at = _utc_now()
        raise


def _ocr_extract_handler(job: dict[str, Any]) -> dict[str, Any]:
    page_id = job["page_id"]
    if page_id is None:
        raise ValueError(f"{STAGE_OCR_EXTRACT} job requires page_id.")

    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise ValueError("Page not found.")
        if bool(page_row.is_missing):
            return {"skipped": True, "reason": "page is missing"}

        current_status = str(page_row.status)
        if current_status not in {"layout_reviewed", "ocr_extracting", "ocr_failed"}:
            return {"skipped": True, "reason": f"page status is {current_status}"}

        page_row.status = "ocr_extracting"
        page_row.updated_at = _utc_now()

    try:
        return extract_ocr_for_page(page_id)
    except Exception:
        with get_session() as session:
            page_row = session.get(Page, page_id)
            if page_row is not None and not bool(page_row.is_missing):
                page_row.status = "ocr_failed"
                page_row.updated_at = _utc_now()
        raise


def get_activity_snapshot(*, limit: int = 30) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 200))
    with get_session() as session:
        running_row = session.execute(
            select(
                PipelineJob.id,
                PipelineJob.stage,
                PipelineJob.page_id,
                PipelineJob.started_at,
                PipelineJob.attempts,
                Page.rel_path,
            )
            .outerjoin(Page, Page.id == PipelineJob.page_id)
            .where(PipelineJob.status == "running")
            .order_by(PipelineJob.started_at.asc(), PipelineJob.id.asc())
            .limit(1)
        ).first()

        queued_rows = session.execute(
            select(
                PipelineJob.id,
                PipelineJob.stage,
                PipelineJob.page_id,
                PipelineJob.created_at,
                Page.rel_path,
            )
            .outerjoin(Page, Page.id == PipelineJob.page_id)
            .where(PipelineJob.status == "queued")
            .order_by(PipelineJob.id.asc())
            .limit(15)
        ).all()

        queued_by_stage_rows = session.execute(
            select(PipelineJob.stage, func.count(PipelineJob.id))
            .where(PipelineJob.status == "queued")
            .group_by(PipelineJob.stage)
            .order_by(PipelineJob.stage)
        ).all()

        events_rows = session.execute(
            select(
                PipelineEvent.id,
                PipelineEvent.ts,
                PipelineEvent.stage,
                PipelineEvent.event_type,
                PipelineEvent.page_id,
                PipelineEvent.message,
                PipelineEvent.data_json,
                Page.rel_path,
            )
            .outerjoin(Page, Page.id == PipelineEvent.page_id)
            .order_by(PipelineEvent.id.desc())
            .limit(safe_limit)
        ).all()

    running = (
        None
        if running_row is None
        else {
            "job_id": int(running_row[0]),
            "stage": running_row[1],
            "page_id": None if running_row[2] is None else int(running_row[2]),
            "rel_path": running_row[5],
            "started_at": running_row[3],
            "attempts": int(running_row[4]),
        }
    )

    queued_preview = [
        {
            "job_id": int(row[0]),
            "stage": row[1],
            "page_id": None if row[2] is None else int(row[2]),
            "rel_path": row[4],
            "created_at": row[3],
        }
        for row in queued_rows
    ]
    queued_by_stage = {str(stage): int(count) for stage, count in queued_by_stage_rows}

    recent_events = [
        {
            "id": int(row[0]),
            "ts": row[1],
            "stage": row[2],
            "event_type": row[3],
            "page_id": None if row[4] is None else int(row[4]),
            "rel_path": row[7],
            "message": row[5],
            "data": _json_loads(row[6]),
        }
        for row in reversed(events_rows)
    ]

    with _WORKER_LOCK:
        worker_running = _WORKER_THREAD is not None and _WORKER_THREAD.is_alive()
    if not worker_running and sum(queued_by_stage.values()) > 0:
        _ensure_worker_running()
        with _WORKER_LOCK:
            worker_running = _WORKER_THREAD is not None and _WORKER_THREAD.is_alive()

    return {
        "worker_running": worker_running,
        "in_progress": running,
        "queued": {
            "total": sum(queued_by_stage.values()),
            "by_stage": queued_by_stage,
            "preview": queued_preview,
        },
        "recent_events": recent_events,
        "registered_stages": sorted(_HANDLERS.keys()),
    }
