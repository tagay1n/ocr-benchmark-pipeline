from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .config import settings as settings
from .db import init_db
from .models import Layout, OcrOutput, Page, PipelineEvent, PipelineJob
from .ocr_extract import extract_ocr_for_page as extract_ocr_for_page
from .pipeline_runtime import (
    emit_event as emit_event,
    enqueue_job as enqueue_job,
    enqueue_layout_detection_for_new_pages as enqueue_layout_detection_for_new_pages,
    register_default_handlers,
)
from .runtime_options import reset_runtime_options_from_settings
from .api import discovery_router, pipeline_router, review_router
from .api.discovery import (
    list_duplicates,
    list_pages,
    pages_summary,
    page_details,
    page_image,
    put_runtime_options,
    remove_page,
    root,
    runtime_options,
    scan_images,
    stats,
    wipe_state,
)
from .api.pipeline import pipeline_activity, pipeline_activity_stream
from .api.review import (
    complete_layout_review,
    complete_ocr_review,
    create_page_layout,
    detect_page_layouts,
    next_layout_review_page,
    next_layout_review_page_global,
    next_ocr_review_page,
    next_ocr_review_page_global,
    page_layouts,
    page_ocr_outputs,
    patch_layout,
    patch_ocr_output,
    put_page_caption_bindings,
    reextract_ocr,
    remove_layout,
    run_final_export,
)
from .api.schemas import (
    BBoxPayload,
    CaptionBindingPayload,
    CreateLayoutRequest,
    DetectLayoutsRequest,
    FinalExportRequest,
    ReextractOcrRequest,
    ReplaceCaptionBindingsRequest,
    RuntimeOptionsUpdateRequest,
    UpdateLayoutRequest,
    UpdateOcrOutputRequest,
    WipeStateRequest,
)
from .api.shared import _utc_now
from .api.shared import run_startup_scan


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    register_default_handlers()
    reset_runtime_options_from_settings()
    run_startup_scan()
    yield


app = FastAPI(title="OCR Pipeline", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(discovery_router)
app.include_router(review_router)
app.include_router(pipeline_router)
