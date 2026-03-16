export function normalizeNextPagePayload(payload) {
  if (payload && payload.has_next && Number.isInteger(payload.next_page_id) && payload.next_page_id > 0) {
    return {
      nextPageId: Number(payload.next_page_id),
      nextPageRelPath: payload.next_page_rel_path ? String(payload.next_page_rel_path) : null,
    };
  }
  return {
    nextPageId: null,
    nextPageRelPath: null,
  };
}

export function findNextPageForStatus(pages, pendingStatus) {
  const list = Array.isArray(pages) ? pages : [];
  const target = String(pendingStatus || "");
  const pending = list
    .filter((page) => page && !page.is_missing && String(page.status || "") === target)
    .sort((a, b) => Number(a.id) - Number(b.id));
  if (pending.length === 0) {
    return {
      nextPageId: null,
      nextPageRelPath: null,
    };
  }
  return {
    nextPageId: Number(pending[0].id),
    nextPageRelPath: pending[0].rel_path ? String(pending[0].rel_path) : null,
  };
}

function normalizeSummaryStatusKey(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
}

function toNonNegativeInt(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 0;
  }
  return Math.floor(parsed);
}

export function pipelineProgressFromSummary(summaryPayload) {
  const total = toNonNegativeInt(summaryPayload?.total_pages);
  const rawByStatus = summaryPayload?.by_status && typeof summaryPayload.by_status === "object"
    ? summaryPayload.by_status
    : {};

  const byStatus = {};
  for (const [statusKey, rawCount] of Object.entries(rawByStatus)) {
    const key = normalizeSummaryStatusKey(statusKey);
    byStatus[key] = (byStatus[key] || 0) + toNonNegativeInt(rawCount);
  }

  const layoutReviewed = [
    "layout_reviewed",
    "ocr_extracting",
    "ocr_done",
    "ocr_failed",
    "ocr_reviewed",
  ].reduce((sum, statusKey) => sum + toNonNegativeInt(byStatus[statusKey]), 0);

  const ocrReviewed = toNonNegativeInt(byStatus.ocr_reviewed);
  const ocrReady = toNonNegativeInt(byStatus.ocr_done) + ocrReviewed;

  return {
    total,
    layoutReviewed: Math.min(total, layoutReviewed),
    ocrReady: Math.min(total, ocrReady),
    ocrReviewed: Math.min(total, ocrReviewed),
  };
}
