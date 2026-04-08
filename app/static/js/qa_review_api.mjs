import { fetchJson } from "./api_client.mjs";

const PAGES_BATCH_URL = "/api/pages?sort=id&direction=asc&limit=200";

export async function fetchAllPagesSortedById() {
  const pages = [];
  let cursor = null;

  while (true) {
    const url = cursor
      ? `${PAGES_BATCH_URL}&cursor=${encodeURIComponent(cursor)}`
      : PAGES_BATCH_URL;
    const payload = await fetchJson(url);
    const chunk = Array.isArray(payload?.pages) ? payload.pages : [];
    pages.push(...chunk);
    if (!payload?.has_more || !payload?.next_cursor) {
      break;
    }
    cursor = String(payload.next_cursor);
  }

  return pages;
}

export function fetchPageDetails(pageId) {
  return fetchJson(`/api/pages/${pageId}`);
}

export function fetchNextQaPage(phase, pageId = null) {
  if (Number.isInteger(pageId) && pageId > 0) {
    return fetchJson(`/api/pages/${pageId}/qa-next?phase=${encodeURIComponent(String(phase || ""))}`);
  }
  return fetchJson(`/api/qa/${phase}/next`);
}

export function patchPageQaStatus(pageId, payload) {
  return fetchJson(`/api/pages/${pageId}/qa-status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
