export function normalizeNextPagePayload(payload) {
  if (payload && payload.has_next && Number.isInteger(payload.next_page_id) && payload.next_page_id > 0) {
    return {
      nextPageId: Number(payload.next_page_id),
      nextPageRelPath: payload.next_page_rel_path ? String(payload.next_page_rel_path) : null,
    };
  }
  return {
    nextPageId: null,
    nextPageRelPath: null,
  };
}

export function findNextPageForStatus(pages, pendingStatus) {
  const list = Array.isArray(pages) ? pages : [];
  const target = String(pendingStatus || "");
  const pending = list
    .filter((page) => page && !page.is_missing && String(page.status || "") === target)
    .sort((a, b) => Number(a.id) - Number(b.id));
  if (pending.length === 0) {
    return {
      nextPageId: null,
      nextPageRelPath: null,
    };
  }
  return {
    nextPageId: Number(pending[0].id),
    nextPageRelPath: pending[0].rel_path ? String(pending[0].rel_path) : null,
  };
}
