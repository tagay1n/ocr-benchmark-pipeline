const SORTABLE_COLUMN_KEYS = new Set(["id", "rel_path", "status", "created_at"]);
const SORT_DIRECTIONS = new Set(["asc", "desc"]);

export const DEFAULT_DASHBOARD_SORT = Object.freeze({
  columnKey: "created_at",
  direction: "desc",
});

function defaultDirectionForColumn(columnKey) {
  if (columnKey === "created_at") {
    return "desc";
  }
  return "asc";
}

function normalizeColumnKey(value) {
  const normalized = String(value || "").trim();
  if (SORTABLE_COLUMN_KEYS.has(normalized)) {
    return normalized;
  }
  return DEFAULT_DASHBOARD_SORT.columnKey;
}

function normalizeDirection(value, fallbackDirection) {
  const normalized = String(value || "").trim().toLowerCase();
  if (SORT_DIRECTIONS.has(normalized)) {
    return normalized;
  }
  return fallbackDirection;
}

function parseTimestamp(value) {
  const parsed = Date.parse(String(value || ""));
  if (Number.isFinite(parsed)) {
    return parsed;
  }
  return Number.NEGATIVE_INFINITY;
}

function statusSortValue(page) {
  if (Boolean(page?.is_missing)) {
    return "missing";
  }
  return String(page?.status || "").trim().toLowerCase();
}

function compareText(left, right) {
  return String(left || "").localeCompare(String(right || ""), undefined, {
    sensitivity: "base",
    numeric: true,
  });
}

function compareValues(left, right, columnKey) {
  if (columnKey === "id") {
    return Number(left?.id || 0) - Number(right?.id || 0);
  }
  if (columnKey === "rel_path") {
    return compareText(left?.rel_path, right?.rel_path);
  }
  if (columnKey === "status") {
    return compareText(statusSortValue(left), statusSortValue(right));
  }
  if (columnKey === "created_at") {
    return parseTimestamp(left?.created_at) - parseTimestamp(right?.created_at);
  }
  return 0;
}

export function normalizeDashboardSortState(rawState) {
  const base = rawState && typeof rawState === "object" ? rawState : {};
  const columnKey = normalizeColumnKey(base.columnKey);
  const direction = normalizeDirection(base.direction, defaultDirectionForColumn(columnKey));
  return { columnKey, direction };
}

export function nextDashboardSortState(rawState, requestedColumnKey) {
  const state = normalizeDashboardSortState(rawState);
  const columnKey = normalizeColumnKey(requestedColumnKey);
  if (columnKey === state.columnKey) {
    return {
      columnKey,
      direction: state.direction === "asc" ? "desc" : "asc",
    };
  }
  return {
    columnKey,
    direction: defaultDirectionForColumn(columnKey),
  };
}

export function sortDashboardPages(rawPages, rawSortState) {
  const pages = Array.isArray(rawPages) ? rawPages : [];
  const sortState = normalizeDashboardSortState(rawSortState);
  const directionMultiplier = sortState.direction === "asc" ? 1 : -1;

  return [...pages].sort((left, right) => {
    const primary = compareValues(left, right, sortState.columnKey) * directionMultiplier;
    if (primary !== 0) {
      return primary;
    }
    return Number(left?.id || 0) - Number(right?.id || 0);
  });
}
