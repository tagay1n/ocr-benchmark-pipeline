export async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    if (payload && typeof payload === "object" && typeof payload.detail === "string" && payload.detail.trim()) {
      throw new Error(payload.detail);
    }
    throw new Error(`Request failed: ${response.status}`);
  }
  return payload ?? {};
}
