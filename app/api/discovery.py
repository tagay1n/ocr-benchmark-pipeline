from __future__ import annotations

import base64
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import and_, delete, func, or_, select

from ..db import get_session
from ..layouts import get_page, normalize_layout_order_mode
from ..models import DuplicateFile, Layout, OcrOutput, Page, PipelineEvent, PipelineJob
from ..ocr_extract import default_ocr_model, supported_ocr_models
from ..ocr_review import list_ocr_outputs
from ..pipeline_constants import (
    EVENT_PAGE_REMOVED,
    EVENT_WIPE_FINISHED,
    EVENT_WIPE_STARTED,
    STAGE_DISCOVERY,
    STAGE_PIPELINE,
)
from ..pipeline_runtime import emit_event, register_default_handlers
from .schemas import WipeStateRequest
from .shared import (
    _settings,
    _pipeline_stats_snapshot,
    run_discovery_scan_with_events,
)

router = APIRouter()

_PAGE_SORT_DEFAULT = "rel_path"
_PAGE_DIRECTION_DEFAULT = "asc"
_PAGE_SORT_KEYS = frozenset({"id", "rel_path", "status", "created_at"})
_PAGE_DIRECTION_KEYS = frozenset({"asc", "desc"})
_PAGE_MAX_LIMIT = 200


def _normalize_pages_sort(sort: str | None, direction: str | None) -> tuple[str, str]:
    normalized_sort = str(sort or "").strip().lower()
    if normalized_sort not in _PAGE_SORT_KEYS:
        normalized_sort = _PAGE_SORT_DEFAULT
    normalized_direction = str(direction or "").strip().lower()
    if normalized_direction not in _PAGE_DIRECTION_KEYS:
        normalized_direction = _PAGE_DIRECTION_DEFAULT
    return normalized_sort, normalized_direction


def _normalize_pages_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    if int(limit) < 1 or int(limit) > _PAGE_MAX_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"limit must be between 1 and {_PAGE_MAX_LIMIT}.",
        )
    return int(limit)


def _pages_sort_column(sort_key: str):
    if sort_key == "id":
        return Page.id
    if sort_key == "status":
        return Page.status
    if sort_key == "created_at":
        return Page.created_at
    return Page.rel_path


def _encode_pages_cursor(*, sort: str, direction: str, value: str | int, page_id: int) -> str:
    payload = {
        "s": sort,
        "d": direction,
        "v": value,
        "i": int(page_id),
    }
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_pages_cursor(cursor: str, *, sort: str, direction: str) -> tuple[str | int, int]:
    normalized = str(cursor or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Invalid cursor.")
    padding = "=" * (-len(normalized) % 4)
    try:
        raw = base64.urlsafe_b64decode((normalized + padding).encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
    except Exception as error:
        raise HTTPException(status_code=400, detail="Invalid cursor.") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid cursor.")
    if str(payload.get("s")) != sort or str(payload.get("d")) != direction:
        raise HTTPException(status_code=400, detail="Cursor does not match current sort parameters.")

    cursor_page_id = payload.get("i")
    if not isinstance(cursor_page_id, int) or cursor_page_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid cursor.")

    cursor_value_raw = payload.get("v")
    if sort == "id":
        if not isinstance(cursor_value_raw, int):
            raise HTTPException(status_code=400, detail="Invalid cursor.")
        cursor_value: str | int = int(cursor_value_raw)
    else:
        cursor_value = str(cursor_value_raw or "")

    return cursor_value, int(cursor_page_id)


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
    response["auto_layout_detection"] = {
        "considered": 0,
        "queued": 0,
        "already_queued_or_running": 0,
    }
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
        auto_layout_detection = {
            "considered": 0,
            "queued": 0,
            "already_queued_or_running": 0,
        }

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
@router.get("/api/pages")
def list_pages(
    limit: int | None = None,
    cursor: str | None = None,
    sort: str | None = None,
    direction: str | None = None,
    dir: str | None = None,
) -> dict[str, object]:
    current_settings = _settings()
    sort_key, direction_key = _normalize_pages_sort(sort, direction if direction is not None else dir)
    page_limit = _normalize_pages_limit(limit)
    if cursor and page_limit is None:
        raise HTTPException(status_code=400, detail="cursor requires a limit.")

    sort_column = _pages_sort_column(sort_key)
    order_expression = sort_column.asc() if direction_key == "asc" else sort_column.desc()
    tie_breaker = Page.id.asc() if direction_key == "asc" else Page.id.desc()

    with get_session() as session:
        total_count = int(session.query(Page).count())
        query = select(Page)
        if page_limit is not None:
            if cursor:
                cursor_value, cursor_page_id = _decode_pages_cursor(
                    str(cursor),
                    sort=sort_key,
                    direction=direction_key,
                )
                if direction_key == "asc":
                    query = query.where(
                        or_(
                            sort_column > cursor_value,
                            and_(sort_column == cursor_value, Page.id > cursor_page_id),
                        )
                    )
                else:
                    query = query.where(
                        or_(
                            sort_column < cursor_value,
                            and_(sort_column == cursor_value, Page.id < cursor_page_id),
                        )
                    )
            rows = (
                session.execute(query.order_by(order_expression, tie_breaker).limit(page_limit + 1))
                .scalars()
                .all()
            )
        else:
            rows = session.execute(query.order_by(order_expression, tie_breaker)).scalars().all()

    has_more = False
    next_cursor: str | None = None
    if page_limit is not None and len(rows) > page_limit:
        has_more = True
        rows = rows[:page_limit]

    if rows:
        last_row = rows[-1]
        cursor_value: str | int
        if sort_key == "id":
            cursor_value = int(last_row.id)
        else:
            cursor_value = str(getattr(last_row, sort_key))
        next_cursor = _encode_pages_cursor(
            sort=sort_key,
            direction=direction_key,
            value=cursor_value,
            page_id=int(last_row.id),
        ) if has_more else None

    pages = [
        {
            "id": int(row.id),
            "rel_path": row.rel_path,
            "status": row.status,
            "is_missing": bool(row.is_missing),
            "layout_order_mode": normalize_layout_order_mode(getattr(row, "layout_order_mode", None)),
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
        "total_count": int(total_count),
        "has_more": bool(has_more),
        "next_cursor": next_cursor,
        "sort": sort_key,
        "direction": direction_key,
        "limit": page_limit,
        "cursor": cursor,
        "pages": pages,
    }


@router.get("/api/pages/summary")
def pages_summary() -> dict[str, object]:
    with get_session() as session:
        total_pages = int(session.query(Page).filter(Page.is_missing.is_(False)).count())
        missing_pages = int(session.query(Page).filter(Page.is_missing.is_(True)).count())
        grouped_rows = session.execute(
            select(Page.status, func.count(Page.id))
            .where(Page.is_missing.is_(False))
            .group_by(Page.status)
            .order_by(Page.status.asc())
        ).all()

    by_status = {str(status): int(count) for status, count in grouped_rows}
    return {
        "total_pages": total_pages,
        "missing_pages": missing_pages,
        "by_status": by_status,
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
        "ocr_models": {
            "default_model": default_ocr_model(),
            "batch_model": default_ocr_model(),
            "supported_models": list(supported_ocr_models()),
        },
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
