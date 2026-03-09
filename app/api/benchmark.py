from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import select, update

from ..db import get_session
from ..layout_benchmark import (
    BENCHMARK_MODEL_CHECKPOINTS,
    get_latest_benchmark_status,
    get_layout_benchmark_grid,
    request_layout_benchmark_stop,
)
from ..layout_detection_defaults import get_layout_detection_defaults
from ..models import PipelineJob
from ..pipeline_constants import (
    EVENT_JOB_ENQUEUED,
    EVENT_JOB_ENQUEUE_SKIPPED,
    EVENT_JOB_PROGRESS,
    STAGE_LAYOUT_BENCHMARK,
)
from ..pipeline_runtime import emit_event, enqueue_job as _enqueue_job, register_default_handlers
from .schemas import RunLayoutBenchmarkRequest

router = APIRouter()


def _enqueue_job_dynamic():
    from .. import main as main_module

    return getattr(main_module, "enqueue_job", _enqueue_job)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@router.get("/api/layout-detection/defaults")
def layout_detection_defaults() -> dict[str, object]:
    defaults = get_layout_detection_defaults()
    return {
        "defaults": defaults,
        "available_models": list(BENCHMARK_MODEL_CHECKPOINTS),
    }


@router.get("/api/layout-benchmark/status")
def layout_benchmark_status() -> dict[str, object]:
    return get_latest_benchmark_status()


@router.get("/api/layout-benchmark/grid")
def layout_benchmark_grid() -> dict[str, object]:
    return get_layout_benchmark_grid()


@router.post("/api/layout-benchmark/run")
def run_layout_benchmark_job(payload: RunLayoutBenchmarkRequest | None = None) -> dict[str, object]:
    params = payload or RunLayoutBenchmarkRequest()
    register_default_handlers()
    enqueued = _enqueue_job_dynamic()(
        STAGE_LAYOUT_BENCHMARK,
        page_id=None,
        payload={"force_full_rerun": bool(params.force_full_rerun)},
    )
    if enqueued:
        emit_event(
            stage=STAGE_LAYOUT_BENCHMARK,
            event_type=EVENT_JOB_ENQUEUED,
            message="Queued layout benchmark job.",
            data={"force_full_rerun": bool(params.force_full_rerun)},
        )
    else:
        emit_event(
            stage=STAGE_LAYOUT_BENCHMARK,
            event_type=EVENT_JOB_ENQUEUE_SKIPPED,
            message="Skipped queuing layout benchmark because a benchmark job is already queued or running.",
            data={"force_full_rerun": bool(params.force_full_rerun)},
        )
    return {"enqueued": bool(enqueued)}


@router.post("/api/layout-benchmark/stop")
def stop_layout_benchmark_job() -> dict[str, object]:
    register_default_handlers()
    queued_cancelled = 0
    running_found = False
    now = _utc_now()
    with get_session() as session:
        running_found = (
            session.execute(
                select(PipelineJob.id)
                .where(PipelineJob.stage == STAGE_LAYOUT_BENCHMARK)
                .where(PipelineJob.status == "running")
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )
        queued_ids = session.execute(
            select(PipelineJob.id)
            .where(PipelineJob.stage == STAGE_LAYOUT_BENCHMARK)
            .where(PipelineJob.status == "queued")
        ).scalars().all()
        queued_cancelled = len(queued_ids)
        if queued_cancelled > 0:
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
    if running_found:
        request_layout_benchmark_stop()

    emit_event(
        stage=STAGE_LAYOUT_BENCHMARK,
        event_type=EVENT_JOB_PROGRESS,
        message=(
            "Layout benchmark stop requested."
            if running_found or queued_cancelled > 0
            else "No active layout benchmark job to stop."
        ),
        data={
            "running_stop_requested": bool(running_found),
            "queued_cancelled": int(queued_cancelled),
        },
    )
    return {
        "running_stop_requested": bool(running_found),
        "queued_cancelled": int(queued_cancelled),
    }
