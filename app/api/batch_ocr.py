from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select, update

from ..db import get_session
from ..models import Layout, OcrOutput, Page, PipelineJob
from ..pipeline_constants import (
    EVENT_JOB_ENQUEUED,
    EVENT_JOB_ENQUEUE_SKIPPED,
    EVENT_JOB_PROGRESS,
    STAGE_OCR_EXTRACT,
)
from ..pipeline_runtime import emit_event, enqueue_job as _enqueue_job, register_default_handlers

router = APIRouter()

BATCH_OCR_TRIGGER = "batch_ocr"
_ELIGIBLE_PAGE_STATUSES = ("layout_reviewed", "ocr_failed", "LAYOUT_REVIEWED", "OCR_FAILED")
_ACTIVE_JOB_STATUSES = ("queued", "running")


def _enqueue_job_dynamic():
    from .. import main as main_module

    return getattr(main_module, "enqueue_job", _enqueue_job)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _load_job_payload(raw_payload: str | None) -> dict[str, Any]:
    if not raw_payload:
        return {}
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_job_result(raw_result: str | None) -> dict[str, Any]:
    if not raw_result:
        return {}
    try:
        result = json.loads(raw_result)
    except json.JSONDecodeError:
        return {}
    return result if isinstance(result, dict) else {}


def _is_batch_ocr_payload(payload: dict[str, Any]) -> bool:
    return str(payload.get("trigger", "")).strip().lower() == BATCH_OCR_TRIGGER


def _batch_run_id_from_payload(payload: dict[str, Any], *, fallback_job_id: int) -> str:
    raw_run_id = str(payload.get("batch_run_id", "")).strip()
    if raw_run_id:
        return raw_run_id
    return f"legacy:{fallback_job_id}"


def _job_layout_ids(payload: dict[str, Any]) -> list[int]:
    raw_layout_ids = payload.get("layout_ids")
    if not isinstance(raw_layout_ids, list):
        return []
    layout_ids: list[int] = []
    for raw_layout_id in raw_layout_ids:
        try:
            layout_id = int(raw_layout_id)
        except (TypeError, ValueError):
            continue
        if layout_id > 0:
            layout_ids.append(layout_id)
    return layout_ids


def _job_total_layouts(payload: dict[str, Any]) -> int:
    layout_ids = _job_layout_ids(payload)
    if layout_ids:
        return len(layout_ids)
    try:
        fallback_total = int(payload.get("batch_total_layouts"))
    except (TypeError, ValueError):
        fallback_total = 0
    return max(0, fallback_total)


def _job_processed_layouts(*, status: str, payload: dict[str, Any], result: dict[str, Any]) -> int:
    total_layouts = _job_total_layouts(payload)
    if status == "queued":
        return 0
    if status == "running":
        progress = result.get("progress")
        if isinstance(progress, dict):
            try:
                processed = int(progress.get("processed_layouts", 0))
            except (TypeError, ValueError):
                processed = 0
            return max(0, min(total_layouts, processed))
        return 0
    if status == "completed":
        try:
            extracted = int(result.get("extracted_count", 0))
        except (TypeError, ValueError):
            extracted = 0
        try:
            skipped = int(result.get("skipped_count", 0))
        except (TypeError, ValueError):
            skipped = 0
        completed = extracted + skipped
        if completed <= 0:
            completed = total_layouts
        return max(0, min(total_layouts, completed))
    if status == "failed":
        progress = result.get("progress")
        if isinstance(progress, dict):
            try:
                processed = int(progress.get("processed_layouts", 0))
            except (TypeError, ValueError):
                processed = 0
            return max(0, min(total_layouts, processed))
        return 0
    return 0


