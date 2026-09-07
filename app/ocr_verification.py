from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
import json
import logging
import re
from threading import Lock, Thread
import time
from typing import Any

from PIL import Image
from sqlalchemy import delete, func, select

from .config import settings
from .db import get_session
from .layout_classes import MARKDOWN_LAYOUT_CLASSES, normalize_class_name
from .layout_orientation import is_effective_vertical
from .models import (
    Layout,
    OcrOutput,
    OcrVerificationFinding,
    OcrVerificationResolution,
    OcrVerificationRun,
    OcrVerificationTask,
    Page,
)
from .ocr_content_postprocess import normalize_ocr_content
from .ocr_extract import (
    _apply_section_header_heading_level,
    _crop_layout_png_bytes,
    _fetch_page_layouts,
    _list_item_indent_levels_by_layout_id,
    _load_usage_state,
    _mark_key_exhausted,
    _next_available_key,
    _normalize_list_item_line,
    _section_header_levels_by_layout_id,
)
from .ocr_gemini_client import (
    DEFAULT_GEMINI_TEMPERATURE,
    gemini_generate_content,
    is_daily_quota_exhausted_error,
    is_gemini_server_error,
    is_quota_error,
    key_alias,
)
from .ocr_key_store import GeminiDailyQuotaExhaustedError, GeminiQuotaExhaustedError
from .ocr_prompts import DEFAULT_PROMPT_TEMPLATE, render_prompt_for_layout_class


COMPARISON_VERSION = 1
logger = logging.getLogger(__name__)
_ACTIVE_RUN_STATUSES = frozenset({"preparing", "running", "stop_requested"})
_ACTIVE_TASK_STATUSES = frozenset({"pending", "waiting"})
_TERMINAL_TASK_STATUSES = frozenset({"succeeded", "unavailable"})
_WORKER_LOCK = Lock()
_WORKER_THREAD: Thread | None = None
_PREPARATION_THREAD: Thread | None = None
_RECALCULATION_THREAD: Thread | None = None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _sha256_payload(value: object) -> str:
    return hashlib.sha256(_json_dumps(value).encode("utf-8")).hexdigest()


