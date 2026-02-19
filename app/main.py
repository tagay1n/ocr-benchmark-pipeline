from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import get_connection, init_db
from .discovery import discover_images
from .layouts import (
    create_layout,
    delete_layout,
    detect_layouts_for_page,
    get_page,
    list_layouts,
    mark_layout_reviewed,
    update_layout,
)
from .pipeline_runtime import (
    emit_event,
    enqueue_layout_detection_for_new_pages,
    get_activity_snapshot,
    register_default_handlers,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    register_default_handlers()
    emit_event(
        stage="discovery",
        event_type="scan_started",
        message="Startup discovery scan started.",
        data={"trigger": "startup"},
    )
    summary = discover_images()
    emit_event(
        stage="discovery",
        event_type="scan_finished",
        message="Startup discovery scan finished.",
        data={
            "trigger": "startup",
            "scanned_files": summary.scanned_files,
            "new_pages": summary.new_pages,
            "updated_pages": summary.updated_pages,
            "missing_marked": summary.missing_marked,
            "duplicate_files": summary.duplicate_files,
        },
    )
    if settings.enable_background_jobs:
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


class BBoxPayload(BaseModel):
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    x2: float = Field(ge=0.0, le=1.0)
    y2: float = Field(ge=0.0, le=1.0)


class DetectLayoutsRequest(BaseModel):
    replace_existing: bool = True
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    iou_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


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


@app.get("/")
def root() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.post("/api/discovery/scan")
def scan_images() -> dict[str, object]:
    register_default_handlers()
    emit_event(
        stage="discovery",
        event_type="scan_started",
        message="Discovery scan started.",
        data={"trigger": "api"},
    )
    summary = discover_images()
    response: dict[str, object] = {
        "source_dir": summary.source_dir,
        "scanned_files": summary.scanned_files,
        "new_pages": summary.new_pages,
        "updated_pages": summary.updated_pages,
        "missing_marked": summary.missing_marked,
        "duplicate_files": summary.duplicate_files,
    }
    emit_event(
        stage="discovery",
        event_type="scan_finished",
        message="Discovery scan finished.",
        data={"trigger": "api", **response},
    )
    if settings.enable_background_jobs:
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

    with get_connection() as conn:
        counts = {
            "pages": int(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]),
            "layouts": int(conn.execute("SELECT COUNT(*) FROM layouts").fetchone()[0]),
            "duplicates": int(conn.execute("SELECT COUNT(*) FROM duplicate_files").fetchone()[0]),
            "pipeline_jobs": int(conn.execute("SELECT COUNT(*) FROM pipeline_jobs").fetchone()[0]),
            "pipeline_events": int(conn.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0]),
        }
        conn.execute("DELETE FROM pipeline_events")
        conn.execute("DELETE FROM pipeline_jobs")
        conn.execute("DELETE FROM duplicate_files")
        conn.execute("DELETE FROM layouts")
        conn.execute("DELETE FROM pages")
        conn.execute(
            """
            DELETE FROM sqlite_sequence
            WHERE name IN ('pages', 'duplicate_files', 'layouts', 'pipeline_jobs', 'pipeline_events')
            """
        )

    rescan_summary: dict[str, int | str] | None = None
    auto_layout_detection: dict[str, int] | None = None
    if payload.rescan:
        emit_event(
            stage="discovery",
            event_type="scan_started",
            message="Discovery scan started after wipe.",
            data={"trigger": "wipe"},
        )
        summary = discover_images()
        rescan_summary = {
            "source_dir": summary.source_dir,
            "scanned_files": summary.scanned_files,
            "new_pages": summary.new_pages,
            "updated_pages": summary.updated_pages,
            "missing_marked": summary.missing_marked,
            "duplicate_files": summary.duplicate_files,
        }
        emit_event(
            stage="discovery",
            event_type="scan_finished",
            message="Discovery scan finished after wipe.",
            data={"trigger": "wipe", **rescan_summary},
        )
        if settings.enable_background_jobs:
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


@app.get("/api/pages")
def list_pages() -> dict[str, object]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, rel_path, status, is_missing, created_at, updated_at, last_seen_at
            FROM pages
            ORDER BY rel_path
            """
        ).fetchall()

    pages = [
        {
            "id": int(row["id"]),
            "rel_path": row["rel_path"],
            "status": row["status"],
            "is_missing": bool(row["is_missing"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_seen_at": row["last_seen_at"],
        }
        for row in rows
    ]

    return {
        "source_dir": str(settings.source_dir),
        "allowed_extensions": list(settings.allowed_extensions),
        "count": len(pages),
        "pages": pages,
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


@app.post("/api/pages/{page_id}/layouts/detect")
def detect_page_layouts(page_id: int, payload: DetectLayoutsRequest) -> dict[str, object]:
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
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                d.rel_path AS duplicate_rel_path,
                d.file_hash,
                d.first_seen_at,
                d.last_seen_at,
                p.rel_path AS canonical_rel_path
            FROM duplicate_files d
            JOIN pages p ON p.id = d.canonical_page_id
            WHERE d.active = 1
            ORDER BY d.rel_path
            """
        ).fetchall()

    duplicates = [
        {
            "duplicate_rel_path": row["duplicate_rel_path"],
            "canonical_rel_path": row["canonical_rel_path"],
            "file_hash": row["file_hash"],
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
        }
        for row in rows
    ]

    return {
        "count": len(duplicates),
        "duplicates": duplicates,
    }


@app.get("/api/stats")
def stats() -> dict[str, int]:
    with get_connection() as conn:
        total_pages = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        missing_pages = conn.execute("SELECT COUNT(*) FROM pages WHERE is_missing = 1").fetchone()[0]
        duplicate_count = conn.execute("SELECT COUNT(*) FROM duplicate_files WHERE active = 1").fetchone()[0]

    return {
        "total_pages": int(total_pages),
        "missing_pages": int(missing_pages),
        "duplicate_files": int(duplicate_count),
    }
