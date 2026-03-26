export function normalizeBBoxRect(bbox) {
  const rawX1 = Number(bbox?.x1);
  const rawY1 = Number(bbox?.y1);
  const rawX2 = Number(bbox?.x2);
  const rawY2 = Number(bbox?.y2);
  if (![rawX1, rawY1, rawX2, rawY2].every((value) => Number.isFinite(value))) {
    return null;
  }
  const x1 = Math.max(0, Math.min(1, Math.min(rawX1, rawX2)));
  const y1 = Math.max(0, Math.min(1, Math.min(rawY1, rawY2)));
  const x2 = Math.max(0, Math.min(1, Math.max(rawX1, rawX2)));
  const y2 = Math.max(0, Math.min(1, Math.max(rawY1, rawY2)));
  if (!(x2 > x1) || !(y2 > y1)) {
    return null;
  }
  return { x1, y1, x2, y2 };
}

function normalizedBBoxPixels(bbox, width, height) {
  const normalized = normalizeBBoxRect(bbox);
  if (!normalized) {
    return null;
  }
  const x1 = Math.max(0, Math.min(width, Number(normalized.x1) * width));
  const x2 = Math.max(0, Math.min(width, Number(normalized.x2) * width));
  const y1 = Math.max(0, Math.min(height, Number(normalized.y1) * height));
  const y2 = Math.max(0, Math.min(height, Number(normalized.y2) * height));
  if (!(x2 > x1) || !(y2 > y1)) {
    return null;
  }
  return { x1, y1, x2, y2 };
}

export function isNormalizedBBoxVisible(
  bbox,
  viewport,
  content,
  { paddingPx = 20 } = {},
) {
  if (!viewport || !content || !bbox) {
    return false;
  }
  const width = Number(content.clientWidth);
  const height = Number(content.clientHeight);
  const viewportW = Number(viewport.clientWidth);
  const viewportH = Number(viewport.clientHeight);
  if (!(width > 0) || !(height > 0) || !(viewportW > 0) || !(viewportH > 0)) {
    return false;
  }

  const rect = normalizedBBoxPixels(bbox, width, height);
  if (!rect) {
    return false;
  }

  const maxLeft = Math.max(0, width - viewportW);
  const maxTop = Math.max(0, height - viewportH);
  const currentLeft = Math.max(0, Math.min(maxLeft, Number(viewport.scrollLeft) || 0));
  const currentTop = Math.max(0, Math.min(maxTop, Number(viewport.scrollTop) || 0));
  const padding = Math.max(0, Number(paddingPx) || 0);
  const visibleLeft = currentLeft + padding;
  const visibleRight = currentLeft + viewportW - padding;
  const visibleTop = currentTop + padding;
  const visibleBottom = currentTop + viewportH - padding;

  return (
    rect.x1 >= visibleLeft &&
    rect.x2 <= visibleRight &&
    rect.y1 >= visibleTop &&
    rect.y2 <= visibleBottom
  );
}

export function ensureNormalizedBBoxVisible(
  bbox,
  viewport,
  content,
  { paddingPx = 20 } = {},
) {
  if (!viewport || !content || !bbox) {
    return false;
  }
  const width = Number(content.clientWidth);
  const height = Number(content.clientHeight);
  const viewportW = Number(viewport.clientWidth);
  const viewportH = Number(viewport.clientHeight);
  if (!(width > 0) || !(height > 0) || !(viewportW > 0) || !(viewportH > 0)) {
    return false;
  }

  const rect = normalizedBBoxPixels(bbox, width, height);
  if (!rect) {
    return false;
  }

  const maxLeft = Math.max(0, width - viewportW);
  const maxTop = Math.max(0, height - viewportH);
  const currentLeft = Math.max(0, Math.min(maxLeft, Number(viewport.scrollLeft) || 0));
  const currentTop = Math.max(0, Math.min(maxTop, Number(viewport.scrollTop) || 0));
  const padding = Math.max(0, Number(paddingPx) || 0);

  let nextLeft = currentLeft;
  let nextTop = currentTop;

  const visibleLeft = currentLeft + padding;
  const visibleRight = currentLeft + viewportW - padding;
  const visibleTop = currentTop + padding;
  const visibleBottom = currentTop + viewportH - padding;

  if (rect.x1 < visibleLeft) {
    nextLeft = rect.x1 - padding;
  } else if (rect.x2 > visibleRight) {
    nextLeft = rect.x2 + padding - viewportW;
  }

  if (rect.y1 < visibleTop) {
    nextTop = rect.y1 - padding;
  } else if (rect.y2 > visibleBottom) {
    nextTop = rect.y2 + padding - viewportH;
  }

  const clampedLeft = Math.round(Math.max(0, Math.min(maxLeft, nextLeft)));
  const clampedTop = Math.round(Math.max(0, Math.min(maxTop, nextTop)));
  const currentLeftRounded = Math.round(currentLeft);
  const currentTopRounded = Math.round(currentTop);
  if (clampedLeft === currentLeftRounded && clampedTop === currentTopRounded) {
    return false;
  }
  viewport.scrollLeft = clampedLeft;
  viewport.scrollTop = clampedTop;
  return true;
}

export function ensureElementVisibleInViewport(element, viewport, { paddingPx = 20 } = {}) {
  if (!(element instanceof HTMLElement) || !(viewport instanceof HTMLElement)) {
    return false;
  }
  const elementRect = element.getBoundingClientRect();
  const viewportRect = viewport.getBoundingClientRect();
  if (
    !(elementRect.width > 0) ||
    !(elementRect.height > 0) ||
    !(viewportRect.width > 0) ||
    !(viewportRect.height > 0)
  ) {
    return false;
  }

  const maxLeft = Math.max(0, Number(viewport.scrollWidth) - Number(viewport.clientWidth));
  const maxTop = Math.max(0, Number(viewport.scrollHeight) - Number(viewport.clientHeight));
  const currentLeft = Math.max(0, Math.min(maxLeft, Number(viewport.scrollLeft) || 0));
  const currentTop = Math.max(0, Math.min(maxTop, Number(viewport.scrollTop) || 0));
  const padding = Math.max(0, Number(paddingPx) || 0);

  let nextLeft = currentLeft;
  let nextTop = currentTop;

  const topLimit = viewportRect.top + padding;
  const bottomLimit = viewportRect.bottom - padding;
  const leftLimit = viewportRect.left + padding;
  const rightLimit = viewportRect.right - padding;

  if (elementRect.top < topLimit) {
    nextTop -= topLimit - elementRect.top;
  } else if (elementRect.bottom > bottomLimit) {
    nextTop += elementRect.bottom - bottomLimit;
  }

  if (elementRect.left < leftLimit) {
    nextLeft -= leftLimit - elementRect.left;
  } else if (elementRect.right > rightLimit) {
    nextLeft += elementRect.right - rightLimit;
  }

  const clampedLeft = Math.round(Math.max(0, Math.min(maxLeft, nextLeft)));
  const clampedTop = Math.round(Math.max(0, Math.min(maxTop, nextTop)));
  const currentLeftRounded = Math.round(currentLeft);
  const currentTopRounded = Math.round(currentTop);
  if (clampedLeft === currentLeftRounded && clampedTop === currentTopRounded) {
    return false;
  }
  viewport.scrollLeft = clampedLeft;
  viewport.scrollTop = clampedTop;
  return true;
}
