import { fetchJson } from "./api_client.mjs";
import { PIPELINE_STAGE } from "./pipeline_event_constants.mjs";

const benchmarkToggleBtn = document.getElementById("benchmark-toggle-btn");
const forceRerunToggle = document.getElementById("benchmark-force-rerun-toggle");
const runStatusEl = document.getElementById("benchmark-run-status");
const processedTasksEl = document.getElementById("benchmark-processed-tasks");
const skippedTasksEl = document.getElementById("benchmark-skipped-tasks");
const currentConfigEl = document.getElementById("benchmark-current-config");
const bestConfigEl = document.getElementById("benchmark-best-config");

const leaderboardTabBtn = document.getElementById("benchmark-view-leaderboard-btn");
const explorerTabBtn = document.getElementById("benchmark-view-explorer-btn");
const leaderboardPanel = document.getElementById("benchmark-leaderboard-panel");
const explorerPanel = document.getElementById("benchmark-explorer-panel");

const gridBody = document.getElementById("benchmark-grid-body");

const explorerModeSelect = document.getElementById("benchmark-explorer-mode");
const explorerModelSelect = document.getElementById("benchmark-explorer-model");
const explorerImgszSelect = document.getElementById("benchmark-explorer-imgsz");
const explorerConfSelect = document.getElementById("benchmark-explorer-conf");
const explorerIouSelect = document.getElementById("benchmark-explorer-iou");
const explorerCaption = document.getElementById("benchmark-explorer-caption");
const heatmapHead = document.getElementById("benchmark-heatmap-head");
const heatmapBody = document.getElementById("benchmark-heatmap-body");

const state = {
  status: null,
  gridRows: [],
  isRunning: false,
  currentConfig: null,
  bestConfig: null,
  busyAction: false,
  lastBenchmarkEventId: 0,
  refreshInFlight: false,
  refreshTimer: null,
  stream: null,
  activeView: "leaderboard",
  explorerMode: "conf_iou",
  selectedModel: "",
  selectedImgsz: "",
  selectedConf: "",
  selectedIou: "",
};

function toFiniteNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toNumberKey(value) {
  const parsed = toFiniteNumber(value);
  return parsed === null ? "" : parsed.toFixed(6);
}

