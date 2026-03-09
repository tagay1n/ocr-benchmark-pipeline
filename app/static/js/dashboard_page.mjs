import {
  DEFAULT_DASHBOARD_SORT,
  nextDashboardSortState,
  normalizeDashboardSortState,
} from "./dashboard_sorting_utils.mjs";
import {
  inferPageStatusFromPipelineEvent,
  stageDisplayName,
} from "./pipeline_event_constants.mjs";
import { fetchJson } from "./api_client.mjs";
import {
  normalizeNextPagePayload,
  pipelineProgressFromSummary,
} from "./dashboard_review_actions_utils.mjs";
import {
  readStorage,
  readStorageBool,
  writeStorage,
} from "./state_event_utils.mjs";

const STORAGE_KEYS = {
  pipelinePanelExpanded: "dashboard.pipeline_panel_expanded",
  pagesSortColumn: "dashboard.pages_sort.column",
  pagesSortDirection: "dashboard.pages_sort.direction",
  pagesPageSize: "dashboard.pages.page_size",
};

const scanBtn = document.getElementById("scan-btn");
const reviewLayoutsBtn = document.getElementById("review-layouts-btn");
const reviewOcrBtn = document.getElementById("review-ocr-btn");
const exportFinalBtn = document.getElementById("export-final-btn");
const autoDetectLayoutsToggle = document.getElementById("auto-detect-layouts-toggle");
const autoExtractTextToggle = document.getElementById("auto-extract-text-toggle");
const wipeBtn = document.getElementById("wipe-btn");
const wipeModal = document.getElementById("wipe-modal");
const wipeConfirmInput = document.getElementById("wipe-confirm-input");
const wipeCancelBtn = document.getElementById("wipe-cancel-btn");
const wipeConfirmBtn = document.getElementById("wipe-confirm-btn");
const removeModal = document.getElementById("remove-modal");
const removeModalRelPath = document.getElementById("remove-modal-rel-path");
const removeCancelBtn = document.getElementById("remove-cancel-btn");
const removeConfirmBtn = document.getElementById("remove-confirm-btn");

const pagesBody = document.getElementById("pages-body");
const pagesMeta = document.getElementById("pages-meta");
const pagesPrevBtn = document.getElementById("pages-prev-btn");
const pagesNextBtn = document.getElementById("pages-next-btn");
const pagesSizeSelect = document.getElementById("pages-size-select");
const duplicatePanel = document.getElementById("duplicate-panel");
const duplicateList = document.getElementById("duplicate-list");
const pipelineToggle = document.getElementById("pipeline-toggle");
const pipelineBody = document.getElementById("pipeline-body");
const pipelineHeadline = document.getElementById("pipeline-headline");
const pipelineToggleIcon = document.getElementById("pipeline-toggle-icon");
const pipelineQueue = document.getElementById("pipeline-queue");
const pipelineEvents = document.getElementById("pipeline-events");
const pagesSortButtons = Array.from(
  document.querySelectorAll("button[data-pages-sort-key]"),
);

let currentPages = [];
let pagesSortState = { ...DEFAULT_DASHBOARD_SORT };
let pagesPageSize = 50;
let pagesTotalCount = 0;
let pagesHasMore = false;
let pagesNextCursor = null;
let pagesCursorHistory = [null];
let pagesCursorIndex = 0;
let pagesLoading = false;
let pipelinePanelExpanded = false;
let activityStream = null;
let streamReconnectTimer = null;
let streamRefreshTimer = null;
let streamRefreshInFlight = false;
let lastProcessedEventId = 0;
let pendingRemovePageId = null;
let runtimeOptions = {
  enable_background_jobs: true,
  auto_detect_layouts_after_discovery: false,
  auto_extract_text_after_layout_review: false,
};
const DATE_LOCALE = "en-GB";
const DATE_TIME_FORMAT = {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
};
const TIME_FORMAT = {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
};

