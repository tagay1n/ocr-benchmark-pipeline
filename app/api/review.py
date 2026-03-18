from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..final_export import export_final_dataset
from ..layouts import (
    create_layout,
    delete_layout,
    detect_layouts_for_page,
    get_page,
    list_layouts,
    mark_layout_reviewed,
    reorder_page_layouts,
    replace_caption_bindings,
    update_page_layout_order_mode,
    update_layout,
)
from ..models import Page
from ..ocr_extract import extract_ocr_for_page as _extract_ocr_for_page
from ..ocr_review import list_ocr_outputs, mark_ocr_reviewed, update_ocr_output
from ..pipeline_constants import (
    EVENT_EXPORT_COMPLETED,
    EVENT_EXPORT_FAILED,
    EVENT_EXPORT_STARTED,
    EVENT_JOB_COMPLETED,
    EVENT_JOB_FAILED,
    EVENT_JOB_STARTED,
    EVENT_MANUAL_DETECT_COMPLETED,
    EVENT_MANUAL_DETECT_FAILED,
    EVENT_MANUAL_DETECT_STARTED,
    EVENT_MANUAL_REVIEW_COMPLETED,
    EVENT_MANUAL_REVIEW_COMPLETE_FAILED,
    EVENT_MANUAL_REVIEW_COMPLETE_STARTED,
    STAGE_FINALIZATION,
    STAGE_LAYOUT_DETECT,
    STAGE_LAYOUT_REVIEW,
    STAGE_OCR_EXTRACT,
    STAGE_OCR_REVIEW,
)
from ..pipeline_runtime import emit_event
from ..db import get_session
from .event_lifecycle_utils import emit_lifecycle_completed, emit_lifecycle_failed, emit_lifecycle_started
from .job_control_utils import resolve_main_callable
from .schemas import (
    CreateLayoutRequest,
    DetectLayoutsRequest,
    FinalExportRequest,
    ReextractOcrRequest,
    ReorderLayoutsRequest,
    ReplaceCaptionBindingsRequest,
    UpdateLayoutOrderModeRequest,
    UpdateLayoutRequest,
    UpdateOcrOutputRequest,
)
from .shared import (
    LAYOUT_REVIEW_QUEUE_STATUSES,
    OCR_REVIEW_QUEUE_STATUS,
    _utc_now,
    ensure_page_exists_or_404,
    next_page_for_status,
    next_page_for_statuses,
)

router = APIRouter()


def _extract_ocr_for_page_dynamic():
    return resolve_main_callable("extract_ocr_for_page", _extract_ocr_for_page)


def _http_exception_from_value_error(
    error: ValueError,
    *,
    not_found_messages: tuple[str, ...] = (),
    default_status: int = 400,
) -> HTTPException:
    message = str(error)
    status_code = 404 if message in not_found_messages else int(default_status)
    return HTTPException(status_code=status_code, detail=message)


def _run_manual_layout_detection(page_id: int, payload: DetectLayoutsRequest) -> dict[str, object]:
    emit_lifecycle_started(
        stage=STAGE_LAYOUT_DETECT,
        event_type=EVENT_MANUAL_DETECT_STARTED,
        page_id=page_id,
        message="Manual layout detection started.",
    )
    try:
        result = detect_layouts_for_page(
            page_id,
            model_checkpoint=payload.model_checkpoint,
            replace_existing=payload.replace_existing,
            confidence_threshold=payload.confidence_threshold,
            iou_threshold=payload.iou_threshold,
            image_size=payload.image_size,
            max_detections=payload.max_detections,
            agnostic_nms=payload.agnostic_nms,
        )
    except ValueError as error:
        emit_lifecycle_failed(
            stage=STAGE_LAYOUT_DETECT,
            event_type=EVENT_MANUAL_DETECT_FAILED,
            page_id=page_id,
            message_prefix="Manual layout detection failed",
            error=error,
        )
        raise HTTPException(status_code=400, detail=str(error)) from error
    emit_lifecycle_completed(
        stage=STAGE_LAYOUT_DETECT,
        event_type=EVENT_MANUAL_DETECT_COMPLETED,
        page_id=page_id,
        message=f"Manual layout detection completed with {result['created']} regions.",
        data={"created": result["created"], "class_counts": result["class_counts"]},
    )
    return result


