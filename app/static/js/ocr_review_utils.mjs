export function normalizeReconstructedRenderMode(rawValue) {
  const value = String(rawValue || "").trim().toLowerCase();
  if (value === "raw") {
    return "raw";
  }
  return "markdown";
}

export function normalizeReviewViewMode(rawValue) {
  const value = String(rawValue || "").trim().toLowerCase();
  if (value === "line_by_line" || value === "line-by-line" || value === "focused_strip") {
    return "line_by_line";
  }
  if (value === "two_panels" || value === "two-panels" || value === "side_by_side") {
    return "two_panels";
  }
  return "two_panels";
}

export function isLineSyncEnabledOutputFormat(outputFormat) {
  return String(outputFormat || "").trim().toLowerCase() === "markdown";
}

const STRUCTURED_TABLE_ALLOWED_TAGS = new Set([
  "table",
  "caption",
  "colgroup",
  "col",
  "thead",
  "tbody",
  "tfoot",
  "tr",
  "th",
  "td",
  "br",
]);

const STRUCTURED_TABLE_SPAN_ATTRS_BY_TAG = Object.freeze({
  colgroup: new Set(["span"]),
  col: new Set(["span"]),
  th: new Set(["colspan", "rowspan"]),
  td: new Set(["colspan", "rowspan"]),
});

function parsePositiveIntegerAttribute(value, { min = 1, max = 1000 } = {}) {
  const text = String(value ?? "").trim();
  if (!/^\d+$/.test(text)) {
    return null;
  }
  const parsed = Number.parseInt(text, 10);
  if (!Number.isFinite(parsed) || parsed < min || parsed > max) {
    return null;
  }
  return String(parsed);
}

export function isAllowedStructuredTableTag(tagName) {
  const normalized = String(tagName || "").trim().toLowerCase();
  return STRUCTURED_TABLE_ALLOWED_TAGS.has(normalized);
}

export function sanitizeStructuredTableAttribute({ tagName, attrName, attrValue } = {}) {
  const normalizedTag = String(tagName || "").trim().toLowerCase();
  const normalizedAttr = String(attrName || "").trim().toLowerCase();
  if (!normalizedAttr || !isAllowedStructuredTableTag(normalizedTag)) {
    return null;
  }

  const spanAttrs = STRUCTURED_TABLE_SPAN_ATTRS_BY_TAG[normalizedTag];
  if (spanAttrs && spanAttrs.has(normalizedAttr)) {
    return parsePositiveIntegerAttribute(attrValue, { min: 1, max: 1000 });
  }

  if (normalizedTag === "th" && normalizedAttr === "scope") {
    const scope = String(attrValue || "").trim().toLowerCase();
    if (scope === "row" || scope === "col" || scope === "rowgroup" || scope === "colgroup") {
      return scope;
    }
    return null;
  }

  return null;
}

export function hasRaisedInlineMarkdownTag(rawValue) {
  return /<\s*(sup|sub)\b/i.test(String(rawValue ?? ""));
}

export function preserveLineHeightRatio({ hasRaisedInlineTag = false, verticalFlow = false } = {}) {
  if (verticalFlow) {
    return 1;
  }
  return hasRaisedInlineTag ? 1.45 : 1.18;
}

export function isLineReviewRequiredOutput({ className, outputFormat } = {}) {
  const normalizedClassName = String(className || "")
    .trim()
    .toLowerCase()
    .replace(/[-/\s]+/g, "_");
  const normalizedFormat = String(outputFormat || "").trim().toLowerCase();
  if (normalizedFormat === "skip" || !normalizedClassName) {
    return false;
  }
  if (normalizedClassName === "formula") {
    return normalizedFormat === "latex";
  }
  return (
    normalizedClassName === "text" ||
    normalizedClassName === "section_header" ||
    normalizedClassName === "list_item" ||
    normalizedClassName === "caption" ||
    normalizedClassName === "footnote" ||
    normalizedClassName === "page_header" ||
    normalizedClassName === "page_footer" ||
    normalizedClassName === "picture_text"
  );
}