def verification_models() -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for raw_model in settings.ocr_verification_models:
        model = str(raw_model or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        output.append(model)
    return tuple(output)


def select_validator_models(source_model: str) -> tuple[str, ...]:
    count = max(1, int(settings.ocr_verification_total_models) - 1)
    source = str(source_model or "").strip()
    return tuple(model for model in verification_models() if model != source)[:count]


def _layout_dict(layout: Layout) -> dict[str, Any]:
    bbox = {
        "x1": float(layout.x1),
        "y1": float(layout.y1),
        "x2": float(layout.x2),
        "y2": float(layout.y2),
    }
    orientation = str(getattr(layout, "orientation", "horizontal"))
    return {
        "id": int(layout.id),
        "class_name": normalize_class_name(str(layout.class_name)),
        "reading_order": int(layout.reading_order),
        "bbox": bbox,
        "orientation": orientation,
        "effective_orientation": (
            "vertical" if is_effective_vertical(orientation=orientation, bbox=bbox) else "horizontal"
        ),
    }


def _verification_context(
    page: Page,
    layout: Layout,
    output: OcrOutput,
    *,
    page_layout_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    layout_payload = _layout_dict(layout)
    if page_layout_context is None:
        page_layout_context = _fetch_page_layouts(int(page.id))
    normalized_page_context = [
        {
            "id": int(row["id"]),
            "class_name": str(row["class_name"]),
            "reading_order": int(row["reading_order"]),
            "bbox": row["bbox"],
            "orientation": str(row["orientation"]),
        }
        for row in page_layout_context
    ]
    rendered = render_prompt_for_layout_class(
        str(layout_payload["class_name"]),
        prompt_template=DEFAULT_PROMPT_TEMPLATE,
    )
    prompt_hash = hashlib.sha256(rendered.prompt.encode("utf-8")).hexdigest()
    base_payload = {
        "page_file_hash": str(page.file_hash),
        "layout_id": int(layout.id),
        "class_name": str(layout_payload["class_name"]),
        "bbox": layout_payload["bbox"],
        "orientation": str(layout_payload["orientation"]),
        "page_layout_context": normalized_page_context,
        "prompt_hash": prompt_hash,
        "prompt_version": int(settings.ocr_verification_prompt_version),
    }
    return {
        "layout": layout_payload,
        "prompt": rendered.prompt,
        "prompt_hash": prompt_hash,
        "output_format": rendered.output_format,
        "base_fingerprint": _sha256_payload(base_payload),
        "source_model": str(output.model_name),
        "baseline_content": str(output.content),
        "validator_models": select_validator_models(str(output.model_name)),
    }


def _task_fingerprint(base_fingerprint: str, model_name: str) -> str:
    return _sha256_payload({"base": base_fingerprint, "model": model_name})


def _eligible_rows() -> list[tuple[Page, Layout, OcrOutput]]:
    with get_session() as session:
        rows = session.execute(
            select(Page, Layout, OcrOutput)
            .join(Layout, Layout.page_id == Page.id)
            .join(OcrOutput, OcrOutput.layout_id == Layout.id)
            .where(Page.is_missing.is_(False))
            .where(func.lower(Page.status) == "ocr_reviewed")
            .order_by(Page.id.asc(), Layout.reading_order.asc(), Layout.id.asc())
        ).all()
        return [
            (page, layout, output)
            for page, layout, output in rows
            if normalize_class_name(str(layout.class_name)) in MARKDOWN_LAYOUT_CLASSES
            and str(output.extraction_status or "").lower() in {"ok", "manual"}
            and str(output.output_format or "").lower() == "markdown"
        ]


def _page_layout_contexts(
    rows: list[tuple[Page, Layout, OcrOutput]],
) -> dict[int, list[dict[str, Any]]]:
    return {
        page_id: _fetch_page_layouts(page_id)
        for page_id in sorted({int(page.id) for page, _layout, _output in rows})
    }


def _upsert_current_tasks(
    run_id: int,
    *,
    rows: list[tuple[Page, Layout, OcrOutput]] | None = None,
    page_contexts: dict[int, list[dict[str, Any]]] | None = None,
) -> tuple[int, set[int]]:
    now = _utc_now()
    task_count = 0
    affected_layout_ids: set[int] = set()
    eligible_rows = _eligible_rows() if rows is None else rows
    contexts = _page_layout_contexts(eligible_rows) if page_contexts is None else page_contexts
    prepared: list[tuple[Page, Layout, dict[str, Any], str, str]] = []
    for page, layout, output in eligible_rows:
        context = _verification_context(
            page,
            layout,
            output,
            page_layout_context=contexts[int(page.id)],
        )
        affected_layout_ids.add(int(layout.id))
        for model_name in context["validator_models"]:
            fingerprint = _task_fingerprint(str(context["base_fingerprint"]), model_name)
            prepared.append((page, layout, context, model_name, fingerprint))

    layout_ids = sorted(affected_layout_ids)
    with get_session() as session:
        existing_tasks = session.execute(
            select(OcrVerificationTask).where(OcrVerificationTask.layout_id.in_(layout_ids))
        ).scalars().all() if layout_ids else []
        existing_by_evidence = {
            (int(task.layout_id), str(task.model_name), str(task.evidence_fingerprint)): task
            for task in existing_tasks
        }
        for page, layout, context, model_name, fingerprint in prepared:
            task = existing_by_evidence.get((int(layout.id), model_name, fingerprint))
            if task is None:
                task = OcrVerificationTask(
                    run_id=run_id,
                    page_id=int(page.id),
                    layout_id=int(layout.id),
                    model_name=model_name,
                    evidence_fingerprint=fingerprint,
                    prompt_hash=str(context["prompt_hash"]),
                    prompt_version=int(settings.ocr_verification_prompt_version),
                    status="pending",
                    attempts=0,
                    transient_count=0,
                    next_retry_at=None,
                    content=None,
                    key_alias=None,
                    error_message=None,
                    created_at=now,
                    updated_at=now,
                    finished_at=None,
                )
                session.add(task)
                task_count += 1
            elif str(task.status) in {"pending", "waiting"}:
                task.run_id = run_id
                # Preserve cooldowns and retry age across manual resumes.
                task_count += 1
    return task_count, affected_layout_ids


def _comparison_groups(
    baseline: str,
    source_model: str,
    tasks: list[OcrVerificationTask],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    def add(content: str, source: dict[str, Any]) -> None:
        group = grouped.setdefault(content, {"content": content, "sources": []})
        group["sources"].append(source)

    add(baseline, {"kind": "baseline", "name": "Reviewed baseline", "source_model": source_model})
    for task in tasks:
        if str(task.status) != "succeeded" or task.content is None:
            continue
        add(
            str(task.content),
            {"kind": "model", "name": str(task.model_name), "task_id": int(task.id)},
        )
    return list(grouped.values())


def refresh_finding(
    layout_id: int,
    *,
    page_layout_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    with get_session() as session:
        row = session.execute(
            select(Page, Layout, OcrOutput)
            .join(Layout, Layout.page_id == Page.id)
            .join(OcrOutput, OcrOutput.layout_id == Layout.id)
            .where(Layout.id == int(layout_id))
        ).one_or_none()
        if row is None:
            return None
        page, layout, output = row
        if (
            bool(page.is_missing)
            or str(page.status).lower() != "ocr_reviewed"
            or normalize_class_name(str(layout.class_name)) not in MARKDOWN_LAYOUT_CLASSES
            or str(output.output_format).lower() != "markdown"
        ):
            return None
        context = _verification_context(
            page,
            layout,
            output,
            page_layout_context=page_layout_context,
        )
        fingerprints = {
            _task_fingerprint(str(context["base_fingerprint"]), model_name)
            for model_name in context["validator_models"]
        }
        tasks = []
        if fingerprints:
            tasks = session.execute(
                select(OcrVerificationTask)
                .where(
                    OcrVerificationTask.layout_id == int(layout_id),
                    OcrVerificationTask.evidence_fingerprint.in_(fingerprints),
                )
                .order_by(OcrVerificationTask.id.asc())
            ).scalars().all()

        responded = sum(1 for task in tasks if str(task.status) == "succeeded")
        finding = session.get(OcrVerificationFinding, int(layout_id))
        active = False
        for task in tasks:
            if str(task.status) not in _ACTIVE_TASK_STATUSES or task.run_id is None:
                continue
            task_run = session.get(OcrVerificationRun, int(task.run_id))
            if (
                task_run is not None
                and str(task_run.status) in _ACTIVE_RUN_STATUSES
                and not bool(task_run.stop_requested)
            ):
                active = True
                break
        groups = _comparison_groups(str(output.content), str(output.model_name), tasks)
        if active:
            state = "waiting"
        elif responded >= 2:
            state = "agreed_full" if len(groups) == 1 else "disagreement_full"
        elif responded == 1:
            state = "agreed_reduced" if len(groups) == 1 else "disagreement_reduced"
        elif not tasks and context["validator_models"]:
            state = (
                "stale"
                if finding is not None
                and str(finding.evidence_fingerprint) != str(context["base_fingerprint"])
                else "not_started"
            )
        else:
            state = "manual_check"

        comparison_fingerprint = _sha256_payload(
            {
                "evidence": str(context["base_fingerprint"]),
                "baseline": str(output.content),
                "validator_models": list(context["validator_models"]),
                "tasks": [
                    {
                        "id": int(task.id),
                        "status": str(task.status),
                        "content": task.content,
                    }
                    for task in tasks
                ],
                "version": COMPARISON_VERSION,
            }
        )
        now = _utc_now()
        if finding is None:
            finding = OcrVerificationFinding(
                layout_id=int(layout_id),
                page_id=int(page.id),
                evidence_fingerprint=str(context["base_fingerprint"]),
                comparison_fingerprint=comparison_fingerprint,
                comparison_version=COMPARISON_VERSION,
                baseline_content=str(output.content),
                source_model=str(output.model_name),
                state=state,
                groups_json=_json_dumps(groups),
                responded_count=responded,
                required_count=max(1, int(settings.ocr_verification_total_models) - 1),
                resolved=False,
                created_at=now,
                updated_at=now,
            )
            session.add(finding)
        else:
            keep_resolution = finding.comparison_fingerprint == comparison_fingerprint and bool(finding.resolved)
            finding.page_id = int(page.id)
            finding.evidence_fingerprint = str(context["base_fingerprint"])
            finding.comparison_fingerprint = comparison_fingerprint
            finding.comparison_version = COMPARISON_VERSION
            finding.baseline_content = str(output.content)
            finding.source_model = str(output.model_name)
            finding.state = state
            finding.groups_json = _json_dumps(groups)
            finding.responded_count = responded
            finding.required_count = max(1, int(settings.ocr_verification_total_models) - 1)
            finding.resolved = keep_resolution
            finding.updated_at = now
        session.flush()
        return _finding_to_dict(finding, page=page, layout=layout, tasks=tasks)


def recalculate_findings() -> dict[str, int]:
    rows = _eligible_rows()
    page_contexts = _page_layout_contexts(rows)
    layout_rows = {
        int(layout.id): (int(page.id), layout)
        for page, layout, _output in rows
    }
    layout_ids = set(layout_rows)
    with get_session() as session:
        existing_ids = set(
            int(value)
            for value in session.execute(select(OcrVerificationFinding.layout_id)).scalars().all()
        )
        obsolete_ids = existing_ids.difference(layout_ids)
        if obsolete_ids:
            session.execute(
                delete(OcrVerificationFinding).where(
                    OcrVerificationFinding.layout_id.in_(sorted(obsolete_ids))
                )
            )
    refreshed = 0
    for layout_id in sorted(layout_ids):
        page_id, _layout = layout_rows[layout_id]
        if refresh_finding(
            layout_id,
            page_layout_context=page_contexts[page_id],
        ) is not None:
            refreshed += 1
    return {"refreshed": refreshed}


def _recalculation_loop() -> None:
    global _RECALCULATION_THREAD
    try:
        recalculate_findings()
    finally:
        with _WORKER_LOCK:
            _RECALCULATION_THREAD = None


def request_findings_recalculation() -> dict[str, Any]:
    global _RECALCULATION_THREAD
    with _WORKER_LOCK:
        if _RECALCULATION_THREAD is not None and _RECALCULATION_THREAD.is_alive():
            return {"started": False, "reason": "already_running"}
        _RECALCULATION_THREAD = Thread(
            target=_recalculation_loop,
            name="ocr-verification-recalculation",
            daemon=True,
        )
        _RECALCULATION_THREAD.start()
    return {"started": True}


def _finding_to_dict(
    finding: OcrVerificationFinding,
    *,
    page: Page,
    layout: Layout,
    tasks: list[OcrVerificationTask],
) -> dict[str, Any]:
    return {
        "layout_id": int(finding.layout_id),
        "page_id": int(finding.page_id),
        "rel_path": str(page.rel_path),
        "class_name": str(layout.class_name),
        "reading_order": int(layout.reading_order),
        "bbox": {
            "x1": float(layout.x1),
            "y1": float(layout.y1),
            "x2": float(layout.x2),
            "y2": float(layout.y2),
        },
        "state": str(finding.state),
        "resolved": bool(finding.resolved),
        "baseline_content": str(finding.baseline_content),
        "source_model": str(finding.source_model),
        "groups": _json_loads(finding.groups_json, []),
        "responded_count": int(finding.responded_count),
        "required_count": int(finding.required_count),
        "missing_count": max(0, int(finding.required_count) - int(finding.responded_count)),
        "tasks": [
            {
                "id": int(task.id),
                "model_name": str(task.model_name),
                "status": str(task.status),
                "attempts": int(task.attempts),
                "transient_count": int(task.transient_count),
                "next_retry_at": task.next_retry_at,
                "error_message": task.error_message,
            }
            for task in tasks
        ],
        "updated_at": str(finding.updated_at),
    }


def _finding_summary(
    finding: OcrVerificationFinding,
    *,
    page: Page,
    layout: Layout,
) -> dict[str, Any]:
    return {
        "layout_id": int(finding.layout_id),
        "page_id": int(finding.page_id),
        "rel_path": str(page.rel_path),
        "class_name": str(layout.class_name),
        "reading_order": int(layout.reading_order),
        "state": str(finding.state),
        "resolved": bool(finding.resolved),
        "source_model": str(finding.source_model),
        "responded_count": int(finding.responded_count),
        "required_count": int(finding.required_count),
        "missing_count": max(0, int(finding.required_count) - int(finding.responded_count)),
        "crop_version": str(finding.evidence_fingerprint),
        "updated_at": str(finding.updated_at),
    }


def _apply_finding_filters(
    query: Any,
    *,
    category: str | None,
    state: str | None,
    resolved: bool | None,
) -> Any:
    normalized_category = str(category or "").strip().lower()
    normalized_state = str(state or "").strip().lower()
    if normalized_category and normalized_category != "all":
        if normalized_category == "resolved":
            query = query.where(OcrVerificationFinding.resolved.is_(True))
        else:
            query = query.where(OcrVerificationFinding.resolved.is_(False))
            if normalized_category == "attention":
                query = query.where(
                    OcrVerificationFinding.state.in_(
                        ("disagreement_full", "disagreement_reduced", "manual_check")
                    )
                )
            elif normalized_category == "agreement":
                query = query.where(OcrVerificationFinding.state.like("agreed_%"))
            else:
                query = query.where(OcrVerificationFinding.state == normalized_category)
    elif normalized_state:
        query = query.where(OcrVerificationFinding.state == normalized_state)
    if resolved is not None and normalized_category != "resolved":
        query = query.where(OcrVerificationFinding.resolved.is_(bool(resolved)))
    return query


def list_findings(
    *,
    category: str | None = None,
    state: str | None = None,
    resolved: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    normalized_limit = max(1, min(100, int(limit)))
    normalized_offset = max(0, int(offset))
    with get_session() as session:
        query = (
            select(OcrVerificationFinding, Page, Layout)
            .join(Page, Page.id == OcrVerificationFinding.page_id)
            .join(Layout, Layout.id == OcrVerificationFinding.layout_id)
        )
        query = _apply_finding_filters(
            query,
            category=category,
            state=state,
            resolved=resolved,
        )
        total = session.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        ).scalar_one()
        rows = session.execute(
            query.order_by(Page.id.asc(), Layout.reading_order.asc())
            .offset(normalized_offset)
            .limit(normalized_limit)
        ).all()
        output = [
            _finding_summary(finding, page=page, layout=layout)
            for finding, page, layout in rows
        ]
        return {
            "count": len(output),
            "total": int(total or 0),
            "limit": normalized_limit,
            "offset": normalized_offset,
            "findings": output,
        }


def get_finding_detail(layout_id: int) -> dict[str, Any]:
    with get_session() as session:
        row = session.execute(
            select(OcrVerificationFinding, Page, Layout)
            .join(Page, Page.id == OcrVerificationFinding.page_id)
            .join(Layout, Layout.id == OcrVerificationFinding.layout_id)
            .where(OcrVerificationFinding.layout_id == int(layout_id))
        ).one_or_none()
        if row is None:
            raise ValueError("Verification finding not found.")
        finding, page, layout = row
        current_models = set(select_validator_models(str(finding.source_model)))
        expected_fingerprints = {
            _task_fingerprint(str(finding.evidence_fingerprint), model_name)
            for model_name in current_models
        }
        tasks = session.execute(
            select(OcrVerificationTask)
            .where(
                OcrVerificationTask.layout_id == int(layout_id),
                OcrVerificationTask.evidence_fingerprint.in_(expected_fingerprints),
            )
            .order_by(OcrVerificationTask.id.asc())
        ).scalars().all() if expected_fingerprints else []
        return _finding_to_dict(finding, page=page, layout=layout, tasks=tasks)


def verification_crop(layout_id: int) -> tuple[bytes, str]:
    with get_session() as session:
        row = session.execute(
            select(OcrVerificationFinding, Page, Layout)
            .join(Page, Page.id == OcrVerificationFinding.page_id)
            .join(Layout, Layout.id == OcrVerificationFinding.layout_id)
            .where(OcrVerificationFinding.layout_id == int(layout_id))
        ).one_or_none()
        if row is None:
            raise ValueError("Verification finding not found.")
        finding, page, layout = row
        image_path = (settings.source_dir / str(page.rel_path)).resolve()
        source_root = settings.source_dir.resolve()
        if source_root not in image_path.parents or not image_path.is_file():
            raise ValueError("Verification source image is unavailable.")
        version = str(finding.evidence_fingerprint)
        cache_dir = settings.project_root / "_artifacts" / "ocr_verification_crops"
        cache_path = cache_dir / f"layout_{int(layout_id)}_{version}.png"
        if cache_path.is_file():
            return cache_path.read_bytes(), version
        layout_payload = _layout_dict(layout)
        full_crop = _crop_layout_png_bytes(
            image_path,
            layout_payload["bbox"],
            rotate_for_vertical=str(layout_payload["effective_orientation"]) == "vertical",
        )
        with Image.open(BytesIO(full_crop)) as image:
            image.load()
            image.thumbnail((1200, 800), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            crop = buffer.getvalue()
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(crop)
        return crop, version


def _normalize_model_response(page_id: int, layout_id: int, raw_content: str) -> str:
    layouts = _fetch_page_layouts(page_id)
    layout = next((row for row in layouts if int(row["id"]) == int(layout_id)), None)
    if layout is None:
        raise RuntimeError("Layout not found during verification extraction.")
    content = normalize_ocr_content(raw_content, output_format="markdown")
    class_name = str(layout["class_name"])
    if class_name == "section_header":
        levels = _section_header_levels_by_layout_id(layouts)
        content = _apply_section_header_heading_level(content, levels.get(int(layout_id), 3))
    elif class_name == "list_item":
        levels = _list_item_indent_levels_by_layout_id(layouts)
        content = _normalize_list_item_line(
            content,
            indent_level=levels.get(int(layout_id), 0),
            fallback_marker="-",
        )
    return normalize_ocr_content(content, output_format="markdown")


def _task_inputs(task_id: int) -> tuple[OcrVerificationTask, Page, Layout, str, bytes]:
    with get_session() as session:
        row = session.execute(
            select(OcrVerificationTask, Page, Layout)
            .join(Page, Page.id == OcrVerificationTask.page_id)
            .join(Layout, Layout.id == OcrVerificationTask.layout_id)
            .where(OcrVerificationTask.id == int(task_id))
        ).one()
        task, page, layout = row
        output = session.get(OcrOutput, int(layout.id))
        if output is None:
            raise RuntimeError("Canonical OCR output is unavailable.")
        context = _verification_context(page, layout, output)
        image_path = (settings.source_dir / str(page.rel_path)).resolve()
        source_root = settings.source_dir.resolve()
        if source_root not in image_path.parents or not image_path.is_file():
            raise RuntimeError("Verification source image is unavailable.")
        image_bytes = _crop_layout_png_bytes(
            image_path,
            context["layout"]["bbox"],
            rotate_for_vertical=str(context["layout"]["effective_orientation"]) == "vertical",
        )
        return task, page, layout, str(context["prompt"]), image_bytes


def _retry_delay_seconds(transient_count: int) -> int:
    return min(300, 5 * (2 ** max(0, min(6, int(transient_count) - 1))))


def _is_fatal_request_error(message: str) -> bool:
    normalized = str(message or "").lower()
    return any(
        marker in normalized
        for marker in (
            "http 400",
            "http 401",
            "http 403",
            "http 404",
            "invalid api key",
            "api key not valid",
            "model not found",
        )
    )


def _persist_task_error(
    task_id: int,
    *,
    error: str,
    transient: bool,
    quota_wait: bool = False,
    fatal: bool = False,
) -> None:
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()
    with get_session() as session:
        task = session.get(OcrVerificationTask, int(task_id))
        if task is None:
            return
        was_terminal = str(task.status) in _TERMINAL_TASK_STATUSES
        if transient or quota_wait:
            task.transient_count = int(task.transient_count) + 1
            task.status = "waiting"
            task.next_retry_at = (
                now_dt + timedelta(seconds=_retry_delay_seconds(int(task.transient_count)))
            ).isoformat()
        elif fatal:
            task.attempts = max(
                int(task.attempts),
                int(settings.ocr_verification_attempts_per_model),
            )
            task.status = "unavailable"
            task.finished_at = now
            task.next_retry_at = None
        else:
            task.attempts = int(task.attempts) + 1
            if int(task.attempts) >= int(settings.ocr_verification_attempts_per_model):
                task.status = "unavailable"
                task.finished_at = now
            else:
                task.status = "pending"
            task.next_retry_at = None
        task.error_message = str(error)
        task.updated_at = now
        layout_id = int(task.layout_id)
        if not was_terminal and str(task.status) in _TERMINAL_TASK_STATUSES and task.run_id is not None:
            run = session.get(OcrVerificationRun, int(task.run_id))
            if run is not None:
                run.completed_tasks = min(
                    int(run.total_tasks),
                    int(run.completed_tasks) + 1,
                )
                run.updated_at = now
    refresh_finding(layout_id)


def _defer_model_for_daily_quota(task_id: int, *, error: str) -> None:
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()
    next_retry_at = (now_dt + timedelta(seconds=300)).isoformat()
    with get_session() as session:
        task = session.get(OcrVerificationTask, int(task_id))
        if task is None or task.run_id is None:
            return
        siblings = session.execute(
            select(OcrVerificationTask).where(
                OcrVerificationTask.run_id == int(task.run_id),
                OcrVerificationTask.model_name == str(task.model_name),
                OcrVerificationTask.status.in_(tuple(_ACTIVE_TASK_STATUSES)),
            )
        ).scalars().all()
        for sibling in siblings:
            sibling.status = "waiting"
            sibling.next_retry_at = next_retry_at
            sibling.updated_at = now
            if int(sibling.id) == int(task_id):
                sibling.error_message = str(error)


def _generate_verification_content(
    task: OcrVerificationTask, key: str, prompt: str, image_bytes: bytes
) -> str:
    """Record each actual model call, including calls made during key rotation."""
    started_at = _utc_now()
    started = time.monotonic()
    outcome = "success"
    http_status = None
    try:
        return gemini_generate_content(
            key, prompt, image_bytes,
            model_name=str(task.model_name),
            temperature=DEFAULT_GEMINI_TEMPERATURE,
        )
    except Exception as error:
        message = str(error).lower()
        status_match = re.search(r"http\s+(\d{3})\b", message)
        http_status = int(status_match.group(1)) if status_match else None
        if is_daily_quota_exhausted_error(message):
            outcome = "daily_quota"
        elif is_quota_error(message):
            outcome = "rate_limit"
        elif "timed out" in message or "timeout" in message:
            outcome = "timeout"
        elif http_status is not None and 500 <= http_status < 600:
            outcome = "server_error"
        elif "json" in message or "empty response" in message or "response text is empty" in message:
            outcome = "invalid_response"
        elif http_status is not None and 400 <= http_status < 500:
            outcome = "request_error"
        else:
            outcome = "other_error"
        raise
    finally:
        record = {
            "run_id": task.run_id,
            "task_id": int(task.id),
            "page_id": int(task.page_id),
            "layout_id": int(task.layout_id),
            "model_name": str(task.model_name),
            "started_at": started_at,
            "finished_at": _utc_now(),
            "duration_ms": round(max(0, time.monotonic() - started) * 1000, 3),
            "outcome": outcome,
            "http_status": http_status,
        }
        try:
            directory = settings.project_root / "_artifacts" / "ocr_verification_attempts"
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / f"run_{task.run_id}.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(_json_dumps(record) + "\n")
        except OSError:
            # Diagnostics must not change extraction/retry outcomes. Never log
            # raw exception text, which may contain credentials or response data.
            logger.warning("Could not write verification attempt timing for task %s", task.id)


def _execute_task(task_id: int) -> str:
    task, _page, _layout, prompt, image_bytes = _task_inputs(task_id)
    model_name = str(task.model_name)
    exhausted_keys = _load_usage_state(model_name=model_name)
    excluded_keys: set[str] = set()
    last_quota_error: str | None = None
    while True:
        try:
            key = _next_available_key(
                exhausted_keys,
                exclude_keys=excluded_keys,
                model_name=model_name,
            )
        except GeminiDailyQuotaExhaustedError as error:
            error_text = last_quota_error or str(error)
            _persist_task_error(task_id, error=error_text, transient=False, quota_wait=True)
            _defer_model_for_daily_quota(task_id, error=error_text)
            return "quota_wait"
        except GeminiQuotaExhaustedError as error:
            _persist_task_error(
                task_id,
                error=last_quota_error or str(error),
                transient=False,
                quota_wait=True,
            )
            return "quota_wait"
        try:
            raw_content = _generate_verification_content(task, key, prompt, image_bytes)
        except Exception as error:
            error_text = str(error)
            if is_quota_error(error_text):
                last_quota_error = error_text
                excluded_keys.add(key)
                if is_daily_quota_exhausted_error(error_text):
                    _mark_key_exhausted(exhausted_keys, key, model_name=model_name)
                continue
            if is_gemini_server_error(error_text):
                _persist_task_error(task_id, error=error_text, transient=True)
                return "waiting"
            _persist_task_error(
                task_id,
                error=error_text,
                transient=False,
                fatal=_is_fatal_request_error(error_text),
            )
            return "failed_attempt"

        try:
            normalized = _normalize_model_response(int(task.page_id), int(task.layout_id), raw_content)
        except Exception as error:
            _persist_task_error(task_id, error=str(error), transient=False)
            return "failed_attempt"
        now = _utc_now()
        with get_session() as session:
            row = session.get(OcrVerificationTask, int(task_id))
            if row is None:
                return "missing"
            was_terminal = str(row.status) in _TERMINAL_TASK_STATUSES
            row.status = "succeeded"
            row.content = normalized
            row.key_alias = key_alias(key)
            row.error_message = None
            row.next_retry_at = None
            row.updated_at = now
            row.finished_at = now
            layout_id = int(row.layout_id)
            if not was_terminal and row.run_id is not None:
                run = session.get(OcrVerificationRun, int(row.run_id))
                if run is not None:
                    run.completed_tasks = min(
                        int(run.total_tasks),
                        int(run.completed_tasks) + 1,
                    )
                    run.updated_at = now
        refresh_finding(layout_id)
        return "succeeded"


def _active_run_id() -> int | None:
    with get_session() as session:
        row = session.execute(
            select(OcrVerificationRun.id)
            .where(OcrVerificationRun.status.in_(tuple(_ACTIVE_RUN_STATUSES)))
            .order_by(OcrVerificationRun.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        return None if row is None else int(row)


def _claim_ready_task(run_id: int) -> int | None:
    now = _utc_now()
    with get_session() as session:
        run = session.get(OcrVerificationRun, int(run_id))
        if run is None or bool(run.stop_requested):
            return None
        active = select(OcrVerificationTask).where(
            OcrVerificationTask.run_id == int(run_id),
            OcrVerificationTask.status.in_(tuple(_ACTIVE_TASK_STATUSES)),
        )
        untouched = active.where(
            OcrVerificationTask.attempts == 0,
            OcrVerificationTask.transient_count == 0,
        )
        # Include quota-blocked checks when deciding whether the first pass
        # is finished; retries must never overtake untouched work.
        if session.scalar(select(untouched.exists())):
            candidates = untouched.order_by(OcrVerificationTask.id.asc())
        else:
            candidates = active.order_by(
                (OcrVerificationTask.attempts + OcrVerificationTask.transient_count).asc(),
                OcrVerificationTask.updated_at.asc(),
                OcrVerificationTask.id.asc(),
            )
        task = session.execute(
            candidates.where(
                (OcrVerificationTask.next_retry_at.is_(None))
                | (OcrVerificationTask.next_retry_at <= now)
            ).limit(1)
        ).scalar_one_or_none()
        return None if task is None else int(task.id)


def _has_active_tasks(run_id: int) -> bool:
    with get_session() as session:
        count = session.execute(
            select(func.count(OcrVerificationTask.id)).where(
                OcrVerificationTask.run_id == int(run_id),
                OcrVerificationTask.status.in_(tuple(_ACTIVE_TASK_STATUSES)),
            )
        ).scalar_one()
        return int(count or 0) > 0


def _finish_run(run_id: int, *, stopped: bool) -> None:
    now = _utc_now()
    with get_session() as session:
        run = session.get(OcrVerificationRun, int(run_id))
        if run is None:
            return
        task_total = session.execute(
            select(func.count(OcrVerificationTask.id)).where(
                OcrVerificationTask.run_id == int(run_id)
            )
        ).scalar_one()
        completed = session.execute(
            select(func.count(OcrVerificationTask.id)).where(
                OcrVerificationTask.run_id == int(run_id),
                OcrVerificationTask.status.in_(("succeeded", "unavailable")),
            )
        ).scalar_one()
        run.total_tasks = int(task_total or 0)
        run.completed_tasks = int(completed or 0)
        run.status = "stopped" if stopped else "completed"
        run.updated_at = now
        run.finished_at = now
    if bool(settings.enable_background_jobs):
        request_findings_recalculation()
    else:
        recalculate_findings()


def _worker_loop(run_id: int) -> None:
    global _WORKER_THREAD
    try:
        while True:
            with get_session() as session:
                run = session.get(OcrVerificationRun, int(run_id))
                if run is None:
                    return
                if bool(run.stop_requested):
                    _finish_run(run_id, stopped=True)
                    return
            task_id = _claim_ready_task(run_id)
            if task_id is not None:
                try:
                    _execute_task(task_id)
                except Exception as error:
                    _persist_task_error(task_id, error=str(error), transient=False)
                continue
            if not _has_active_tasks(run_id):
                _finish_run(run_id, stopped=False)
                return
            time.sleep(1.0)
    finally:
        with _WORKER_LOCK:
            _WORKER_THREAD = None


def _ensure_worker(run_id: int) -> None:
    global _WORKER_THREAD
    if not bool(settings.enable_background_jobs):
        return
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return
        _WORKER_THREAD = Thread(
            target=_worker_loop,
            args=(int(run_id),),
            name="ocr-verification-worker",
            daemon=True,
        )
        _WORKER_THREAD.start()


def _prepare_run(run_id: int) -> dict[str, Any]:
    eligible_rows = _eligible_rows()
    page_contexts = _page_layout_contexts(eligible_rows)
    page_id_by_layout_id = {
        int(layout.id): int(page.id)
        for page, layout, _output in eligible_rows
    }
    total_tasks, layout_ids = _upsert_current_tasks(
        run_id,
        rows=eligible_rows,
        page_contexts=page_contexts,
    )
    stopped = False
    with get_session() as session:
        run = session.get(OcrVerificationRun, run_id)
        if run is None:
            return {"started": False, "run_id": run_id, "reason": "missing_run"}
        run.total_tasks = int(total_tasks)
        run.updated_at = _utc_now()
        stopped = bool(run.stop_requested)
        if stopped:
            run.status = "stop_requested"
        elif total_tasks == 0:
            run.status = "completed"
            run.finished_at = _utc_now()
        else:
            run.status = "running"
    for layout_id in sorted(layout_ids):
        refresh_finding(
            layout_id,
            page_layout_context=page_contexts[page_id_by_layout_id[layout_id]],
        )
    if stopped:
        _finish_run(run_id, stopped=True)
    elif total_tasks > 0:
        _ensure_worker(run_id)
    return {"started": total_tasks > 0, "run_id": run_id, "total_tasks": total_tasks}


def _preparation_loop(run_id: int) -> None:
    global _PREPARATION_THREAD
    try:
        _prepare_run(run_id)
    finally:
        with _WORKER_LOCK:
            _PREPARATION_THREAD = None


def _ensure_preparation(run_id: int) -> None:
    global _PREPARATION_THREAD
    with _WORKER_LOCK:
        if _PREPARATION_THREAD is not None and _PREPARATION_THREAD.is_alive():
            return
        _PREPARATION_THREAD = Thread(
            target=_preparation_loop,
            args=(int(run_id),),
            name="ocr-verification-preparation",
            daemon=True,
        )
        _PREPARATION_THREAD.start()


def start_verification() -> dict[str, Any]:
    active_id = _active_run_id()
    if active_id is not None:
        return {"started": False, "run_id": active_id, "reason": "already_running"}
    now = _utc_now()
    config_payload = {
        "models": list(verification_models()),
        "total_models_per_region": int(settings.ocr_verification_total_models),
        "attempts_per_model": int(settings.ocr_verification_attempts_per_model),
        "prompt_version": int(settings.ocr_verification_prompt_version),
        "comparison_version": COMPARISON_VERSION,
    }
    with get_session() as session:
        run = OcrVerificationRun(
            status="preparing" if bool(settings.enable_background_jobs) else "running",
            stop_requested=False,
            config_json=_json_dumps(config_payload),
            total_tasks=0,
            completed_tasks=0,
            created_at=now,
            updated_at=now,
            started_at=now,
            finished_at=None,
        )
        session.add(run)
        session.flush()
        run_id = int(run.id)
    if bool(settings.enable_background_jobs):
        _ensure_preparation(run_id)
        return {"started": True, "preparing": True, "run_id": run_id, "total_tasks": 0}
    return _prepare_run(run_id)


def request_verification_stop(*, reason: str = "Stopped by user request.") -> dict[str, Any]:
    run_id = _active_run_id()
    if run_id is None:
        return {"stop_requested": False, "reason": "not_running"}
    with get_session() as session:
        run = session.get(OcrVerificationRun, run_id)
        if run is not None:
            run.stop_requested = True
            run.status = "stop_requested"
            run.updated_at = _utc_now()
        session.query(OcrVerificationTask).filter(
            OcrVerificationTask.run_id == run_id,
            OcrVerificationTask.status == "pending",
        ).update(
            {OcrVerificationTask.status: "waiting", OcrVerificationTask.error_message: reason},
            synchronize_session=False,
        )
    with _WORKER_LOCK:
        worker_alive = _WORKER_THREAD is not None and _WORKER_THREAD.is_alive()
        preparation_alive = _PREPARATION_THREAD is not None and _PREPARATION_THREAD.is_alive()
    if not worker_alive and not preparation_alive:
        _finish_run(run_id, stopped=True)
    return {"stop_requested": True, "run_id": run_id}


def recover_verification_after_restart() -> dict[str, Any]:
    now = _utc_now()
    recovered = 0
    with get_session() as session:
        runs = session.execute(
            select(OcrVerificationRun).where(OcrVerificationRun.status.in_(tuple(_ACTIVE_RUN_STATUSES)))
        ).scalars().all()
        for run in runs:
            run.status = "stopped"
            run.stop_requested = True
            run.updated_at = now
            run.finished_at = now
            recovered += 1
    recalculation = (
        request_findings_recalculation()
        if bool(settings.enable_background_jobs)
        else {"started": False, **recalculate_findings()}
    )
    return {"recovered_runs": recovered, "recalculation": recalculation}


def verification_status() -> dict[str, Any]:
    with _WORKER_LOCK:
        recalculation_running = (
            _RECALCULATION_THREAD is not None and _RECALCULATION_THREAD.is_alive()
        )
    with get_session() as session:
        run = session.execute(
            select(OcrVerificationRun).order_by(OcrVerificationRun.id.desc()).limit(1)
        ).scalar_one_or_none()
        state_rows = session.execute(
            select(OcrVerificationFinding.state, OcrVerificationFinding.resolved, func.count())
            .group_by(OcrVerificationFinding.state, OcrVerificationFinding.resolved)
        ).all()
        counters: dict[str, int] = {}
        for state, resolved, count in state_rows:
            key = "resolved" if bool(resolved) else str(state)
            counters[key] = counters.get(key, 0) + int(count or 0)
        if run is None:
            return {
                "is_running": False,
                "recalculation_running": recalculation_running,
                "run": None,
                "counters": counters,
            }
        return {
            "is_running": str(run.status) in _ACTIVE_RUN_STATUSES,
            "recalculation_running": recalculation_running,
            "run": {
                "id": int(run.id),
                "status": str(run.status),
                "stop_requested": bool(run.stop_requested),
                "total_tasks": int(run.total_tasks),
                "completed_tasks": int(run.completed_tasks),
                "config": _json_loads(run.config_json, {}),
            },
            "counters": counters,
        }


def resolve_finding(
    layout_id: int,
    *,
    action: str,
    content: str | None = None,
    source_task_id: int | None = None,
) -> dict[str, Any]:
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"keep", "apply"}:
        raise ValueError("action must be keep or apply.")
    finding_payload = refresh_finding(layout_id)
    if finding_payload is None:
        raise ValueError("Verification finding not found.")
    if str(finding_payload["state"]) == "waiting":
        raise ValueError("Stop verification or wait for active model requests before resolving this region.")
    now = _utc_now()
    with get_session() as session:
        finding = session.get(OcrVerificationFinding, int(layout_id))
        output = session.get(OcrOutput, int(layout_id))
        if finding is None or output is None:
            raise ValueError("Verification finding not found.")
        previous = str(output.content)
        resolved_content = previous
        resolution_action = "keep"
        selected_task: OcrVerificationTask | None = None
        if normalized_action == "apply":
            resolved_content = normalize_ocr_content(str(content or ""), output_format=str(output.output_format))
            if source_task_id is not None:
                selected_task = session.get(OcrVerificationTask, int(source_task_id))
                if selected_task is None or int(selected_task.layout_id) != int(layout_id):
                    raise ValueError("Selected verification variant not found.")
            resolution_action = (
                "variant"
                if selected_task is not None and str(selected_task.content or "") == resolved_content
                else "edited"
            )
            output.content = resolved_content
            output.extraction_status = "manual"
            output.error_message = None
            output.updated_at = now
        comparison_fingerprint = str(finding.comparison_fingerprint)
        page_id = int(finding.page_id)
        session.add(
            OcrVerificationResolution(
                page_id=page_id,
                layout_id=int(layout_id),
                comparison_fingerprint=comparison_fingerprint,
                action=resolution_action,
                previous_content=previous,
                resolved_content=resolved_content,
                source_task_id=None if selected_task is None else int(selected_task.id),
                created_at=now,
            )
        )
    refreshed = refresh_finding(layout_id)
    with get_session() as session:
        finding = session.get(OcrVerificationFinding, int(layout_id))
        if finding is not None:
            finding.resolved = True
            finding.updated_at = _utc_now()
    return refresh_finding(layout_id) or refreshed or {}


def recheck_layout(layout_id: int) -> dict[str, Any]:
    if _active_run_id() is not None:
        raise ValueError("Stop OCR verification before rechecking a region.")
    with get_session() as session:
        finding = session.get(OcrVerificationFinding, int(layout_id))
        if finding is None:
            raise ValueError("Verification finding not found.")
        session.execute(
            delete(OcrVerificationTask).where(
                OcrVerificationTask.layout_id == int(layout_id),
                OcrVerificationTask.prompt_version == int(settings.ocr_verification_prompt_version),
            )
        )
        finding.resolved = False
        finding.updated_at = _utc_now()
    return {"layout_id": int(layout_id), "recheck_ready": True}