def _run_manual_ocr_reextract(page_id: int, params: ReextractOcrRequest) -> dict[str, object]:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise HTTPException(status_code=404, detail="Page not found.")
        if bool(page_row.is_missing):
            raise HTTPException(status_code=400, detail="Page is marked as missing.")

        current_status = str(page_row.status)
        if current_status not in {"layout_reviewed", "ocr_done", "ocr_reviewed", "ocr_failed", "ocr_extracting"}:
            raise HTTPException(
                status_code=400,
                detail=f"Page status must allow OCR extraction (got {current_status}).",
            )

        page_row.status = "ocr_extracting"
        page_row.updated_at = _utc_now()

    emit_event(
        stage=STAGE_OCR_EXTRACT,
        event_type=EVENT_JOB_STARTED,
        page_id=page_id,
        message="Manual OCR reextraction started.",
        data={
            "trigger": "manual_reextract",
            "layout_ids": params.layout_ids,
            "temperature": params.temperature,
            "max_retries_per_layout": params.max_retries_per_layout,
            "prompt_template": params.prompt_template,
        },
    )
    try:
        result = _extract_ocr_for_page_dynamic()(
            page_id,
            layout_ids=params.layout_ids,
            prompt_template=params.prompt_template,
            temperature=params.temperature,
            max_retries_per_layout=params.max_retries_per_layout,
        )
    except Exception as error:
        with get_session() as session:
            page_row = session.get(Page, page_id)
            if page_row is not None and not bool(page_row.is_missing):
                page_row.status = "ocr_failed"
                page_row.updated_at = _utc_now()
        emit_event(
            stage=STAGE_OCR_EXTRACT,
            event_type=EVENT_JOB_FAILED,
            page_id=page_id,
            message=f"Manual OCR reextraction failed: {error}",
            data={"trigger": "manual_reextract"},
        )
        raise HTTPException(status_code=400, detail=str(error)) from error

    emit_event(
        stage=STAGE_OCR_EXTRACT,
        event_type=EVENT_JOB_COMPLETED,
        page_id=page_id,
        message=(
            f"Manual OCR reextraction completed. "
            f"Extracted {result['extracted_count']}, skipped {result['skipped_count']}, "
            f"Gemini requests {result['requests_count']}."
        ),
        data={"trigger": "manual_reextract", "result": result},
    )
    return result


@router.get("/api/pages/{page_id}/layouts")
def page_layouts(page_id: int) -> dict[str, object]:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    layouts = list_layouts(page_id)
    return {"page_id": page_id, "count": len(layouts), "layouts": layouts}


@router.patch("/api/pages/{page_id}/layout-order-mode")
def patch_layout_order_mode(
    page_id: int, payload: UpdateLayoutOrderModeRequest
) -> dict[str, object]:
    try:
        return update_page_layout_order_mode(page_id, mode=payload.mode)
    except ValueError as error:
        raise _http_exception_from_value_error(
            error,
            not_found_messages=("Page not found.",),
        ) from error


@router.post("/api/pages/{page_id}/layouts/reorder")
def reorder_layouts(page_id: int, payload: ReorderLayoutsRequest | None = None) -> dict[str, object]:
    mode = None if payload is None else payload.mode
    try:
        return reorder_page_layouts(page_id, mode=mode)
    except ValueError as error:
        raise _http_exception_from_value_error(
            error,
            not_found_messages=("Page not found.",),
        ) from error


@router.get("/api/layout-review/next")
def next_layout_review_page_global() -> dict[str, object]:
    return next_page_for_statuses(statuses=LAYOUT_REVIEW_QUEUE_STATUSES)


@router.get("/api/ocr-review/next")
def next_ocr_review_page_global() -> dict[str, object]:
    return next_page_for_status(status=OCR_REVIEW_QUEUE_STATUS)