export function resolveReconstructedLineFlow({
  className,
  outputFormat,
  orientation = null,
  effectiveOrientation = null,
  bbox = null,
} = {}) {
  const normalizedFormat = String(outputFormat || "").trim().toLowerCase();
  if (normalizedFormat !== "markdown") {
    return "horizontal";
  }
  if (!isLineReviewRequiredOutput({ className, outputFormat: normalizedFormat })) {
    return "horizontal";
  }
  const effective = resolveOutputEffectiveOrientation({
    orientation,
    effectiveOrientation,
    bbox,
  });
  return effective === "vertical" ? "vertical" : "horizontal";
}

export function resolveLineMatchingOrientation({
  className,
  outputFormat,
  orientation = null,
  effectiveOrientation = null,
  bbox = null,
  totalLines = 1,
} = {}) {
  const flow = resolveReconstructedLineFlow({
    className,
    outputFormat,
    orientation,
    effectiveOrientation,
    bbox,
  });
  const lineCount = Number(totalLines);
  const safeLineCount = Number.isFinite(lineCount) && lineCount > 0 ? Math.max(1, Math.floor(lineCount)) : 1;
  if (flow === "vertical" && safeLineCount >= 1) {
    return "vertical";
  }
  return "horizontal";
}

export function resolveLineMatchingBandCount({
  className,
  outputFormat,
  orientation = null,
  effectiveOrientation = null,
  bbox = null,
  totalLines = 1,
  singleColumnAspectThreshold = 4,
} = {}) {
  const lineCount = Number(totalLines);
  const safeLineCount = Number.isFinite(lineCount) && lineCount > 0 ? Math.max(1, Math.floor(lineCount)) : 1;
  if (safeLineCount <= 1) {
    return 1;
  }
  const matchingOrientation = resolveLineMatchingOrientation({
    className,
    outputFormat,
    orientation,
    effectiveOrientation,
    bbox,
    totalLines: safeLineCount,
  });
  if (matchingOrientation !== "vertical") {
    return safeLineCount;
  }
  const x1 = Number(bbox?.x1);
  const y1 = Number(bbox?.y1);
  const x2 = Number(bbox?.x2);
  const y2 = Number(bbox?.y2);
  if (![x1, y1, x2, y2].every((value) => Number.isFinite(value))) {
    return safeLineCount;
  }
  const width = Math.max(0, Math.abs(x2 - x1));
  const height = Math.max(0, Math.abs(y2 - y1));
  if (width <= 0 || height <= 0) {
    return safeLineCount;
  }
  const aspect = height / width;
  const threshold = Math.max(1, Number(singleColumnAspectThreshold) || 4);
  if (aspect >= threshold) {
    return 1;
  }
  return safeLineCount;
}

function normalizeOutputClassName(className) {
  return String(className || "")
    .trim()
    .toLowerCase()
    .replace(/[-/\s]+/g, "_");
}

export function reconstructedLayerRankForOutputClass(className) {
  const normalized = normalizeOutputClassName(className);
  if (normalized === "picture") {
    return 1;
  }
  if (normalized === "picture_text") {
    return 3;
  }
  return 2;
}

function toFiniteScroll(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return 0;
  }
  return numeric;
}

export function resolveViewportScrollSyncUpdate({
  sourceLeft,
  sourceTop,
  targetLeft,
  targetTop,
} = {}) {
  const nextLeft = toFiniteScroll(sourceLeft);
  const nextTop = toFiniteScroll(sourceTop);
  const currentLeft = toFiniteScroll(targetLeft);
  const currentTop = toFiniteScroll(targetTop);
  if (nextLeft === currentLeft && nextTop === currentTop) {
    return null;
  }
  return {
    left: nextLeft,
    top: nextTop,
  };
}

function clampNumber(value, min, max) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return min;
  }
  return Math.max(min, Math.min(max, numeric));
}

