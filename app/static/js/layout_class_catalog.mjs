export const KNOWN_LAYOUT_CLASSES = Object.freeze([
  "section_header",
  "text",
  "list_item",
  "table",
  "picture",
  "caption",
  "footnote",
  "formula",
  "page_header",
  "page_footer",
]);

export const CLASS_COLORS = Object.freeze({
  section_header: "#355fa8",
  text: "#4f5d69",
  list_item: "#2f6f5f",
  table: "#6f7d2f",
  picture: "#8a6831",
  caption: "#496f98",
  footnote: "#7a6030",
  formula: "#7b5a95",
  page_header: "#3f6e69",
  page_footer: "#8b5949",
});

export const CAPTION_LAYOUT_CLASS = "caption";
export const CAPTION_TARGET_CLASSES = Object.freeze(["table", "picture", "formula"]);

const FALLBACK_COLORS = Object.freeze(["#4e6f8f", "#7c5f90", "#3f7b69", "#8d6a3b", "#82605b", "#537987", "#6e6b3f"]);

function hashString(value) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(index);
    hash |= 0;
  }
  return Math.abs(hash);
}

export function normalizeClassName(className) {
  return String(className || "")
    .trim()
    .toLowerCase()
    .replace(/[-/\s]+/g, "_");
}

export function formatClassLabel(className) {
  const normalized = normalizeClassName(className).replace(/_/g, " ");
  if (!normalized) return "";
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function colorForClass(className) {
  const normalized = normalizeClassName(className);
  if (CLASS_COLORS[normalized]) {
    return CLASS_COLORS[normalized];
  }
  return FALLBACK_COLORS[hashString(normalized) % FALLBACK_COLORS.length];
}

export function isCaptionClassName(className) {
  return normalizeClassName(className) === CAPTION_LAYOUT_CLASS;
}

export function isCaptionTargetClassName(className) {
  return CAPTION_TARGET_CLASSES.includes(normalizeClassName(className));
}
