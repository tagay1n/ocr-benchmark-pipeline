import { fetchJson } from "./api_client.mjs";
import { PIPELINE_STAGE } from "./pipeline_event_constants.mjs";

const benchmarkToggleBtn = document.getElementById("benchmark-toggle-btn");
const benchmarkRescoreBtn = document.getElementById("benchmark-rescore-btn");
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
  busyRescore: false,
  lastBenchmarkEventId: 0,
  refreshInFlight: false,
  refreshTimer: null,
  stream: null,
  activeView: "leaderboard",
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
  renderRescoreButton();
}

function setRescoreBusy(busy) {
  state.busyRescore = Boolean(busy);
  benchmarkRescoreBtn.classList.toggle("is-busy", state.busyRescore);
  renderActionButton();
  renderRescoreButton();
}

function renderActionButton() {
  if (state.isRunning) {
    benchmarkToggleBtn.textContent = "Stop benchmark";
    benchmarkToggleBtn.classList.add("danger");
    benchmarkToggleBtn.disabled = state.busyAction || state.busyRescore;
    benchmarkToggleBtn.title = "Stop the running layout benchmark.";
    return;
  }
  benchmarkToggleBtn.textContent = "Start benchmark";
  benchmarkToggleBtn.classList.remove("danger");
  benchmarkToggleBtn.disabled = state.busyAction || state.busyRescore;
  benchmarkToggleBtn.title = "Start layout benchmark.";
}

function renderRescoreButton() {
  benchmarkRescoreBtn.textContent = "Recalculate score";
  benchmarkRescoreBtn.classList.remove("danger");
  benchmarkRescoreBtn.disabled = state.busyAction || state.busyRescore || state.isRunning;
  benchmarkRescoreBtn.title = state.isRunning
    ? "Stop benchmark before recalculating scores."
    : "Recalculate benchmark scores from stored predictions.";
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
    tr.innerHTML = '<td class="empty" colspan="10">No benchmark results yet.</td>';
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
    const aStd = toFiniteNumber(a.std_dev);
    const bStd = toFiniteNumber(b.std_dev);
    if (aStd !== null && bStd !== null && aStd !== bStd) {
      return aStd - bStd;
    }
    if (aStd === null && bStd !== null) {
      return 1;
    }
    if (aStd !== null && bStd === null) {
      return -1;
    }

    const aMin = toFiniteNumber(a.min_score);
    const bMin = toFiniteNumber(b.min_score);
    if (aMin !== null && bMin !== null && aMin !== bMin) {
      return bMin - aMin;
    }
    if (aMin === null && bMin !== null) {
      return 1;
    }
    if (aMin !== null && bMin === null) {
      return -1;
    }

    const aHard = toFiniteNumber(a.hard_case_score);
    const bHard = toFiniteNumber(b.hard_case_score);
    if (aHard !== null && bHard !== null && aHard !== bHard) {
      return bHard - aHard;
    }
    if (aHard === null && bHard !== null) {
      return 1;
    }
    if (aHard !== null && bHard === null) {
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
    const minScore =
      typeof row.min_score === "number" && Number.isFinite(row.min_score)
        ? row.min_score.toFixed(4)
        : "-";
    const stdDev =
      typeof row.std_dev === "number" && Number.isFinite(row.std_dev)
        ? row.std_dev.toFixed(4)
        : "-";
    const hardCaseScore =
      typeof row.hard_case_score === "number" && Number.isFinite(row.hard_case_score)
        ? row.hard_case_score.toFixed(4)
        : "-";
    const hardCasePages =
      Number.isInteger(row.hard_case_page_count) && row.hard_case_page_count > 0
        ? row.hard_case_page_count
        : null;
    const hardCaseCell = hardCasePages === null ? hardCaseScore : `${hardCaseScore} (p:${hardCasePages})`;
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
      <td>${minScore}</td>
      <td>${stdDev}</td>
      <td>${hardCaseCell}</td>
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

function pickBestCellRow(rows) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return null;
  }
  const ranked = [...rows].sort((left, right) => {
    const leftScore = toFiniteNumber(left.mean_score);
    const rightScore = toFiniteNumber(right.mean_score);
    if (leftScore !== null && rightScore !== null && leftScore !== rightScore) {
      return rightScore - leftScore;
    }
    if (leftScore === null && rightScore !== null) {
      return 1;
    }
    if (leftScore !== null && rightScore === null) {
      return -1;
    }
    const leftPages = Number(left.page_count || 0);
    const rightPages = Number(right.page_count || 0);
    if (leftPages !== rightPages) {
      return rightPages - leftPages;
    }
    const leftConf = Number(left.confidence_threshold || 0);
    const rightConf = Number(right.confidence_threshold || 0);
    if (leftConf !== rightConf) {
      return leftConf - rightConf;
    }
    const leftIou = Number(left.iou_threshold || 0);
    const rightIou = Number(right.iou_threshold || 0);
    if (leftIou !== rightIou) {
      return leftIou - rightIou;
    }
    return configLabel(left).localeCompare(configLabel(right));
  });
  return ranked[0] || null;
}

