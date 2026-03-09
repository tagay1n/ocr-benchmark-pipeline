import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_DASHBOARD_SORT,
  nextDashboardSortState,
  normalizeDashboardSortState,
  sortDashboardPages,
} from "../app/static/js/dashboard_sorting_utils.mjs";

test("normalizeDashboardSortState falls back to default added time desc", () => {
  assert.deepEqual(normalizeDashboardSortState(null), DEFAULT_DASHBOARD_SORT);
  assert.deepEqual(
    normalizeDashboardSortState({ columnKey: "unknown", direction: "up" }),
    DEFAULT_DASHBOARD_SORT,
  );
});

test("normalizeDashboardSortState keeps valid values", () => {
  assert.deepEqual(
    normalizeDashboardSortState({ columnKey: "id", direction: "asc" }),
    { columnKey: "id", direction: "asc" },
  );
});

test("nextDashboardSortState toggles direction for current column", () => {
  const first = nextDashboardSortState({ columnKey: "id", direction: "asc" }, "id");
  assert.deepEqual(first, { columnKey: "id", direction: "desc" });
  const second = nextDashboardSortState(first, "id");
  assert.deepEqual(second, { columnKey: "id", direction: "asc" });
});

test("nextDashboardSortState uses column-specific default direction", () => {
  assert.deepEqual(
    nextDashboardSortState({ columnKey: "id", direction: "asc" }, "created_at"),
    { columnKey: "created_at", direction: "desc" },
  );
  assert.deepEqual(
    nextDashboardSortState({ columnKey: "created_at", direction: "desc" }, "rel_path"),
    { columnKey: "rel_path", direction: "asc" },
  );
});

test("sortDashboardPages defaults to created_at newest first", () => {
  const pages = [
    { id: 3, created_at: "2026-03-07T12:00:00Z" },
    { id: 1, created_at: "2026-03-09T12:00:00Z" },
    { id: 2, created_at: "2026-03-08T12:00:00Z" },
  ];
  const sorted = sortDashboardPages(pages, null);
  assert.deepEqual(
    sorted.map((page) => page.id),
    [1, 2, 3],
  );
});

test("sortDashboardPages supports rel_path asc with numeric compare", () => {
  const pages = [
    { id: 1, rel_path: "books/page_10.png" },
    { id: 2, rel_path: "books/page_2.png" },
    { id: 3, rel_path: "books/page_1.png" },
  ];
  const sorted = sortDashboardPages(pages, { columnKey: "rel_path", direction: "asc" });
  assert.deepEqual(
    sorted.map((page) => page.id),
    [3, 2, 1],
  );
});

test("sortDashboardPages sorts status using missing marker", () => {
  const pages = [
    { id: 1, status: "ocr_done", is_missing: false },
    { id: 2, status: "layout_detected", is_missing: false },
    { id: 3, status: "new", is_missing: true },
  ];
  const sortedAsc = sortDashboardPages(pages, { columnKey: "status", direction: "asc" });
  assert.deepEqual(
    sortedAsc.map((page) => page.id),
    [2, 3, 1],
  );
  const sortedDesc = sortDashboardPages(pages, { columnKey: "status", direction: "desc" });
  assert.deepEqual(
    sortedDesc.map((page) => page.id),
    [1, 3, 2],
  );
});
