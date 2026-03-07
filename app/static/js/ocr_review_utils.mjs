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

function toFiniteNumber(value, fallback = 0) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return numeric;
}

export function isRectOnscreen(rect, { windowWidth, windowHeight } = {}) {
  if (!rect || typeof rect !== "object") {
    return false;
  }
  const width = toFiniteNumber(rect.width, 0);
  const height = toFiniteNumber(rect.height, 0);
  const left = toFiniteNumber(rect.left, 0);
  const right = toFiniteNumber(rect.right, left + width);
  const top = toFiniteNumber(rect.top, 0);
  const bottom = toFiniteNumber(rect.bottom, top + height);
  const viewportWidth = toFiniteNumber(windowWidth, 0);
  const viewportHeight = toFiniteNumber(windowHeight, 0);

  if (width <= 0 || height <= 0 || viewportWidth <= 0 || viewportHeight <= 0) {
    return false;
  }
  if (bottom <= 0 || top >= viewportHeight) {
    return false;
  }
  if (right <= 0 || left >= viewportWidth) {
    return false;
  }
  return true;
}

export function computeFloatingControlPlacement({
  anchorRect,
  controlHeight,
  windowWidth,
  windowHeight,
  desiredTop = 10,
  edgeInset = 6,
} = {}) {
  if (!isRectOnscreen(anchorRect, { windowWidth, windowHeight })) {
    return { visible: false, top: null, right: null };
  }

  const inset = Math.max(0, Math.round(toFiniteNumber(edgeInset, 6)));
  const safeControlHeight = Math.max(0, toFiniteNumber(controlHeight, 0));
  const minTop = Math.round(toFiniteNumber(anchorRect.top, 0) + inset);
  const maxTop = Math.round(toFiniteNumber(anchorRect.bottom, 0) - safeControlHeight - inset);
  const preferredTop = Math.round(toFiniteNumber(desiredTop, 10));
  const top = maxTop >= minTop ? Math.min(Math.max(preferredTop, minTop), maxTop) : minTop;
  const right = Math.round(toFiniteNumber(windowWidth, 0) - toFiniteNumber(anchorRect.right, 0) + inset);

  return { visible: true, top, right };
}
