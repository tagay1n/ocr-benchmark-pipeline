export function clampZoomPercent(value, { min = 1, max = 400, fallback = 100 } = {}) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, numeric));
}

export const ZOOM_PRESET_PERCENTS = Object.freeze([
  10,
  20,
  30,
  40,
  50,
  70,
  85,
  100,
  125,
  150,
  175,
  200,
  300,
  400,
]);

export function normalizeZoomMode(value, { fallback = "automatic", allowCustom = true } = {}) {
  const mode = String(value || "").trim().toLowerCase();
  const allowedModes = allowCustom
    ? ["fit-page", "fit-width", "fit-height", "automatic", "custom"]
    : ["fit-page", "fit-width", "fit-height", "automatic"];
  if (allowedModes.includes(mode)) {
    return mode;
  }
  return fallback;
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
  const fitHeightScale = viewportHeight / naturalHeight;
  const fitPageScale = Math.min(fitWidthScale, viewportHeight / naturalHeight);
  const automaticScale = Math.min(fitWidthScale, 1);

  if (mode === "fit-page") {
    return fitPageScale;
  }
  if (mode === "fit-width") {
    return fitWidthScale;
  }
  if (mode === "fit-height") {
    return fitHeightScale;
  }
  if (mode === "automatic") {
    return automaticScale;
  }
  return clampZoomPercent(zoomPercent) / 100;
}

export function reconstructionLineHeight(outputFormat) {
  const normalized = String(outputFormat || "").trim().toLowerCase();
  if (normalized === "latex") {
    return 1.02;
  }
  if (normalized === "html") {
    return 1.08;
  }
  return 1.1;
}

export function reconstructionHorizontalScale({
  measuredContentWidth,
  availableWidth,
  maxScale = 1.22,
  minGainRatio = 0.03,
}) {
  const measured = Number(measuredContentWidth);
  const available = Number(availableWidth);
  if (!Number.isFinite(measured) || !Number.isFinite(available) || measured <= 0 || available <= 0) {
    return 1;
  }
  const ratio = available / measured;
  if (!Number.isFinite(ratio) || ratio <= 1 + Number(minGainRatio || 0)) {
    return 1;
  }
  const cap = Number(maxScale);
  if (!Number.isFinite(cap) || cap <= 1) {
    return 1;
  }
  return Math.min(cap, ratio);
}

export function countStretchableSpaces(value) {
  const text = String(value ?? "");
  if (!text) {
    return 0;
  }
  let count = 0;
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === " ") {
      count += 1;
    }
  }
  return count;
}

export function countStretchableGlyphs(value) {
  const text = String(value ?? "");
  if (!text) {
    return 0;
  }
  let count = 0;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === " " || char === "\n" || char === "\r" || char === "\t") {
      continue;
    }
    count += 1;
  }
  return count;
}

export function reconstructionWordSpacing({
  measuredContentWidth,
  availableWidth,
  spacesCount,
  maxWordSpacing = 1.6,
  minGainRatio = 0.02,
}) {
  const measured = Number(measuredContentWidth);
  const available = Number(availableWidth);
  const spaces = Number(spacesCount);
  if (!Number.isFinite(measured) || !Number.isFinite(available) || measured <= 0 || available <= 0) {
    return 0;
  }
  if (!Number.isFinite(spaces) || spaces <= 0) {
    return 0;
  }
  const gap = available - measured;
  if (gap <= 0) {
    return 0;
  }
  const gainThreshold = available * Math.max(0, Number(minGainRatio) || 0);
  if (gap <= gainThreshold) {
    return 0;
  }
  const raw = gap / spaces;
  const cap = Number(maxWordSpacing);
  if (!Number.isFinite(raw) || raw <= 0 || !Number.isFinite(cap) || cap <= 0) {
    return 0;
  }
  return Math.min(cap, raw);
}