function fromNumberKey(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function configKey(config) {
  if (!config || typeof config !== "object") {
    return "";
  }
  return [
    String(config.model_checkpoint || ""),
    String(Number(config.image_size || 0)),
    toNumberKey(config.confidence_threshold || 0),
    toNumberKey(config.iou_threshold || 0),
  ].join("|");
}

function configLabel(config) {
  if (!config || typeof config !== "object") {
    return "-";
  }
  const model = String(config.model_checkpoint || "-");
  const imageSize = Number(config.image_size || 0);
  const conf = Number(config.confidence_threshold || 0);
  const iou = Number(config.iou_threshold || 0);
  return `${model} imgsz=${imageSize} conf=${conf.toFixed(2)} iou=${iou.toFixed(2)}`;
}

function setActionBusy(busy) {
  state.busyAction = Boolean(busy);
  benchmarkToggleBtn.classList.toggle("is-busy", state.busyAction);
  renderActionButton();
}

function renderActionButton() {
  if (state.isRunning) {
    benchmarkToggleBtn.textContent = "Stop benchmark";
    benchmarkToggleBtn.classList.add("danger");
    benchmarkToggleBtn.disabled = state.busyAction;
    benchmarkToggleBtn.title = "Stop the running layout benchmark.";
    return;
  }
  benchmarkToggleBtn.textContent = "Start benchmark";
  benchmarkToggleBtn.classList.remove("danger");
  benchmarkToggleBtn.disabled = state.busyAction;
  benchmarkToggleBtn.title = "Start layout benchmark.";
}

function renderSummary() {
  const run = state.status?.run && typeof state.status.run === "object" ? state.status.run : null;
  runStatusEl.textContent = run ? String(run.status || "-").toUpperCase() : "-";
  if (run) {
    const processed = Number.isInteger(run.processed_tasks) ? run.processed_tasks : 0;
    const total = Number.isInteger(run.total_tasks) ? run.total_tasks : 0;
    processedTasksEl.textContent = `${processed}/${total}`;
    skippedTasksEl.textContent = String(Number.isInteger(run.skipped_tasks) ? run.skipped_tasks : 0);
    currentConfigEl.textContent = configLabel(run.current_config);
  } else {
    processedTasksEl.textContent = "-";
    skippedTasksEl.textContent = "-";
    currentConfigEl.textContent = "-";
  }
  bestConfigEl.textContent = configLabel(state.bestConfig);
}

function rowsWithCurrentPlaceholder() {
  const rows = Array.isArray(state.gridRows)
    ? state.gridRows.map((row) => ({ ...row }))
    : [];
  const currentKey = configKey(state.currentConfig);
  if (
    state.isRunning &&
    currentKey &&
    !rows.some((row) => configKey(row) === currentKey)
  ) {
    rows.unshift({
      ...state.currentConfig,
      mean_score: null,
      page_count: null,
      _placeholder: true,
    });
  }
  return rows;
}

function renderLeaderboard() {
  gridBody.innerHTML = "";
  const currentKey = configKey(state.currentConfig);
  const bestKey = configKey(state.bestConfig);
  const rows = rowsWithCurrentPlaceholder();

  if (rows.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td class="empty" colspan="7">No benchmark results yet.</td>';
    gridBody.appendChild(tr);
    return;
  }

  const sortedRows = [...rows].sort((a, b) => {
    const aRunning = state.isRunning && configKey(a) === currentKey;
    const bRunning = state.isRunning && configKey(b) === currentKey;
    if (aRunning !== bRunning) {
      return aRunning ? -1 : 1;
    }
    const aScore = toFiniteNumber(a.mean_score);
    const bScore = toFiniteNumber(b.mean_score);
    if (aScore !== null && bScore !== null && aScore !== bScore) {
      return bScore - aScore;
    }
    if (aScore === null && bScore !== null) {
      return 1;
    }
    if (aScore !== null && bScore === null) {
      return -1;
    }
    const aPages = Number(a.page_count || 0);
    const bPages = Number(b.page_count || 0);
    if (aPages !== bPages) {
      return bPages - aPages;
    }
    return String(a.model_checkpoint || "").localeCompare(String(b.model_checkpoint || ""));
  });

  for (const row of sortedRows) {
    const rowKey = configKey(row);
    const tr = document.createElement("tr");
    if (rowKey === currentKey && state.isRunning) {
      tr.classList.add("current-row");
    }
    if (rowKey === bestKey) {
      tr.classList.add("best-row");
    }

    const stateCell = document.createElement("td");
    const tags = [];
    if (rowKey === currentKey && state.isRunning) {
      tags.push('<span class="row-state running">RUNNING</span>');
    }
    if (rowKey === bestKey) {
      tags.push('<span class="row-state best">BEST</span>');
    }
    stateCell.innerHTML = tags.join(" ");

    const meanScore =
      typeof row.mean_score === "number" && Number.isFinite(row.mean_score)
        ? row.mean_score.toFixed(4)
        : "-";
    const pageCount =
      Number.isInteger(row.page_count) && row.page_count >= 0
        ? String(row.page_count)
        : "-";

    tr.appendChild(stateCell);
    tr.innerHTML += `
      <td>${String(row.model_checkpoint || "-")}</td>
      <td>${Number(row.image_size || 0) || "-"}</td>
      <td>${Number(row.confidence_threshold || 0).toFixed(2)}</td>
      <td>${Number(row.iou_threshold || 0).toFixed(2)}</td>
      <td>${meanScore}</td>
      <td>${pageCount}</td>
    `;
    gridBody.appendChild(tr);
  }
}

function setActiveView(view) {
  state.activeView = view === "explorer" ? "explorer" : "leaderboard";
  const leaderboardActive = state.activeView === "leaderboard";
  leaderboardTabBtn.classList.toggle("active", leaderboardActive);
  leaderboardTabBtn.setAttribute("aria-selected", leaderboardActive ? "true" : "false");
  explorerTabBtn.classList.toggle("active", !leaderboardActive);
  explorerTabBtn.setAttribute("aria-selected", leaderboardActive ? "false" : "true");
  leaderboardPanel.hidden = !leaderboardActive;
  explorerPanel.hidden = leaderboardActive;
}

function setSelectOptions(selectEl, options, selectedValue) {
  const normalizedOptions = Array.isArray(options) ? options : [];
  const values = normalizedOptions.map((option) => String(option.value));
  const targetValue = values.includes(String(selectedValue))
    ? String(selectedValue)
    : values.length > 0
      ? values[0]
      : "";

  selectEl.innerHTML = "";
  for (const option of normalizedOptions) {
    const optionEl = document.createElement("option");
    optionEl.value = String(option.value);
    optionEl.textContent = String(option.label);
    selectEl.appendChild(optionEl);
  }
  selectEl.disabled = values.length === 0;
  if (targetValue) {
    selectEl.value = targetValue;
  }
  return targetValue;
}

function collectDimensionValues(rows) {
  const models = new Set();
  const imgsz = new Set();
  const conf = new Set();
  const iou = new Set();
  for (const row of rows) {
    if (row.model_checkpoint) {
      models.add(String(row.model_checkpoint));
    }
    const imageSize = Number(row.image_size);
    if (Number.isFinite(imageSize)) {
      imgsz.add(String(Math.round(imageSize)));
    }
    const confKey = toNumberKey(row.confidence_threshold);
    if (confKey) {
      conf.add(confKey);
    }
    const iouKey = toNumberKey(row.iou_threshold);
    if (iouKey) {
      iou.add(iouKey);
    }
  }

  return {
    models: Array.from(models).sort((a, b) => a.localeCompare(b)),
    imgsz: Array.from(imgsz).sort((a, b) => Number(a) - Number(b)),
    conf: Array.from(conf).sort((a, b) => Number(a) - Number(b)),
    iou: Array.from(iou).sort((a, b) => Number(a) - Number(b)),
  };
}

function ensureExplorerControls(rows) {
  const dimensions = collectDimensionValues(rows);

  state.selectedModel = setSelectOptions(
    explorerModelSelect,
    dimensions.models.map((value) => ({ value, label: value })),
    state.selectedModel || state.currentConfig?.model_checkpoint || "",
  );

  state.selectedImgsz = setSelectOptions(
    explorerImgszSelect,
    dimensions.imgsz.map((value) => ({ value, label: value })),
    state.selectedImgsz || String(state.currentConfig?.image_size || ""),
  );

  state.selectedConf = setSelectOptions(
    explorerConfSelect,
    dimensions.conf.map((value) => ({
      value,
      label: Number(value).toFixed(2),
    })),
    state.selectedConf || toNumberKey(state.currentConfig?.confidence_threshold || ""),
  );

  state.selectedIou = setSelectOptions(
    explorerIouSelect,
    dimensions.iou.map((value) => ({
      value,
      label: Number(value).toFixed(2),
    })),
    state.selectedIou || toNumberKey(state.currentConfig?.iou_threshold || ""),
  );
}

function scoreColor(score, minScore, maxScore) {
  if (!Number.isFinite(score)) {
    return "";
  }
  const range = maxScore - minScore;
  const t = range > 0 ? (score - minScore) / range : 1;
  const clamped = Math.max(0, Math.min(1, t));
  const lightness = 93 - clamped * 32;
  return `hsl(166, 45%, ${lightness}%)`;
}

function renderHeatmap(mode, rows) {
  const currentKey = configKey(state.currentConfig);
  const bestKey = configKey(state.bestConfig);

  let xValues = [];
  let yValues = [];
  let cornerLabel = "";
  let matcher = () => null;

  if (mode === "conf_iou") {
    const conf = Array.from(new Set(rows.map((row) => toNumberKey(row.confidence_threshold)).filter(Boolean)))
      .sort((a, b) => Number(a) - Number(b));
    const iou = Array.from(new Set(rows.map((row) => toNumberKey(row.iou_threshold)).filter(Boolean)))
      .sort((a, b) => Number(a) - Number(b));
    yValues = conf.map((value) => ({ key: value, label: Number(value).toFixed(2) }));
    xValues = iou.map((value) => ({ key: value, label: Number(value).toFixed(2) }));
    cornerLabel = "Conf \\ IoU";
    matcher = (rowKey, colKey) =>
      rows.find(
        (row) =>
          String(row.model_checkpoint) === state.selectedModel &&
          String(Math.round(Number(row.image_size || 0))) === state.selectedImgsz &&
          toNumberKey(row.confidence_threshold) === rowKey &&
          toNumberKey(row.iou_threshold) === colKey,
      ) || null;

    explorerCaption.textContent = `Axes: Conf (rows) x IoU (columns). Fixed model=${state.selectedModel || "-"}, imgsz=${state.selectedImgsz || "-"}.`;
    explorerModelSelect.disabled = false;
    explorerImgszSelect.disabled = false;
    explorerConfSelect.disabled = true;
    explorerIouSelect.disabled = true;
  } else {
    const models = Array.from(new Set(rows.map((row) => String(row.model_checkpoint || "")).filter(Boolean)))
      .sort((a, b) => a.localeCompare(b));
    const imgsz = Array.from(new Set(rows.map((row) => String(Math.round(Number(row.image_size || 0)))).filter(Boolean)))
      .sort((a, b) => Number(a) - Number(b));
    yValues = models.map((value) => ({ key: value, label: value }));
    xValues = imgsz.map((value) => ({ key: value, label: value }));
    cornerLabel = "Model \\ Img size";
    matcher = (rowKey, colKey) =>
      rows.find(
        (row) =>
          toNumberKey(row.confidence_threshold) === state.selectedConf &&
          toNumberKey(row.iou_threshold) === state.selectedIou &&
          String(row.model_checkpoint) === rowKey &&
          String(Math.round(Number(row.image_size || 0))) === colKey,
      ) || null;

    explorerCaption.textContent = `Axes: Model (rows) x image size (columns). Fixed conf=${Number(state.selectedConf || 0).toFixed(2)}, iou=${Number(state.selectedIou || 0).toFixed(2)}.`;
    explorerModelSelect.disabled = true;
    explorerImgszSelect.disabled = true;
    explorerConfSelect.disabled = false;
    explorerIouSelect.disabled = false;
  }

  const cellScores = [];
  for (const rowValue of yValues) {
    for (const colValue of xValues) {
      const item = matcher(rowValue.key, colValue.key);
      const score = toFiniteNumber(item?.mean_score);
      if (score !== null) {
        cellScores.push(score);
      }
    }
  }
  const minScore = cellScores.length > 0 ? Math.min(...cellScores) : 0;
  const maxScore = cellScores.length > 0 ? Math.max(...cellScores) : 1;

  heatmapHead.innerHTML = "";
  const headRow = document.createElement("tr");
  const corner = document.createElement("th");
  corner.textContent = cornerLabel;
  headRow.appendChild(corner);
  for (const colValue of xValues) {
    const th = document.createElement("th");
    th.textContent = colValue.label;
    headRow.appendChild(th);
  }
  heatmapHead.appendChild(headRow);

  heatmapBody.innerHTML = "";
  if (xValues.length === 0 || yValues.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td class="empty" colspan="2">No matrix data yet.</td>';
    heatmapBody.appendChild(tr);
    return;
  }

  for (const rowValue of yValues) {
    const tr = document.createElement("tr");
    const yLabel = document.createElement("th");
    yLabel.textContent = rowValue.label;
    tr.appendChild(yLabel);

    for (const colValue of xValues) {
      const item = matcher(rowValue.key, colValue.key);
      const td = document.createElement("td");
      td.className = "heatmap-cell";
      if (!item) {
        td.classList.add("is-empty");
        td.textContent = "-";
        tr.appendChild(td);
        continue;
      }

      const rowConfigKey = configKey(item);
      const score = toFiniteNumber(item.mean_score);
      if (score !== null) {
        td.style.backgroundColor = scoreColor(score, minScore, maxScore);
      } else {
        td.classList.add("is-empty");
      }

      const scoreLine = document.createElement("span");
      scoreLine.className = "heatmap-score";
      scoreLine.textContent = score === null ? "-" : score.toFixed(4);
      td.appendChild(scoreLine);

      const pagesLine = document.createElement("span");
      pagesLine.className = "heatmap-pages";
      const pages = Number.isInteger(item.page_count) ? item.page_count : null;
      pagesLine.textContent = pages === null ? "p:-" : `p:${pages}`;
      td.appendChild(pagesLine);

      const markers = document.createElement("span");
      markers.className = "heatmap-markers";
      if (state.isRunning && rowConfigKey === currentKey) {
        const marker = document.createElement("span");
        marker.className = "heatmap-marker running";
        marker.textContent = "RUNNING";
        markers.appendChild(marker);
      }
      if (rowConfigKey === bestKey) {
        const marker = document.createElement("span");
        marker.className = "heatmap-marker best";
        marker.textContent = "BEST";
        markers.appendChild(marker);
      }
      if (markers.childElementCount > 0) {
        td.appendChild(markers);
      }
      tr.appendChild(td);
    }
    heatmapBody.appendChild(tr);
  }
}

function renderExplorer() {
  const rows = rowsWithCurrentPlaceholder();
  ensureExplorerControls(rows);
  const mode = explorerModeSelect.value === "model_imgsz" ? "model_imgsz" : "conf_iou";
  state.explorerMode = mode;
  renderHeatmap(mode, rows);
}

function applyPayloads(statusPayload, gridPayload) {
  state.status = statusPayload && typeof statusPayload === "object" ? statusPayload : null;
  state.gridRows = Array.isArray(gridPayload?.rows) ? gridPayload.rows : [];
  state.isRunning = Boolean(statusPayload?.is_running);
  state.currentConfig = statusPayload?.run?.current_config || null;
  state.bestConfig = gridPayload?.best_config || statusPayload?.run?.best_config || null;

  renderActionButton();
  renderSummary();
  renderLeaderboard();
  renderExplorer();
}

async function refreshAll() {
  if (state.refreshInFlight) {
    return;
  }
  state.refreshInFlight = true;
  try {
    const [statusPayload, gridPayload] = await Promise.all([
      fetchJson("/api/layout-benchmark/status"),
      fetchJson("/api/layout-benchmark/grid"),
    ]);
    applyPayloads(statusPayload, gridPayload);
  } catch (error) {
    console.error(`Failed to refresh benchmark page: ${error.message}`);
  } finally {
    state.refreshInFlight = false;
  }
}

function maybeScheduleRefreshFromEvents(activityPayload) {
  const events = Array.isArray(activityPayload?.recent_events) ? activityPayload.recent_events : [];
  let maxBenchmarkEventId = state.lastBenchmarkEventId;
  for (const event of events) {
    if (String(event?.stage || "") !== PIPELINE_STAGE.LAYOUT_BENCHMARK) {
      continue;
    }
    const eventId = Number(event?.id);
    if (Number.isInteger(eventId) && eventId > maxBenchmarkEventId) {
      maxBenchmarkEventId = eventId;
    }
  }
  if (maxBenchmarkEventId <= state.lastBenchmarkEventId) {
    return;
  }
  state.lastBenchmarkEventId = maxBenchmarkEventId;
  if (state.refreshTimer !== null) {
    window.clearTimeout(state.refreshTimer);
  }
  state.refreshTimer = window.setTimeout(() => {
    state.refreshTimer = null;
    refreshAll().catch((error) => {
      console.error(`Benchmark refresh failed: ${error.message}`);
    });
  }, 200);
}

function closeStream() {
  if (state.stream) {
    state.stream.close();
    state.stream = null;
  }
}

function startStream() {
  closeStream();
  if (!("EventSource" in window)) {
    return;
  }
  state.stream = new EventSource("/api/pipeline/activity/stream?limit=60");
  state.stream.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      maybeScheduleRefreshFromEvents(payload);
    } catch {
      // Ignore malformed stream events.
    }
  };
  state.stream.onerror = () => {
    closeStream();
    window.setTimeout(startStream, 4000);
  };
}