export function computeViewportAutoCenterTarget({
  bbox,
  contentWidth,
  contentHeight,
  viewportWidth,
  viewportHeight,
  currentLeft = 0,
  currentTop = 0,
  horizontalMarginRatio = 0.2,
  verticalMarginRatio = 0.25,
  maxMarginPx = 220,
  preferVerticalCenter = false,
  centerThresholdPx = 8,
} = {}) {
  const width = Number(contentWidth);
  const height = Number(contentHeight);
  const viewportW = Number(viewportWidth);
  const viewportH = Number(viewportHeight);
  if (
    !bbox ||
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    !Number.isFinite(viewportW) ||
    !Number.isFinite(viewportH) ||
    width <= 0 ||
    height <= 0 ||
    viewportW <= 0 ||
    viewportH <= 0
  ) {
    return null;
  }

  const x1 = Number(bbox.x1);
  const y1 = Number(bbox.y1);
  const x2 = Number(bbox.x2);
  const y2 = Number(bbox.y2);
  if (![x1, y1, x2, y2].every((value) => Number.isFinite(value))) {
    return null;
  }

  const leftRatio = Math.max(0, Math.min(1, Math.min(x1, x2)));
  const rightRatio = Math.max(0, Math.min(1, Math.max(x1, x2)));
  const topRatio = Math.max(0, Math.min(1, Math.min(y1, y2)));
  const bottomRatio = Math.max(0, Math.min(1, Math.max(y1, y2)));
  if (rightRatio <= leftRatio || bottomRatio <= topRatio) {
    return null;
  }

  const boxLeft = leftRatio * width;
  const boxRight = rightRatio * width;
  const boxTop = topRatio * height;
  const boxBottom = bottomRatio * height;
  const boxCenterX = (boxLeft + boxRight) / 2;
  const boxCenterY = (boxTop + boxBottom) / 2;

  const maxLeft = Math.max(0, width - viewportW);
  const maxTop = Math.max(0, height - viewportH);
  const currentX = clampNumber(currentLeft, 0, maxLeft);
  const currentY = clampNumber(currentTop, 0, maxTop);

  const marginCap = Math.max(0, Number(maxMarginPx) || 0);
  const marginRatioX = Math.max(0, Number(horizontalMarginRatio) || 0);
  const marginRatioY = Math.max(0, Number(verticalMarginRatio) || 0);
  const marginX = Math.min(marginCap, Math.max(0, viewportW * marginRatioX), Math.max(0, viewportW / 2 - 1));
  const marginY = Math.min(marginCap, Math.max(0, viewportH * marginRatioY), Math.max(0, viewportH / 2 - 1));

  let nextLeft = currentX;
  let nextTop = currentY;

  const safeLeft = currentX + marginX;
  const safeRight = currentX + viewportW - marginX;
  const safeTop = currentY + marginY;
  const safeBottom = currentY + viewportH - marginY;

  if (boxLeft < safeLeft) {
    nextLeft = boxLeft - marginX;
  } else if (boxRight > safeRight) {
    nextLeft = boxRight + marginX - viewportW;
  }

  if (preferVerticalCenter) {
    const centeredTop = boxCenterY - viewportH / 2;
    if (Math.abs(centeredTop - currentY) > Math.max(0, Number(centerThresholdPx) || 0)) {
      nextTop = centeredTop;
    }
  } else if (boxTop < safeTop) {
    nextTop = boxTop - marginY;
  } else if (boxBottom > safeBottom) {
    nextTop = boxBottom + marginY - viewportH;
  }

  const clampedLeft = Math.round(clampNumber(nextLeft, 0, maxLeft));
  const clampedTop = Math.round(clampNumber(nextTop, 0, maxTop));
  if (clampedLeft === Math.round(currentX) && clampedTop === Math.round(currentY)) {
    return null;
  }
  return { left: clampedLeft, top: clampedTop };
}

export function computeEditorToolbarState({ editorHidden, outputFormat } = {}) {
  const editorVisible = !Boolean(editorHidden);
  const markdownEnabled = editorVisible && String(outputFormat || "").trim().toLowerCase() === "markdown";
  return {
    toolbarHidden: !editorVisible,
    markdownActionsEnabled: markdownEnabled,
  };
}

