from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from ..db import get_session
from ..layout_benchmark import (
    BENCHMARK_MODEL_CHECKPOINTS,
    get_latest_benchmark_status,
    get_layout_benchmark_grid,
    recalculate_layout_benchmark_scores,
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


def _top_layout_detection_configs(
    rows: list[dict[str, object]] | None,
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    top_rows = rows if isinstance(rows, list) else []
    seen: set[tuple[str, int]] = set()
    output: list[dict[str, object]] = []
    for row in top_rows:
        if not isinstance(row, dict):
            continue
        model_checkpoint = str(row.get("model_checkpoint") or "").strip()
        try:
            image_size = int(row.get("image_size"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not model_checkpoint or image_size <= 0:
            continue
        key = (model_checkpoint, image_size)
        if key in seen:
            continue
        seen.add(key)
        try:
            mean_score = float(row.get("mean_score"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            mean_score = 0.0
        output.append(
            {
                "model_checkpoint": model_checkpoint,
                "image_size": image_size,
                "mean_score": mean_score,
            }
        )
        if len(output) >= int(limit):
            break
    return output


@router.get("/api/layout-detection/defaults")
def layout_detection_defaults() -> dict[str, object]:
    defaults = get_layout_detection_defaults()
    benchmark_grid = get_layout_benchmark_grid()
    top_configs = _top_layout_detection_configs(benchmark_grid.get("rows"))  # type: ignore[arg-type]
    return {
        "defaults": defaults,
        "available_models": list(BENCHMARK_MODEL_CHECKPOINTS),
        "top_configs": top_configs,
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


@router.post("/api/layout-benchmark/rescore")
def rescore_layout_benchmark() -> dict[str, object]:
    register_default_handlers()
    status = get_latest_benchmark_status()
    if bool(status.get("is_running")):
        raise HTTPException(status_code=409, detail="Cannot recalculate scores while benchmark is running.")

    emit_event(
        stage=STAGE_LAYOUT_BENCHMARK,
        event_type=EVENT_JOB_PROGRESS,
        message="Layout benchmark score recalculation started.",
    )
    result = recalculate_layout_benchmark_scores()
    emit_event(
        stage=STAGE_LAYOUT_BENCHMARK,
        event_type=EVENT_JOB_PROGRESS,
        message=(
            "Layout benchmark score recalculation finished. "
            f"Recalculated {int(result['recalculated_rows'])}/{int(result['total_rows'])} rows."
        ),
        data=result,
    )
    return result
