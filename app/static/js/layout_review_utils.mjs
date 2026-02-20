export function clampZoomPercent(value, { min = 1, max = 400, fallback = 100 } = {}) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, numeric));
}

export function formatZoomPercent(percentValue) {
  const rounded = Math.round(Number(percentValue) * 10) / 10;
  if (Number.isInteger(rounded)) {
    return `${rounded}%`;
  }
  return `${rounded.toFixed(1)}%`;
}

export function computeZoomScale({
  mode,
  zoomPercent,
  naturalWidth,
  naturalHeight,
  viewportWidth,
  viewportHeight,
}) {
  if (!naturalWidth || !naturalHeight || !viewportWidth || !viewportHeight) {
    return null;
  }

  const fitWidthScale = viewportWidth / naturalWidth;
  const fitPageScale = Math.min(fitWidthScale, viewportHeight / naturalHeight);
  const automaticScale = Math.min(fitWidthScale, 1);

  if (mode === "fit-page") {
    return fitPageScale;
  }
  if (mode === "fit-width") {
    return fitWidthScale;
  }
  if (mode === "automatic") {
    return automaticScale;
  }
  return clampZoomPercent(zoomPercent) / 100;
}

export function pointHandleForCoordinateKey(key) {
  if (key === "x1" || key === "y1") {
    return "nw";
  }
  if (key === "x2" || key === "y2") {
    return "se";
  }
  return null;
}

export function compactReadingOrdersAfterDeletion(layouts, deletedOrder) {
  const threshold = Number(deletedOrder);
  if (!Number.isInteger(threshold) || threshold < 1) {
    return { layouts: [...layouts], shiftedIds: [] };
  }

  const shiftedIds = [];
  const compactedLayouts = layouts.map((layout) => {
    const order = Number(layout.reading_order);
    if (!Number.isInteger(order) || order <= threshold) {
      return layout;
    }
    shiftedIds.push(Number(layout.id));
    return {
      ...layout,
      reading_order: order - 1,
    };
  });
  return { layouts: compactedLayouts, shiftedIds };
}

export function computeViewportScrollToCenterBBox({
  bbox,
  contentWidth,
  contentHeight,
  viewportWidth,
  viewportHeight,
}) {
  if (!bbox || !Number.isFinite(contentWidth) || !Number.isFinite(contentHeight)) {
    return null;
  }
  if (!Number.isFinite(viewportWidth) || !Number.isFinite(viewportHeight)) {
    return null;
  }
  if (contentWidth <= 0 || contentHeight <= 0 || viewportWidth <= 0 || viewportHeight <= 0) {
    return null;
  }

  const centerX = ((Number(bbox.x1) + Number(bbox.x2)) / 2) * contentWidth;
  const centerY = ((Number(bbox.y1) + Number(bbox.y2)) / 2) * contentHeight;
  if (!Number.isFinite(centerX) || !Number.isFinite(centerY)) {
    return null;
  }

  const maxLeft = Math.max(0, contentWidth - viewportWidth);
  const maxTop = Math.max(0, contentHeight - viewportHeight);
  const targetLeft = Math.max(0, Math.min(maxLeft, centerX - viewportWidth / 2));
  const targetTop = Math.max(0, Math.min(maxTop, centerY - viewportHeight / 2));

  return {
    left: Math.round(targetLeft),
    top: Math.round(targetTop),
  };
}

export function computeViewportScrollTargetForLayoutId({
  layoutId,
  layouts,
  contentWidth,
  contentHeight,
  viewportWidth,
  viewportHeight,
}) {
  const normalizedLayoutId = Number(layoutId);
  if (!Number.isInteger(normalizedLayoutId) || normalizedLayoutId <= 0) {
    return null;
  }

  if (!Array.isArray(layouts)) {
    return null;
  }

  const layout = layouts.find((candidate) => Number(candidate?.id) === normalizedLayoutId);
  if (!layout || !layout.bbox) {
    return null;
  }

  return computeViewportScrollToCenterBBox({
    bbox: layout.bbox,
    contentWidth,
    contentHeight,
    viewportWidth,
    viewportHeight,
  });
}