@router.get("/api/pages/{page_id}/layout-review-next")
def next_layout_review_page(page_id: int) -> dict[str, object]:
    ensure_page_exists_or_404(page_id)
    return next_page_for_statuses(statuses=LAYOUT_REVIEW_QUEUE_STATUSES, current_page_id=page_id)


@router.get("/api/pages/{page_id}/ocr-review-next")
def next_ocr_review_page(page_id: int) -> dict[str, object]:
    ensure_page_exists_or_404(page_id)
    return next_page_for_status(status=OCR_REVIEW_QUEUE_STATUS, current_page_id=page_id)


@router.post("/api/pages/{page_id}/layouts/detect")
def detect_page_layouts(page_id: int, payload: DetectLayoutsRequest) -> dict[str, object]:
    return _run_manual_layout_detection(page_id, payload)


@router.post("/api/pages/{page_id}/layouts")
def create_page_layout(page_id: int, payload: CreateLayoutRequest) -> dict[str, object]:
    class_name = payload.class_name.strip()
    if not class_name:
        raise HTTPException(status_code=400, detail="class_name cannot be empty.")
    try:
        layout = create_layout(
            page_id,
            class_name=class_name,
            x1=payload.bbox.x1,
            y1=payload.bbox.y1,
            x2=payload.bbox.x2,
            y2=payload.bbox.y2,
            reading_order=payload.reading_order,
        )
    except ValueError as error:
        raise _http_exception_from_value_error(error) from error
    return {"layout": layout}


@router.put("/api/pages/{page_id}/caption-bindings")
def put_page_caption_bindings(
    page_id: int, payload: ReplaceCaptionBindingsRequest
) -> dict[str, object]:
    bindings_by_caption_id: dict[int, list[int]] = {}
    for binding in payload.bindings:
        caption_layout_id = int(binding.caption_layout_id)
        target_layout_ids = [int(target_id) for target_id in binding.target_layout_ids]
        current = bindings_by_caption_id.setdefault(caption_layout_id, [])
        current.extend(target_layout_ids)

    for caption_layout_id, target_layout_ids in list(bindings_by_caption_id.items()):
        deduplicated_ids: list[int] = []
        seen_target_ids: set[int] = set()
        for target_layout_id in target_layout_ids:
            if target_layout_id in seen_target_ids:
                continue
            seen_target_ids.add(target_layout_id)
            deduplicated_ids.append(target_layout_id)
        bindings_by_caption_id[caption_layout_id] = deduplicated_ids

    try:
        result = replace_caption_bindings(page_id, bindings_by_caption_id)
    except ValueError as error:
        raise _http_exception_from_value_error(error) from error
    return result


@router.patch("/api/layouts/{layout_id}")
def patch_layout(layout_id: int, payload: UpdateLayoutRequest) -> dict[str, object]:
    class_name = None if payload.class_name is None else payload.class_name.strip()
    if class_name == "":
        raise HTTPException(status_code=400, detail="class_name cannot be empty.")
    try:
        layout = update_layout(
            layout_id,
            class_name=class_name,
            reading_order=payload.reading_order,
            x1=None if payload.bbox is None else payload.bbox.x1,
            y1=None if payload.bbox is None else payload.bbox.y1,
            x2=None if payload.bbox is None else payload.bbox.x2,
            y2=None if payload.bbox is None else payload.bbox.y2,
        )
    except ValueError as error:
        raise _http_exception_from_value_error(
            error,
            not_found_messages=("Layout not found.",),
        ) from error
    return {"layout": layout}


@router.delete("/api/layouts/{layout_id}")
def remove_layout(layout_id: int) -> dict[str, object]:
    try:
        delete_layout(layout_id)
    except ValueError as error:
        raise _http_exception_from_value_error(error, default_status=404) from error
    return {"deleted": True, "layout_id": layout_id}


