export function normalizeReconstructedRenderMode(rawValue) {
  const value = String(rawValue || "").trim().toLowerCase();
  if (value === "raw") {
    return "raw";
  }
  return "markdown";
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

function isWordTokenChar(char) {
  return /[\p{L}\p{N}_]/u.test(char);
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