export function resolveEditorDrawerLayout({
  requestedWidth,
  viewportWidth,
  minWidth = 420,
  maxRatio = 0.9,
  responsiveBreakpoint = 1120,
} = {}) {
  const viewport = Number(viewportWidth);
  if (!Number.isFinite(viewport) || viewport <= 0) {
    return { resizable: false, width: null };
  }
  const resizable = viewport > Number(responsiveBreakpoint);
  if (!resizable) {
    return { resizable: false, width: null };
  }

  const max = Math.floor(viewport * Number(maxRatio));
  if (!Number.isFinite(max) || max <= 0) {
    return { resizable: false, width: null };
  }
  const min = Math.min(Math.max(1, Math.floor(Number(minWidth) || 1)), max);

  if (requestedWidth === null || requestedWidth === undefined) {
    return { resizable: true, width: null };
  }
  if (typeof requestedWidth === "string" && requestedWidth.trim() === "") {
    return { resizable: true, width: null };
  }
  const raw = Number(requestedWidth);
  if (!Number.isFinite(raw)) {
    return { resizable: true, width: null };
  }
  const width = Math.max(min, Math.min(max, Math.round(raw)));
  return { resizable: true, width };
}

function containsMarkdownTableLike(text) {
  const normalized = String(text ?? "");
  if (!normalized) {
    return false;
  }
  const lines = normalized.split(/\r?\n/);
  let insideFence = false;
  for (let index = 0; index < lines.length - 1; index += 1) {
    const current = String(lines[index] ?? "");
    const next = String(lines[index + 1] ?? "");
    const trimmed = current.trim();
    if (/^(```|~~~)/.test(trimmed)) {
      insideFence = !insideFence;
      continue;
    }
    if (insideFence) {
      continue;
    }
    if (!current.includes("|")) {
      continue;
    }
    if (/^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(next)) {
      return true;
    }
  }
  return false;
}

function hasUnbalancedMarkdownFences(text) {
  const normalized = String(text ?? "");
  const lines = normalized.split(/\r?\n/);
  let fenceCount = 0;
  for (const rawLine of lines) {
    const line = String(rawLine ?? "").trim();
    if (/^(```|~~~)/.test(line)) {
      fenceCount += 1;
    }
  }
  return fenceCount % 2 !== 0;
}

function hasUnbalancedLatexBraces(text) {
  const normalized = String(text ?? "");
  let balance = 0;
  for (let index = 0; index < normalized.length; index += 1) {
    const char = normalized[index];
    if (char === "\\") {
      index += 1;
      continue;
    }
    if (char === "{") {
      balance += 1;
      continue;
    }
    if (char === "}") {
      balance -= 1;
      if (balance < 0) {
        return true;
      }
    }
  }
  return balance !== 0;
}

export function detectEditorValidationIssues({ content, format } = {}) {
  const normalizedContent = String(content ?? "");
  const normalizedFormat = String(format ?? "").trim().toLowerCase();
  const issues = [];
  if (!normalizedContent) {
    return issues;
  }

  if (normalizedFormat === "markdown" || !normalizedFormat) {
    if (containsMarkdownTableLike(normalizedContent)) {
      issues.push({
        code: "markdown_table",
        severity: "warn",
        label: "Markdown table detected",
      });
    }
    if (hasUnbalancedMarkdownFences(normalizedContent)) {
      issues.push({
        code: "markdown_fence",
        severity: "warn",
        label: "Unbalanced code fences",
      });
    }
  }

  if (normalizedFormat === "latex") {
    if (hasUnbalancedLatexBraces(normalizedContent)) {
      issues.push({
        code: "latex_braces",
        severity: "warn",
        label: "Unbalanced braces",
      });
    }
  }

  return issues;
}

