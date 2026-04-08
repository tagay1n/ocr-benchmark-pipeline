import {
  fetchAllPagesSortedById,
  fetchNextQaPage,
  patchPageQaStatus,
  fetchPageDetails,
} from "./qa_review_api.mjs";

const PHASES = ["bbox", "class", "order", "ocr"];
const PHASE_LABELS = {
  bbox: "BBox boundaries",
  class: "Class labels",
  order: "Reading order",
  ocr: "OCR text",
};
const PHASE_EDITOR_URL_BASE = Object.freeze({
  bbox: "/static/layouts.html?page_id=",
  class: "/static/layouts.html?page_id=",
  order: "/static/layouts.html?page_id=",
  ocr: "/static/ocr_review.html?page_id=",
});

const phaseButtons = {
  bbox: document.getElementById("phase-bbox-btn"),
  class: document.getElementById("phase-class-btn"),
  order: document.getElementById("phase-order-btn"),
  ocr: document.getElementById("phase-ocr-btn"),
};
const qaMarkReviewedBtn = document.getElementById("qa-mark-reviewed-btn");
const qaMarkPendingBtn = document.getElementById("qa-mark-pending-btn");
const qaPrevPageBtn = document.getElementById("qa-prev-page-btn");
const qaNextPageBtn = document.getElementById("qa-next-page-btn");
const qaNextPendingBtn = document.getElementById("qa-next-pending-btn");
const qaOpenSourceBtn = document.getElementById("qa-open-source-btn");
const qaProgress = document.getElementById("qa-progress");
const qaPageMeta = document.getElementById("qa-page-meta");
const qaPhaseStatusList = document.getElementById("qa-phase-status-list");
const qaReviewFrame = document.getElementById("qa-review-frame");

const state = {
  pages: [],
  pageId: null,
  phase: "bbox",
  saving: false,
};

function normalizePhase(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (PHASES.includes(normalized)) {
    return normalized;
  }
  return "bbox";
}

function normalizeQaStatus(value) {
  return String(value || "").trim().toLowerCase() === "reviewed"
    ? "reviewed"
    : "pending";
}

function qaStatusesFromPage(page) {
  const source = page?.qa_statuses && typeof page.qa_statuses === "object"
    ? page.qa_statuses
    : {};
  return {
    bbox: normalizeQaStatus(source.bbox),
    class: normalizeQaStatus(source.class),
    order: normalizeQaStatus(source.order),
    ocr: normalizeQaStatus(source.ocr),
  };
}

function pageIndexById(pageId) {
  return state.pages.findIndex((page) => Number(page.id) === Number(pageId));
}

function currentPage() {
  const index = pageIndexById(state.pageId);
  if (index < 0) {
    return null;
  }
  return state.pages[index];
}

function currentQaStatus() {
  const page = currentPage();
  if (!page) {
    return "pending";
  }
  const statuses = qaStatusesFromPage(page);
  return statuses[state.phase] || "pending";
}

function buildEditorUrl(pageId) {
  const base = PHASE_EDITOR_URL_BASE[state.phase] || PHASE_EDITOR_URL_BASE.bbox;
  return `${base}${pageId}&qa_phase=${encodeURIComponent(state.phase)}`;
}

function updateBrowserUrl() {
  const params = new URLSearchParams(window.location.search);
  if (Number.isInteger(state.pageId) && state.pageId > 0) {
    params.set("page_id", String(state.pageId));
  } else {
    params.delete("page_id");
  }
  params.set("phase", state.phase);
  const query = params.toString();
  const nextUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname;
  window.history.replaceState({}, "", nextUrl);
}

function renderPhaseButtons() {
  for (const phase of PHASES) {
    const button = phaseButtons[phase];
    if (!(button instanceof HTMLButtonElement)) {
      continue;
    }
    const isActive = phase === state.phase;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  }
}

function renderProgress() {
  const total = state.pages.length;
  const reviewed = state.pages.filter((page) => {
    const statuses = qaStatusesFromPage(page);
    return statuses[state.phase] === "reviewed";
  }).length;
  qaProgress.textContent = `Phase: ${PHASE_LABELS[state.phase]} | reviewed ${reviewed}/${total}`;
}

function renderPageMeta() {
  const page = currentPage();
  if (!page) {
    qaPageMeta.textContent = "No indexed pages found.";
    return;
  }
  qaPageMeta.textContent = `Page ${page.id} | ${page.rel_path || "-"} | ${PHASE_LABELS[state.phase]}`;
}

function renderPhaseStatusList() {
  const page = currentPage();
  qaPhaseStatusList.innerHTML = "";
  if (!page) {
    return;
  }
  const statuses = qaStatusesFromPage(page);
  for (const phase of PHASES) {
    const item = document.createElement("li");
    item.className = `qa-phase-status-item is-${statuses[phase]}`;
    item.textContent = `${PHASE_LABELS[phase]}: ${statuses[phase]}`;
    qaPhaseStatusList.appendChild(item);
  }
}

function renderFrame() {
  const page = currentPage();
  if (!page) {
    qaReviewFrame.removeAttribute("src");
    return;
  }
  qaReviewFrame.src = buildEditorUrl(Number(page.id));
}

