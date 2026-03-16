function toPositiveInt(value) {
  const numeric = Number(value);
  if (!Number.isInteger(numeric) || numeric <= 0) {
    return null;
  }
  return numeric;
}

export function persistReviewHistoryState({
  writeStorage,
  historyKey,
  historyIndexKey,
  history,
  historyIndex,
} = {}) {
  if (typeof writeStorage !== "function") {
    return;
  }
  writeStorage(historyKey, JSON.stringify(Array.isArray(history) ? history : []));
  writeStorage(historyIndexKey, String(Number.isInteger(historyIndex) ? historyIndex : 0));
}

export function loadReviewHistoryState({
  readStorage,
  historyKey,
  historyIndexKey,
  normalizeReviewHistory,
} = {}) {
  const readStorageFn = typeof readStorage === "function" ? readStorage : () => null;
  const normalizeFn =
    typeof normalizeReviewHistory === "function"
      ? normalizeReviewHistory
      : (history, index) => ({ history: Array.isArray(history) ? history : [], index: Number(index) || 0 });

  let parsedHistory = [];
  const rawHistory = readStorageFn(historyKey);
  if (rawHistory) {
    try {
      parsedHistory = JSON.parse(rawHistory);
    } catch {
      parsedHistory = [];
    }
  }
  const rawIndex = readStorageFn(historyIndexKey);
  const normalized = normalizeFn(parsedHistory, rawIndex);
  return {
    history: Array.isArray(normalized?.history) ? normalized.history : [],
    index: Number.isInteger(normalized?.index) ? normalized.index : 0,
  };
}

export function sanitizeReviewHistoryFromPages({
  history,
  historyIndex,
  pages,
  currentPageId,
  filterReviewHistory,
} = {}) {
  const filterFn =
    typeof filterReviewHistory === "function"
      ? filterReviewHistory
      : (rawHistory, rawIndex) => ({
          history: Array.isArray(rawHistory) ? rawHistory : [],
          index: Number.isInteger(rawIndex) ? rawIndex : 0,
        });
  const validPageIds = new Set(
    (Array.isArray(pages) ? pages : [])
      .filter((page) => !Boolean(page?.is_missing))
      .map((page) => Number(page?.id))
      .filter((id) => Number.isInteger(id) && id > 0),
  );
  const normalizedCurrentPageId = toPositiveInt(currentPageId);
  if (normalizedCurrentPageId !== null) {
    validPageIds.add(normalizedCurrentPageId);
  }
  return filterFn(history, historyIndex, validPageIds);
}

export function registerCurrentPageVisit({
  history,
  historyIndex,
  currentPageId,
  updateReviewHistoryOnVisit,
  maxLength,
} = {}) {
  const updateFn =
    typeof updateReviewHistoryOnVisit === "function"
      ? updateReviewHistoryOnVisit
      : (rawHistory, rawIndex) => ({
          history: Array.isArray(rawHistory) ? rawHistory : [],
          index: Number.isInteger(rawIndex) ? rawIndex : 0,
        });
  if (Number.isInteger(maxLength)) {
    return updateFn(history, historyIndex, currentPageId, maxLength);
  }
  return updateFn(history, historyIndex, currentPageId);
}

export function historyNavigationTargets({
  history,
  historyIndex,
  nextReviewPageId = null,
  previousHistoryPageId,
  nextHistoryPageId,
} = {}) {
  const prevFn = typeof previousHistoryPageId === "function" ? previousHistoryPageId : () => null;
  const nextFn = typeof nextHistoryPageId === "function" ? nextHistoryPageId : () => null;
  const backTarget = toPositiveInt(prevFn(history, historyIndex));
  const forwardHistoryTarget = toPositiveInt(nextFn(history, historyIndex));
  const queueTarget = toPositiveInt(nextReviewPageId);
  return {
    backTarget,
    forwardHistoryTarget,
    queueTarget,
  };
}
