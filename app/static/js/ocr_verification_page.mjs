import { fetchJson } from "./api_client.mjs";
import {
  compactDiff,
  evidenceLabel,
  verificationControlState,
} from "./ocr_verification_utils.mjs";

const runBtn = document.getElementById("run-btn");
const recalculateBtn = document.getElementById("recalculate-btn");
const filterSelect = document.getElementById("filter");
const progress = document.getElementById("progress");
const counters = document.getElementById("counters");
const findingsRoot = document.getElementById("findings");
const empty = document.getElementById("empty");
const pagePrev = document.getElementById("page-prev");
const pageNext = document.getElementById("page-next");
const pageLabel = document.getElementById("page-label");

let statusPayload = { is_running: false, run: null, counters: {} };
let findings = [];
const pendingActions = new Set();
let recalculateInFlight = false;
let statusPollInFlight = false;
const pageSize = 25;
let pageOffset = 0;
let pageTotal = 0;

function setBusy(button, busy) {
  button.disabled = busy;
  const oldDot = button.querySelector(".busy-dot");
  if (oldDot) oldDot.remove();
  if (busy) {
    const dot = document.createElement("span");
    dot.className = "busy-dot";
    dot.setAttribute("aria-hidden", "true");
    button.prepend(dot);
  }
}

function renderStatus() {
  const run = statusPayload.run;
  const actionInFlight = pendingActions.has("stop")
    ? "stop"
    : pendingActions.has("start") ? "start" : "";
  const controls = verificationControlState({
    isRunning: statusPayload.is_running,
    stopRequested: run?.stop_requested,
    runStatus: String(run?.status || ""),
    actionInFlight,
    recalculateBusy: recalculateInFlight || Boolean(statusPayload.recalculation_running),
  });
  runBtn.textContent = controls.actionLabel;
  runBtn.classList.toggle("danger", controls.actionDanger);
  runBtn.classList.toggle(
    "is-busy",
    actionInFlight === "stop" || (actionInFlight === "start" && !statusPayload.is_running),
  );
  runBtn.disabled = controls.actionDisabled;
  runBtn.title = controls.actionTitle;
  recalculateBtn.classList.toggle(
    "is-busy",
    recalculateInFlight || Boolean(statusPayload.recalculation_running),
  );
  recalculateBtn.disabled = controls.recalculateDisabled;
  recalculateBtn.title = controls.recalculateTitle;
  const completed = Number(run?.completed_tasks || 0);
  const total = Number(run?.total_tasks || 0);
  progress.textContent = run ? `${String(run.status).replaceAll("_", " ")} · ${completed}/${total}` : "Idle";
  counters.replaceChildren();
  for (const [name, count] of Object.entries(statusPayload.counters || {})) {
    const span = document.createElement("span");
    span.className = "counter";
    span.textContent = `${name.replaceAll("_", " ")}: ${count}`;
    counters.appendChild(span);
  }
}

function badge(text, className = "") {
  const span = document.createElement("span");
  span.className = `badge ${className}`.trim();
  span.textContent = text;
  return span;
}

function appendDiff(pre, baseline, content) {
  const diff = compactDiff(baseline, content);
  pre.append(document.createTextNode(diff.prefix));
  if (diff.removed) {
    const removed = document.createElement("del");
    removed.textContent = diff.removed;
    pre.append(removed);
  }
  if (diff.changed) {
    const mark = document.createElement("mark");
    mark.textContent = diff.changed;
    pre.append(mark);
  }
  pre.append(document.createTextNode(diff.suffix));
}

