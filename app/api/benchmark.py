from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..layout_benchmark import (
    BENCHMARK_MODEL_CHECKPOINTS,
    get_latest_benchmark_status,
    get_layout_benchmark_grid,
    recalculate_layout_benchmark_scores,
    request_layout_benchmark_stop,
)
from ..layout_detection_defaults import get_layout_detection_defaults
from ..pipeline_constants import (
    EVENT_JOB_ENQUEUED,
    EVENT_JOB_ENQUEUE_SKIPPED,
    EVENT_JOB_PROGRESS,
    STAGE_LAYOUT_BENCHMARK,
)
from ..pipeline_runtime import emit_event, enqueue_job as _enqueue_job, register_default_handlers
from .event_lifecycle_utils import emit_lifecycle_completed, emit_lifecycle_failed, emit_lifecycle_started
from .job_control_utils import coerce_int, resolve_main_callable, stop_stage_jobs, utc_now_iso
from .schemas import RunLayoutBenchmarkRequest

router = APIRouter()


def _enqueue_job_dynamic():
    return resolve_main_callable("enqueue_job", _enqueue_job)


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
        image_size = coerce_int(row.get("image_size"), default=0, minimum=0)
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
    stop_result = stop_stage_jobs(
        STAGE_LAYOUT_BENCHMARK,
        now_iso=utc_now_iso(),
        stop_error="Stopped by user request.",
    )
    queued_cancelled = int(stop_result["queued_cancelled"])
    running_found = bool(stop_result["running_found"])
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

    emit_lifecycle_started(
        stage=STAGE_LAYOUT_BENCHMARK,
        event_type=EVENT_JOB_PROGRESS,
        message="Layout benchmark score recalculation started.",
    )
    try:
        result = recalculate_layout_benchmark_scores()
    except ValueError as error:
        emit_lifecycle_failed(
            stage=STAGE_LAYOUT_BENCHMARK,
            event_type=EVENT_JOB_PROGRESS,
            message_prefix="Layout benchmark score recalculation failed",
            error=error,
        )
        raise HTTPException(status_code=400, detail=str(error)) from error
    emit_lifecycle_completed(
        stage=STAGE_LAYOUT_BENCHMARK,
        event_type=EVENT_JOB_PROGRESS,
        message=(
            "Layout benchmark score recalculation finished. "
            f"Recalculated {int(result['recalculated_rows'])}/{int(result['total_rows'])} rows."
        ),
        data=result,
    )
    return result