function clampSelectionRange(textLength, start, end) {
  const safeLength = Math.max(0, Number(textLength) || 0);
  const rawStart = Number(start);
  const rawEnd = Number(end);
  const clampedStart = Number.isFinite(rawStart) ? Math.max(0, Math.min(safeLength, Math.floor(rawStart))) : 0;
  const clampedEnd = Number.isFinite(rawEnd) ? Math.max(0, Math.min(safeLength, Math.floor(rawEnd))) : clampedStart;
  if (clampedStart <= clampedEnd) {
    return { start: clampedStart, end: clampedEnd };
  }
  return { start: clampedEnd, end: clampedStart };
}

export function applyInlineMarkdownWrapper({
  content,
  selectionStart,
  selectionEnd,
  left = "",
  right = "",
  placeholder = "",
} = {}) {
  const text = String(content ?? "");
  const { start, end } = clampSelectionRange(text.length, selectionStart, selectionEnd);
  const prefix = String(left ?? "");
  const suffix = String(right ?? "");
  const template = String(placeholder ?? "");
  const selected = text.slice(start, end);
  const inner = selected.length > 0 ? selected : template;
  const nextText = `${text.slice(0, start)}${prefix}${inner}${suffix}${text.slice(end)}`;
  const innerStart = start + prefix.length;
  const innerEnd = innerStart + inner.length;
  return {
    content: nextText,
    selectionStart: innerStart,
    selectionEnd: innerEnd,
  };
}

function touchedLineStartOffsets(text, selectionStart, selectionEnd) {
  const { start, end } = clampSelectionRange(text.length, selectionStart, selectionEnd);
  const lineStarts = [0];
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === "\n") {
      lineStarts.push(index + 1);
    }
  }

  let lastTouch = end;
  if (end > start && end > 0 && text[end - 1] === "\n") {
    lastTouch = end - 1;
  }
  const touched = [];
  for (const lineStart of lineStarts) {
    const nextBreak = text.indexOf("\n", lineStart);
    const lineEnd = nextBreak === -1 ? text.length : nextBreak;
    const intersects = lineEnd >= start && lineStart <= lastTouch;
    if (intersects) {
      touched.push(lineStart);
    }
  }
  if (touched.length === 0) {
    touched.push(0);
  }
  return touched;
}

export function applyLinePrefixMarkdown({
  content,
  selectionStart,
  selectionEnd,
  kind = "unordered",
} = {}) {
  const text = String(content ?? "");
  const { start, end } = clampSelectionRange(text.length, selectionStart, selectionEnd);
  const lineStarts = touchedLineStartOffsets(text, start, end);

  let nextText = text;
  let nextStart = start;
  let nextEnd = end;
  for (let index = lineStarts.length - 1; index >= 0; index -= 1) {
    const lineStart = lineStarts[index];
    const prefix = kind === "ordered" ? `${index + 1}. ` : "- ";
    nextText = `${nextText.slice(0, lineStart)}${prefix}${nextText.slice(lineStart)}`;
    if (lineStart <= nextStart) {
      nextStart += prefix.length;
    }
    if (lineStart < nextEnd || (start === end && lineStart === nextEnd)) {
      nextEnd += prefix.length;
    }
  }

  return {
    content: nextText,
    selectionStart: nextStart,
    selectionEnd: nextEnd,
  };
}

export function countTextLines(content) {
  const text = String(content ?? "");
  if (!text) {
    return 1;
  }
  let count = 1;
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === "\n") {
      count += 1;
    }
  }
  return count;
}

export function lineIndexFromTextOffset(content, offset) {
  const text = String(content ?? "");
  const length = text.length;
  const rawOffset = Number(offset);
  const clampedOffset = Number.isFinite(rawOffset) ? Math.max(0, Math.min(length, Math.floor(rawOffset))) : length;
  let lineIndex = 0;
  for (let index = 0; index < clampedOffset; index += 1) {
    if (text[index] === "\n") {
      lineIndex += 1;
    }
  }
  return lineIndex;
}