function renderHeatmap(rows) {
  const currentKey = configKey(state.currentConfig);
  const bestKey = configKey(state.bestConfig);
  const models = Array.from(new Set(rows.map((row) => String(row.model_checkpoint || "")).filter(Boolean)))
    .sort((a, b) => a.localeCompare(b));
  const imageSizes = Array.from(
    new Set(rows.map((row) => String(Math.round(Number(row.image_size || 0)))).filter(Boolean)),
  ).sort((a, b) => Number(a) - Number(b));
  const yValues = models.map((value) => ({ key: value, label: value }));
  const xValues = imageSizes.map((value) => ({ key: value, label: value }));
  const cornerLabel = "Model \\ Img size";
  explorerCaption.textContent = "Cells show the best mean mAP50-95 available for each model and image size.";

  const rowsByCell = new Map();
  for (const row of rows) {
    const model = String(row.model_checkpoint || "");
    const imageSize = String(Math.round(Number(row.image_size || 0)));
    if (!model || !imageSize) {
      continue;
    }
    const cellKey = `${model}|${imageSize}`;
    const currentRows = rowsByCell.get(cellKey) || [];
    currentRows.push(row);
    rowsByCell.set(cellKey, currentRows);
  }

  const cellScores = [];
  for (const rowValue of yValues) {
    for (const colValue of xValues) {
      const cellKey = `${rowValue.key}|${colValue.key}`;
      const item = pickBestCellRow(rowsByCell.get(cellKey) || []);
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
      const cellKey = `${rowValue.key}|${colValue.key}`;
      const cellRows = rowsByCell.get(cellKey) || [];
      const item = pickBestCellRow(cellRows);
      const td = document.createElement("td");
      td.className = "heatmap-cell";
      if (!item) {
        td.classList.add("is-empty");
        td.textContent = "-";
        tr.appendChild(td);
        continue;
      }

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
      if (state.isRunning && cellRows.some((row) => configKey(row) === currentKey)) {
        const marker = document.createElement("span");
        marker.className = "heatmap-marker running";
        marker.textContent = "RUNNING";
        markers.appendChild(marker);
      }
      if (cellRows.some((row) => configKey(row) === bestKey)) {
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
  renderHeatmap(rows);
}

function applyPayloads(statusPayload, gridPayload) {
  state.status = statusPayload && typeof statusPayload === "object" ? statusPayload : null;
  state.gridRows = Array.isArray(gridPayload?.rows) ? gridPayload.rows : [];
  state.isRunning = Boolean(statusPayload?.is_running);
  state.currentConfig = statusPayload?.run?.current_config || null;
  state.bestConfig = gridPayload?.best_config || statusPayload?.run?.best_config || null;

  renderActionButton();
  renderRescoreButton();
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
  if (state.busyAction || state.busyRescore) {
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

async function onRescoreClick() {
  if (state.busyAction || state.busyRescore || state.isRunning) {
    return;
  }
  setRescoreBusy(true);
  try {
    await fetchJson("/api/layout-benchmark/rescore", { method: "POST" });
    await refreshAll();
  } catch (error) {
    console.error(`Benchmark rescore failed: ${error.message}`);
  } finally {
    setRescoreBusy(false);
  }
}

benchmarkToggleBtn.addEventListener("click", onToggleBenchmarkClick);
benchmarkRescoreBtn.addEventListener("click", onRescoreClick);
leaderboardTabBtn.addEventListener("click", () => {
  setActiveView("leaderboard");
});
explorerTabBtn.addEventListener("click", () => {
  setActiveView("explorer");
});

window.addEventListener("beforeunload", () => {
  closeStream();
});

setActiveView("leaderboard");
refreshAll().catch((error) => {
  console.error(`Failed to load benchmark page: ${error.message}`);
});
startStream();
