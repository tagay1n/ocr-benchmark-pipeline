from __future__ import annotations

from typing import Final, Literal, TypeAlias

PipelineStage: TypeAlias = Literal[
    "discovery",
    "layout_detect",
    "layout_review",
    "ocr_extract",
    "ocr_review",
    "finalization",
    "pipeline",
]

STAGE_DISCOVERY: Final[PipelineStage] = "discovery"
STAGE_LAYOUT_DETECT: Final[PipelineStage] = "layout_detect"
STAGE_LAYOUT_REVIEW: Final[PipelineStage] = "layout_review"
STAGE_OCR_EXTRACT: Final[PipelineStage] = "ocr_extract"
STAGE_OCR_REVIEW: Final[PipelineStage] = "ocr_review"
STAGE_FINALIZATION: Final[PipelineStage] = "finalization"
STAGE_PIPELINE: Final[PipelineStage] = "pipeline"

PIPELINE_STAGES: Final[tuple[PipelineStage, ...]] = (
    STAGE_DISCOVERY,
    STAGE_LAYOUT_DETECT,
    STAGE_LAYOUT_REVIEW,
    STAGE_OCR_EXTRACT,
    STAGE_OCR_REVIEW,
    STAGE_FINALIZATION,
    STAGE_PIPELINE,
)

PipelineEventType: TypeAlias = Literal[
    "scan_started",
    "scan_finished",
    "jobs_enqueued",
    "manual_detect_started",
    "manual_detect_failed",
    "manual_detect_completed",
    "job_queued",
    "job_enqueued",
    "job_enqueue_skipped",
    "job_started",
    "job_completed",
    "job_failed",
    "manual_review_complete_started",
    "manual_review_complete_failed",
    "manual_review_completed",
    "wipe_started",
    "wipe_finished",
    "runtime_options_updated",
    "page_removed",
    "export_started",
    "export_failed",
    "export_completed",
]

EVENT_SCAN_STARTED: Final[PipelineEventType] = "scan_started"
EVENT_SCAN_FINISHED: Final[PipelineEventType] = "scan_finished"
EVENT_JOBS_ENQUEUED: Final[PipelineEventType] = "jobs_enqueued"
EVENT_MANUAL_DETECT_STARTED: Final[PipelineEventType] = "manual_detect_started"
EVENT_MANUAL_DETECT_FAILED: Final[PipelineEventType] = "manual_detect_failed"
EVENT_MANUAL_DETECT_COMPLETED: Final[PipelineEventType] = "manual_detect_completed"
EVENT_JOB_QUEUED: Final[PipelineEventType] = "job_queued"
EVENT_JOB_ENQUEUED: Final[PipelineEventType] = "job_enqueued"
EVENT_JOB_ENQUEUE_SKIPPED: Final[PipelineEventType] = "job_enqueue_skipped"
EVENT_JOB_STARTED: Final[PipelineEventType] = "job_started"
EVENT_JOB_COMPLETED: Final[PipelineEventType] = "job_completed"
EVENT_JOB_FAILED: Final[PipelineEventType] = "job_failed"
EVENT_MANUAL_REVIEW_COMPLETE_STARTED: Final[PipelineEventType] = "manual_review_complete_started"
EVENT_MANUAL_REVIEW_COMPLETE_FAILED: Final[PipelineEventType] = "manual_review_complete_failed"
EVENT_MANUAL_REVIEW_COMPLETED: Final[PipelineEventType] = "manual_review_completed"
EVENT_WIPE_STARTED: Final[PipelineEventType] = "wipe_started"
EVENT_WIPE_FINISHED: Final[PipelineEventType] = "wipe_finished"
EVENT_RUNTIME_OPTIONS_UPDATED: Final[PipelineEventType] = "runtime_options_updated"
EVENT_PAGE_REMOVED: Final[PipelineEventType] = "page_removed"
EVENT_EXPORT_STARTED: Final[PipelineEventType] = "export_started"
EVENT_EXPORT_FAILED: Final[PipelineEventType] = "export_failed"
EVENT_EXPORT_COMPLETED: Final[PipelineEventType] = "export_completed"


def stage_display_name(stage: str | None) -> str:
    if not stage:
        return "pipeline"
    if stage == STAGE_LAYOUT_DETECT:
        return "layout detection"
    if stage == STAGE_OCR_EXTRACT:
        return "OCR extraction"
    if stage == STAGE_OCR_REVIEW:
        return "OCR review"
    return stage.replace("_", " ")