export function textOffsetForLineIndex(content, lineIndex) {
  const text = String(content ?? "");
  const targetLine = Number(lineIndex);
  if (!Number.isFinite(targetLine) || targetLine <= 0) {
    return 0;
  }
  const desired = Math.floor(targetLine);
  let seenLineBreaks = 0;
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] !== "\n") {
      continue;
    }
    seenLineBreaks += 1;
    if (seenLineBreaks >= desired) {
      return index + 1;
    }
  }
  return text.length;
}

export function lineBandFromLineIndex(lineIndex, totalLines) {
  const rawTotal = Number(totalLines);
  const effectiveTotal = Number.isFinite(rawTotal) && rawTotal > 0 ? Math.max(1, Math.floor(rawTotal)) : 1;
  const rawIndex = Number(lineIndex);
  const clampedIndex = Number.isFinite(rawIndex)
    ? Math.max(0, Math.min(effectiveTotal - 1, Math.floor(rawIndex)))
    : 0;
  return {
    lineIndex: clampedIndex,
    topRatio: clampedIndex / effectiveTotal,
    heightRatio: 1 / effectiveTotal,
    totalLines: effectiveTotal,
  };
}

export function normalizeLayoutOrientationValue(value, { fallback = "horizontal" } = {}) {
  const normalized = String(value || "").trim().toLowerCase().replace(/_/g, "-");
  if (normalized === "vertical" || normalized === "v") {
    return "vertical";
  }
  if (normalized === "horizontal" || normalized === "h") {
    return "horizontal";
  }
  const fallbackNormalized = String(fallback || "").trim().toLowerCase();
  return fallbackNormalized === "vertical" ? "vertical" : "horizontal";
}

export function resolveOutputEffectiveOrientation({
  orientation = null,
  effectiveOrientation = null,
  bbox = null,
} = {}) {
  const explicitEffective = String(effectiveOrientation || "").trim();
  if (explicitEffective) {
    return normalizeLayoutOrientationValue(explicitEffective);
  }
  const explicitOrientation = String(orientation || "").trim();
  if (explicitOrientation) {
    return normalizeLayoutOrientationValue(explicitOrientation);
  }
  const x1 = Number(bbox?.x1);
  const y1 = Number(bbox?.y1);
  const x2 = Number(bbox?.x2);
  const y2 = Number(bbox?.y2);
  if (![x1, y1, x2, y2].every((value) => Number.isFinite(value))) {
    return "horizontal";
  }
  const width = Math.max(0, Math.abs(x2 - x1));
  const height = Math.max(0, Math.abs(y2 - y1));
  if (width <= 0 || height <= 0) {
    return "horizontal";
  }
  return height / width >= 2 ? "vertical" : "horizontal";
}

export function lineIndexFromPointerOffset({ offset, axisSize, totalLines } = {}) {
  const size = Number(axisSize);
  const lines = Number(totalLines);
  const safeLines = Number.isFinite(lines) && lines > 0 ? Math.max(1, Math.floor(lines)) : 1;
  if (!Number.isFinite(size) || size <= 0) {
    return 0;
  }
  const rawOffset = Number(offset);
  const safeOffset = Number.isFinite(rawOffset) ? Math.max(0, Math.min(size - 0.001, rawOffset)) : 0;
  const ratio = safeOffset / size;
  return Math.max(0, Math.min(safeLines - 1, Math.floor(ratio * safeLines)));
}

export function resolveLineBandAxisRect(lineBand, orientation = "horizontal") {
  if (!lineBand) {
    return null;
  }
  const axisStart = Math.max(0, Math.min(1, Number(lineBand.topRatio)));
  const axisSpan = Math.max(0, Math.min(1 - axisStart, Number(lineBand.heightRatio)));
  if (!(axisSpan > 0)) {
    return null;
  }
  const mode = normalizeLayoutOrientationValue(orientation);
  if (mode === "vertical") {
    return {
      leftRatio: axisStart,
      topRatio: 0,
      widthRatio: axisSpan,
      heightRatio: 1,
    };
  }
  return {
    leftRatio: 0,
    topRatio: axisStart,
    widthRatio: 1,
    heightRatio: axisSpan,
  };
}

