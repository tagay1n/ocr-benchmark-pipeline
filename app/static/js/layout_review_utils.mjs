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

export function normalizeLayoutOrderMode(value, { fallback = "auto" } = {}) {
  const normalized = String(value || "").trim().toLowerCase().replace(/_/g, "-");
  if (normalized === "single-column" || normalized === "single") {
    return "single";
  }
  if (normalized === "auto") {
    return "auto";
  }
  if (normalized === "single") {
    return "single";
  }
  if (normalized === "multi-column") {
    return "multi-column";
  }
  if (normalized === "two-page") {
    return "two-page";
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

export function isLayoutNotFoundErrorMessage(value) {
  const message = String(value ?? "").trim().toLowerCase();
  return message === "layout not found" || message === "layout not found.";
}

export function computeZoomScale({
  mode,
  zoomPercent,
  naturalWidth,
  naturalHeight,
  viewportWidth,
  viewportHeight,
  extraVerticalSpace = 0,
}) {
  if (!naturalWidth || !naturalHeight || !viewportWidth || !viewportHeight) {
    return null;
  }

  const verticalInset = Math.max(0, Number(extraVerticalSpace) || 0);
  const effectiveViewportHeight = Math.max(1, viewportHeight - verticalInset);
  const fitWidthScale = viewportWidth / naturalWidth;
  const fitHeightScale = effectiveViewportHeight / naturalHeight;
  const fitPageScale = Math.min(fitWidthScale, fitHeightScale);
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

export function computeOverlayBadgeScale(
  zoomScale,
  {
    minScale = 0.85,
    maxScale = 1.35,
    multiplier = 0.95,
    curve = 0.5,
    fallbackScale = 0.95,
  } = {},
) {
  const scale = Number(zoomScale);
  const min = Math.max(0.01, Number(minScale) || 0.85);
  const max = Math.max(min, Number(maxScale) || min);
  const factor = Math.max(0.1, Number(multiplier) || 0.95);
  const exponent = Math.max(0.1, Number(curve) || 0.5);
  const fallback = Math.min(max, Math.max(min, Number(fallbackScale) || 0.95));
  if (!Number.isFinite(scale) || scale <= 0) {
    return fallback;
  }
  // Adaptive screen-space scaling: keep badges readable at low zoom and
  // prevent oversized labels at high zoom.
  const adaptive = Math.pow(scale, exponent) * factor;
  return Math.min(max, Math.max(min, adaptive));
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

export function intermediateResizeHandleCount(
  sideLengthPx,
  { spacingPx = 180, minCount = 1, maxCount = 10 } = {},
) {
  const side = Number(sideLengthPx);
  const spacing = Number(spacingPx);
  const min = Math.max(0, Math.floor(Number(minCount) || 0));
  const max = Math.max(min, Math.floor(Number(maxCount) || min));
  if (!Number.isFinite(side) || side <= 0 || !Number.isFinite(spacing) || spacing <= 0) {
    return min;
  }
  const estimated = Math.floor(side / spacing);
  return Math.max(min, Math.min(max, estimated));
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

export function nextManualReadingOrder(layouts) {
  if (!Array.isArray(layouts) || layouts.length === 0) {
    return 1;
  }
  let visibleCount = 0;
  for (const layout of layouts) {
    const layoutId = Number(layout?.id);
    if (!Number.isInteger(layoutId) || layoutId <= 0) {
      continue;
    }
    visibleCount += 1;
  }
  return Math.max(1, visibleCount + 1);
}

export function guessManualReadingOrderByY(layouts, bbox) {
  const y1 = Number(bbox?.y1);
  const y2 = Number(bbox?.y2);
  if (!Number.isFinite(y1) || !Number.isFinite(y2)) {
    return nextManualReadingOrder(layouts);
  }
  const newCenterY = (y1 + y2) / 2;
  if (!Number.isFinite(newCenterY)) {
    return nextManualReadingOrder(layouts);
  }

  const orderedLayouts = (Array.isArray(layouts) ? layouts : [])
    .map((layout) => {
      const order = Number(layout?.reading_order);
      const ly1 = Number(layout?.bbox?.y1);
      const ly2 = Number(layout?.bbox?.y2);
      if (
        !Number.isInteger(order) ||
        order < 1 ||
        !Number.isFinite(ly1) ||
        !Number.isFinite(ly2)
      ) {
        return null;
      }
      return {
        readingOrder: order,
        centerY: (ly1 + ly2) / 2,
      };
    })
    .filter((row) => row && Number.isFinite(row.centerY))
    .sort((left, right) => left.readingOrder - right.readingOrder);

  if (orderedLayouts.length === 0) {
    return 1;
  }

  for (const layout of orderedLayouts) {
    if (newCenterY < layout.centerY) {
      return layout.readingOrder;
    }
  }
  return orderedLayouts.length + 1;
}

export function shiftDraftReadingOrdersAfterInsertion({
  layouts,
  localEditsById,
  insertedOrder,
}) {
  const threshold = Number(insertedOrder);
  if (!Number.isInteger(threshold) || threshold < 1) {
    return { ...(localEditsById || {}) };
  }
  const nextEdits = { ...(localEditsById || {}) };
  const orderedLayouts = (Array.isArray(layouts) ? layouts : [])
    .map((layout) => {
      const layoutId = Number(layout?.id);
      const readingOrder = Number(layout?.reading_order);
      if (!Number.isInteger(layoutId) || layoutId <= 0 || !Number.isInteger(readingOrder)) {
        return null;
      }
      return { id: layoutId, readingOrder };
    })
    .filter((item) => item !== null)
    .sort((left, right) => {
      if (left.readingOrder !== right.readingOrder) {
        return left.readingOrder - right.readingOrder;
      }
      return left.id - right.id;
    });

  for (const item of orderedLayouts) {
    if (item.readingOrder < threshold) {
      continue;
    }
    const key = String(item.id);
    const existingDraft = nextEdits[key];
    if (!existingDraft || typeof existingDraft !== "object") {
      continue;
    }
    nextEdits[key] = {
      ...existingDraft,
      reading_order: item.readingOrder + 1,
    };
  }
  return nextEdits;
}

export function hasContiguousUniqueReadingOrders(layouts) {
  const rows = (Array.isArray(layouts) ? layouts : [])
    .map((layout) => ({
      id: Number(layout?.id),
      readingOrder: Number(layout?.reading_order),
    }))
    .filter((row) => Number.isInteger(row.id) && row.id > 0);
  if (rows.length === 0) {
    return true;
  }
  if (rows.some((row) => !Number.isInteger(row.readingOrder) || row.readingOrder < 1)) {
    return false;
  }
  const orders = rows.map((row) => row.readingOrder).sort((left, right) => left - right);
  if (new Set(orders).size !== orders.length) {
    return false;
  }
  for (let index = 0; index < orders.length; index += 1) {
    if (orders[index] !== index + 1) {
      return false;
    }
  }
  return true;
}

function normalizeDraftClassNameForCompare(value) {
  return String(value ?? "").trim().toLowerCase();
}

function normalizeDraftOrientationForCompare(value) {
  const normalized = String(value ?? "").trim().toLowerCase().replace(/_/g, "-");
  if (normalized === "vertical" || normalized === "v") {
    return "vertical";
  }
  return "horizontal";
}

function normalizeDraftReadingOrderForCompare(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = Number(value);
  if (!Number.isInteger(numeric) || numeric < 1) {
    return null;
  }
  return numeric;
}

function normalizeDraftBboxCoordForCompare(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  return Math.round(numeric * 10000) / 10000;
}

function hasBlockingBboxDifference(draftBBox, baselineBBox) {
  if (!draftBBox || typeof draftBBox !== "object" || !baselineBBox || typeof baselineBBox !== "object") {
    return true;
  }
  const keys = ["x1", "y1", "x2", "y2"];
  for (const key of keys) {
    const draftValue = normalizeDraftBboxCoordForCompare(draftBBox[key]);
    const baselineValue = normalizeDraftBboxCoordForCompare(baselineBBox[key]);
    if (draftValue === null || baselineValue === null) {
      return true;
    }
    if (draftValue !== baselineValue) {
      return true;
    }
  }
  return false;
}

export function summarizeDraftChangesForReorder({
  localEditsById = {},
  serverLayoutsById = {},
} = {}) {
  const readingOrderOnlyLayoutIds = [];
  const blockingLayoutIds = [];
  const localEdits = localEditsById && typeof localEditsById === "object" ? localEditsById : {};
  const serverLayouts = serverLayoutsById && typeof serverLayoutsById === "object" ? serverLayoutsById : {};

  for (const [rawLayoutId, rawDraft] of Object.entries(localEdits)) {
    const layoutId = Number(rawLayoutId);
    if (!Number.isInteger(layoutId) || layoutId <= 0) {
      continue;
    }
    const draft = rawDraft && typeof rawDraft === "object" ? rawDraft : null;
    const baseline = serverLayouts[String(layoutId)];
    if (!draft || !baseline || typeof baseline !== "object") {
      blockingLayoutIds.push(layoutId);
      continue;
    }

    const classChanged =
      normalizeDraftClassNameForCompare(draft.class_name) !==
      normalizeDraftClassNameForCompare(baseline.class_name);
    const orientationChanged =
      normalizeDraftOrientationForCompare(draft.orientation) !==
      normalizeDraftOrientationForCompare(baseline.orientation);
    const bboxChanged = hasBlockingBboxDifference(draft.bbox, baseline.bbox);
    const readingOrderChanged =
      normalizeDraftReadingOrderForCompare(draft.reading_order) !==
      normalizeDraftReadingOrderForCompare(baseline.reading_order);

    if (classChanged || orientationChanged || bboxChanged) {
      blockingLayoutIds.push(layoutId);
      continue;
    }
    if (readingOrderChanged) {
      readingOrderOnlyLayoutIds.push(layoutId);
    }
  }

  readingOrderOnlyLayoutIds.sort((left, right) => left - right);
  blockingLayoutIds.sort((left, right) => left - right);
  return {
    readingOrderOnlyLayoutIds,
    blockingLayoutIds,
    readingOrderOnlyDraftCount: readingOrderOnlyLayoutIds.length,
    blockingDraftCount: blockingLayoutIds.length,
  };
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

export function swapReadingOrderIds({
  orderedIds,
  movedId,
  targetOrder,
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

  const layoutId = Number(movedId);
  if (!Number.isInteger(layoutId) || layoutId <= 0) {
    return null;
  }
  const fromIndex = normalizedIds.indexOf(layoutId);
  if (fromIndex < 0) {
    return null;
  }

  const target = Number(targetOrder);
  if (!Number.isInteger(target)) {
    return null;
  }
  const clampedTarget = Math.max(1, Math.min(normalizedIds.length, target));
  const toIndex = clampedTarget - 1;
  if (toIndex === fromIndex) {
    return normalizedIds;
  }

  const next = [...normalizedIds];
  const [fromValue, toValue] = [next[fromIndex], next[toIndex]];
  next[fromIndex] = toValue;
  next[toIndex] = fromValue;
  return next;
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
      orientation: draft.orientation,
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

export function detectOverlappingBorderSegments({
  layouts,
  contentWidth,
  contentHeight,
  tolerancePx = 0,
  coordinateSnapDigits = 6,
  minOverlapPx = 1,
} = {}) {
  const width = Number(contentWidth);
  const height = Number(contentHeight);
  if (!Array.isArray(layouts) || layouts.length < 2) {
    return [];
  }
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return [];
  }
  const tolerance = Number.isFinite(Number(tolerancePx)) ? Math.max(0, Number(tolerancePx)) : 0;
  const snapDigits = Number.isInteger(Number(coordinateSnapDigits))
    ? Math.max(0, Number(coordinateSnapDigits))
    : 6;
  const snapScale = 10 ** snapDigits;
  const snapRatio = (value) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return Number.NaN;
    }
    return Math.round(numeric * snapScale) / snapScale;
  };
  const minOverlap = Number.isFinite(Number(minOverlapPx)) ? Math.max(0, Number(minOverlapPx)) : 1;
  const clampX = (value) => Math.max(0, Math.min(width, value));
  const clampY = (value) => Math.max(0, Math.min(height, value));

  const rects = [];
  const edges = [];
  for (const layout of layouts) {
    const layoutId = Number(layout?.id);
    const bbox = layout?.bbox;
    if (!Number.isInteger(layoutId) || layoutId <= 0 || !bbox) {
      continue;
    }
    const rawX1 = snapRatio(bbox.x1) * width;
    const rawY1 = snapRatio(bbox.y1) * height;
    const rawX2 = snapRatio(bbox.x2) * width;
    const rawY2 = snapRatio(bbox.y2) * height;
    if (![rawX1, rawY1, rawX2, rawY2].every(Number.isFinite)) {
      continue;
    }
    const x1 = Math.min(clampX(rawX1), clampX(rawX2));
    const x2 = Math.max(clampX(rawX1), clampX(rawX2));
    const y1 = Math.min(clampY(rawY1), clampY(rawY2));
    const y2 = Math.max(clampY(rawY1), clampY(rawY2));
    if (x2 <= x1 || y2 <= y1) {
      continue;
    }
    rects.push({ layoutId, x1, y1, x2, y2 });
    edges.push({ orientation: "vertical", coordPx: x1, startPx: y1, endPx: y2, layoutId });
    edges.push({ orientation: "vertical", coordPx: x2, startPx: y1, endPx: y2, layoutId });
    edges.push({ orientation: "horizontal", coordPx: y1, startPx: x1, endPx: x2, layoutId });
    edges.push({ orientation: "horizontal", coordPx: y2, startPx: x1, endPx: x2, layoutId });
  }

  const overlapKeySet = new Set();
  const overlaps = [];
  const addOverlap = ({
    orientation,
    coordPx,
    startPx,
    endPx,
    layoutIdA,
    layoutIdB,
  }) => {
    if (!Number.isFinite(coordPx) || !Number.isFinite(startPx) || !Number.isFinite(endPx)) {
      return;
    }
    if (endPx - startPx < minOverlap) {
      return;
    }
    const idA = Number(layoutIdA);
    const idB = Number(layoutIdB);
    if (!Number.isInteger(idA) || !Number.isInteger(idB) || idA <= 0 || idB <= 0 || idA === idB) {
      return;
    }
    const lowId = Math.min(idA, idB);
    const highId = Math.max(idA, idB);
    const key = [
      String(orientation),
      coordPx.toFixed(3),
      startPx.toFixed(3),
      endPx.toFixed(3),
      lowId,
      highId,
    ].join("|");
    if (overlapKeySet.has(key)) {
      return;
    }
    overlapKeySet.add(key);
    overlaps.push({
      orientation: String(orientation),
      coordPx,
      startPx,
      endPx,
      layoutIdA: idA,
      layoutIdB: idB,
    });
  };

  for (let index = 0; index < edges.length; index += 1) {
    const left = edges[index];
    for (let inner = index + 1; inner < edges.length; inner += 1) {
      const right = edges[inner];
      if (left.layoutId === right.layoutId) {
        continue;
      }
      if (left.orientation !== right.orientation) {
        continue;
      }
      if (Math.abs(left.coordPx - right.coordPx) > tolerance) {
        continue;
      }
      const startPx = Math.max(left.startPx, right.startPx);
      const endPx = Math.min(left.endPx, right.endPx);
      if (!Number.isFinite(startPx) || !Number.isFinite(endPx)) {
        continue;
      }
      addOverlap({
        orientation: left.orientation,
        coordPx: (left.coordPx + right.coordPx) / 2,
        startPx,
        endPx,
        layoutIdA: left.layoutId,
        layoutIdB: right.layoutId,
      });
    }
  }

  for (let index = 0; index < rects.length; index += 1) {
    const left = rects[index];
    for (let inner = index + 1; inner < rects.length; inner += 1) {
      const right = rects[inner];
      const overlapYStart = Math.max(left.y1, right.y1);
      const overlapYEnd = Math.min(left.y2, right.y2);
      const overlapXStart = Math.max(left.x1, right.x1);
      const overlapXEnd = Math.min(left.x2, right.x2);

      if (overlapYEnd - overlapYStart >= minOverlap) {
        if (left.x1 > right.x1 + tolerance && left.x1 < right.x2 - tolerance) {
          addOverlap({
            orientation: "vertical",
            coordPx: left.x1,
            startPx: overlapYStart,
            endPx: overlapYEnd,
            layoutIdA: left.layoutId,
            layoutIdB: right.layoutId,
          });
        }
        if (left.x2 > right.x1 + tolerance && left.x2 < right.x2 - tolerance) {
          addOverlap({
            orientation: "vertical",
            coordPx: left.x2,
            startPx: overlapYStart,
            endPx: overlapYEnd,
            layoutIdA: left.layoutId,
            layoutIdB: right.layoutId,
          });
        }
        if (right.x1 > left.x1 + tolerance && right.x1 < left.x2 - tolerance) {
          addOverlap({
            orientation: "vertical",
            coordPx: right.x1,
            startPx: overlapYStart,
            endPx: overlapYEnd,
            layoutIdA: right.layoutId,
            layoutIdB: left.layoutId,
          });
        }
        if (right.x2 > left.x1 + tolerance && right.x2 < left.x2 - tolerance) {
          addOverlap({
            orientation: "vertical",
            coordPx: right.x2,
            startPx: overlapYStart,
            endPx: overlapYEnd,
            layoutIdA: right.layoutId,
            layoutIdB: left.layoutId,
          });
        }
      }

      if (overlapXEnd - overlapXStart >= minOverlap) {
        if (left.y1 > right.y1 + tolerance && left.y1 < right.y2 - tolerance) {
          addOverlap({
            orientation: "horizontal",
            coordPx: left.y1,
            startPx: overlapXStart,
            endPx: overlapXEnd,
            layoutIdA: left.layoutId,
            layoutIdB: right.layoutId,
          });
        }
        if (left.y2 > right.y1 + tolerance && left.y2 < right.y2 - tolerance) {
          addOverlap({
            orientation: "horizontal",
            coordPx: left.y2,
            startPx: overlapXStart,
            endPx: overlapXEnd,
            layoutIdA: left.layoutId,
            layoutIdB: right.layoutId,
          });
        }
        if (right.y1 > left.y1 + tolerance && right.y1 < left.y2 - tolerance) {
          addOverlap({
            orientation: "horizontal",
            coordPx: right.y1,
            startPx: overlapXStart,
            endPx: overlapXEnd,
            layoutIdA: right.layoutId,
            layoutIdB: left.layoutId,
          });
        }
        if (right.y2 > left.y1 + tolerance && right.y2 < left.y2 - tolerance) {
          addOverlap({
            orientation: "horizontal",
            coordPx: right.y2,
            startPx: overlapXStart,
            endPx: overlapXEnd,
            layoutIdA: right.layoutId,
            layoutIdB: left.layoutId,
          });
        }
      }
    }
  }

  return overlaps;
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