async function onToggleBenchmarkClick() {
  if (state.busyAction) {
    return;
  }
  setActionBusy(true);
  try {
    if (state.isRunning) {
      await fetchJson("/api/layout-benchmark/stop", { method: "POST" });
    } else {
      await fetchJson("/api/layout-benchmark/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force_full_rerun: Boolean(forceRerunToggle.checked) }),
      });
    }
    await refreshAll();
  } catch (error) {
    console.error(`Benchmark action failed: ${error.message}`);
  } finally {
    setActionBusy(false);
  }
}

function onExplorerModeChange() {
  state.explorerMode = explorerModeSelect.value === "model_imgsz" ? "model_imgsz" : "conf_iou";
  renderExplorer();
}

function onExplorerFilterChange() {
  state.selectedModel = explorerModelSelect.value;
  state.selectedImgsz = explorerImgszSelect.value;
  state.selectedConf = explorerConfSelect.value;
  state.selectedIou = explorerIouSelect.value;
  renderExplorer();
}

benchmarkToggleBtn.addEventListener("click", onToggleBenchmarkClick);
leaderboardTabBtn.addEventListener("click", () => {
  setActiveView("leaderboard");
});
explorerTabBtn.addEventListener("click", () => {
  setActiveView("explorer");
});
explorerModeSelect.addEventListener("change", onExplorerModeChange);
explorerModelSelect.addEventListener("change", onExplorerFilterChange);
explorerImgszSelect.addEventListener("change", onExplorerFilterChange);
explorerConfSelect.addEventListener("change", onExplorerFilterChange);
explorerIouSelect.addEventListener("change", onExplorerFilterChange);

window.addEventListener("beforeunload", () => {
  closeStream();
});

setActiveView("leaderboard");
refreshAll().catch((error) => {
  console.error(`Failed to load benchmark page: ${error.message}`);
});
startStream();