function isWordTokenChar(char) {
  return /[\p{L}\p{N}\p{M}_]/u.test(char);
}

function classifyTokenChar(char) {
  if (!char || /\s/.test(char)) {
    return "space";
  }
  return isWordTokenChar(char) ? "word" : "punct";
}

export function tokenBoundsAtOffset(content, offset) {
  const text = String(content ?? "");
  if (!text) {
    return null;
  }

  const rawOffset = Number(offset);
  let index = Number.isFinite(rawOffset) ? Math.floor(rawOffset) : 0;
  if (index < 0) index = 0;
  if (index >= text.length) index = text.length - 1;

  let charClass = classifyTokenChar(text[index]);
  if (charClass === "space") {
    let left = index - 1;
    while (left >= 0 && classifyTokenChar(text[left]) === "space") {
      left -= 1;
    }
    let right = index + 1;
    while (right < text.length && classifyTokenChar(text[right]) === "space") {
      right += 1;
    }
    if (left < 0 && right >= text.length) {
      return null;
    }
    if (left < 0) {
      index = right;
    } else if (right >= text.length) {
      index = left;
    } else {
      const leftDistance = Math.abs(index - left);
      const rightDistance = Math.abs(right - index);
      index = rightDistance < leftDistance ? right : left;
    }
    charClass = classifyTokenChar(text[index]);
  }

  if (charClass === "space") {
    return null;
  }

  let start = index;
  let end = index + 1;
  while (start > 0 && classifyTokenChar(text[start - 1]) === charClass) {
    start -= 1;
  }
  while (end < text.length && classifyTokenChar(text[end]) === charClass) {
    end += 1;
  }

  const token = text.slice(start, end);
  if (!token) {
    return null;
  }
  return {
    start,
    end,
    token,
    kind: charClass,
  };
}

function isWholeWordMatch(content, start, end) {
  const text = String(content ?? "");
  const leftChar = start > 0 ? text[start - 1] : "";
  const rightChar = end < text.length ? text[end] : "";
  return !isWordTokenChar(leftChar) && !isWordTokenChar(rightChar);
}

export function findBestTokenOccurrence(content, token, { preferredOffset = 0, wholeWord = true } = {}) {
  const text = String(content ?? "");
  const needle = String(token ?? "");
  if (!text || !needle) {
    return null;
  }
  const targetOffset = Number.isFinite(Number(preferredOffset)) ? Number(preferredOffset) : 0;

  let cursor = 0;
  let best = null;
  while (cursor <= text.length - needle.length) {
    const index = text.indexOf(needle, cursor);
    if (index === -1) {
      break;
    }
    const end = index + needle.length;
    if (!wholeWord || isWholeWordMatch(text, index, end)) {
      const score = Math.abs(index - targetOffset);
      if (!best || score < best.score || (score === best.score && index < best.start)) {
        best = {
          start: index,
          end,
          score,
        };
      }
    }
    cursor = index + 1;
  }

  if (!best) {
    return null;
  }
  return {
    start: best.start,
    end: best.end,
  };
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

function clampUnit(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return 0;
  }
  return Math.max(0, Math.min(1, numeric));
}

function normalizePercent(value) {
  const rounded = Math.round(Number(value) * 1_000_000) / 1_000_000;
  if (Object.is(rounded, -0)) {
    return 0;
  }
  return rounded;
}

