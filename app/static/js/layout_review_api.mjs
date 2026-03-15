import { fetchJson } from "./api_client.mjs";

export function fetchPages() {
  return fetchJson("/api/pages");
}

export function fetchPageDetails(pageId) {
  return fetchJson(`/api/pages/${pageId}`);
}

export function fetchPageLayouts(pageId) {
  return fetchJson(`/api/pages/${pageId}/layouts`);
}

export function fetchLayoutDetectionDefaults() {
  return fetchJson("/api/layout-detection/defaults");
}

export function fetchLayoutBenchmarkGrid() {
  return fetchJson("/api/layout-benchmark/grid");
}

export function fetchNextLayoutReviewPage(pageId) {
  return fetchJson(`/api/pages/${pageId}/layout-review-next`);
}

export function detectPageLayouts(pageId, payload) {
  return fetchJson(`/api/pages/${pageId}/layouts/detect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function createPageLayout(pageId, payload) {
  return fetchJson(`/api/pages/${pageId}/layouts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteLayout(layoutId) {
  return fetchJson(`/api/layouts/${layoutId}`, { method: "DELETE" });
}

export function patchLayout(layoutId, payload) {
  return fetchJson(`/api/layouts/${layoutId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function putCaptionBindings(pageId, payload) {
  return fetchJson(`/api/pages/${pageId}/caption-bindings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function completeLayoutReview(pageId) {
  return fetchJson(`/api/pages/${pageId}/layouts/review-complete`, {
    method: "POST",
  });
}
