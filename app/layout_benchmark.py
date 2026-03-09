from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import time
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from sqlalchemy import func, select

from .config import settings
from .db import get_session
from .layout_classes import normalize_detected_class_name
from .layout_detection_defaults import get_layout_detection_defaults, update_layout_detection_defaults
from .layouts import _detect_doclaynet_layouts
from .models import Layout, LayoutBenchmarkResult, LayoutBenchmarkRun, Page, PipelineJob
from .pipeline_constants import STAGE_LAYOUT_BENCHMARK
from .statuses import normalize_db_status

BENCHMARK_MODEL_CHECKPOINTS: tuple[str, ...] = (
    "yolov10m-doclaynet.pt",
    "yolov10l-doclaynet.pt",
    "yolov11m-doclaynet.pt",
    "yolov11l-doclaynet.pt",
    "yolov12m-doclaynet.pt",
    "yolov12l-doclaynet.pt",
    "yolo26m-doclaynet.pt",
    "yolo26l-doclaynet.pt",
)
BENCHMARK_IMAGE_SIZES: tuple[int, ...] = (256, 512, 768, 1024, 1280, 1536, 2048)
BENCHMARK_CONFIDENCE_THRESHOLDS: tuple[float, ...] = (0.15, 0.20, 0.25)
BENCHMARK_IOU_THRESHOLDS: tuple[float, ...] = (0.35, 0.50, 0.65)

AUTO_APPLY_MIN_SAMPLE_SIZE = 10
AUTO_APPLY_MIN_RELATIVE_IMPROVEMENT = 0.025
AUTO_APPLY_STABILITY_PAGES = 2
PROGRESS_EMIT_INTERVAL_SECONDS = 1.5
MATCH_IOU_THRESHOLD = 0.5

CLASS_WEIGHTS: dict[str, float] = {
    "text": 1.0,
    "section_header": 1.15,
    "caption": 1.2,
    "table": 1.25,
    "formula": 1.25,
    "footnote": 0.95,
    "page_header": 0.8,
    "page_footer": 0.8,
    "picture": 0.7,
    "list_item": 1.0,
}

_ELIGIBLE_STATUSES = frozenset(
    {
        "LAYOUT_REVIEWED",
        "OCR_EXTRACTING",
        "OCR_DONE",
        "OCR_FAILED",
        "OCR_REVIEWED",
    }
)

_STOP_LOCK = Lock()
_STOP_REQUESTED = False


@dataclass(frozen=True)
class BenchmarkPage:
    page_id: int
    rel_path: str
    updated_at: str
    fingerprint: str
    gt_layouts: tuple[dict[str, Any], ...]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def clear_layout_benchmark_stop_request() -> None:
    global _STOP_REQUESTED
    with _STOP_LOCK:
        _STOP_REQUESTED = False


def request_layout_benchmark_stop() -> None:
    global _STOP_REQUESTED
    with _STOP_LOCK:
        _STOP_REQUESTED = True


def is_layout_benchmark_stop_requested() -> bool:
    with _STOP_LOCK:
        return bool(_STOP_REQUESTED)


def _float_key(value: float) -> str:
    return f"{float(value):.6f}"


def _config_key(config: dict[str, Any]) -> tuple[str, int, str, str]:
    return (
        str(config["model_checkpoint"]),
        int(config["image_size"]),
        _float_key(float(config["confidence_threshold"])),
        _float_key(float(config["iou_threshold"])),
    )


def _config_label(config: dict[str, Any]) -> str:
    return (
        f"{config['model_checkpoint']} | imgsz={config['image_size']} "
        f"conf={float(config['confidence_threshold']):.2f} iou={float(config['iou_threshold']):.2f}"
    )


def _normalize_layout_class_for_benchmark(class_name: str) -> str:
    # Keep benchmark scoring consistent with detector output normalization policy.
    return normalize_detected_class_name(class_name)