const REVIEW_ACTIONS = Object.freeze({
  layout: {
    button: reviewLayoutsBtn,
    pendingStatus: "layout_detected",
    fallbackOpenTitle: "Open next layout review page",
    noItemsTitle: "No images available for layout review.",
    hrefBase: "/static/layouts.html?page_id=",
  },
  ocr: {
    button: reviewOcrBtn,
    pendingStatus: "ocr_done",
    fallbackOpenTitle: "Open next OCR review page",
    noItemsTitle: "No images available for OCR review.",
    hrefBase: "/static/ocr_review.html?page_id=",
  },
});

const reviewActionState = {
  layout: { nextPageId: null },
  ocr: { nextPageId: null },
};

function formatDateTime(value) {
  const date = new Date(value);
  return date.toLocaleString(DATE_LOCALE, DATE_TIME_FORMAT);
}

function formatTime(value) {
  const date = new Date(value);
  return date.toLocaleTimeString(DATE_LOCALE, TIME_FORMAT);
}

function toSentenceCaseLabel(value) {
  const normalized = String(value || "")
    .replace(/_/g, " ")
    .trim()
    .toLowerCase();
  if (!normalized) {
    return "";
  }
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function toUpperStatusLabel(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .trim()
    .toUpperCase();
}

function loadPagesSortState() {
  pagesSortState = normalizeDashboardSortState({
    columnKey: readStorage(STORAGE_KEYS.pagesSortColumn),
    direction: readStorage(STORAGE_KEYS.pagesSortDirection),
  });
}

function persistPagesSortState() {
  writeStorage(STORAGE_KEYS.pagesSortColumn, pagesSortState.columnKey);
  writeStorage(STORAGE_KEYS.pagesSortDirection, pagesSortState.direction);
}

function loadPagesPageSize() {
  const stored = Number(readStorage(STORAGE_KEYS.pagesPageSize));
  if ([25, 50, 100].includes(stored)) {
    pagesPageSize = stored;
  } else {
    pagesPageSize = 50;
  }
}

function persistPagesPageSize() {
  writeStorage(STORAGE_KEYS.pagesPageSize, String(pagesPageSize));
}

function pagesRequestUrl(cursor = null) {
  const params = new URLSearchParams();
  params.set("limit", String(pagesPageSize));
  params.set("sort", pagesSortState.columnKey);
  params.set("dir", pagesSortState.direction);
  if (cursor) {
    params.set("cursor", String(cursor));
  }
  return `/api/pages?${params.toString()}`;
}

function resetPagesPagination() {
  pagesCursorHistory = [null];
  pagesCursorIndex = 0;
  pagesHasMore = false;
  pagesNextCursor = null;
  pagesTotalCount = 0;
}

function updatePagesSortControls() {
  for (const button of pagesSortButtons) {
    if (!(button instanceof HTMLButtonElement)) {
      continue;
    }
    const columnKey = String(button.dataset.pagesSortKey || "");
    const indicator = button.querySelector("[data-pages-sort-indicator]");
    const headerCell = button.closest("th");
    const isActive = columnKey === pagesSortState.columnKey;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");

    if (headerCell instanceof HTMLTableCellElement) {
      if (isActive) {
        headerCell.setAttribute(
          "aria-sort",
          pagesSortState.direction === "asc" ? "ascending" : "descending",
        );
      } else {
        headerCell.setAttribute("aria-sort", "none");
      }
    }

    if (indicator instanceof HTMLElement) {
      indicator.textContent = isActive
        ? pagesSortState.direction === "asc"
          ? "▲"
          : "▼"
        : "↕";
    }
  }
}

function updatePagesPaginationControls() {
  const start = pagesTotalCount === 0 ? 0 : pagesCursorIndex * pagesPageSize + 1;
  const end = pagesTotalCount === 0 ? 0 : start + currentPages.length - 1;
  pagesMeta.textContent = `Showing ${start}-${end} of ${pagesTotalCount}`;
  pagesPrevBtn.disabled = pagesLoading || pagesCursorIndex <= 0;
  pagesNextBtn.disabled = pagesLoading || !pagesHasMore || !pagesNextCursor;
  pagesSizeSelect.disabled = pagesLoading;
}

function applyRuntimeOptions(options) {
  runtimeOptions = {
    enable_background_jobs: Boolean(options?.enable_background_jobs),
    auto_detect_layouts_after_discovery: Boolean(options?.auto_detect_layouts_after_discovery),
    auto_extract_text_after_layout_review: Boolean(options?.auto_extract_text_after_layout_review),
  };

  autoDetectLayoutsToggle.checked = runtimeOptions.auto_detect_layouts_after_discovery;
  autoExtractTextToggle.checked = runtimeOptions.auto_extract_text_after_layout_review;

  const disabled = !runtimeOptions.enable_background_jobs;
  autoDetectLayoutsToggle.disabled = disabled;
  autoExtractTextToggle.disabled = disabled;
  autoDetectLayoutsToggle.title = disabled ? "Background jobs are disabled in config." : "";
  autoExtractTextToggle.title = disabled ? "Background jobs are disabled in config." : "";
}

function setPipelinePanelExpanded(expanded) {
  pipelinePanelExpanded = expanded;
  pipelineToggle.setAttribute("aria-expanded", expanded ? "true" : "false");
  pipelineBody.hidden = !expanded;
  pipelineToggleIcon.textContent = expanded ? "-" : "+";
  writeStorage(STORAGE_KEYS.pipelinePanelExpanded, expanded ? "1" : "0");
}

function loadThumbnail(slot) {
  if (!(slot instanceof HTMLElement)) {
    return;
  }
  const img = slot.querySelector(".thumbnail-image");
  if (!(img instanceof HTMLImageElement)) {
    return;
  }
  if (img.dataset.loaded === "1" || img.dataset.loading === "1") {
    return;
  }
  const src = img.dataset.src;
  if (!src) {
    return;
  }
  const placeholder = slot.querySelector(".thumbnail-placeholder");
  img.dataset.loading = "1";
  const onLoad = () => {
    img.dataset.loaded = "1";
    img.classList.add("is-loaded");
    delete img.dataset.loading;
    if (placeholder instanceof HTMLElement) {
      placeholder.hidden = true;
    }
  };
  const onError = () => {
    img.dataset.loaded = "0";
    delete img.dataset.loading;
    if (placeholder instanceof HTMLElement) {
      placeholder.hidden = false;
      placeholder.textContent = "Preview unavailable";
      placeholder.classList.add("is-error");
    }
  };
  img.addEventListener("load", onLoad, { once: true });
  img.addEventListener("error", onError, { once: true });
  img.src = src;
  if (img.complete) {
    if (img.naturalWidth > 0 && img.naturalHeight > 0) {
      onLoad();
    } else {
      onError();
    }
  }
}

function renderPages(pages) {
  pagesBody.innerHTML = "";
  const visiblePages = Array.isArray(pages) ? pages : [];
  if (visiblePages.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td class="empty-row" colspan="6">No indexed documents found yet.</td>';
    pagesBody.appendChild(tr);
    return;
  }

  for (const page of visiblePages) {
    const tr = document.createElement("tr");
    tr.dataset.pageId = String(page.id);
    tr.innerHTML = `
      <td>${page.id}</td>
      <td>
        <div class="thumbnail-slot" data-thumbnail-slot>
          <div class="thumbnail-placeholder">${page.is_missing ? "Missing" : "Loading preview"}</div>
          ${
            page.is_missing
              ? ""
              : `<img
                  class="thumbnail-image"
                  data-src="/api/pages/${page.id}/image"
                  alt="Thumbnail for page ${page.id}"
                  loading="lazy"
                  decoding="async"
                />`
          }
        </div>
      </td>
      <td>${page.rel_path}</td>
      <td>
        <span class="status ${page.is_missing ? "missing" : ""}">
          ${page.is_missing ? "missing" : page.status}
        </span>
      </td>
      <td>${formatDateTime(page.created_at)}</td>
      <td>
        <div class="row-open-actions">
          <button class="secondary row-open-btn" type="button" data-target="layout"${
            page.is_missing ? " disabled" : ""
          }>
            Layout
          </button>
          <button class="secondary row-open-btn" type="button" data-target="ocr"${
            page.is_missing ? " disabled" : ""
          }>
            OCR
          </button>
          <button class="danger-btn row-open-btn" type="button" data-target="remove">
            Remove
          </button>
        </div>
      </td>
    `;
    const statusBadge = tr.querySelector(".status");
    if (statusBadge) {
      statusBadge.textContent = page.is_missing
        ? "MISSING"
        : toUpperStatusLabel(page.status);
    }
    pagesBody.appendChild(tr);
    const thumbnailSlot = tr.querySelector("[data-thumbnail-slot]");
    if (thumbnailSlot && !page.is_missing) {
      loadThumbnail(thumbnailSlot);
    }
  }
}

function applyPagesPayload(pagesPayload) {
  currentPages = Array.isArray(pagesPayload?.pages)
    ? pagesPayload.pages.map((page) => ({ ...page }))
    : [];
  pagesTotalCount = Number.isInteger(pagesPayload?.total_count)
    ? Number(pagesPayload.total_count)
    : currentPages.length;
  pagesHasMore = Boolean(pagesPayload?.has_more);
  pagesNextCursor = pagesPayload?.next_cursor ? String(pagesPayload.next_cursor) : null;
  renderPages(currentPages);
  updatePagesPaginationControls();
}

async function loadCurrentPagesSlice({ allowAutoBack = true } = {}) {
  const cursor = pagesCursorHistory[pagesCursorIndex] || null;
  pagesLoading = true;
  updatePagesPaginationControls();
  try {
    const payload = await fetchJson(pagesRequestUrl(cursor));
    applyPagesPayload(payload);
    if (
      allowAutoBack &&
      pagesTotalCount > 0 &&
      currentPages.length === 0 &&
      pagesCursorIndex > 0
    ) {
      pagesCursorIndex -= 1;
      return await loadCurrentPagesSlice({ allowAutoBack: false });
    }
  } finally {
    pagesLoading = false;
    updatePagesPaginationControls();
  }
}

function applyReviewActionAvailability(actionKey, nextPageId, nextPageRelPath) {
  const action = REVIEW_ACTIONS[actionKey];
  const state = reviewActionState[actionKey];
  if (!action || !state) {
    return;
  }
  state.nextPageId = Number.isInteger(nextPageId) && nextPageId > 0 ? Number(nextPageId) : null;
  if (state.nextPageId !== null) {
    action.button.disabled = false;
    action.button.title = nextPageRelPath
      ? `Open next page: ${nextPageRelPath}`
      : action.fallbackOpenTitle;
    return;
  }
  action.button.disabled = true;
  action.button.title = action.noItemsTitle;
}

function applyPipelineProgressLabels(summaryPayload) {
  const progress = pipelineProgressFromSummary(summaryPayload);
  scanBtn.textContent = `Scan(${progress.total})`;
  reviewLayoutsBtn.textContent = `Review layouts(${progress.layoutReviewed}/${progress.total})`;
  reviewOcrBtn.textContent = `Review OCR(${progress.ocrReviewed}/${progress.total})`;
  return progress;
}

function applyPagesSummary(summaryPayload) {
  const progress = applyPipelineProgressLabels(summaryPayload);
  const reviewedCount = progress.ocrReviewed;
  if (reviewedCount > 0) {
    exportFinalBtn.disabled = false;
    exportFinalBtn.title = `Export ${reviewedCount} OCR-reviewed page${reviewedCount === 1 ? "" : "s"}.`;
    return;
  }
  exportFinalBtn.disabled = true;
  exportFinalBtn.title = "No OCR-reviewed pages available for export.";
}

async function refreshReviewActionState() {
  const [nextReviewPayload, nextOcrPayload] = await Promise.all([
    fetchJson("/api/layout-review/next"),
    fetchJson("/api/ocr-review/next"),
  ]);
  applyNextReviewStatePayload("layout", nextReviewPayload);
  applyNextReviewStatePayload("ocr", nextOcrPayload);
}

async function refreshPagesSummary() {
  const summaryPayload = await fetchJson("/api/pages/summary");
  applyPagesSummary(summaryPayload);
}

function renderDuplicates(duplicates) {
  if (duplicates.length === 0) {
    duplicatePanel.hidden = true;
    duplicateList.innerHTML = "";
    return;
  }

  duplicatePanel.hidden = false;
  const ul = document.createElement("ul");
  for (const duplicate of duplicates) {
    const li = document.createElement("li");
    li.textContent = `${duplicate.duplicate_rel_path} (kept: ${duplicate.canonical_rel_path})`;
    ul.appendChild(li);
  }
  duplicateList.innerHTML = "";
  duplicateList.appendChild(ul);
}

function renderActivity(activity) {
  const running = activity.in_progress;
  if (running) {
    const pageText = running.rel_path ? ` | ${running.rel_path}` : "";
    pipelineHeadline.textContent = `Running ${stageDisplayName(running.stage, toSentenceCaseLabel)}${pageText}`;
  } else if (activity.worker_running) {
    pipelineHeadline.textContent = "Pipeline worker active";
  } else {
    pipelineHeadline.textContent = "Pipeline worker idle";
  }

  const queueParts = [];
  const queued = activity.queued || { total: 0, by_stage: {} };
  queueParts.push(`Queued jobs: ${queued.total || 0}`);
  if (queued.by_stage && Object.keys(queued.by_stage).length > 0) {
    queueParts.push(
      Object.entries(queued.by_stage)
        .map(([stage, count]) => `${stageDisplayName(stage, toSentenceCaseLabel)}=${count}`)
        .join(", "),
    );
  }
  pipelineQueue.textContent = queueParts.join(" | ");

  const events = activity.recent_events || [];
  pipelineEvents.innerHTML = "";
  if (events.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No backend activity yet.";
    pipelineEvents.appendChild(li);
    return;
  }

  for (const event of events.slice(-10).reverse()) {
    const li = document.createElement("li");
    const ts = formatTime(event.ts);
    const pageText = event.rel_path ? ` (${event.rel_path})` : "";
    const tsSpan = document.createElement("span");
    tsSpan.className = "activity-event-ts";
    tsSpan.textContent = `[${ts}] `;
    li.appendChild(tsSpan);
    li.appendChild(document.createTextNode(`${event.message}${pageText}`));
    pipelineEvents.appendChild(li);
  }
}

function applyNextReviewStatePayload(actionKey, payload) {
  const next = normalizeNextPagePayload(payload);
  applyReviewActionAvailability(actionKey, next.nextPageId, next.nextPageRelPath);
}

function openNextReviewActionPage(actionKey) {
  const action = REVIEW_ACTIONS[actionKey];
  const state = reviewActionState[actionKey];
  if (!action || !state || !Number.isInteger(state.nextPageId) || state.nextPageId <= 0) {
    return;
  }
  window.location.href = `${action.hrefBase}${state.nextPageId}`;
}

function syncLastProcessedEventId(events) {
  if (!Array.isArray(events) || events.length === 0) {
    lastProcessedEventId = 0;
    return;
  }
  let maxId = 0;
  for (const event of events) {
    const eventId = Number(event?.id);
    if (Number.isInteger(eventId) && eventId > maxId) {
      maxId = eventId;
    }
  }
  lastProcessedEventId = maxId;
}

function applyPageStatusUpdate(pageId, status) {
  const page = currentPages.find((row) => Number(row.id) === Number(pageId));
  if (!page) {
    return false;
  }
  if (page.is_missing || page.status === status) {
    return false;
  }
  page.status = status;
  const row = pagesBody.querySelector(`tr[data-page-id="${pageId}"]`);
  const badge = row ? row.querySelector(".status") : null;
  if (badge) {
    badge.classList.toggle("missing", Boolean(page.is_missing));
    badge.textContent = toUpperStatusLabel(status);
  }
  return true;
}

function applyStatusUpdatesFromEvents(events) {
  if (!Array.isArray(events) || events.length === 0) {
    return { changed: false, sawNewEvent: false };
  }
  let maxId = 0;
  for (const event of events) {
    const eventId = Number(event?.id);
    if (Number.isInteger(eventId) && eventId > maxId) {
      maxId = eventId;
    }
  }
  if (maxId > 0 && maxId < lastProcessedEventId) {
    // Event IDs can reset after wipe + sqlite_sequence reset.
    lastProcessedEventId = 0;
  }

  let changed = false;
  let sawNewEvent = false;
  for (const event of events) {
    const eventId = Number(event?.id);
    if (!Number.isInteger(eventId) || eventId <= lastProcessedEventId) {
      continue;
    }
    sawNewEvent = true;
    lastProcessedEventId = eventId;

    const pageId = Number(event?.page_id);
    if (!Number.isInteger(pageId) || pageId <= 0) {
      continue;
    }
    const nextStatus = inferPageStatusFromPipelineEvent(event);
    if (!nextStatus) {
      continue;
    }
    if (applyPageStatusUpdate(pageId, nextStatus)) {
      changed = true;
    }
  }
  if (changed) {
    if (pagesSortState.columnKey === "status") {
      renderPages(currentPages);
    }
    updatePagesPaginationControls();
  }
  return { changed, sawNewEvent };
}

async function reloadDashboard() {
  const [duplicatesPayload, activityPayload, runtimeOptionsPayload] = await Promise.all([
    fetchJson("/api/duplicates"),
    fetchJson("/api/pipeline/activity"),
    fetchJson("/api/runtime-options"),
  ]);
  await Promise.all([
    loadCurrentPagesSlice(),
    refreshReviewActionState(),
    refreshPagesSummary(),
  ]);
  renderDuplicates(duplicatesPayload.duplicates);
  renderActivity(activityPayload);
  applyRuntimeOptions(runtimeOptionsPayload);
  syncLastProcessedEventId(activityPayload.recent_events);
}

async function refreshDashboardFromStream() {
  if (streamRefreshInFlight) {
    return;
  }
  streamRefreshInFlight = true;
  try {
    await Promise.all([
      loadCurrentPagesSlice(),
      refreshReviewActionState(),
      refreshPagesSummary(),
    ]);
  } catch (error) {
    console.error(`Failed to refresh dashboard from stream: ${error.message}`);
  } finally {
    streamRefreshInFlight = false;
  }
}

function scheduleDashboardRefreshFromStream() {
  if (streamRefreshTimer !== null) {
    window.clearTimeout(streamRefreshTimer);
  }
  streamRefreshTimer = window.setTimeout(() => {
    streamRefreshTimer = null;
    refreshDashboardFromStream().catch((error) => {
      console.error(`Stream refresh failed: ${error.message}`);
    });
  }, 300);
}

function closeActivityStream() {
  if (activityStream) {
    activityStream.close();
    activityStream = null;
  }
  if (streamRefreshTimer !== null) {
    window.clearTimeout(streamRefreshTimer);
    streamRefreshTimer = null;
  }
}

function scheduleActivityReconnect() {
  if (streamReconnectTimer !== null) {
    return;
  }
  streamReconnectTimer = window.setTimeout(() => {
    streamReconnectTimer = null;
    startActivityStream();
  }, 4000);
}

function startActivityStream() {
  closeActivityStream();

  if (!("EventSource" in window)) {
    return;
  }

  activityStream = new EventSource("/api/pipeline/activity/stream?limit=30");
  activityStream.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      renderActivity(payload);
      const statusUpdate = applyStatusUpdatesFromEvents(payload.recent_events);
      if (statusUpdate.sawNewEvent) {
        scheduleDashboardRefreshFromStream();
      }
    } catch {
      // Ignore malformed events.
    }
  };
  activityStream.onerror = () => {
    closeActivityStream();
    scheduleActivityReconnect();
  };
}