export function computeDraggedBBox({
  startX,
  startY,
  endX,
  endY,
  contentWidth,
  contentHeight,
  minPixels = 6,
}) {
  const values = [startX, startY, endX, endY, contentWidth, contentHeight, minPixels];
  if (values.some((value) => !Number.isFinite(value))) {
    return null;
  }
  if (contentWidth <= 0 || contentHeight <= 0 || minPixels < 0) {
    return null;
  }

  const clampX = (value) => Math.max(0, Math.min(contentWidth, value));
  const clampY = (value) => Math.max(0, Math.min(contentHeight, value));

  const x1px = Math.min(clampX(startX), clampX(endX));
  const x2px = Math.max(clampX(startX), clampX(endX));
  const y1px = Math.min(clampY(startY), clampY(endY));
  const y2px = Math.max(clampY(startY), clampY(endY));

  if (x2px - x1px < minPixels || y2px - y1px < minPixels) {
    return null;
  }

  return {
    x1: x1px / contentWidth,
    y1: y1px / contentHeight,
    x2: x2px / contentWidth,
    y2: y2px / contentHeight,
  };
}

export function computeViewportCenterPadding({
  contentWidth,
  contentHeight,
  viewportWidth,
  viewportHeight,
}) {
  if (!Number.isFinite(contentWidth) || !Number.isFinite(contentHeight)) {
    return { x: 0, y: 0 };
  }
  if (!Number.isFinite(viewportWidth) || !Number.isFinite(viewportHeight)) {
    return { x: 0, y: 0 };
  }
  if (contentWidth <= 0 || contentHeight <= 0 || viewportWidth <= 0 || viewportHeight <= 0) {
    return { x: 0, y: 0 };
  }

  const x = Math.max(0, Math.floor((viewportWidth - contentWidth) / 2));
  const y = Math.max(0, Math.floor((viewportHeight - contentHeight) / 2));
  return { x, y };
}

export function nextLayoutReviewUrl(nextPayload) {
  if (!nextPayload || !nextPayload.has_next) {
    return null;
  }
  const nextPageId = Number(nextPayload.next_page_id);
  if (!Number.isInteger(nextPageId) || nextPageId <= 0) {
    return null;
  }
  return `/static/layouts.html?page_id=${nextPageId}`;
}

export function normalizeReviewHistory(rawHistory, rawIndex) {
  const validHistory = Array.isArray(rawHistory)
    ? rawHistory
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && value > 0)
    : [];
  if (validHistory.length === 0) {
    return { history: [], index: -1 };
  }
  const parsedIndex = Number(rawIndex);
  if (!Number.isInteger(parsedIndex)) {
    return { history: validHistory, index: validHistory.length - 1 };
  }
  const safeIndex = Math.max(0, Math.min(parsedIndex, validHistory.length - 1));
  return { history: validHistory, index: safeIndex };
}

export function updateReviewHistoryOnVisit(rawHistory, rawIndex, currentPageId, maxLength = 200) {
  const pageId = Number(currentPageId);
  if (!Number.isInteger(pageId) || pageId <= 0) {
    return normalizeReviewHistory(rawHistory, rawIndex);
  }

  const normalized = normalizeReviewHistory(rawHistory, rawIndex);
  let history = [...normalized.history];
  let index = normalized.index;

  if (history.length === 0) {
    return { history: [pageId], index: 0 };
  }
  if (index >= 0 && history[index] === pageId) {
    return { history, index };
  }

  if (index < history.length - 1) {
    history = history.slice(0, index + 1);
  }

  history.push(pageId);
  index = history.length - 1;

  if (history.length > maxLength) {
    const overflow = history.length - maxLength;
    history = history.slice(overflow);
    index = Math.max(0, index - overflow);
  }

  return { history, index };
}

export function previousHistoryPageId(rawHistory, rawIndex) {
  const { history, index } = normalizeReviewHistory(rawHistory, rawIndex);
  if (history.length === 0 || index <= 0) {
    return null;
  }
  return history[index - 1];
}