def _bbox_iou(box_a: dict[str, float], box_b: dict[str, float]) -> float:
    source_a = box_a["bbox"] if isinstance(box_a.get("bbox"), dict) else box_a
    source_b = box_b["bbox"] if isinstance(box_b.get("bbox"), dict) else box_b
    ax1, ay1, ax2, ay2 = (
        float(source_a["x1"]),
        float(source_a["y1"]),
        float(source_a["x2"]),
        float(source_a["y2"]),
    )
    bx1, by1, bx2, by2 = (
        float(source_b["x1"]),
        float(source_b["y1"]),
        float(source_b["x2"]),
        float(source_b["y2"]),
    )
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    intersection = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(0.0, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(0.0, (bx2 - bx1) * (by2 - by1))
    union = area_a + area_b - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _greedy_match_counts(
    gt_boxes: list[dict[str, Any]],
    pred_boxes: list[dict[str, Any]],
    *,
    iou_threshold: float,
) -> tuple[int, int, int]:
    if not gt_boxes:
        return 0, len(pred_boxes), 0
    if not pred_boxes:
        return 0, 0, len(gt_boxes)

    candidates: list[tuple[float, int, int]] = []
    for gt_idx, gt_box in enumerate(gt_boxes):
        for pred_idx, pred_box in enumerate(pred_boxes):
            iou = _bbox_iou(gt_box, pred_box)
            if iou >= iou_threshold:
                candidates.append((iou, gt_idx, pred_idx))
    candidates.sort(key=lambda row: row[0], reverse=True)

    matched_gt: set[int] = set()
    matched_pred: set[int] = set()
    for _iou, gt_idx, pred_idx in candidates:
        if gt_idx in matched_gt or pred_idx in matched_pred:
            continue
        matched_gt.add(gt_idx)
        matched_pred.add(pred_idx)

    tp = len(matched_gt)
    fp = len(pred_boxes) - tp
    fn = len(gt_boxes) - tp
    return tp, fp, fn


def _weighted_f1_score(
    gt_layouts: tuple[dict[str, Any], ...],
    pred_layouts: list[dict[str, Any]],
) -> tuple[float, dict[str, Any]]:
    gt_by_class: dict[str, list[dict[str, Any]]] = {}
    pred_by_class: dict[str, list[dict[str, Any]]] = {}

    for row in gt_layouts:
        class_name = _normalize_layout_class_for_benchmark(str(row["class_name"]))
        gt_by_class.setdefault(class_name, []).append(row)
    for row in pred_layouts:
        class_name = _normalize_layout_class_for_benchmark(str(row["class_name"]))
        pred_by_class.setdefault(class_name, []).append(row)

    class_names = sorted(set(gt_by_class.keys()) | set(pred_by_class.keys()))
    if not class_names:
        return 1.0, {"per_class": {}, "weighted_f1": 1.0}

    weighted_sum = 0.0
    total_weight = 0.0
    per_class: dict[str, dict[str, float]] = {}
    for class_name in class_names:
        gt_boxes = gt_by_class.get(class_name, [])
        pred_boxes = pred_by_class.get(class_name, [])
        tp, fp, fn = _greedy_match_counts(gt_boxes, pred_boxes, iou_threshold=MATCH_IOU_THRESHOLD)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        weight = float(CLASS_WEIGHTS.get(class_name, 1.0))
        weighted_sum += weight * f1
        total_weight += weight
        per_class[class_name] = {
            "tp": float(tp),
            "fp": float(fp),
            "fn": float(fn),
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "weight": weight,
        }

    weighted_f1 = weighted_sum / total_weight if total_weight > 0 else 0.0
    return weighted_f1, {"per_class": per_class, "weighted_f1": weighted_f1}


def _serialize_fingerprint_layouts(layout_rows: list[Layout]) -> str:
    normalized_rows = []
    for layout in sorted(layout_rows, key=lambda row: (int(row.reading_order), int(row.id))):
        normalized_rows.append(
            {
                "order": int(layout.reading_order),
                "class_name": _normalize_layout_class_for_benchmark(str(layout.class_name)),
                "bbox": {
                    "x1": round(float(layout.x1), 6),
                    "y1": round(float(layout.y1), 6),
                    "x2": round(float(layout.x2), 6),
                    "y2": round(float(layout.y2), 6),
                },
            }
        )
    payload = json.dumps(normalized_rows, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_eligible_pages() -> list[BenchmarkPage]:
    with get_session() as session:
        rows = session.execute(
            select(Page)
            .where(Page.is_missing.is_(False))
            .order_by(Page.id.asc())
        ).scalars().all()

        pages: list[BenchmarkPage] = []
        for page in rows:
            page_status = normalize_db_status(str(page.status))
            if page_status not in _ELIGIBLE_STATUSES:
                continue
            layout_rows = session.execute(
                select(Layout)
                .where(Layout.page_id == int(page.id))
                .order_by(Layout.reading_order.asc(), Layout.id.asc())
            ).scalars().all()
            if not layout_rows:
                continue
            fingerprint = _serialize_fingerprint_layouts(layout_rows)
            gt_layouts = tuple(
                {
                    "class_name": str(layout.class_name),
                    "bbox": {
                        "x1": float(layout.x1),
                        "y1": float(layout.y1),
                        "x2": float(layout.x2),
                        "y2": float(layout.y2),
                    },
                }
                for layout in layout_rows
            )
            pages.append(
                BenchmarkPage(
                    page_id=int(page.id),
                    rel_path=str(page.rel_path),
                    updated_at=str(page.updated_at),
                    fingerprint=fingerprint,
                    gt_layouts=gt_layouts,
                )
            )
    return pages


def _benchmark_configs() -> list[dict[str, Any]]:
    defaults = get_layout_detection_defaults()
    baseline = {
        "model_checkpoint": str(defaults["model_checkpoint"]),
        "image_size": int(defaults["image_size"]),
        "confidence_threshold": float(defaults["confidence_threshold"]),
        "iou_threshold": float(defaults["iou_threshold"]),
    }

    seen: set[tuple[str, int, str, str]] = set()
    configs: list[dict[str, Any]] = []
    for model_checkpoint in BENCHMARK_MODEL_CHECKPOINTS:
        for image_size in BENCHMARK_IMAGE_SIZES:
            for confidence_threshold in BENCHMARK_CONFIDENCE_THRESHOLDS:
                for iou_threshold in BENCHMARK_IOU_THRESHOLDS:
                    config = {
                        "model_checkpoint": str(model_checkpoint),
                        "image_size": int(image_size),
                        "confidence_threshold": float(confidence_threshold),
                        "iou_threshold": float(iou_threshold),
                    }
                    key = _config_key(config)
                    if key in seen:
                        continue
                    seen.add(key)
                    configs.append(config)

    baseline_key = _config_key(baseline)
    if baseline_key not in seen:
        configs.append(baseline)
    return configs


def _load_existing_scores_for_page(page_id: int, fingerprint: str) -> dict[tuple[str, int, str, str], float]:
    with get_session() as session:
        rows = session.execute(
            select(LayoutBenchmarkResult)
            .where(LayoutBenchmarkResult.page_id == page_id)
            .where(LayoutBenchmarkResult.page_fingerprint == fingerprint)
        ).scalars().all()

    out: dict[tuple[str, int, str, str], float] = {}
    for row in rows:
        key = (
            str(row.model_checkpoint),
            int(row.image_size),
            _float_key(float(row.confidence_threshold)),
            _float_key(float(row.iou_threshold)),
        )
        out[key] = float(row.score)
    return out


def _save_page_result(
    *,
    page_id: int,
    fingerprint: str,
    config: dict[str, Any],
    score: float,
    metrics: dict[str, Any],
) -> None:
    now = _utc_now()
    model_checkpoint = str(config["model_checkpoint"])
    image_size = int(config["image_size"])
    confidence_threshold = float(config["confidence_threshold"])
    iou_threshold = float(config["iou_threshold"])
    with get_session() as session:
        row = session.execute(
            select(LayoutBenchmarkResult)
            .where(LayoutBenchmarkResult.page_id == page_id)
            .where(LayoutBenchmarkResult.page_fingerprint == fingerprint)
            .where(LayoutBenchmarkResult.model_checkpoint == model_checkpoint)
            .where(LayoutBenchmarkResult.image_size == image_size)
            .where(LayoutBenchmarkResult.confidence_threshold == confidence_threshold)
            .where(LayoutBenchmarkResult.iou_threshold == iou_threshold)
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            session.add(
                LayoutBenchmarkResult(
                    page_id=page_id,
                    page_fingerprint=fingerprint,
                    model_checkpoint=model_checkpoint,
                    image_size=image_size,
                    confidence_threshold=confidence_threshold,
                    iou_threshold=iou_threshold,
                    score=float(score),
                    metrics_json=json.dumps(metrics, ensure_ascii=True, separators=(",", ":")),
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.score = float(score)
            row.metrics_json = json.dumps(metrics, ensure_ascii=True, separators=(",", ":"))
            row.updated_at = now


def _upsert_run(
    *,
    run_id: int,
    status: str | None = None,
    total_pages: int | None = None,
    total_configs: int | None = None,
    total_tasks: int | None = None,
    processed_tasks: int | None = None,
    skipped_tasks: int | None = None,
    current_page_id: int | None = None,
    current_config: dict[str, Any] | None = None,
    best_config: dict[str, Any] | None = None,
    applied_defaults: bool | None = None,
    error: str | None = None,
    finished: bool = False,
) -> None:
    with get_session() as session:
        row = session.get(LayoutBenchmarkRun, run_id)
        if row is None:
            return
        if status is not None:
            row.status = status
        if total_pages is not None:
            row.total_pages = int(total_pages)
        if total_configs is not None:
            row.total_configs = int(total_configs)
        if total_tasks is not None:
            row.total_tasks = int(total_tasks)
        if processed_tasks is not None:
            row.processed_tasks = int(processed_tasks)
        if skipped_tasks is not None:
            row.skipped_tasks = int(skipped_tasks)
        row.current_page_id = current_page_id
        row.current_config_json = (
            None
            if current_config is None
            else json.dumps(current_config, ensure_ascii=True, separators=(",", ":"))
        )
        row.best_config_json = (
            None
            if best_config is None
            else json.dumps(best_config, ensure_ascii=True, separators=(",", ":"))
        )
        if applied_defaults is not None:
            row.applied_defaults = bool(applied_defaults)
        if error is not None:
            row.error = str(error)
        row.updated_at = _utc_now()
        if finished:
            row.finished_at = _utc_now()


def _start_run(force_full_rerun: bool) -> int:
    now = _utc_now()
    with get_session() as session:
        row = LayoutBenchmarkRun(
            status="running",
            force_full_rerun=bool(force_full_rerun),
            total_pages=0,
            total_configs=0,
            total_tasks=0,
            processed_tasks=0,
            skipped_tasks=0,
            current_page_id=None,
            current_config_json=None,
            best_config_json=None,
            applied_defaults=False,
            error=None,
            created_at=now,
            updated_at=now,
            finished_at=None,
        )
        session.add(row)
        session.flush()
        return int(row.id)


def _detect_for_page(page: BenchmarkPage, config: dict[str, Any]) -> list[dict[str, Any]]:
    image_path = (settings.source_dir / page.rel_path).resolve()
    source_root = settings.source_dir.resolve()
    if source_root not in image_path.parents:
        raise ValueError(f"Invalid page image path for benchmark: {page.rel_path}")
    if not image_path.exists() or not image_path.is_file():
        raise ValueError(f"Image file missing for benchmark: {page.rel_path}")
    rows, _params = _detect_doclaynet_layouts(
        image_path,
        model_checkpoint=str(config["model_checkpoint"]),
        confidence_threshold=float(config["confidence_threshold"]),
        iou_threshold=float(config["iou_threshold"]),
        image_size=int(config["image_size"]),
        max_detections=None,
        agnostic_nms=None,
    )
    return rows


def _aggregate_scores(
    pages: list[BenchmarkPage],
    configs: list[dict[str, Any]],
    page_scores: dict[int, dict[tuple[str, int, str, str], float]],
) -> dict[tuple[str, int, str, str], dict[str, Any]]:
    aggregate: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for config in configs:
        key = _config_key(config)
        values: list[float] = []
        per_page: dict[int, float] = {}
        for page in pages:
            page_value = page_scores.get(page.page_id, {}).get(key)
            if page_value is None:
                continue
            values.append(float(page_value))
            per_page[page.page_id] = float(page_value)
        if not values:
            continue
        aggregate[key] = {
            "config": config,
            "page_count": len(values),
            "mean_score": sum(values) / len(values),
            "per_page": per_page,
        }
    return aggregate


def _apply_suggested_defaults_if_needed(
    *,
    pages: list[BenchmarkPage],
    aggregate: dict[tuple[str, int, str, str], dict[str, Any]],
) -> tuple[dict[str, Any] | None, bool, str]:
    defaults = get_layout_detection_defaults()
    baseline_config = {
        "model_checkpoint": str(defaults["model_checkpoint"]),
        "image_size": int(defaults["image_size"]),
        "confidence_threshold": float(defaults["confidence_threshold"]),
        "iou_threshold": float(defaults["iou_threshold"]),
    }
    baseline_key = _config_key(baseline_config)
    baseline_stats = aggregate.get(baseline_key)
    if baseline_stats is None:
        return None, False, "Baseline config has no benchmark scores."
    if len(pages) < AUTO_APPLY_MIN_SAMPLE_SIZE:
        return None, False, "Not enough reviewed pages for auto-apply."

    best_stats = max(aggregate.values(), key=lambda row: float(row["mean_score"]))
    best_key = _config_key(dict(best_stats["config"]))
    if best_key == baseline_key:
        return dict(best_stats["config"]), False, "Current defaults already best."

    baseline_score = float(baseline_stats["mean_score"])
    best_score = float(best_stats["mean_score"])
    if baseline_score <= 0:
        relative_improvement = 1.0 if best_score > baseline_score else 0.0
    else:
        relative_improvement = (best_score - baseline_score) / baseline_score
    if relative_improvement < AUTO_APPLY_MIN_RELATIVE_IMPROVEMENT:
        return dict(best_stats["config"]), False, "Improvement below threshold."

    recent_pages = sorted(pages, key=lambda page: str(page.updated_at), reverse=True)[:AUTO_APPLY_STABILITY_PAGES]
    for page in recent_pages:
        best_page_score = float(best_stats["per_page"].get(page.page_id, -1.0))
        baseline_page_score = float(baseline_stats["per_page"].get(page.page_id, -1.0))
        if best_page_score <= baseline_page_score:
            return dict(best_stats["config"]), False, "Stability gate failed."

    applied = update_layout_detection_defaults(
        model_checkpoint=str(best_stats["config"]["model_checkpoint"]),
        confidence_threshold=float(best_stats["config"]["confidence_threshold"]),
        iou_threshold=float(best_stats["config"]["iou_threshold"]),
        image_size=int(best_stats["config"]["image_size"]),
        updated_by="layout_benchmark_auto_apply",
    )
    return applied, True, "Applied benchmark suggestion."


def run_layout_benchmark(
    *,
    force_full_rerun: bool,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    clear_layout_benchmark_stop_request()
    run_id = _start_run(force_full_rerun)
    pages = _load_eligible_pages()
    configs = _benchmark_configs()
    page_scores: dict[int, dict[tuple[str, int, str, str], float]] = {}

    for page in pages:
        page_scores[page.page_id] = _load_existing_scores_for_page(page.page_id, page.fingerprint)

    total_tasks = 0
    skipped_tasks = 0
    for page in pages:
        existing_scores = page_scores[page.page_id]
        for config in configs:
            key = _config_key(config)
            if not force_full_rerun and key in existing_scores:
                skipped_tasks += 1
                continue
            total_tasks += 1

    _upsert_run(
        run_id=run_id,
        total_pages=len(pages),
        total_configs=len(configs),
        total_tasks=total_tasks,
        processed_tasks=0,
        skipped_tasks=skipped_tasks,
        status="running",
    )
    if progress_callback is not None:
        progress_callback(
            {
                "run_id": run_id,
                "total_pages": len(pages),
                "total_configs": len(configs),
                "total_tasks": total_tasks,
                "processed_tasks": 0,
                "skipped_tasks": skipped_tasks,
                "status": "running",
                "message": "Layout benchmark started.",
            }
        )

    processed_tasks = 0
    last_emit = 0.0
    try:
        for page in pages:
            for config in configs:
                if is_layout_benchmark_stop_requested():
                    aggregate = _aggregate_scores(pages, configs, page_scores)
                    best_stats = (
                        max(aggregate.values(), key=lambda row: float(row["mean_score"]))
                        if aggregate
                        else None
                    )
                    best_config = None if best_stats is None else dict(best_stats["config"])
                    _upsert_run(
                        run_id=run_id,
                        processed_tasks=processed_tasks,
                        skipped_tasks=skipped_tasks,
                        best_config=best_config,
                        applied_defaults=False,
                        status="stopped",
                        finished=True,
                    )
                    result = {
                        "run_id": run_id,
                        "status": "stopped",
                        "stopped": True,
                        "total_pages": len(pages),
                        "total_configs": len(configs),
                        "total_tasks": total_tasks,
                        "processed_tasks": processed_tasks,
                        "skipped_tasks": skipped_tasks,
                        "best_config": best_config,
                        "best_score": None if best_stats is None else float(best_stats["mean_score"]),
                        "applied_defaults": False,
                        "applied_defaults_payload": None,
                        "apply_message": "Stopped by user request.",
                    }
                    if progress_callback is not None:
                        progress_callback(
                            {
                                **result,
                                "message": "Layout benchmark stopped by user request.",
                            }
                        )
                    clear_layout_benchmark_stop_request()
                    return result
                key = _config_key(config)
                existing = page_scores[page.page_id].get(key)
                if existing is not None and not force_full_rerun:
                    continue

                predicted = _detect_for_page(page, config)
                score, metrics = _weighted_f1_score(page.gt_layouts, predicted)
                _save_page_result(
                    page_id=page.page_id,
                    fingerprint=page.fingerprint,
                    config=config,
                    score=score,
                    metrics=metrics,
                )
                page_scores[page.page_id][key] = float(score)
                processed_tasks += 1

                _upsert_run(
                    run_id=run_id,
                    processed_tasks=processed_tasks,
                    skipped_tasks=skipped_tasks,
                    current_page_id=page.page_id,
                    current_config=config,
                    status="running",
                )
                now_monotonic = time.monotonic()
                if progress_callback is not None and (
                    now_monotonic - last_emit >= PROGRESS_EMIT_INTERVAL_SECONDS
                    or processed_tasks == total_tasks
                ):
                    last_emit = now_monotonic
                    progress_callback(
                        {
                            "run_id": run_id,
                            "total_pages": len(pages),
                            "total_configs": len(configs),
                            "total_tasks": total_tasks,
                            "processed_tasks": processed_tasks,
                            "skipped_tasks": skipped_tasks,
                            "status": "running",
                            "current_page_id": page.page_id,
                            "current_rel_path": page.rel_path,
                            "current_config": dict(config),
                            "current_label": _config_label(config),
                        }
                    )

        aggregate = _aggregate_scores(pages, configs, page_scores)
        best_stats = max(aggregate.values(), key=lambda row: float(row["mean_score"])) if aggregate else None
        best_config = None if best_stats is None else dict(best_stats["config"])
        applied_defaults = False
        apply_message = "No benchmark results."
        applied_payload: dict[str, Any] | None = None
        if best_stats is not None:
            applied_payload, applied_defaults, apply_message = _apply_suggested_defaults_if_needed(
                pages=pages,
                aggregate=aggregate,
            )

        _upsert_run(
            run_id=run_id,
            processed_tasks=processed_tasks,
            skipped_tasks=skipped_tasks,
            best_config=best_config,
            applied_defaults=applied_defaults,
            status="completed",
            finished=True,
        )

        result = {
            "run_id": run_id,
            "status": "completed",
            "total_pages": len(pages),
            "total_configs": len(configs),
            "total_tasks": total_tasks,
            "processed_tasks": processed_tasks,
            "skipped_tasks": skipped_tasks,
            "best_config": best_config,
            "best_score": None if best_stats is None else float(best_stats["mean_score"]),
            "applied_defaults": applied_defaults,
            "applied_defaults_payload": applied_payload,
            "apply_message": apply_message,
        }
        if progress_callback is not None:
            progress_callback(
                {
                    **result,
                    "message": (
                        "Layout benchmark finished. "
                        f"Processed {processed_tasks}, skipped {skipped_tasks}, pages {len(pages)}."
                    ),
                }
            )
        clear_layout_benchmark_stop_request()
        return result
    except Exception as error:
        _upsert_run(
            run_id=run_id,
            processed_tasks=processed_tasks,
            skipped_tasks=skipped_tasks,
            status="failed",
            error=str(error),
            finished=True,
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "run_id": run_id,
                    "status": "failed",
                    "total_pages": len(pages),
                    "total_configs": len(configs),
                    "total_tasks": total_tasks,
                    "processed_tasks": processed_tasks,
                    "skipped_tasks": skipped_tasks,
                    "error": str(error),
                    "message": f"Layout benchmark failed: {error}",
                }
            )
        clear_layout_benchmark_stop_request()
        raise


def get_latest_benchmark_status() -> dict[str, Any]:
    with get_session() as session:
        latest_run = session.execute(
            select(LayoutBenchmarkRun).order_by(LayoutBenchmarkRun.id.desc()).limit(1)
        ).scalar_one_or_none()
        active_job_count = int(
            session.execute(
                select(func.count(PipelineJob.id))
                .where(PipelineJob.stage == STAGE_LAYOUT_BENCHMARK)
                .where(PipelineJob.status.in_(("queued", "running")))
            ).scalar_one()
            or 0
        )

    if latest_run is None:
        return {
            "has_run": False,
            "is_running": active_job_count > 0,
            "run": None,
            "defaults": get_layout_detection_defaults(),
        }

    total_tasks = int(latest_run.total_tasks)
    processed_tasks = int(latest_run.processed_tasks)
    progress_ratio = 1.0 if total_tasks <= 0 else min(1.0, max(0.0, processed_tasks / total_tasks))
    current_config = None
    if latest_run.current_config_json:
        try:
            current_config = json.loads(latest_run.current_config_json)
        except json.JSONDecodeError:
            current_config = None
    best_config = None
    if latest_run.best_config_json:
        try:
            best_config = json.loads(latest_run.best_config_json)
        except json.JSONDecodeError:
            best_config = None

    return {
        "has_run": True,
        "is_running": bool(latest_run.status == "running" or active_job_count > 0),
        "run": {
            "run_id": int(latest_run.id),
            "status": str(latest_run.status),
            "force_full_rerun": bool(latest_run.force_full_rerun),
            "total_pages": int(latest_run.total_pages),
            "total_configs": int(latest_run.total_configs),
            "total_tasks": int(latest_run.total_tasks),
            "processed_tasks": int(latest_run.processed_tasks),
            "skipped_tasks": int(latest_run.skipped_tasks),
            "current_page_id": None if latest_run.current_page_id is None else int(latest_run.current_page_id),
            "current_config": current_config,
            "best_config": best_config,
            "applied_defaults": bool(latest_run.applied_defaults),
            "error": latest_run.error,
            "created_at": str(latest_run.created_at),
            "updated_at": str(latest_run.updated_at),
            "finished_at": latest_run.finished_at,
            "progress_ratio": progress_ratio,
        },
        "defaults": get_layout_detection_defaults(),
    }


def get_layout_benchmark_grid() -> dict[str, Any]:
    with get_session() as session:
        rows = session.execute(
            select(LayoutBenchmarkResult).order_by(
                LayoutBenchmarkResult.updated_at.desc(),
                LayoutBenchmarkResult.id.desc(),
            )
        ).scalars().all()

    latest_per_page_and_config: dict[tuple[int, str, int, str, str], LayoutBenchmarkResult] = {}
    for row in rows:
        key = (
            int(row.page_id),
            str(row.model_checkpoint),
            int(row.image_size),
            _float_key(float(row.confidence_threshold)),
            _float_key(float(row.iou_threshold)),
        )
        if key in latest_per_page_and_config:
            continue
        latest_per_page_and_config[key] = row

    aggregate: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for row in latest_per_page_and_config.values():
        config_key = (
            str(row.model_checkpoint),
            int(row.image_size),
            _float_key(float(row.confidence_threshold)),
            _float_key(float(row.iou_threshold)),
        )
        bucket = aggregate.setdefault(
            config_key,
            {
                "model_checkpoint": str(row.model_checkpoint),
                "image_size": int(row.image_size),
                "confidence_threshold": float(row.confidence_threshold),
                "iou_threshold": float(row.iou_threshold),
                "score_sum": 0.0,
                "page_count": 0,
            },
        )
        bucket["score_sum"] += float(row.score)
        bucket["page_count"] += 1

    grid_rows: list[dict[str, Any]] = []
    for bucket in aggregate.values():
        page_count = int(bucket["page_count"])
        mean_score = float(bucket["score_sum"]) / page_count if page_count > 0 else 0.0
        grid_rows.append(
            {
                "model_checkpoint": str(bucket["model_checkpoint"]),
                "image_size": int(bucket["image_size"]),
                "confidence_threshold": float(bucket["confidence_threshold"]),
                "iou_threshold": float(bucket["iou_threshold"]),
                "page_count": page_count,
                "mean_score": mean_score,
            }
        )

    grid_rows.sort(
        key=lambda row: (
            float(row["mean_score"]),
            int(row["page_count"]),
            str(row["model_checkpoint"]),
            int(row["image_size"]),
        ),
        reverse=True,
    )
    best_row = grid_rows[0] if grid_rows else None
    return {
        "rows": grid_rows,
        "best_config": (
            None
            if best_row is None
            else {
                "model_checkpoint": str(best_row["model_checkpoint"]),
                "image_size": int(best_row["image_size"]),
                "confidence_threshold": float(best_row["confidence_threshold"]),
                "iou_threshold": float(best_row["iou_threshold"]),
            }
        ),
        "best_score": None if best_row is None else float(best_row["mean_score"]),
    }