async function runScan() {
  scanBtn.disabled = true;
  reviewLayoutsBtn.disabled = true;
  reviewOcrBtn.disabled = true;
  exportFinalBtn.disabled = true;
  wipeBtn.disabled = true;
  try {
    await fetchJson("/api/discovery/scan", { method: "POST" });
    await reloadDashboard();
  } catch (error) {
    console.error(`Scan failed: ${error.message}`);
  } finally {
    scanBtn.disabled = false;
    wipeBtn.disabled = false;
  }
}

function openWipeModal() {
  wipeModal.hidden = false;
  wipeConfirmInput.value = "";
  wipeConfirmBtn.disabled = true;
  wipeConfirmInput.focus();
}

function closeWipeModal() {
  wipeModal.hidden = true;
  wipeConfirmInput.value = "";
  wipeConfirmBtn.disabled = true;
}

function openRemoveModal(pageId) {
  const page = currentPages.find((row) => Number(row.id) === Number(pageId));
  if (!page) {
    return;
  }
  pendingRemovePageId = Number(page.id);
  removeModalRelPath.textContent = page.rel_path || "—";
  removeModal.hidden = false;
}

function closeRemoveModal() {
  removeModal.hidden = true;
  pendingRemovePageId = null;
  removeModalRelPath.textContent = "—";
}

