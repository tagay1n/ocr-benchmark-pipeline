from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select

from .config import settings
from .db import get_session, init_db
from .discovery import discover_images
from .final_export import export_final_dataset
from .layouts import (
    create_layout,
    delete_layout,
    detect_layouts_for_page,
    get_page,
    list_layouts,
    mark_layout_reviewed,
    replace_caption_bindings,
    update_layout,
)
from .ocr_extract import extract_ocr_for_page
from .models import DuplicateFile, Layout, OcrOutput, Page, PipelineEvent, PipelineJob
from .pipeline_runtime import (
    emit_event,
    enqueue_job,
    enqueue_layout_detection_for_new_pages,
    get_activity_snapshot,
    register_default_handlers,
)
from .ocr_review import list_ocr_outputs, mark_ocr_reviewed, update_ocr_output
from .runtime_options import (
    get_runtime_options,
    reset_runtime_options_from_settings,
    should_auto_detect_layouts_after_discovery,
    should_auto_extract_text_after_layout_review,
    update_runtime_options,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    register_default_handlers()
    reset_runtime_options_from_settings()
    source_dir, allowed_extensions = _discovery_source_info()
    allowed_text = ", ".join(allowed_extensions)
    emit_event(
        stage="discovery",
        event_type="scan_started",
        message=f"Startup discovery scan started for folder {source_dir} (formats: {allowed_text}).",
        data={
            "trigger": "startup",
            "source_dir": source_dir,
            "allowed_extensions": allowed_extensions,
        },
    )
    summary = discover_images()
    stats_snapshot = _pipeline_stats_snapshot()
    emit_event(
        stage="discovery",
        event_type="scan_finished",
        message=_scan_finished_message(
            "Startup discovery scan finished.",
            {
                "scanned_files": summary.scanned_files,
                "new_pages": summary.new_pages,
                "updated_pages": summary.updated_pages,
                "missing_marked": summary.missing_marked,
                "duplicate_files": summary.duplicate_files,
                **stats_snapshot,
            },
        ),
        data={
            "trigger": "startup",
            "scanned_files": summary.scanned_files,
            "new_pages": summary.new_pages,
            "updated_pages": summary.updated_pages,
            "missing_marked": summary.missing_marked,
            "duplicate_files": summary.duplicate_files,
            **stats_snapshot,
        },
    )
    if should_auto_detect_layouts_after_discovery():
        auto = enqueue_layout_detection_for_new_pages()
        emit_event(
            stage="layout_detect",
            event_type="jobs_enqueued",
            message=f"Auto-enqueued {auto['queued']} layout detection jobs after startup discovery.",
            data={"trigger": "startup", **auto},
        )
    yield


app = FastAPI(title="OCR Pipeline", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _discovery_source_info() -> tuple[str, list[str]]:
    return str(settings.source_dir), list(settings.allowed_extensions)


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


class BBoxPayload(BaseModel):
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    x2: float = Field(ge=0.0, le=1.0)
    y2: float = Field(ge=0.0, le=1.0)


class DetectLayoutsRequest(BaseModel):
    replace_existing: bool = True
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    iou_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    image_size: int | None = Field(default=None, ge=32)
    max_detections: int | None = Field(default=None, ge=1)
    agnostic_nms: bool | None = None


class CreateLayoutRequest(BaseModel):
    class_name: str = Field(min_length=1, max_length=120)
    bbox: BBoxPayload
    reading_order: int | None = Field(default=None, ge=1)


class UpdateLayoutRequest(BaseModel):
    class_name: str | None = Field(default=None, min_length=1, max_length=120)
    reading_order: int | None = Field(default=None, ge=1)
    bbox: BBoxPayload | None = None


class WipeStateRequest(BaseModel):
    confirm: bool = False
    rescan: bool = True


class CaptionBindingPayload(BaseModel):
    caption_layout_id: int = Field(ge=1)
    target_layout_ids: list[int] = Field(default_factory=list)


class ReplaceCaptionBindingsRequest(BaseModel):
    bindings: list[CaptionBindingPayload] = Field(default_factory=list)


class UpdateOcrOutputRequest(BaseModel):
    content: str = ""


class ReextractOcrRequest(BaseModel):
    layout_ids: list[int] | None = None
    prompt_template: str | None = Field(default=None, max_length=20000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_retries_per_layout: int | None = Field(default=None, ge=1, le=10)


class RuntimeOptionsUpdateRequest(BaseModel):
    auto_detect_layouts_after_discovery: bool | None = None
    auto_extract_text_after_layout_review: bool | None = None


class FinalExportRequest(BaseModel):
    confirm: bool = False


def _run_manual_layout_detection(page_id: int, payload: DetectLayoutsRequest) -> dict[str, object]:
    emit_event(
        stage="layout_detect",
        event_type="manual_detect_started",
        page_id=page_id,
        message="Manual layout detection started.",
    )
    try:
        result = detect_layouts_for_page(
            page_id,
            replace_existing=payload.replace_existing,
            confidence_threshold=payload.confidence_threshold,
            iou_threshold=payload.iou_threshold,
            image_size=payload.image_size,
            max_detections=payload.max_detections,
            agnostic_nms=payload.agnostic_nms,
        )
    except ValueError as error:
        emit_event(
            stage="layout_detect",
            event_type="manual_detect_failed",
            page_id=page_id,
            message=f"Manual layout detection failed: {error}",
        )
        raise HTTPException(status_code=400, detail=str(error)) from error
    emit_event(
        stage="layout_detect",
        event_type="manual_detect_completed",
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
        stage="ocr_extract",
        event_type="job_started",
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
        result = extract_ocr_for_page(
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
            stage="ocr_extract",
            event_type="job_failed",
            page_id=page_id,
            message=f"Manual OCR reextraction failed: {error}",
            data={"trigger": "manual_reextract"},
        )
        raise HTTPException(status_code=400, detail=str(error)) from error

    emit_event(
        stage="ocr_extract",
        event_type="job_completed",
        page_id=page_id,
        message=(
            f"Manual OCR reextraction completed. "
            f"Extracted {result['extracted_count']}, skipped {result['skipped_count']}, "
            f"Gemini requests {result['requests_count']}."
        ),
        data={"trigger": "manual_reextract", "result": result},
    )
    return result


@app.get("/")
def root() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.post("/api/discovery/scan")
def scan_images() -> dict[str, object]:
    register_default_handlers()
    source_dir, allowed_extensions = _discovery_source_info()
    allowed_text = ", ".join(allowed_extensions)
    emit_event(
        stage="discovery",
        event_type="scan_started",
        message=f"Discovery scan started for folder {source_dir} (formats: {allowed_text}).",
        data={
            "trigger": "api",
            "source_dir": source_dir,
            "allowed_extensions": allowed_extensions,
        },
    )
    summary = discover_images()
    stats_snapshot = _pipeline_stats_snapshot()
    response: dict[str, object] = {
        "source_dir": summary.source_dir,
        "scanned_files": summary.scanned_files,
        "new_pages": summary.new_pages,
        "updated_pages": summary.updated_pages,
        "missing_marked": summary.missing_marked,
        "duplicate_files": summary.duplicate_files,
        **stats_snapshot,
    }
    emit_event(
        stage="discovery",
        event_type="scan_finished",
        message=_scan_finished_message("Discovery scan finished.", response),
        data={"trigger": "api", **response},
    )
    if should_auto_detect_layouts_after_discovery():
        auto = enqueue_layout_detection_for_new_pages()
        response["auto_layout_detection"] = auto
        emit_event(
            stage="layout_detect",
            event_type="jobs_enqueued",
            message=f"Auto-enqueued {auto['queued']} layout detection jobs after discovery scan.",
            data={"trigger": "api", **auto},
        )
    else:
        response["auto_layout_detection"] = {
            "considered": 0,
            "queued": 0,
            "already_queued_or_running": 0,
        }
    return response


@app.post("/api/state/wipe")
def wipe_state(payload: WipeStateRequest) -> dict[str, object]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Wipe not confirmed.")
    emit_event(
        stage="pipeline",
        event_type="wipe_started",
        message="Pipeline state wipe started.",
    )

    with get_session() as session:
        counts = {
            "pages": int(session.query(Page).count()),
            "layouts": int(session.query(Layout).count()),
            "duplicates": int(session.query(DuplicateFile).count()),
            "pipeline_jobs": int(session.query(PipelineJob).count()),
            "pipeline_events": int(session.query(PipelineEvent).count()),
        }
        session.execute(delete(PipelineEvent))
        session.execute(delete(PipelineJob))
        session.execute(delete(DuplicateFile))
        session.execute(delete(Layout))
        session.execute(delete(Page))

    rescan_summary: dict[str, int | str] | None = None
    auto_layout_detection: dict[str, int] | None = None
    if payload.rescan:
        source_dir, allowed_extensions = _discovery_source_info()
        allowed_text = ", ".join(allowed_extensions)
        emit_event(
            stage="discovery",
            event_type="scan_started",
            message=f"Discovery scan started after wipe for folder {source_dir} (formats: {allowed_text}).",
            data={
                "trigger": "wipe",
                "source_dir": source_dir,
                "allowed_extensions": allowed_extensions,
            },
        )
        summary = discover_images()
        stats_snapshot = _pipeline_stats_snapshot()
        rescan_summary = {
            "source_dir": summary.source_dir,
            "scanned_files": summary.scanned_files,
            "new_pages": summary.new_pages,
            "updated_pages": summary.updated_pages,
            "missing_marked": summary.missing_marked,
            "duplicate_files": summary.duplicate_files,
            **stats_snapshot,
        }
        emit_event(
            stage="discovery",
            event_type="scan_finished",
            message=_scan_finished_message("Discovery scan finished after wipe.", rescan_summary),
            data={"trigger": "wipe", **rescan_summary},
        )
        if should_auto_detect_layouts_after_discovery():
            register_default_handlers()
            auto_layout_detection = enqueue_layout_detection_for_new_pages()
            emit_event(
                stage="layout_detect",
                event_type="jobs_enqueued",
                message=f"Auto-enqueued {auto_layout_detection['queued']} layout detection jobs after wipe scan.",
                data={"trigger": "wipe", **auto_layout_detection},
            )

    emit_event(
        stage="pipeline",
        event_type="wipe_finished",
        message="Pipeline state wipe finished.",
        data={"deleted_counts": counts, "rescanned": payload.rescan},
    )
    return {
        "wiped": True,
        "deleted_counts": counts,
        "rescanned": payload.rescan,
        "rescan_summary": rescan_summary,
        "auto_layout_detection": auto_layout_detection,
    }


@app.get("/api/runtime-options")
def runtime_options() -> dict[str, object]:
    snapshot = get_runtime_options()
    return {
        "enable_background_jobs": snapshot.enable_background_jobs,
        "auto_detect_layouts_after_discovery": snapshot.auto_detect_layouts_after_discovery,
        "auto_extract_text_after_layout_review": snapshot.auto_extract_text_after_layout_review,
    }


@app.put("/api/runtime-options")
def put_runtime_options(payload: RuntimeOptionsUpdateRequest) -> dict[str, object]:
    snapshot = update_runtime_options(
        auto_detect_layouts_after_discovery=payload.auto_detect_layouts_after_discovery,
        auto_extract_text_after_layout_review=payload.auto_extract_text_after_layout_review,
    )
    emit_event(
        stage="pipeline",
        event_type="runtime_options_updated",
        message=(
            "Runtime pipeline options updated: "
            f"auto detect after discovery={snapshot.auto_detect_layouts_after_discovery}, "
            f"auto extract after layout review={snapshot.auto_extract_text_after_layout_review}."
        ),
        data={
            "auto_detect_layouts_after_discovery": snapshot.auto_detect_layouts_after_discovery,
            "auto_extract_text_after_layout_review": snapshot.auto_extract_text_after_layout_review,
        },
    )
    return {
        "enable_background_jobs": snapshot.enable_background_jobs,
        "auto_detect_layouts_after_discovery": snapshot.auto_detect_layouts_after_discovery,
        "auto_extract_text_after_layout_review": snapshot.auto_extract_text_after_layout_review,
    }


@app.get("/api/pages")
def list_pages() -> dict[str, object]:
    with get_session() as session:
        rows = session.execute(select(Page).order_by(Page.rel_path.asc())).scalars().all()

    pages = [
        {
            "id": int(row.id),
            "rel_path": row.rel_path,
            "status": row.status,
            "is_missing": bool(row.is_missing),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "last_seen_at": row.last_seen_at,
        }
        for row in rows
    ]

    return {
        "source_dir": str(settings.source_dir),
        "allowed_extensions": list(settings.allowed_extensions),
        "count": len(pages),
        "pages": pages,
    }


@app.delete("/api/pages/{page_id}")
def remove_page(page_id: int) -> dict[str, object]:
    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise HTTPException(status_code=404, detail="Page not found.")

        rel_path = str(page_row.rel_path)
        source_root = settings.source_dir.resolve()
        image_path = (source_root / rel_path).resolve()
        try:
            image_path.relative_to(source_root)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid page image path.") from error

        related_counts = {
            "layouts": int(session.query(Layout).filter(Layout.page_id == page_id).count()),
            "ocr_outputs": int(session.query(OcrOutput).filter(OcrOutput.page_id == page_id).count()),
            "duplicate_files": int(
                session.query(DuplicateFile)
                .filter(
                    (DuplicateFile.canonical_page_id == page_id)
                    | (DuplicateFile.rel_path == rel_path)
                )
                .count()
            ),
            "pipeline_jobs": int(session.query(PipelineJob).filter(PipelineJob.page_id == page_id).count()),
        }

    file_existed = image_path.exists()
    file_deleted = False
    if file_existed:
        if not image_path.is_file():
            raise HTTPException(status_code=400, detail="Page image path is not a file.")
        try:
            image_path.unlink()
            file_deleted = True
        except OSError as error:
            raise HTTPException(status_code=400, detail=f"Failed to remove image file: {error}") from error

    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise HTTPException(status_code=404, detail="Page not found.")

        session.execute(
            delete(DuplicateFile).where(
                (DuplicateFile.canonical_page_id == page_id)
                | (DuplicateFile.rel_path == rel_path)
            )
        )
        session.delete(page_row)

    stats_snapshot = _pipeline_stats_snapshot()
    emit_event(
        stage="discovery",
        event_type="page_removed",
        message=f"Removed page {rel_path} from dashboard dataset.",
        data={
            "page_id": page_id,
            "rel_path": rel_path,
            "file_existed": file_existed,
            "file_deleted": file_deleted,
            "related_counts": related_counts,
            **stats_snapshot,
        },
    )
    return {
        "deleted": True,
        "page_id": page_id,
        "rel_path": rel_path,
        "file_existed": file_existed,
        "file_deleted": file_deleted,
        "related_counts": related_counts,
        **stats_snapshot,
    }


@app.get("/api/pages/{page_id}")
def page_details(page_id: int) -> dict[str, object]:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    image_path = settings.source_dir / page["rel_path"]
    image_exists = image_path.exists() and image_path.is_file()
    image_version = int(image_path.stat().st_mtime_ns) if image_exists else 0
    return {
        "page": page,
        "image_url": f"/api/pages/{page_id}/image?v={image_version}",
        "image_exists": image_exists,
    }


@app.get("/api/pages/{page_id}/image")
def page_image(page_id: int) -> FileResponse:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    image_path = (settings.source_dir / page["rel_path"]).resolve()
    source_root = settings.source_dir.resolve()
    if source_root not in image_path.parents:
        raise HTTPException(status_code=400, detail="Invalid page image path.")
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image file not found.")
    return FileResponse(
        image_path,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/pages/{page_id}/layouts")
def page_layouts(page_id: int) -> dict[str, object]:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    layouts = list_layouts(page_id)
    return {"page_id": page_id, "count": len(layouts), "layouts": layouts}


@app.get("/api/layout-review/next")
def next_layout_review_page_global() -> dict[str, object]:
    with get_session() as session:
        row = session.execute(
            select(Page.id, Page.rel_path)
            .where(Page.is_missing.is_(False))
            .where(Page.status == "layout_detected")
            .order_by(Page.id.asc())
            .limit(1)
        ).first()

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


@app.get("/api/ocr-review/next")
def next_ocr_review_page_global() -> dict[str, object]:
    with get_session() as session:
        row = session.execute(
            select(Page.id, Page.rel_path)
            .where(Page.is_missing.is_(False))
            .where(Page.status == "ocr_done")
            .order_by(Page.id.asc())
            .limit(1)
        ).first()

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


@app.get("/api/pages/{page_id}/layout-review-next")
def next_layout_review_page(page_id: int) -> dict[str, object]:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    with get_session() as session:
        row = session.execute(
            select(Page.id, Page.rel_path)
            .where(Page.is_missing.is_(False))
            .where(Page.status == "layout_detected")
            .where(Page.id > page_id)
            .order_by(Page.id.asc())
            .limit(1)
        ).first()
        if row is None:
            row = session.execute(
                select(Page.id, Page.rel_path)
                .where(Page.is_missing.is_(False))
                .where(Page.status == "layout_detected")
                .where(Page.id < page_id)
                .order_by(Page.id.asc())
                .limit(1)
            ).first()

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


@app.get("/api/pages/{page_id}/ocr-review-next")
def next_ocr_review_page(page_id: int) -> dict[str, object]:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    with get_session() as session:
        row = session.execute(
            select(Page.id, Page.rel_path)
            .where(Page.is_missing.is_(False))
            .where(Page.status == "ocr_done")
            .where(Page.id > page_id)
            .order_by(Page.id.asc())
            .limit(1)
        ).first()
        if row is None:
            row = session.execute(
                select(Page.id, Page.rel_path)
                .where(Page.is_missing.is_(False))
                .where(Page.status == "ocr_done")
                .where(Page.id < page_id)
                .order_by(Page.id.asc())
                .limit(1)
            ).first()

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


@app.post("/api/pages/{page_id}/layouts/detect")
def detect_page_layouts(page_id: int, payload: DetectLayoutsRequest) -> dict[str, object]:
    return _run_manual_layout_detection(page_id, payload)


@app.post("/api/pages/{page_id}/layouts")
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
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"layout": layout}


@app.put("/api/pages/{page_id}/caption-bindings")
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
        raise HTTPException(status_code=400, detail=str(error)) from error
    return result


@app.patch("/api/layouts/{layout_id}")
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
        message = str(error)
        if message == "Layout not found.":
            raise HTTPException(status_code=404, detail=message) from error
        raise HTTPException(status_code=400, detail=message) from error
    return {"layout": layout}


@app.delete("/api/layouts/{layout_id}")
def remove_layout(layout_id: int) -> dict[str, object]:
    try:
        delete_layout(layout_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"deleted": True, "layout_id": layout_id}


@app.post("/api/pages/{page_id}/layouts/review-complete")
def complete_layout_review(page_id: int) -> dict[str, object]:
    emit_event(
        stage="layout_review",
        event_type="manual_review_complete_started",
        page_id=page_id,
        message="Layout review completion requested.",
    )
    try:
        result = mark_layout_reviewed(page_id)
    except ValueError as error:
        emit_event(
            stage="layout_review",
            event_type="manual_review_complete_failed",
            page_id=page_id,
            message=f"Layout review completion failed: {error}",
        )
        raise HTTPException(status_code=400, detail=str(error)) from error
    emit_event(
        stage="layout_review",
        event_type="manual_review_completed",
        page_id=page_id,
        message="Layout review completed.",
        data={"layout_count": result["layout_count"]},
    )
    if should_auto_extract_text_after_layout_review():
        enqueued = enqueue_job("ocr_extract", page_id=page_id, payload={"trigger": "layout_review_complete"})
        if enqueued:
            emit_event(
                stage="ocr_extract",
                event_type="job_enqueued",
                page_id=page_id,
                message="Queued OCR extraction after layout review completion.",
                data={"trigger": "layout_review_complete"},
            )
        else:
            emit_event(
                stage="ocr_extract",
                event_type="job_enqueue_skipped",
                page_id=page_id,
                message="Skipped queuing OCR extraction because a job is already queued or running.",
                data={"trigger": "layout_review_complete"},
            )
    return result


@app.get("/api/pages/{page_id}/ocr-outputs")
def page_ocr_outputs(page_id: int) -> dict[str, object]:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    try:
        outputs = list_ocr_outputs(page_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"page_id": page_id, "count": len(outputs), "outputs": outputs}


@app.patch("/api/ocr-outputs/{layout_id}")
def patch_ocr_output(layout_id: int, payload: UpdateOcrOutputRequest) -> dict[str, object]:
    try:
        output = update_ocr_output(layout_id, content=payload.content)
    except ValueError as error:
        message = str(error)
        if message == "OCR output not found.":
            raise HTTPException(status_code=404, detail=message) from error
        raise HTTPException(status_code=400, detail=message) from error
    return {"output": output}


@app.post("/api/pages/{page_id}/ocr/review-complete")
def complete_ocr_review(page_id: int) -> dict[str, object]:
    emit_event(
        stage="ocr_review",
        event_type="manual_review_complete_started",
        page_id=page_id,
        message="OCR review completion requested.",
    )
    try:
        result = mark_ocr_reviewed(page_id)
    except ValueError as error:
        emit_event(
            stage="ocr_review",
            event_type="manual_review_complete_failed",
            page_id=page_id,
            message=f"OCR review completion failed: {error}",
        )
        raise HTTPException(status_code=400, detail=str(error)) from error
    emit_event(
        stage="ocr_review",
        event_type="manual_review_completed",
        page_id=page_id,
        message="OCR review completed.",
        data={"output_count": result["output_count"]},
    )
    return result


@app.post("/api/pages/{page_id}/ocr/reextract")
def reextract_ocr(page_id: int, payload: ReextractOcrRequest | None = None) -> dict[str, object]:
    params = payload or ReextractOcrRequest()
    return _run_manual_ocr_reextract(page_id, params)


@app.post("/api/final/export")
def run_final_export(payload: FinalExportRequest) -> dict[str, object]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Final export not confirmed.")
    emit_event(
        stage="finalization",
        event_type="export_started",
        message="Final dataset export started.",
    )
    try:
        result = export_final_dataset()
    except ValueError as error:
        emit_event(
            stage="finalization",
            event_type="export_failed",
            message=f"Final dataset export failed: {error}",
        )
        raise HTTPException(status_code=400, detail=str(error)) from error

    emit_event(
        stage="finalization",
        event_type="export_completed",
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


@app.get("/api/pipeline/activity")
def pipeline_activity(limit: int = 30) -> dict[str, object]:
    register_default_handlers()
    return get_activity_snapshot(limit=limit)


@app.get("/api/pipeline/activity/stream")
async def pipeline_activity_stream(request: Request, limit: int = 30) -> StreamingResponse:
    register_default_handlers()
    safe_limit = max(1, min(limit, 200))

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            payload = get_activity_snapshot(limit=safe_limit)
            yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
            await asyncio.sleep(2.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/duplicates")
def list_duplicates() -> dict[str, object]:
    with get_session() as session:
        rows = session.execute(
            select(
                DuplicateFile.rel_path,
                DuplicateFile.file_hash,
                DuplicateFile.first_seen_at,
                DuplicateFile.last_seen_at,
                Page.rel_path,
            )
            .join(Page, Page.id == DuplicateFile.canonical_page_id)
            .where(DuplicateFile.active.is_(True))
            .order_by(DuplicateFile.rel_path.asc())
        ).all()

    duplicates = [
        {
            "duplicate_rel_path": row[0],
            "canonical_rel_path": row[4],
            "file_hash": row[1],
            "first_seen_at": row[2],
            "last_seen_at": row[3],
        }
        for row in rows
    ]

    return {
        "count": len(duplicates),
        "duplicates": duplicates,
    }


@app.get("/api/stats")
def stats() -> dict[str, int]:
    snapshot = _pipeline_stats_snapshot()
    return {
        "total_pages": snapshot["total_pages"],
        "missing_pages": snapshot["missing_pages"],
        "duplicate_files": snapshot["active_duplicate_files"],
    }