@router.post("/api/pages/{page_id}/layouts/review-complete")
def complete_layout_review(page_id: int) -> dict[str, object]:
    emit_lifecycle_started(
        stage=STAGE_LAYOUT_REVIEW,
        event_type=EVENT_MANUAL_REVIEW_COMPLETE_STARTED,
        page_id=page_id,
        message="Layout review completion requested.",
    )
    try:
        result = mark_layout_reviewed(page_id)
    except ValueError as error:
        emit_lifecycle_failed(
            stage=STAGE_LAYOUT_REVIEW,
            event_type=EVENT_MANUAL_REVIEW_COMPLETE_FAILED,
            page_id=page_id,
            message_prefix="Layout review completion failed",
            error=error,
        )
        raise _http_exception_from_value_error(error) from error
    emit_lifecycle_completed(
        stage=STAGE_LAYOUT_REVIEW,
        event_type=EVENT_MANUAL_REVIEW_COMPLETED,
        page_id=page_id,
        message="Layout review completed.",
        data={
            "layout_count": result["layout_count"],
            "status": result["status"],
            "ocr_invalidated_count": result.get("ocr_invalidated_count", 0),
            "ocr_missing_layout_count": result.get("ocr_missing_layout_count", 0),
        },
    )
    return result


@router.get("/api/pages/{page_id}/ocr-outputs")
def page_ocr_outputs(page_id: int) -> dict[str, object]:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    try:
        outputs = list_ocr_outputs(page_id)
    except ValueError as error:
        raise _http_exception_from_value_error(error) from error
    return {"page_id": page_id, "count": len(outputs), "outputs": outputs}


@router.patch("/api/ocr-outputs/{layout_id}")
def patch_ocr_output(layout_id: int, payload: UpdateOcrOutputRequest) -> dict[str, object]:
    try:
        output = update_ocr_output(layout_id, content=payload.content)
    except ValueError as error:
        raise _http_exception_from_value_error(
            error,
            not_found_messages=("OCR output not found.",),
        ) from error
    return {"output": output}


@router.post("/api/pages/{page_id}/ocr/review-complete")
def complete_ocr_review(page_id: int) -> dict[str, object]:
    emit_lifecycle_started(
        stage=STAGE_OCR_REVIEW,
        event_type=EVENT_MANUAL_REVIEW_COMPLETE_STARTED,
        page_id=page_id,
        message="OCR review completion requested.",
    )
    try:
        result = mark_ocr_reviewed(page_id)
    except ValueError as error:
        emit_lifecycle_failed(
            stage=STAGE_OCR_REVIEW,
            event_type=EVENT_MANUAL_REVIEW_COMPLETE_FAILED,
            page_id=page_id,
            message_prefix="OCR review completion failed",
            error=error,
        )
        raise _http_exception_from_value_error(error) from error
    emit_lifecycle_completed(
        stage=STAGE_OCR_REVIEW,
        event_type=EVENT_MANUAL_REVIEW_COMPLETED,
        page_id=page_id,
        message="OCR review completed.",
        data={"output_count": result["output_count"]},
    )
    return result


@router.post("/api/pages/{page_id}/ocr/reextract")
def reextract_ocr(page_id: int, payload: ReextractOcrRequest | None = None) -> dict[str, object]:
    params = payload or ReextractOcrRequest()
    return _run_manual_ocr_reextract(page_id, params)


@router.post("/api/final/export")
def run_final_export(payload: FinalExportRequest) -> dict[str, object]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Final export not confirmed.")
    emit_lifecycle_started(
        stage=STAGE_FINALIZATION,
        event_type=EVENT_EXPORT_STARTED,
        message="Final dataset export started.",
    )
    try:
        result = export_final_dataset()
    except ValueError as error:
        emit_lifecycle_failed(
            stage=STAGE_FINALIZATION,
            event_type=EVENT_EXPORT_FAILED,
            message_prefix="Final dataset export failed",
            error=error,
        )
        raise _http_exception_from_value_error(error) from error

    emit_lifecycle_completed(
        stage=STAGE_FINALIZATION,
        event_type=EVENT_EXPORT_COMPLETED,
        message=(
            "Final dataset export completed. "
            f"Pages: {result['page_count']}, images: {result['image_count']}, reconstructed: {result['reconstructed_count']}."
        ),
        data={
            "export_dir": result["export_dir"],
            "metadata_file": result["metadata_file"],
            "page_count": result["page_count"],
            "image_count": result["image_count"],
            "reconstructed_count": result["reconstructed_count"],
        },
    )
    return result
