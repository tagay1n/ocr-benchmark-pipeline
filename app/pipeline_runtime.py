from __future__ import annotations

from datetime import UTC, datetime
import json
from threading import Lock, Thread
from typing import Any, Callable

from .db import get_connection
from .layouts import detect_layouts_for_page

JobHandler = Callable[[dict[str, Any]], dict[str, Any] | None]

_HANDLERS: dict[str, JobHandler] = {}
_HANDLERS_LOCK = Lock()

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


def _stage_label(stage: str) -> str:
    if stage == "layout_detect":
        return "layout detection"
    if stage == "ocr_extract":
        return "OCR extraction"
    return stage.replace("_", " ")


def emit_event(
    *,
    stage: str,
    event_type: str,
    message: str,
    page_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pipeline_events(ts, stage, event_type, page_id, message, data_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (_utc_now(), stage, event_type, page_id, message, None if data is None else _json_dumps(data)),
        )


def register_default_handlers() -> None:
    global _DEFAULT_HANDLERS_REGISTERED
    if _DEFAULT_HANDLERS_REGISTERED:
        return
    register_stage_handler("layout_detect", _layout_detect_handler)
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
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, stage, page_id, payload_json
                FROM pipeline_jobs
                WHERE status = 'queued'
                ORDER BY id ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None

            now = _utc_now()
            updated = conn.execute(
                """
                UPDATE pipeline_jobs
                SET status = 'running',
                    attempts = attempts + 1,
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, int(row["id"])),
            )
            if updated.rowcount == 1:
                return {
                    "id": int(row["id"]),
                    "stage": row["stage"],
                    "page_id": None if row["page_id"] is None else int(row["page_id"]),
                    "payload": _json_loads(row["payload_json"]),
                }


def _finalize_job_success(job_id: int, result: dict[str, Any] | None) -> None:
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE pipeline_jobs
            SET status = 'completed',
                result_json = ?,
                error = NULL,
                finished_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (None if result is None else _json_dumps(result), now, now, job_id),
        )


def _finalize_job_failure(job_id: int, error: str) -> None:
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE pipeline_jobs
            SET status = 'failed',
                error = ?,
                finished_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (error, now, now, job_id),
        )


def _completion_message(stage: str, result: dict[str, Any] | None) -> str:
    if not result:
        return f"Completed {_stage_label(stage)}."
    if result.get("skipped"):
        reason = str(result.get("reason") or "not applicable")
        return f"Skipped {_stage_label(stage)}: {reason}."
    if stage == "layout_detect":
        created = int(result.get("created", 0))
        return f"Completed layout detection, created {created} regions."
    return f"Completed {_stage_label(stage)}."


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
            event_type="job_started",
            page_id=page_id,
            message=f"Started {_stage_label(stage)}.",
            data={"job_id": job["id"]},
        )

        with _HANDLERS_LOCK:
            handler = _HANDLERS.get(stage)
        if handler is None:
            error = f"No handler registered for stage '{stage}'."
            _finalize_job_failure(job["id"], error)
            emit_event(
                stage=stage,
                event_type="job_failed",
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
                event_type="job_completed",
                page_id=page_id,
                message=_completion_message(stage, result),
                data={"job_id": job["id"], "result": result},
            )
        except Exception as error:
            error_text = str(error)
            _finalize_job_failure(job["id"], error_text)
            emit_event(
                stage=stage,
                event_type="job_failed",
                page_id=page_id,
                message=error_text,
                data={"job_id": job["id"]},
            )


def enqueue_job(stage: str, *, page_id: int | None, payload: dict[str, Any] | None = None) -> bool:
    payload_json = None if payload is None else _json_dumps(payload)
    with get_connection() as conn:
        if page_id is None:
            existing = conn.execute(
                """
                SELECT 1
                FROM pipeline_jobs
                WHERE stage = ? AND page_id IS NULL AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (stage,),
            ).fetchone()
        else:
            existing = conn.execute(
                """
                SELECT 1
                FROM pipeline_jobs
                WHERE stage = ? AND page_id = ? AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (stage, page_id),
            ).fetchone()

        if existing is not None:
            return False

        now = _utc_now()
        conn.execute(
            """
            INSERT INTO pipeline_jobs(stage, page_id, status, payload_json, created_at, updated_at)
            VALUES (?, ?, 'queued', ?, ?, ?)
            """,
            (stage, page_id, payload_json, now, now),
        )

    emit_event(
        stage=stage,
        event_type="job_queued",
        page_id=page_id,
        message=f"Queued {_stage_label(stage)}.",
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
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM pages
            WHERE is_missing = 0 AND status = 'new'
            ORDER BY id ASC
            """
        ).fetchall()

    page_ids = [int(row["id"]) for row in rows]
    return enqueue_stage_for_pages(
        "layout_detect",
        page_ids=page_ids,
        payload_factory=lambda _page_id: {"trigger": "auto"},
    )


def _layout_detect_handler(job: dict[str, Any]) -> dict[str, Any]:
    page_id = job["page_id"]
    if page_id is None:
        raise ValueError("layout_detect job requires page_id.")

    with get_connection() as conn:
        page_row = conn.execute(
            "SELECT id, status, is_missing FROM pages WHERE id = ?",
            (page_id,),
        ).fetchone()
        if page_row is None:
            raise ValueError("Page not found.")
        if int(page_row["is_missing"]) == 1:
            return {"skipped": True, "reason": "page is missing"}

        current_status = str(page_row["status"])
        if current_status not in {"new", "layout_detecting"}:
            return {"skipped": True, "reason": f"page status is {current_status}"}

        now = _utc_now()
        conn.execute(
            "UPDATE pages SET status = 'layout_detecting', updated_at = ? WHERE id = ?",
            (now, page_id),
        )

    try:
        return detect_layouts_for_page(
            page_id,
            replace_existing=True,
            confidence_threshold=None,
            iou_threshold=None,
        )
    except Exception:
        with get_connection() as conn:
            conn.execute(
                "UPDATE pages SET status = 'new', updated_at = ? WHERE id = ? AND is_missing = 0",
                (_utc_now(), page_id),
            )
        raise


def get_activity_snapshot(*, limit: int = 30) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 200))
    with get_connection() as conn:
        running_row = conn.execute(
            """
            SELECT j.id, j.stage, j.page_id, j.started_at, j.attempts, p.rel_path
            FROM pipeline_jobs j
            LEFT JOIN pages p ON p.id = j.page_id
            WHERE j.status = 'running'
            ORDER BY j.started_at ASC, j.id ASC
            LIMIT 1
            """
        ).fetchone()

        queued_rows = conn.execute(
            """
            SELECT j.id, j.stage, j.page_id, j.created_at, p.rel_path
            FROM pipeline_jobs j
            LEFT JOIN pages p ON p.id = j.page_id
            WHERE j.status = 'queued'
            ORDER BY j.id ASC
            LIMIT 15
            """
        ).fetchall()

        queued_by_stage_rows = conn.execute(
            """
            SELECT stage, COUNT(*) AS count
            FROM pipeline_jobs
            WHERE status = 'queued'
            GROUP BY stage
            ORDER BY stage
            """
        ).fetchall()

        events_rows = conn.execute(
            """
            SELECT e.id, e.ts, e.stage, e.event_type, e.page_id, e.message, e.data_json, p.rel_path
            FROM pipeline_events e
            LEFT JOIN pages p ON p.id = e.page_id
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

    running = (
        None
        if running_row is None
        else {
            "job_id": int(running_row["id"]),
            "stage": running_row["stage"],
            "page_id": None if running_row["page_id"] is None else int(running_row["page_id"]),
            "rel_path": running_row["rel_path"],
            "started_at": running_row["started_at"],
            "attempts": int(running_row["attempts"]),
        }
    )

    queued_preview = [
        {
            "job_id": int(row["id"]),
            "stage": row["stage"],
            "page_id": None if row["page_id"] is None else int(row["page_id"]),
            "rel_path": row["rel_path"],
            "created_at": row["created_at"],
        }
        for row in queued_rows
    ]
    queued_by_stage = {row["stage"]: int(row["count"]) for row in queued_by_stage_rows}

    recent_events = [
        {
            "id": int(row["id"]),
            "ts": row["ts"],
            "stage": row["stage"],
            "event_type": row["event_type"],
            "page_id": None if row["page_id"] is None else int(row["page_id"]),
            "rel_path": row["rel_path"],
            "message": row["message"],
            "data": _json_loads(row["data_json"]),
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
