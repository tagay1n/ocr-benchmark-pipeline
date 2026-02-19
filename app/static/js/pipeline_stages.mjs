const REACHED_LAYOUT_DETECTION = new Set(["layout_detected", "layout_reviewed", "ocr_done", "ocr_reviewed"]);
const REACHED_OCR_EXTRACTION = new Set(["layout_reviewed", "ocr_done", "ocr_reviewed"]);
const REACHED_OCR_REVIEW = new Set(["ocr_done", "ocr_reviewed"]);
const REACHED_FINALIZATION = new Set(["ocr_reviewed"]);

export const STAGES = [
  {
    id: "discovery",
    name: "Discovery",
    description: "All indexed documents across all pipeline stages.",
    pendingMatcher: (page) => !page.is_missing && page.status === "new",
    historyMatcher: () => true,
  },
  {
    id: "layout_review",
    name: "Layout Review",
    description: "All docs that reached layout review (including already moved forward).",
    pendingMatcher: (page) => !page.is_missing && page.status === "layout_detected",
    historyMatcher: (page) => REACHED_LAYOUT_DETECTION.has(page.status),
  },
  {
    id: "ocr_extraction",
    name: "OCR Extraction",
    description: "All docs that reached OCR extraction (including already moved forward).",
    pendingMatcher: (page) => !page.is_missing && page.status === "layout_reviewed",
    historyMatcher: (page) => REACHED_OCR_EXTRACTION.has(page.status),
  },
  {
    id: "ocr_review",
    name: "OCR Review",
    description: "All docs that reached OCR review (including already moved forward).",
    pendingMatcher: (page) => !page.is_missing && page.status === "ocr_done",
    historyMatcher: (page) => REACHED_OCR_REVIEW.has(page.status),
  },
  {
    id: "finalization",
    name: "Finalization",
    description: "Pages that passed OCR review and are waiting final confirmation.",
    pendingMatcher: (page) => !page.is_missing && page.status === "ocr_reviewed",
    historyMatcher: (page) => REACHED_FINALIZATION.has(page.status),
  },
];

export function getStageById(stageId) {
  return STAGES.find((stage) => stage.id === stageId) || null;
}

export function stageCount(stage, pages) {
  return pages.filter(stage.pendingMatcher).length;
}

export function filterPagesForStage(stage, pages) {
  return pages.filter(stage.historyMatcher);
}

export function stageDashboardHref(stageId) {
  return `/?stage=${encodeURIComponent(stageId)}`;
}