async function runRemovePage() {
  const pageId = Number(pendingRemovePageId);
  if (!Number.isInteger(pageId) || pageId <= 0) {
    return;
  }
  closeRemoveModal();
  scanBtn.disabled = true;
  reviewLayoutsBtn.disabled = true;
  reviewOcrBtn.disabled = true;
  exportFinalBtn.disabled = true;
  wipeBtn.disabled = true;
  try {
    await fetchJson(`/api/pages/${pageId}`, { method: "DELETE" });
    await reloadDashboard();
  } catch (error) {
    console.error(`Remove failed: ${error.message}`);
  } finally {
    scanBtn.disabled = false;
    wipeBtn.disabled = false;
  }
}

async function runWipe() {
  closeWipeModal();
  scanBtn.disabled = true;
  reviewLayoutsBtn.disabled = true;
  reviewOcrBtn.disabled = true;
  exportFinalBtn.disabled = true;
  wipeBtn.disabled = true;

  try {
    await fetchJson("/api/state/wipe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true, rescan: true }),
    });
    await reloadDashboard();
  } catch (error) {
    console.error(`Wipe failed: ${error.message}`);
  } finally {
    scanBtn.disabled = false;
    wipeBtn.disabled = false;
  }
}

async function runFinalExport() {
  scanBtn.disabled = true;
  reviewLayoutsBtn.disabled = true;
  reviewOcrBtn.disabled = true;
  exportFinalBtn.disabled = true;
  wipeBtn.disabled = true;
  try {
    await fetchJson("/api/final/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
    await reloadDashboard();
  } catch (error) {
    console.error(`Export failed: ${error.message}`);
  } finally {
    scanBtn.disabled = false;
    wipeBtn.disabled = false;
    updatePagesPaginationControls();
  }
}

function bindRuntimeOptionToggle(toggleElement, optionKey) {
  toggleElement.addEventListener("change", async () => {
    const previousValue = Boolean(runtimeOptions[optionKey]);
    toggleElement.disabled = true;
    try {
      const payload = await fetchJson("/api/runtime-options", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          [optionKey]: toggleElement.checked,
        }),
      });
      applyRuntimeOptions(payload);
    } catch (error) {
      console.error(`Failed to update runtime options: ${error.message}`);
      toggleElement.checked = previousValue;
      applyRuntimeOptions(runtimeOptions);
    }
  });
}