export function computeReconstructedImageCropStyle(bbox) {
  if (!bbox || typeof bbox !== "object") {
    return null;
  }
  const x1 = clampUnit(bbox.x1);
  const y1 = clampUnit(bbox.y1);
  const x2 = clampUnit(bbox.x2);
  const y2 = clampUnit(bbox.y2);
  if (x2 <= x1 || y2 <= y1) {
    return null;
  }

  const widthRatio = x2 - x1;
  const heightRatio = y2 - y1;
  const widthPercent = 100 / widthRatio;
  const heightPercent = 100 / heightRatio;
  const leftPercent = -(x1 / widthRatio) * 100;
  const topPercent = -(y1 / heightRatio) * 100;

  return {
    widthPercent: normalizePercent(widthPercent),
    heightPercent: normalizePercent(heightPercent),
    leftPercent: normalizePercent(leftPercent),
    topPercent: normalizePercent(topPercent),
  };
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

export function computeLineReviewDisplayGeometry({
  bbox,
  crop = null,
  reelWidth = 0,
  imageWidth = 0,
  imageHeight = 0,
  targetHeightPx = 44,
  minHeightPx = 30,
  maxHeightPx = 62,
  minWidthPx = 120,
  minWidthRatioFallback = 0.08,
  maxWidthRatio = 0.94,
} = {}) {
  const x1 = clampUnit(bbox?.x1);
  const y1 = clampUnit(bbox?.y1);
  const x2 = clampUnit(bbox?.x2);
  const y2 = clampUnit(bbox?.y2);
  const normalizedRect = x2 > x1 && y2 > y1 ? { x1, y1, x2, y2 } : null;
  const contentWidth = Math.max(1e-6, normalizedRect ? normalizedRect.x2 - normalizedRect.x1 : 0.5);
  let widthRatio = Math.min(maxWidthRatio, Math.max(0.18, contentWidth));
  let heightPx = targetHeightPx;

  const safeReelWidth = Number(reelWidth);
  const safeImageWidth = Number(imageWidth);
  const safeImageHeight = Number(imageHeight);
  const cropWidth = Number(crop?.cropWidth || contentWidth);
  const cropHeight = Number(crop?.cropHeight || 0);
  if (
    Number.isFinite(safeReelWidth) && safeReelWidth > 0 &&
    Number.isFinite(safeImageWidth) && safeImageWidth > 0 &&
    Number.isFinite(safeImageHeight) && safeImageHeight > 0 &&
    cropWidth > 0 &&
    cropHeight > 0
  ) {
    const imageAspectRatio = safeImageHeight / safeImageWidth;
    const cropAspectRatio = (cropHeight / cropWidth) * imageAspectRatio;
    const aspectFactor = safeReelWidth * cropAspectRatio;
    if (Number.isFinite(aspectFactor) && aspectFactor > 0) {
      const minWidthRatioFromPx = Math.max(
        minWidthRatioFallback,
        Math.min(maxWidthRatio, minWidthPx / safeReelWidth),
      );
      const widthForTarget = targetHeightPx / aspectFactor;
      const widthForMinHeight = minHeightPx / aspectFactor;
      const widthForMaxHeight = maxHeightPx / aspectFactor;
      const minAllowedWidth = Math.max(minWidthRatioFromPx, widthForMinHeight);
      const maxAllowedWidth = Math.min(maxWidthRatio, widthForMaxHeight);
      if (minAllowedWidth <= maxAllowedWidth) {
        widthRatio = Math.max(minAllowedWidth, Math.min(maxAllowedWidth, widthForTarget));
      } else {
        widthRatio = Math.max(minWidthRatioFromPx, Math.min(maxWidthRatio, widthForTarget));
      }
      heightPx = aspectFactor * widthRatio;
    }
  }

  const safeHeight = Math.max(minHeightPx, Math.min(maxHeightPx, Number(heightPx) || targetHeightPx));
  const safeWidth = Math.max(minWidthRatioFallback, Math.min(maxWidthRatio, Number(widthRatio) || 0.5));
  return {
    leftRatio: Math.max(0, (1 - safeWidth) / 2),
    widthRatio: safeWidth,
    contentWidth,
    heightPx: safeHeight,
  };
}

export function resolveStretchableLineText({ rawLine = "", renderedText = "" } = {}) {
  const raw = String(rawLine ?? "").replace(/\u00A0/g, " ");
  const rendered = String(renderedText ?? "").replace(/\u00A0/g, " ");
  return rendered.trim().length > 0 ? rendered : raw;
}

export function containsCombiningMarks(value) {
  return /[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]/u.test(String(value ?? ""));
}
