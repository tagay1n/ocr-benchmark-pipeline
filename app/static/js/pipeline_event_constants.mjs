export const PIPELINE_STAGE = Object.freeze({
  DISCOVERY: "discovery",
  LAYOUT_DETECT: "layout_detect",
  LAYOUT_REVIEW: "layout_review",
  OCR_EXTRACT: "ocr_extract",
  OCR_REVIEW: "ocr_review",
  FINALIZATION: "finalization",
  PIPELINE: "pipeline",
});

export const PIPELINE_EVENT = Object.freeze({
  SCAN_STARTED: "scan_started",
  SCAN_FINISHED: "scan_finished",
  JOBS_ENQUEUED: "jobs_enqueued",
  MANUAL_DETECT_STARTED: "manual_detect_started",
  MANUAL_DETECT_FAILED: "manual_detect_failed",
  MANUAL_DETECT_COMPLETED: "manual_detect_completed",
  JOB_QUEUED: "job_queued",
  JOB_ENQUEUED: "job_enqueued",
  JOB_ENQUEUE_SKIPPED: "job_enqueue_skipped",
  JOB_STARTED: "job_started",
  JOB_COMPLETED: "job_completed",
  JOB_FAILED: "job_failed",
  MANUAL_REVIEW_COMPLETE_STARTED: "manual_review_complete_started",
  MANUAL_REVIEW_COMPLETE_FAILED: "manual_review_complete_failed",
  MANUAL_REVIEW_COMPLETED: "manual_review_completed",
  WIPE_STARTED: "wipe_started",
  WIPE_FINISHED: "wipe_finished",
  RUNTIME_OPTIONS_UPDATED: "runtime_options_updated",
  PAGE_REMOVED: "page_removed",
  EXPORT_STARTED: "export_started",
  EXPORT_FAILED: "export_failed",
  EXPORT_COMPLETED: "export_completed",
});

export function stageDisplayName(stage, toSentenceCaseLabel) {
  if (!stage) return "Pipeline";
  if (stage === PIPELINE_STAGE.LAYOUT_DETECT) return "Layout detection";
  if (stage === PIPELINE_STAGE.OCR_EXTRACT) return "OCR extraction";
  if (stage === PIPELINE_STAGE.OCR_REVIEW) return "OCR review";
  if (typeof toSentenceCaseLabel === "function") {
    return toSentenceCaseLabel(stage);
  }
  return String(stage).replace(/_/g, " ");
}

export function inferPageStatusFromPipelineEvent(event) {
  const stage = String(event?.stage || "");
  const eventType = String(event?.event_type || "");
  const result = event?.data && typeof event.data === "object" ? event.data.result : null;
  if (stage === PIPELINE_STAGE.LAYOUT_DETECT) {
    if (eventType === PIPELINE_EVENT.JOB_STARTED) return "layout_detecting";
    if (eventType === PIPELINE_EVENT.JOB_COMPLETED && !(result && result.skipped)) return "layout_detected";
    if (eventType === PIPELINE_EVENT.JOB_FAILED) return "new";
    if (eventType === PIPELINE_EVENT.MANUAL_DETECT_COMPLETED) return "layout_detected";
    return null;
  }
  if (stage === PIPELINE_STAGE.LAYOUT_REVIEW) {
    if (eventType === PIPELINE_EVENT.MANUAL_REVIEW_COMPLETED) return "layout_reviewed";
    return null;
  }
  if (stage === PIPELINE_STAGE.OCR_EXTRACT) {
    if (eventType === PIPELINE_EVENT.JOB_STARTED) return "ocr_extracting";
    if (eventType === PIPELINE_EVENT.JOB_COMPLETED && !(result && result.skipped)) return "ocr_done";
    if (eventType === PIPELINE_EVENT.JOB_FAILED) return "ocr_failed";
    return null;
  }
  if (stage === PIPELINE_STAGE.OCR_REVIEW) {
    if (eventType === PIPELINE_EVENT.MANUAL_REVIEW_COMPLETED) return "ocr_reviewed";
    return null;
  }
  return null;
}
