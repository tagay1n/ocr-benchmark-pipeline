from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select

from ..db import get_session
from ..layouts import get_page
from ..models import DuplicateFile, Layout, OcrOutput, Page, PipelineEvent, PipelineJob
from ..ocr_review import list_ocr_outputs
from ..pipeline_constants import (
    EVENT_PAGE_REMOVED,
    EVENT_RUNTIME_OPTIONS_UPDATED,
    EVENT_WIPE_FINISHED,
    EVENT_WIPE_STARTED,
    STAGE_DISCOVERY,
    STAGE_PIPELINE,
)
from ..pipeline_runtime import emit_event, register_default_handlers
from ..runtime_options import (
    get_runtime_options,
    should_auto_detect_layouts_after_discovery,
    update_runtime_options,
)
from .schemas import RuntimeOptionsUpdateRequest, WipeStateRequest
from .shared import (
    _settings,
    _pipeline_stats_snapshot,
    emit_auto_layout_enqueue_event,
    run_discovery_scan_with_events,
)

router = APIRouter()


@router.get("/")
def root() -> FileResponse:
    return FileResponse("app/static/index.html")


@router.post("/api/discovery/scan")
def scan_images() -> dict[str, object]:
    register_default_handlers()
    response = run_discovery_scan_with_events(
        trigger="api",
        started_message="Discovery scan started",
        finished_prefix="Discovery scan finished.",
    )
    response["auto_layout_detection"] = (
        emit_auto_layout_enqueue_event(trigger="api", context_label="discovery scan")
        if should_auto_detect_layouts_after_discovery()
        else {
            "considered": 0,
            "queued": 0,
            "already_queued_or_running": 0,
        }
    )
    return response


@router.post("/api/state/wipe")
def wipe_state(payload: WipeStateRequest) -> dict[str, object]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Wipe not confirmed.")
    emit_event(
        stage=STAGE_PIPELINE,
        event_type=EVENT_WIPE_STARTED,
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
        rescan_summary = run_discovery_scan_with_events(
            trigger="wipe",
            started_message="Discovery scan started after wipe",
            finished_prefix="Discovery scan finished after wipe.",
        )
        if should_auto_detect_layouts_after_discovery():
            register_default_handlers()
            auto_layout_detection = emit_auto_layout_enqueue_event(
                trigger="wipe",
                context_label="wipe scan",
            )

    emit_event(
        stage=STAGE_PIPELINE,
        event_type=EVENT_WIPE_FINISHED,
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


@router.get("/api/runtime-options")
def runtime_options() -> dict[str, object]:
    snapshot = get_runtime_options()
    return {
        "enable_background_jobs": snapshot.enable_background_jobs,
        "auto_detect_layouts_after_discovery": snapshot.auto_detect_layouts_after_discovery,
        "auto_extract_text_after_layout_review": snapshot.auto_extract_text_after_layout_review,
    }


@router.put("/api/runtime-options")
def put_runtime_options(payload: RuntimeOptionsUpdateRequest) -> dict[str, object]:
    snapshot = update_runtime_options(
        auto_detect_layouts_after_discovery=payload.auto_detect_layouts_after_discovery,
        auto_extract_text_after_layout_review=payload.auto_extract_text_after_layout_review,
    )
    emit_event(
        stage=STAGE_PIPELINE,
        event_type=EVENT_RUNTIME_OPTIONS_UPDATED,
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


@router.get("/api/pages")
def list_pages() -> dict[str, object]:
    current_settings = _settings()
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
        "source_dir": str(current_settings.source_dir),
        "allowed_extensions": list(current_settings.allowed_extensions),
        "count": len(pages),
        "pages": pages,
    }


@router.delete("/api/pages/{page_id}")
def remove_page(page_id: int) -> dict[str, object]:
    current_settings = _settings()
    with get_session() as session:
        page_row = session.get(Page, page_id)
        if page_row is None:
            raise HTTPException(status_code=404, detail="Page not found.")

        rel_path = str(page_row.rel_path)
        source_root = current_settings.source_dir.resolve()
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
        stage=STAGE_DISCOVERY,
        event_type=EVENT_PAGE_REMOVED,
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


@router.get("/api/pages/{page_id}")
def page_details(page_id: int) -> dict[str, object]:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    image_path = _settings().source_dir / page["rel_path"]
    image_exists = image_path.exists() and image_path.is_file()
    image_version = int(image_path.stat().st_mtime_ns) if image_exists else 0
    return {
        "page": page,
        "image_url": f"/api/pages/{page_id}/image?v={image_version}",
        "image_exists": image_exists,
    }


@router.get("/api/pages/{page_id}/image")
def page_image(page_id: int) -> FileResponse:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    current_settings = _settings()
    image_path = (current_settings.source_dir / page["rel_path"]).resolve()
    source_root = current_settings.source_dir.resolve()
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


@router.get("/api/duplicates")
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


@router.get("/api/stats")
def stats() -> dict[str, int]:
    snapshot = _pipeline_stats_snapshot()
    return {
        "total_pages": snapshot["total_pages"],
        "missing_pages": snapshot["missing_pages"],
        "duplicate_files": snapshot["active_duplicate_files"],
    }