pipelineToggle.addEventListener("click", () => {
  setPipelinePanelExpanded(!pipelinePanelExpanded);
});
scanBtn.addEventListener("click", runScan);
reviewLayoutsBtn.addEventListener("click", () => {
  openNextReviewActionPage("layout");
});
reviewOcrBtn.addEventListener("click", () => {
  openNextReviewActionPage("ocr");
});
for (const sortBtn of pagesSortButtons) {
  sortBtn.addEventListener("click", () => {
    const columnKey = String(sortBtn.dataset.pagesSortKey || "");
    const nextState = nextDashboardSortState(pagesSortState, columnKey);
    if (
      nextState.columnKey === pagesSortState.columnKey &&
      nextState.direction === pagesSortState.direction
    ) {
      return;
    }
    pagesSortState = nextState;
    persistPagesSortState();
    updatePagesSortControls();
    resetPagesPagination();
    loadCurrentPagesSlice().catch((error) => {
      console.error(`Failed to load sorted pages: ${error.message}`);
    });
  });
}
pagesPrevBtn.addEventListener("click", () => {
  if (pagesLoading || pagesCursorIndex <= 0) {
    return;
  }
  pagesCursorIndex -= 1;
  loadCurrentPagesSlice().catch((error) => {
    console.error(`Failed to load previous page slice: ${error.message}`);
  });
});
pagesNextBtn.addEventListener("click", () => {
  if (pagesLoading || !pagesHasMore || !pagesNextCursor) {
    return;
  }
  const nextIndex = pagesCursorIndex + 1;
  pagesCursorHistory = pagesCursorHistory.slice(0, nextIndex);
  pagesCursorHistory[nextIndex] = String(pagesNextCursor);
  pagesCursorIndex = nextIndex;
  loadCurrentPagesSlice().catch((error) => {
    console.error(`Failed to load next page slice: ${error.message}`);
  });
});
pagesSizeSelect.addEventListener("change", () => {
  const requestedSize = Number(pagesSizeSelect.value);
  if (![25, 50, 100].includes(requestedSize)) {
    pagesSizeSelect.value = String(pagesPageSize);
    return;
  }
  if (requestedSize === pagesPageSize) {
    return;
  }
  pagesPageSize = requestedSize;
  persistPagesPageSize();
  resetPagesPagination();
  loadCurrentPagesSlice().catch((error) => {
    console.error(`Failed to load paginated pages: ${error.message}`);
  });
});
pagesBody.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const openBtn = target.closest(".row-open-btn");
  if (!(openBtn instanceof HTMLButtonElement) || openBtn.disabled) {
    return;
  }
  const row = openBtn.closest("tr[data-page-id]");
  if (!row) {
    return;
  }
  const pageId = Number(row.dataset.pageId);
  if (!Number.isInteger(pageId) || pageId <= 0) {
    return;
  }
  const reviewTarget = openBtn.dataset.target;
  if (reviewTarget === "layout") {
    window.location.href = `/static/layouts.html?page_id=${pageId}`;
    return;
  }
  if (reviewTarget === "ocr") {
    window.location.href = `/static/ocr_review.html?page_id=${pageId}`;
    return;
  }
  if (reviewTarget === "remove") {
    openRemoveModal(pageId);
  }
});
bindRuntimeOptionToggle(autoDetectLayoutsToggle, "auto_detect_layouts_after_discovery");
bindRuntimeOptionToggle(autoExtractTextToggle, "auto_extract_text_after_layout_review");
exportFinalBtn.addEventListener("click", runFinalExport);
wipeBtn.addEventListener("click", openWipeModal);
wipeCancelBtn.addEventListener("click", closeWipeModal);
wipeConfirmBtn.addEventListener("click", runWipe);
removeCancelBtn.addEventListener("click", closeRemoveModal);
removeConfirmBtn.addEventListener("click", runRemovePage);

wipeConfirmInput.addEventListener("input", () => {
  wipeConfirmBtn.disabled = wipeConfirmInput.value.trim().toLowerCase() !== "wipe";
});

wipeModal.addEventListener("click", (event) => {
  if (event.target === wipeModal) {
    closeWipeModal();
  }
});
removeModal.addEventListener("click", (event) => {
  if (event.target === removeModal) {
    closeRemoveModal();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }
  if (!wipeModal.hidden) {
    closeWipeModal();
    return;
  }
  if (!removeModal.hidden) {
    closeRemoveModal();
  }
});

loadPagesSortState();
loadPagesPageSize();
pagesSizeSelect.value = String(pagesPageSize);
resetPagesPagination();
updatePagesSortControls();
updatePagesPaginationControls();
setPipelinePanelExpanded(readStorageBool(STORAGE_KEYS.pipelinePanelExpanded, false));
reloadDashboard().catch((error) => {
  console.error(`Failed to load dashboard: ${error.message}`);
});
startActivityStream();
