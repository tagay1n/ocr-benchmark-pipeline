from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ..ocr_verification import (
    list_findings,
    get_finding_detail,
    request_findings_recalculation,
    recheck_layout,
    request_verification_stop,
    resolve_finding,
    start_verification,
    verification_status,
    verification_crop,
)
from .schemas import ResolveOcrVerificationRequest


router = APIRouter()


@router.get("/api/ocr-verification/status")
def get_ocr_verification_status() -> dict[str, object]:
    return verification_status()


@router.post("/api/ocr-verification/run")
def run_ocr_verification() -> dict[str, object]:
    return start_verification()


@router.post("/api/ocr-verification/stop")
def stop_ocr_verification() -> dict[str, object]:
    return request_verification_stop()


@router.post("/api/ocr-verification/recalculate")
def recalculate_ocr_verification() -> dict[str, object]:
    return request_findings_recalculation()


@router.get("/api/ocr-verification/findings")
def get_ocr_verification_findings(
    category: str | None = None,
    state: str | None = None,
    resolved: bool | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    return list_findings(
        category=category,
        state=state,
        resolved=resolved,
        limit=limit,
        offset=offset,
    )


@router.get("/api/ocr-verification/findings/{layout_id}")
def get_ocr_verification_finding(layout_id: int) -> dict[str, object]:
    try:
        return get_finding_detail(layout_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/api/ocr-verification/layouts/{layout_id}/crop")
def get_ocr_verification_crop(layout_id: int, request: Request) -> Response:
    try:
        crop, version = verification_crop(layout_id)
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    etag = f'"{version}"'
    headers = {
        "Cache-Control": "private, max-age=86400, immutable",
        "ETag": etag,
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=crop, media_type="image/png", headers=headers)


@router.post("/api/ocr-verification/layouts/{layout_id}/resolve")
def resolve_ocr_verification(
    layout_id: int,
    payload: ResolveOcrVerificationRequest,
) -> dict[str, object]:
    try:
        return resolve_finding(
            layout_id,
            action=payload.action,
            content=payload.content,
            source_task_id=payload.source_task_id,
        )
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@router.post("/api/ocr-verification/layouts/{layout_id}/recheck")
def recheck_ocr_verification(layout_id: int) -> dict[str, object]:
    try:
        return recheck_layout(layout_id)
    except ValueError as error:
        status_code = 404 if "not found" in str(error).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error
