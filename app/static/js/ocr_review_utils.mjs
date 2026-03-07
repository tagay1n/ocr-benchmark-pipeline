export function normalizeReconstructedRenderMode(rawValue) {
  const value = String(rawValue || "").trim().toLowerCase();
  if (value === "raw") {
    return "raw";
  }
  return "markdown";
}

export function hasLocalDraftForLayout(localEditsByLayoutId, layoutId) {
  const normalized = Number(layoutId);
  if (!Number.isInteger(normalized) || normalized <= 0) {
    return false;
  }
  if (!localEditsByLayoutId || typeof localEditsByLayoutId !== "object") {
    return false;
  }
  return Object.prototype.hasOwnProperty.call(localEditsByLayoutId, String(normalized));
}

export function isReconstructedRestoreDisabled({
  reviewSubmitInProgress,
  reextractInProgress,
  outputFormat,
}) {
  if (Boolean(reviewSubmitInProgress) || Boolean(reextractInProgress)) {
    return true;
  }
  return String(outputFormat || "").trim().toLowerCase() === "skip";
}
