from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    discover_images()
    yield


app = FastAPI(title="OCR Benchmark Pipeline", lifespan=lifespan)
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


@app.get("/")
def root() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.post("/api/discovery/scan")
def scan_images() -> dict[str, int | str]:
    summary = discover_images()
    return {
        "source_dir": summary.source_dir,
        "scanned_files": summary.scanned_files,
        "new_pages": summary.new_pages,
        "updated_pages": summary.updated_pages,
        "missing_marked": summary.missing_marked,
        "duplicate_files": summary.duplicate_files,
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
    return {
        "page": page,
        "image_url": f"/api/pages/{page_id}/image",
        "image_exists": image_path.exists() and image_path.is_file(),
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
    return FileResponse(image_path)


@app.get("/api/pages/{page_id}/layouts")
def page_layouts(page_id: int) -> dict[str, object]:
    page = get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    layouts = list_layouts(page_id)
    return {"page_id": page_id, "count": len(layouts), "layouts": layouts}


@app.post("/api/pages/{page_id}/layouts/detect")
def detect_page_layouts(page_id: int, payload: DetectLayoutsRequest) -> dict[str, object]:
    try:
        result = detect_layouts_for_page(
            page_id,
            replace_existing=payload.replace_existing,
            confidence_threshold=payload.confidence_threshold,
            iou_threshold=payload.iou_threshold,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
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
    try:
        result = mark_layout_reviewed(page_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return result


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