function renderFinding(finding) {
  const article = document.createElement("article");
  article.className = "finding";
  const head = document.createElement("div");
  head.className = "finding-head";
  const title = document.createElement("strong");
  title.textContent = `${finding.rel_path} · region ${finding.reading_order} · ${finding.class_name}`;
  head.append(title);
  const stateClass = String(finding.state).startsWith("agreed")
    ? "agreed"
    : String(finding.state).includes("disagreement")
      ? "disagreement"
      : String(finding.state) === "manual_check" ? "manual" : "reduced";
  head.append(badge(evidenceLabel(finding), stateClass));
  if (finding.resolved) head.append(badge("Resolved", "agreed"));
  article.append(head);

  const grid = document.createElement("div");
  grid.className = "finding-grid";
  const sourcePanel = document.createElement("div");
  sourcePanel.className = "source-panel";
  const image = new Image();
  image.loading = "lazy";
  image.alt = "Source region crop";
  image.src = `/api/ocr-verification/layouts/${finding.layout_id}/crop?v=${encodeURIComponent(finding.crop_version || finding.updated_at || "")}`;
  sourcePanel.append(image);
  const sourceLink = document.createElement("a");
  sourceLink.href = `/api/pages/${encodeURIComponent(finding.page_id)}/image`;
  sourceLink.target = "_blank";
  sourceLink.rel = "noopener";
  sourceLink.textContent = "Open full source image";
  sourcePanel.append(sourceLink);
  grid.append(sourcePanel);

  const editorPanel = document.createElement("div");
  const variants = document.createElement("div");
  variants.className = "variants";
  const draft = document.createElement("textarea");
  draft.className = "draft";
  draft.value = finding.baseline_content || "";
  let selectedTaskId = null;
  for (const group of finding.groups || []) {
    const variant = document.createElement("button");
    variant.type = "button";
    variant.className = "variant";
    const labels = document.createElement("span");
    labels.className = "variant-label";
    for (const source of group.sources || []) {
      if (source.kind === "baseline") {
        labels.append(badge(`Reviewed · source ${source.source_model}`, ""));
      } else {
        labels.append(badge(source.name, ""));
      }
    }
    const pre = document.createElement("pre");
    appendDiff(pre, finding.baseline_content || "", group.content || "");
    variant.append(labels, pre);
    variant.addEventListener("click", () => {
      variants.querySelectorAll(".variant").forEach((node) => node.classList.remove("selected"));
      variant.classList.add("selected");
      draft.value = group.content || "";
      const modelSource = (group.sources || []).find((source) => source.kind === "model");
      selectedTaskId = modelSource?.task_id || null;
    });
    variants.append(variant);
  }
  editorPanel.append(variants);

  const errors = (finding.tasks || []).filter((task) => task.error_message);
  if (errors.length || Number(finding.missing_count || 0) > errors.length) {
    const errorList = document.createElement("div");
    errorList.className = "task-errors";
    const messages = errors.map((task) => `${task.model_name}: ${task.status} — ${task.error_message}`);
    const unseen = Math.max(0, Number(finding.missing_count || 0) - errors.length);
    if (unseen) messages.push(`${unseen} validator model slot(s) are not configured.`);
    errorList.textContent = messages.join(" · ");
    editorPanel.append(errorList);
  }
  editorPanel.append(draft);
  const actions = document.createElement("div");
  actions.className = "actions";
  const keepBtn = document.createElement("button");
  keepBtn.type = "button";
  keepBtn.textContent = "Keep reviewed";
  const applyBtn = document.createElement("button");
  applyBtn.type = "button";
  applyBtn.className = "primary";
  applyBtn.textContent = "Apply draft";
  const recheckBtn = document.createElement("button");
  recheckBtn.type = "button";
  recheckBtn.textContent = "Recheck";
  const waiting = finding.state === "waiting";
  keepBtn.disabled = waiting;
  applyBtn.disabled = waiting;
  recheckBtn.disabled = Boolean(statusPayload.is_running);
  async function resolve(action) {
    setBusy(action === "keep" ? keepBtn : applyBtn, true);
    try {
      await fetchJson(`/api/ocr-verification/layouts/${finding.layout_id}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          content: action === "apply" ? draft.value : null,
          source_task_id: action === "apply" ? selectedTaskId : null,
        }),
      });
      await refreshAll();
    } catch (error) {
      window.alert(error.message);
    } finally {
      setBusy(action === "keep" ? keepBtn : applyBtn, false);
    }
  }
  keepBtn.addEventListener("click", () => resolve("keep"));
  applyBtn.addEventListener("click", () => resolve("apply"));
  recheckBtn.addEventListener("click", async () => {
    setBusy(recheckBtn, true);
    try {
      await fetchJson(`/api/ocr-verification/layouts/${finding.layout_id}/recheck`, { method: "POST" });
      await fetchJson("/api/ocr-verification/run", { method: "POST" });
      await refreshAll();
    } catch (error) {
      window.alert(error.message);
    } finally {
      setBusy(recheckBtn, false);
    }
  });
  actions.append(keepBtn, applyBtn, recheckBtn);
  editorPanel.append(actions);
  grid.append(editorPanel);
  article.append(grid);
  return article;
}

function renderFindingSummary(finding) {
  const article = document.createElement("article");
  article.className = "finding finding-summary";
  const head = document.createElement("div");
  head.className = "finding-head";
  const title = document.createElement("strong");
  title.textContent = `${finding.rel_path} · region ${finding.reading_order} · ${finding.class_name}`;
  head.append(title);
  const stateClass = String(finding.state).startsWith("agreed")
    ? "agreed"
    : String(finding.state).includes("disagreement")
      ? "disagreement"
      : String(finding.state) === "manual_check" ? "manual" : "reduced";
  head.append(badge(evidenceLabel(finding), stateClass));
  if (finding.resolved) head.append(badge("Resolved", "agreed"));
  const openButton = document.createElement("button");
  openButton.type = "button";
  openButton.className = "secondary";
  openButton.textContent = "Open comparison";
  openButton.addEventListener("click", async () => {
    setBusy(openButton, true);
    try {
      const detail = await fetchJson(`/api/ocr-verification/findings/${finding.layout_id}`);
      detail.crop_version = finding.crop_version;
      article.replaceWith(renderFinding(detail));
    } catch (error) {
      window.alert(error.message);
      setBusy(openButton, false);
    }
  });
  head.append(openButton);
  article.append(head);
  return article;
}

function renderFindings() {
  findingsRoot.replaceChildren();
  empty.hidden = findings.length > 0;
  for (const finding of findings) findingsRoot.append(renderFindingSummary(finding));
  const pageNumber = pageTotal ? Math.floor(pageOffset / pageSize) + 1 : 0;
  const pageCount = pageTotal ? Math.ceil(pageTotal / pageSize) : 0;
  pageLabel.textContent = `${pageNumber} / ${pageCount} · ${pageTotal} findings`;
  pagePrev.disabled = pageOffset <= 0;
  pageNext.disabled = pageOffset + pageSize >= pageTotal;
}

async function refreshStatus() {
  statusPayload = await fetchJson("/api/ocr-verification/status");
  renderStatus();
}

async function refreshFindings() {
  const nextFindings = await fetchJson(
    `/api/ocr-verification/findings?category=${encodeURIComponent(filterSelect.value)}&limit=25&offset=${pageOffset}`,
  );
  findings = Array.isArray(nextFindings.findings) ? nextFindings.findings : [];
  pageTotal = Number(nextFindings.total || 0);
  if (pageOffset >= pageTotal && pageOffset > 0) {
    pageOffset = Math.max(0, Math.floor(Math.max(0, pageTotal - 1) / pageSize) * pageSize);
    return refreshFindings();
  }
  renderFindings();
}

async function refreshAll() {
  await Promise.all([
    refreshStatus(),
    refreshFindings(),
  ]);
}

async function pollStatus() {
  if (statusPollInFlight) return;
  statusPollInFlight = true;
  const wasRunning = Boolean(statusPayload.is_running);
  const wasRecalculating = Boolean(statusPayload.recalculation_running);
  try {
    await refreshStatus();
    if (
      (wasRunning && !statusPayload.is_running)
      || (wasRecalculating && !statusPayload.recalculation_running)
    ) await refreshFindings();
  } finally {
    statusPollInFlight = false;
  }
}

runBtn.addEventListener("click", async () => {
  const endpoint = statusPayload.is_running ? "stop" : "run";
  if (recalculateInFlight || pendingActions.has("stop")) return;
  if (endpoint === "run" && pendingActions.has("start")) return;
  pendingActions.add(endpoint);
  renderStatus();
  try {
    await fetchJson(`/api/ocr-verification/${endpoint}`, { method: "POST" });
    await refreshAll();
  } catch (error) {
    window.alert(error.message);
  } finally {
    pendingActions.delete(endpoint);
    renderStatus();
  }
});

recalculateBtn.addEventListener("click", async () => {
  if (
    pendingActions.size
    || recalculateInFlight
    || statusPayload.recalculation_running
    || statusPayload.is_running
  ) return;
  recalculateInFlight = true;
  renderStatus();
  try {
    await fetchJson("/api/ocr-verification/recalculate", { method: "POST" });
    await refreshStatus();
    if (!statusPayload.recalculation_running) await refreshFindings();
  } catch (error) {
    window.alert(error.message);
  } finally {
    recalculateInFlight = false;
    renderStatus();
  }
});

filterSelect.addEventListener("change", () => {
  pageOffset = 0;
  refreshFindings().catch((error) => window.alert(error.message));
});
pagePrev.addEventListener("click", () => {
  pageOffset = Math.max(0, pageOffset - pageSize);
  refreshFindings().catch((error) => window.alert(error.message));
});
pageNext.addEventListener("click", () => {
  if (pageOffset + pageSize >= pageTotal) return;
  pageOffset += pageSize;
  refreshFindings().catch((error) => window.alert(error.message));
});

refreshAll().catch((error) => {
  progress.textContent = `Unable to load verification: ${error.message}`;
});
setInterval(() => {
  pollStatus().catch((error) => console.error(`Verification status refresh failed: ${error.message}`));
}, 2500);
