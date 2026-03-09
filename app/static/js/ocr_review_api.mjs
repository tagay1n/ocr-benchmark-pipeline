import { fetchJson } from "./api_client.mjs";

export function fetchPages() {
  return fetchJson("/api/pages");
}

export function fetchPageDetails(pageId) {
  return fetchJson(`/api/pages/${pageId}`);
}

export function fetchPageOcrOutputs(pageId) {
  return fetchJson(`/api/pages/${pageId}/ocr-outputs`);
}

export function fetchPageLayouts(pageId) {
  return fetchJson(`/api/pages/${pageId}/layouts`);
}

export function fetchNextOcrReviewPage(pageId) {
  return fetchJson(`/api/pages/${pageId}/ocr-review-next`);
}

export function patchOcrOutput(layoutId, payload) {
  return fetchJson(`/api/ocr-outputs/${layoutId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function completeOcrReview(pageId) {
  return fetchJson(`/api/pages/${pageId}/ocr/review-complete`, {
    method: "POST",
  });
}

export function reextractPageOcr(pageId, payload) {
  return fetchJson(`/api/pages/${pageId}/ocr/reextract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