def _pending_layout_ids_by_page() -> dict[int, list[int]]:
    with get_session() as session:
        rows = session.execute(
            select(Layout.page_id, Layout.id)
            .join(Page, Page.id == Layout.page_id)
            .outerjoin(OcrOutput, OcrOutput.layout_id == Layout.id)
            .where(Page.is_missing.is_(False))
            .where(Page.status.in_(_ELIGIBLE_PAGE_STATUSES))
            .where(OcrOutput.layout_id.is_(None))
            .order_by(Layout.page_id.asc(), Layout.reading_order.asc(), Layout.id.asc())
        ).all()

    output: dict[int, list[int]] = {}
    for page_id, layout_id in rows:
        key = int(page_id)
        output.setdefault(key, []).append(int(layout_id))
    return output


def _active_batch_job_counts() -> tuple[int, int]:
    with get_session() as session:
        jobs = session.execute(
            select(PipelineJob.status, PipelineJob.payload_json)
            .where(PipelineJob.stage == STAGE_OCR_EXTRACT)
            .where(PipelineJob.status.in_(_ACTIVE_JOB_STATUSES))
        ).all()

    running = 0
    queued = 0
    for status, payload_json in jobs:
        payload = _load_job_payload(payload_json)
        if not _is_batch_ocr_payload(payload):
            continue
        if str(status) == "running":
            running += 1
        elif str(status) == "queued":
            queued += 1
    return running, queued


def _active_batch_run_progress() -> tuple[int, int]:
    with get_session() as session:
        rows = session.execute(
            select(
                PipelineJob.id,
                PipelineJob.status,
                PipelineJob.payload_json,
                PipelineJob.result_json,
            )
            .where(PipelineJob.stage == STAGE_OCR_EXTRACT)
            .order_by(PipelineJob.id.asc())
        ).all()

    run_rows: dict[str, list[tuple[str, dict[str, Any], dict[str, Any], int]]] = {}
    active_run_id: str | None = None
    active_run_latest_job_id = -1

    for row_id, status_raw, payload_json, result_json in rows:
        payload = _load_job_payload(payload_json)
        if not _is_batch_ocr_payload(payload):
            continue
        status = str(status_raw)
        result = _load_job_result(result_json)
        run_id = _batch_run_id_from_payload(payload, fallback_job_id=int(row_id))
        run_rows.setdefault(run_id, []).append((status, payload, result, int(row_id)))
        if status in _ACTIVE_JOB_STATUSES and int(row_id) > active_run_latest_job_id:
            active_run_latest_job_id = int(row_id)
            active_run_id = run_id

    if not active_run_id:
        return 0, 0

    rows_for_run = run_rows.get(active_run_id, [])
    total_layouts = 0
    processed_layouts = 0
    run_total_hint = 0
    for status, payload, result, _job_id in rows_for_run:
        if status not in {"queued", "running", "completed", "failed"}:
            continue
        try:
            hint = int(payload.get("batch_total_layouts", 0))
        except (TypeError, ValueError):
            hint = 0
        run_total_hint = max(run_total_hint, hint)
        total_layouts += _job_total_layouts(payload)
        processed_layouts += _job_processed_layouts(status=status, payload=payload, result=result)

    if run_total_hint > 0:
        total_layouts = max(total_layouts, run_total_hint)
    if total_layouts <= 0:
        return 0, 0
    processed_layouts = max(0, min(total_layouts, processed_layouts))
    return processed_layouts, total_layouts


@router.get("/api/ocr-batch/status")
def batch_ocr_status() -> dict[str, object]:
    register_default_handlers()
    pending_by_page = _pending_layout_ids_by_page()
    running_jobs, queued_jobs = _active_batch_job_counts()
    progress_current, progress_total = _active_batch_run_progress()
    pending_pages = len(pending_by_page)
    pending_layouts = sum(len(layout_ids) for layout_ids in pending_by_page.values())
    is_running = running_jobs > 0 or queued_jobs > 0
    return {
        "is_running": bool(is_running),
        "running_jobs": int(running_jobs),
        "queued_jobs": int(queued_jobs),
        "pending_pages": int(pending_pages),
        "pending_layouts": int(pending_layouts),
        "progress_current": int(progress_current),
        "progress_total": int(progress_total),
    }