export function reconstructionLetterSpacing({
  measuredContentWidth,
  availableWidth,
  glyphsCount,
  maxLetterSpacing = 0.7,
  minGainRatio = 0.006,
}) {
  const measured = Number(measuredContentWidth);
  const available = Number(availableWidth);
  const glyphs = Number(glyphsCount);
  if (!Number.isFinite(measured) || !Number.isFinite(available) || measured <= 0 || available <= 0) {
    return 0;
  }
  if (!Number.isFinite(glyphs) || glyphs <= 1) {
    return 0;
  }
  const gap = available - measured;
  if (gap <= 0) {
    return 0;
  }
  const gainThreshold = available * Math.max(0, Number(minGainRatio) || 0);
  if (gap <= gainThreshold) {
    return 0;
  }
  const raw = gap / Math.max(1, glyphs - 1);
  const cap = Number(maxLetterSpacing);
  if (!Number.isFinite(raw) || raw <= 0 || !Number.isFinite(cap) || cap <= 0) {
    return 0;
  }
  return Math.min(cap, raw);
}

export function findMaxFittingFontSize({
  minFontSize = 6,
  maxFontSize,
  iterations = 12,
  fitsAtFontSize,
}) {
  const min = Number(minFontSize);
  const max = Number(maxFontSize);
  if (!Number.isFinite(min) || !Number.isFinite(max) || min <= 0 || max <= 0) {
    return 6;
  }
  if (typeof fitsAtFontSize !== "function") {
    return Math.max(1, Math.min(min, max));
  }
  const safeMin = Math.max(1, Math.min(min, max));
  const safeMax = Math.max(safeMin, max);
  if (!fitsAtFontSize(safeMin)) {
    return safeMin;
  }
  if (fitsAtFontSize(safeMax)) {
    return safeMax;
  }

  let low = safeMin;
  let high = safeMax;
  let best = safeMin;
  const passes = Number.isInteger(iterations) && iterations > 0 ? iterations : 12;
  for (let index = 0; index < passes; index += 1) {
    const mid = (low + high) / 2;
    if (fitsAtFontSize(mid)) {
      best = mid;
      low = mid;
    } else {
      high = mid;
    }
  }
  return best;
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

export function reorderReadingOrderIds({
  orderedIds,
  draggedId,
  targetId,
  position = "after",
}) {
  if (!Array.isArray(orderedIds)) {
    return null;
  }

  const normalizedIds = [];
  const seen = new Set();
  for (const rawId of orderedIds) {
    const id = Number(rawId);
    if (!Number.isInteger(id) || id <= 0 || seen.has(id)) {
      continue;
    }
    seen.add(id);
    normalizedIds.push(id);
  }
  if (normalizedIds.length === 0) {
    return null;
  }

  const dragId = Number(draggedId);
  if (!Number.isInteger(dragId) || dragId <= 0) {
    return null;
  }
  const dragIndex = normalizedIds.indexOf(dragId);
  if (dragIndex < 0) {
    return null;
  }

  const nextIds = [...normalizedIds];
  nextIds.splice(dragIndex, 1);

  if (targetId === null || targetId === undefined) {
    nextIds.push(dragId);
    return nextIds;
  }

  const dropId = Number(targetId);
  if (!Number.isInteger(dropId) || dropId <= 0) {
    return null;
  }
  if (dragId === dropId) {
    return normalizedIds;
  }

  const dropIndex = nextIds.indexOf(dropId);
  if (dropIndex < 0) {
    return null;
  }

  const placeBefore = position === "before";
  const insertIndex = placeBefore ? dropIndex : dropIndex + 1;
  nextIds.splice(insertIndex, 0, dragId);
  return nextIds;
}

export function mergeLayoutsForReview({
  layouts,
  localEditsById = {},
  deletedLayoutIds = [],
} = {}) {
  const inputLayouts = Array.isArray(layouts) ? layouts : [];
  const deletedSet = new Set(
    (Array.isArray(deletedLayoutIds) ? deletedLayoutIds : [])
      .map((value) => Number(value))
      .filter((value) => Number.isInteger(value) && value > 0),
  );

  const serverLayoutsById = {};
  const mergedLayouts = [];
  const cloneLayout = (layout) => {
    const bbox = layout?.bbox && typeof layout.bbox === "object" ? { ...layout.bbox } : null;
    const boundTargetIds = Array.isArray(layout?.bound_target_ids) ? [...layout.bound_target_ids] : [];
    return {
      ...layout,
      bbox,
      bound_target_ids: boundTargetIds,
    };
  };

  for (const layout of inputLayouts) {
    const layoutId = Number(layout?.id);
    if (!Number.isInteger(layoutId) || layoutId <= 0) {
      continue;
    }

    const serverLayout = cloneLayout(layout);
    serverLayoutsById[String(layoutId)] = serverLayout;
    if (deletedSet.has(layoutId)) {
      continue;
    }

    const draft = localEditsById[String(layoutId)];
    if (!draft) {
      mergedLayouts.push(cloneLayout(serverLayout));
      continue;
    }
    mergedLayouts.push({
      ...serverLayout,
      class_name: draft.class_name,
      reading_order: draft.reading_order,
      bbox: { ...draft.bbox },
    });
  }

  return { serverLayoutsById, mergedLayouts };
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

export function computeApproxLineBand({
  offsetY,
  contentHeight,
  lineHeight,
  minLineHeight = 6,
} = {}) {
  const y = Number(offsetY);
  const height = Number(contentHeight);
  const lh = Number(lineHeight);
  const minLh = Number(minLineHeight);
  if (!Number.isFinite(y) || !Number.isFinite(height) || !Number.isFinite(lh)) {
    return null;
  }
  if (height <= 0 || lh <= 0) {
    return null;
  }

  const safeMin = Number.isFinite(minLh) && minLh > 0 ? minLh : 6;
  const effectiveLineHeight = Math.max(safeMin, lh);
  const clampedY = Math.max(0, Math.min(height - 0.001, y));
  const lineIndex = Math.max(0, Math.floor(clampedY / effectiveLineHeight));
  return computeApproxLineBandByIndex({
    lineIndex,
    contentHeight: height,
    lineHeight: effectiveLineHeight,
    minLineHeight: safeMin,
  });
}

export function computeApproxLineBandByIndex({
  lineIndex,
  contentHeight,
  lineHeight,
  minLineHeight = 6,
} = {}) {
  const index = Number(lineIndex);
  const height = Number(contentHeight);
  const lh = Number(lineHeight);
  const minLh = Number(minLineHeight);
  if (!Number.isFinite(index) || !Number.isFinite(height) || !Number.isFinite(lh)) {
    return null;
  }
  if (height <= 0 || lh <= 0) {
    return null;
  }
  const safeMin = Number.isFinite(minLh) && minLh > 0 ? minLh : 6;
  const effectiveLineHeight = Math.max(safeMin, lh);
  const totalLines = Math.max(1, Math.ceil(height / effectiveLineHeight));
  const clampedIndex = Math.max(0, Math.min(totalLines - 1, Math.floor(index)));
  const topPx = Math.min(height, clampedIndex * effectiveLineHeight);
  const bandHeightPx = Math.max(1, Math.min(effectiveLineHeight, height - topPx));
  if (bandHeightPx <= 0) {
    return null;
  }

  return {
    lineIndex: clampedIndex,
    topRatio: topPx / height,
    heightRatio: bandHeightPx / height,
    totalLines,
  };
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

export function nextHistoryPageId(rawHistory, rawIndex) {
  const { history, index } = normalizeReviewHistory(rawHistory, rawIndex);
  if (history.length === 0 || index < 0 || index >= history.length - 1) {
    return null;
  }
  return history[index + 1];
}

export function filterReviewHistory(rawHistory, rawIndex, allowedPageIds) {
  const normalized = normalizeReviewHistory(rawHistory, rawIndex);
  const allowedSet = new Set(
    (Array.isArray(allowedPageIds) ? allowedPageIds : Array.from(allowedPageIds || []))
      .map((value) => Number(value))
      .filter((value) => Number.isInteger(value) && value > 0),
  );
  if (allowedSet.size === 0) {
    return { history: [], index: -1 };
  }

  const filteredHistory = [];
  let filteredIndex = -1;
  for (let index = 0; index < normalized.history.length; index += 1) {
    const pageId = normalized.history[index];
    if (!allowedSet.has(pageId)) {
      continue;
    }
    if (index <= normalized.index) {
      filteredIndex = filteredHistory.length;
    }
    filteredHistory.push(pageId);
  }

  if (filteredHistory.length === 0) {
    return { history: [], index: -1 };
  }
  if (filteredIndex < 0) {
    filteredIndex = 0;
  }
  filteredIndex = Math.max(0, Math.min(filteredIndex, filteredHistory.length - 1));
  return { history: filteredHistory, index: filteredIndex };
}