function renderNavigationButtons() {
  const index = pageIndexById(state.pageId);
  const hasPage = index >= 0;
  qaPrevPageBtn.disabled = !hasPage || index <= 0;
  qaNextPageBtn.disabled = !hasPage || index >= state.pages.length - 1;
  qaNextPendingBtn.disabled = !hasPage;
  qaOpenSourceBtn.disabled = !hasPage;
  if (state.saving) {
    qaMarkReviewedBtn.disabled = true;
    qaMarkPendingBtn.disabled = true;
    return;
  }
  if (!hasPage) {
    qaMarkReviewedBtn.disabled = true;
    qaMarkPendingBtn.disabled = true;
    return;
  }
  const status = currentQaStatus();
  qaMarkReviewedBtn.disabled = status === "reviewed";
  qaMarkPendingBtn.disabled = status === "pending";
}

function renderAll() {
  renderPhaseButtons();
  renderProgress();
  renderPageMeta();
  renderPhaseStatusList();
  renderFrame();
  renderNavigationButtons();
  updateBrowserUrl();
}

function setPhase(nextPhase) {
  state.phase = normalizePhase(nextPhase);
  renderAll();
}

function setPage(pageId) {
  const numeric = Number(pageId);
  if (!Number.isInteger(numeric) || numeric <= 0 || pageIndexById(numeric) < 0) {
    return;
  }
  state.pageId = numeric;
  renderAll();
}

async function refreshCurrentPageDetails() {
  const page = currentPage();
  if (!page) {
    return;
  }
  try {
    const payload = await fetchPageDetails(Number(page.id));
    if (!payload?.page) {
      return;
    }
    const index = pageIndexById(Number(page.id));
    if (index < 0) {
      return;
    }
    state.pages[index] = {
      ...state.pages[index],
      ...payload.page,
    };
    renderAll();
  } catch (error) {
    console.error(`Failed to refresh QA page details: ${error.message}`);
  }
}

async function applyQaStatus(status) {
  const page = currentPage();
  if (!page || state.saving) {
    return;
  }
  state.saving = true;
  renderNavigationButtons();
  try {
    const payload = await patchPageQaStatus(Number(page.id), {
      phase: state.phase,
      status,
    });
    const index = pageIndexById(Number(page.id));
    if (index >= 0) {
      state.pages[index] = {
        ...state.pages[index],
        qa_statuses: payload?.qa_statuses || state.pages[index].qa_statuses,
      };
    }
    renderAll();
  } catch (error) {
    console.error(`Failed to update QA status: ${error.message}`);
  } finally {
    state.saving = false;
    renderNavigationButtons();
  }
}

async function goToNextPending() {
  const page = currentPage();
  if (!page) {
    return;
  }
  try {
    let payload = await fetchNextQaPage(state.phase, Number(page.id));
    if (!payload?.has_next) {
      payload = await fetchNextQaPage(state.phase);
    }
    if (payload?.has_next && Number.isInteger(payload.next_page_id)) {
      setPage(Number(payload.next_page_id));
      return;
    }
  } catch (error) {
    console.error(`Failed to load next pending QA page: ${error.message}`);
  }
}

function openCurrentSourcePage() {
  const page = currentPage();
  if (!page) {
    return;
  }
  window.location.href = buildEditorUrl(Number(page.id));
}

function goRelativePage(step) {
  const index = pageIndexById(state.pageId);
  if (index < 0) {
    return;
  }
  const nextIndex = index + step;
  if (nextIndex < 0 || nextIndex >= state.pages.length) {
    return;
  }
  setPage(Number(state.pages[nextIndex].id));
}

async function init() {
  try {
    state.pages = await fetchAllPagesSortedById();
  } catch (error) {
    console.error(`Failed to load pages for QA review: ${error.message}`);
    state.pages = [];
  }

  const params = new URLSearchParams(window.location.search);
  state.phase = normalizePhase(params.get("phase"));
  const requestedPageId = Number(params.get("page_id"));

  if (state.pages.length > 0) {
    if (Number.isInteger(requestedPageId) && pageIndexById(requestedPageId) >= 0) {
      state.pageId = requestedPageId;
    } else {
      state.pageId = Number(state.pages[0].id);
    }
  }

  renderAll();
  await refreshCurrentPageDetails();
}

for (const phase of PHASES) {
  const button = phaseButtons[phase];
  if (!(button instanceof HTMLButtonElement)) {
    continue;
  }
  button.addEventListener("click", () => {
    setPhase(phase);
  });
}

qaMarkReviewedBtn.addEventListener("click", () => {
  applyQaStatus("reviewed").catch((error) => {
    console.error(`Failed to mark QA reviewed: ${error.message}`);
  });
});
qaMarkPendingBtn.addEventListener("click", () => {
  applyQaStatus("pending").catch((error) => {
    console.error(`Failed to mark QA pending: ${error.message}`);
  });
});
qaPrevPageBtn.addEventListener("click", () => {
  goRelativePage(-1);
});
qaNextPageBtn.addEventListener("click", () => {
  goRelativePage(1);
});
qaNextPendingBtn.addEventListener("click", () => {
  goToNextPending().catch((error) => {
    console.error(`Failed to navigate next pending QA page: ${error.message}`);
  });
});
qaOpenSourceBtn.addEventListener("click", () => {
  openCurrentSourcePage();
});

window.addEventListener("focus", () => {
  refreshCurrentPageDetails().catch((error) => {
    console.error(`Failed to refresh QA page details on focus: ${error.message}`);
  });
});

init().catch((error) => {
  console.error(`Failed to initialize QA review page: ${error.message}`);
});