@router.post("/api/ocr-batch/run")
def run_batch_ocr_job() -> dict[str, object]:
    register_default_handlers()
    pending_by_page = _pending_layout_ids_by_page()
    considered_pages = len(pending_by_page)
    considered_layouts = sum(len(layout_ids) for layout_ids in pending_by_page.values())
    batch_run_id = _utc_now()
    queued = 0
    already_queued_or_running = 0
    enqueue_job = _enqueue_job_dynamic()

    for page_id, layout_ids in pending_by_page.items():
        enqueued = enqueue_job(
            STAGE_OCR_EXTRACT,
            page_id=int(page_id),
            payload={
                "trigger": BATCH_OCR_TRIGGER,
                "batch_run_id": batch_run_id,
                "batch_total_layouts": int(considered_layouts),
                "layout_ids": [int(layout_id) for layout_id in layout_ids],
                "replace_existing": False,
            },
        )
        if enqueued:
            queued += 1
        else:
            already_queued_or_running += 1

    if queued > 0:
        emit_event(
            stage=STAGE_OCR_EXTRACT,
            event_type=EVENT_JOB_ENQUEUED,
            message=(
                "Queued Batch OCR jobs "
                f"for {queued}/{considered_pages} pages "
                f"({considered_layouts} pending layouts)."
            ),
            data={
                "trigger": BATCH_OCR_TRIGGER,
                "considered_pages": considered_pages,
                "considered_layouts": considered_layouts,
                "queued_pages": queued,
                "already_queued_or_running": already_queued_or_running,
            },
        )
    else:
        emit_event(
            stage=STAGE_OCR_EXTRACT,
            event_type=EVENT_JOB_ENQUEUE_SKIPPED,
            message=(
                "Skipped Batch OCR queue request "
                f"(pending pages: {considered_pages}, already queued/running: {already_queued_or_running})."
            ),
            data={
                "trigger": BATCH_OCR_TRIGGER,
                "considered_pages": considered_pages,
                "considered_layouts": considered_layouts,
                "queued_pages": queued,
                "already_queued_or_running": already_queued_or_running,
            },
        )
    return {
        "enqueued": queued > 0,
        "considered_pages": considered_pages,
        "considered_layouts": considered_layouts,
        "queued_pages": queued,
        "already_queued_or_running": already_queued_or_running,
    }


@router.post("/api/ocr-batch/stop")
def stop_batch_ocr_job() -> dict[str, object]:
    register_default_handlers()
    now = _utc_now()
    queued_ids: list[int] = []
    running_found = False

    with get_session() as session:
        rows = session.execute(
            select(PipelineJob.id, PipelineJob.status, PipelineJob.payload_json)
            .where(PipelineJob.stage == STAGE_OCR_EXTRACT)
            .where(PipelineJob.status.in_(("queued", "running")))
        ).all()

        for row_id, status, payload_json in rows:
            payload = _load_job_payload(payload_json)
            if not _is_batch_ocr_payload(payload):
                continue
            if str(status) == "queued":
                queued_ids.append(int(row_id))
            elif str(status) == "running":
                running_found = True

        if queued_ids:
            session.execute(
                update(PipelineJob)
                .where(PipelineJob.id.in_(queued_ids))
                .values(
                    status="failed",
                    error="Stopped by user request.",
                    finished_at=now,
                    updated_at=now,
                )
            )

    emit_event(
        stage=STAGE_OCR_EXTRACT,
        event_type=EVENT_JOB_PROGRESS,
        message=(
            "Batch OCR stop requested."
            if running_found or bool(queued_ids)
            else "No active Batch OCR job to stop."
        ),
        data={
            "trigger": BATCH_OCR_TRIGGER,
            "running_stop_requested": bool(running_found),
            "queued_cancelled": len(queued_ids),
        },
    )
    return {
        "running_stop_requested": bool(running_found),
        "queued_cancelled": len(queued_ids),
    }
