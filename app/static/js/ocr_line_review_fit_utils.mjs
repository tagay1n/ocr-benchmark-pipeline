import {
  countStretchableGlyphs,
  countStretchableSpaces,
} from "./layout_review_utils.mjs";

let lineReviewTextMeasureNode = null;

function ensureLineReviewTextMeasureNode() {
  if (lineReviewTextMeasureNode instanceof HTMLElement) {
    return lineReviewTextMeasureNode;
  }
  const node = document.createElement("span");
  node.style.position = "fixed";
  node.style.left = "-100000px";
  node.style.top = "-100000px";
  node.style.visibility = "hidden";
  node.style.pointerEvents = "none";
  node.style.whiteSpace = "pre";
  node.style.padding = "0";
  node.style.margin = "0";
  node.style.border = "0";
  document.body.appendChild(node);
  lineReviewTextMeasureNode = node;
  return node;
}

function measureLineReviewTextMetrics(
  lineNode,
  text,
  {
    fontSize = null,
    lineHeight = null,
    wordSpacing = 0,
    letterSpacing = 0,
  } = {},
) {
  if (!(lineNode instanceof HTMLElement)) {
    return { width: 0, height: 0 };
  }
  const measureNode = ensureLineReviewTextMeasureNode();
  const computed = window.getComputedStyle(lineNode);
  measureNode.style.fontFamily = computed.fontFamily;
  measureNode.style.fontSize = fontSize ? `${fontSize}px` : computed.fontSize;
  measureNode.style.fontWeight = computed.fontWeight;
  measureNode.style.fontStyle = computed.fontStyle;
  measureNode.style.fontStretch = computed.fontStretch;
  measureNode.style.lineHeight = lineHeight
    ? `${lineHeight}px`
    : computed.lineHeight;
  measureNode.style.letterSpacing = `${Number(letterSpacing) || 0}px`;
  measureNode.style.wordSpacing = `${Number(wordSpacing) || 0}px`;
  measureNode.textContent = String(text ?? "");
  const rect = measureNode.getBoundingClientRect();
  return {
    width: Number.isFinite(rect.width) ? rect.width : 0,
    height: Number.isFinite(rect.height) ? rect.height : 0,
  };
}

function percentileFromSorted(values, percentile) {
  if (!Array.isArray(values) || values.length === 0) {
    return 0;
  }
  const clampedPercentile = Math.max(0, Math.min(1, Number(percentile) || 0));
  if (values.length === 1) {
    return Number(values[0]) || 0;
  }
  const rawIndex = (values.length - 1) * clampedPercentile;
  const lowerIndex = Math.floor(rawIndex);
  const upperIndex = Math.ceil(rawIndex);
  const lower = Number(values[lowerIndex]) || 0;
  const upper = Number(values[upperIndex]) || 0;
  if (lowerIndex === upperIndex) {
    return lower;
  }
  const ratio = rawIndex - lowerIndex;
  return lower + (upper - lower) * ratio;
}

export function resolveLineReviewCommonFitProfile(lineNode, allLines) {
  if (!(lineNode instanceof HTMLElement)) {
    return null;
  }
  const computed = window.getComputedStyle(lineNode);
  const paddingLeft = Number.parseFloat(computed.paddingLeft) || 0;
  const paddingRight = Number.parseFloat(computed.paddingRight) || 0;
  const paddingTop = Number.parseFloat(computed.paddingTop) || 0;
  const paddingBottom = Number.parseFloat(computed.paddingBottom) || 0;
  const availableWidth = Math.max(1, lineNode.clientWidth - paddingLeft - paddingRight);
  const availableHeight = Math.max(1, lineNode.clientHeight - paddingTop - paddingBottom);
  if (availableWidth <= 2) {
    return null;
  }
  const targetWidth = Math.max(1, availableWidth - 2);

  const baseFontSize = Number.parseFloat(computed.fontSize) || 12;
  const baseLineHeightPx = Number.parseFloat(computed.lineHeight);
  const lineHeightRatio =
    Number.isFinite(baseLineHeightPx) && baseFontSize > 0
      ? baseLineHeightPx / baseFontSize
      : 1.2;
  const maxByHeight = availableHeight / Math.max(1e-6, lineHeightRatio);
  const candidates = Array.isArray(allLines) ? allLines : [];
  const baseWidths = [];
  for (const line of candidates) {
    const measured = measureLineReviewTextMetrics(lineNode, String(line ?? "") || " ", {
      fontSize: baseFontSize,
      lineHeight: baseFontSize * lineHeightRatio,
      wordSpacing: 0,
      letterSpacing: 0,
    });
    const width = Number(measured.width);
    if (!Number.isFinite(width) || width <= 0) {
      continue;
    }
    baseWidths.push(width);
  }
  const sortedBaseWidths = baseWidths.slice().sort((left, right) => left - right);
  const dominantBaseWidth = percentileFromSorted(sortedBaseWidths, 0.75);
  const widthDrivenFontSize =
    dominantBaseWidth > 0
      ? baseFontSize * (targetWidth / dominantBaseWidth)
      : maxByHeight;
  const fittedFontSize = Math.max(10, Math.min(56, maxByHeight, widthDrivenFontSize));
  const fittedLineHeightPx = fittedFontSize * lineHeightRatio;

  return {
    targetWidth,
    fontSize: fittedFontSize,
    lineHeight: fittedLineHeightPx,
  };
}

export function fitLineReviewGeminiText(lineNode, text, fitProfile = null) {
  if (!(lineNode instanceof HTMLElement)) {
    return;
  }
  const textNode = lineNode.querySelector(".line-review-gemini-line-text");
  if (!(textNode instanceof HTMLElement)) {
    return;
  }
  const rawText = String(text ?? "");
  textNode.style.wordSpacing = "0px";
  textNode.style.letterSpacing = "0px";
  textNode.style.transform = "scaleX(1)";
  textNode.style.fontSize = "";
  textNode.style.lineHeight = "";
  if (!rawText) {
    return;
  }
  const profile = fitProfile || resolveLineReviewCommonFitProfile(lineNode, [rawText]);
  if (!profile) {
    return;
  }
  textNode.style.fontSize = `${profile.fontSize}px`;
  textNode.style.lineHeight = `${profile.lineHeight}px`;

  const measured = measureLineReviewTextMetrics(textNode, rawText, {
    fontSize: profile.fontSize,
    lineHeight: profile.lineHeight,
    wordSpacing: 0,
    letterSpacing: 0,
  });
  let width = Number(measured.width);
  if (!Number.isFinite(width) || width <= 0) {
    textNode.style.transform = "scaleX(1)";
    return;
  }

  let wordSpacing = 0;
  let letterSpacing = 0;
  if (profile.targetWidth > width + 0.25) {
    const spacesCount = countStretchableSpaces(rawText);
    if (spacesCount > 0) {
      const requiredExtra = profile.targetWidth - width;
      wordSpacing = Math.max(0, Math.min(6, requiredExtra / spacesCount));
      textNode.style.wordSpacing = `${wordSpacing}px`;
      const wsMeasured = measureLineReviewTextMetrics(textNode, rawText, {
        fontSize: profile.fontSize,
        lineHeight: profile.lineHeight,
        wordSpacing,
        letterSpacing,
      });
      const wsWidth = Number(wsMeasured.width);
      if (Number.isFinite(wsWidth) && wsWidth > 0) {
        width = wsWidth;
      }
    }
    if (profile.targetWidth > width + 0.25) {
      const glyphsCount = countStretchableGlyphs(rawText);
      if (glyphsCount > 1) {
        const requiredExtra = profile.targetWidth - width;
        letterSpacing = Math.max(0, Math.min(1.2, requiredExtra / (glyphsCount - 1)));
        textNode.style.letterSpacing = `${letterSpacing}px`;
        const lsMeasured = measureLineReviewTextMetrics(textNode, rawText, {
          fontSize: profile.fontSize,
          lineHeight: profile.lineHeight,
          wordSpacing,
          letterSpacing,
        });
        const lsWidth = Number(lsMeasured.width);
        if (Number.isFinite(lsWidth) && lsWidth > 0) {
          width = lsWidth;
        }
      }
    }
  }
  if (profile.targetWidth < width - 0.25) {
    const spacesCount = countStretchableSpaces(rawText);
    if (spacesCount > 0) {
      const requiredReduce = width - profile.targetWidth;
      wordSpacing = -Math.max(0, Math.min(1.8, requiredReduce / spacesCount));
      textNode.style.wordSpacing = `${wordSpacing}px`;
      const wsMeasured = measureLineReviewTextMetrics(textNode, rawText, {
        fontSize: profile.fontSize,
        lineHeight: profile.lineHeight,
        wordSpacing,
        letterSpacing,
      });
      const wsWidth = Number(wsMeasured.width);
      if (Number.isFinite(wsWidth) && wsWidth > 0) {
        width = wsWidth;
      }
    }
    if (profile.targetWidth < width - 0.25) {
      const glyphsCount = countStretchableGlyphs(rawText);
      if (glyphsCount > 1) {
        const requiredReduce = width - profile.targetWidth;
        letterSpacing = -Math.max(0, Math.min(0.35, requiredReduce / (glyphsCount - 1)));
        textNode.style.letterSpacing = `${letterSpacing}px`;
        const lsMeasured = measureLineReviewTextMetrics(textNode, rawText, {
          fontSize: profile.fontSize,
          lineHeight: profile.lineHeight,
          wordSpacing,
          letterSpacing,
        });
        const lsWidth = Number(lsMeasured.width);
        if (Number.isFinite(lsWidth) && lsWidth > 0) {
          width = lsWidth;
        }
      }
    }
  }

  const fitScale = profile.targetWidth / Math.max(1e-6, width);
  const maxExpandScale = 1.12;
  let appliedScale = Math.max(0.12, Math.min(maxExpandScale, fitScale));
  textNode.style.transform = `scaleX(${appliedScale})`;
  const renderedWidth = Number(textNode.getBoundingClientRect().width);
  if (Number.isFinite(renderedWidth) && renderedWidth > profile.targetWidth + 0.25) {
    const overflowScale = profile.targetWidth / Math.max(1e-6, renderedWidth);
    appliedScale = Math.max(0.08, appliedScale * overflowScale);
    textNode.style.transform = `scaleX(${appliedScale})`;
  }
}

export function fitLineReviewGeminiLatex(lineNode) {
  if (!(lineNode instanceof HTMLElement)) {
    return;
  }
  const latexNode = lineNode.querySelector(".line-review-gemini-line-latex");
  if (!(latexNode instanceof HTMLElement)) {
    return;
  }
  latexNode.style.transform = "scale(1)";
  latexNode.style.transformOrigin = "center center";

  const computed = window.getComputedStyle(lineNode);
  const paddingLeft = Number.parseFloat(computed.paddingLeft) || 0;
  const paddingRight = Number.parseFloat(computed.paddingRight) || 0;
  const paddingTop = Number.parseFloat(computed.paddingTop) || 0;
  const paddingBottom = Number.parseFloat(computed.paddingBottom) || 0;
  const availableWidth = Math.max(1, lineNode.clientWidth - paddingLeft - paddingRight);
  const availableHeight = Math.max(1, lineNode.clientHeight - paddingTop - paddingBottom);

  const renderedNode =
    latexNode.querySelector(".katex-display") ||
    latexNode.querySelector(".katex") ||
    latexNode;
  if (!(renderedNode instanceof HTMLElement)) {
    return;
  }
  const rect = renderedNode.getBoundingClientRect();
  const width = Number(rect.width);
  const height = Number(rect.height);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return;
  }
  const scaleX = availableWidth / width;
  const scaleY = availableHeight / height;
  const appliedScale = Math.max(0.12, Math.min(8, scaleX, scaleY));
  latexNode.style.transform = `scale(${appliedScale})`;
}

export function fitLineReviewGeminiInlineMarkdownMath(lineNode, rawText, fitProfile = null) {
  if (!(lineNode instanceof HTMLElement)) {
    return;
  }
  const textNode = lineNode.querySelector(".line-review-gemini-line-text");
  if (!(textNode instanceof HTMLElement)) {
    return;
  }
  textNode.style.wordSpacing = "0px";
  textNode.style.letterSpacing = "0px";
  textNode.style.transform = "scaleX(1)";
  textNode.style.fontSize = "";
  textNode.style.lineHeight = "";

  const profile = fitProfile || resolveLineReviewCommonFitProfile(lineNode, [String(rawText ?? "") || " "]);
  if (!profile) {
    return;
  }
  textNode.style.fontSize = `${profile.fontSize}px`;
  textNode.style.lineHeight = `${profile.lineHeight}px`;

  const computed = window.getComputedStyle(lineNode);
  const paddingTop = Number.parseFloat(computed.paddingTop) || 0;
  const paddingBottom = Number.parseFloat(computed.paddingBottom) || 0;
  const availableHeight = Math.max(1, lineNode.clientHeight - paddingTop - paddingBottom);

  let rect = textNode.getBoundingClientRect();
  if (Number.isFinite(rect.height) && rect.height > availableHeight + 0.25) {
    const shrinkRatio = availableHeight / Math.max(1e-6, rect.height);
    const nextFont = Math.max(6, profile.fontSize * shrinkRatio);
    const nextLineHeight = Math.max(6, profile.lineHeight * shrinkRatio);
    textNode.style.fontSize = `${nextFont}px`;
    textNode.style.lineHeight = `${nextLineHeight}px`;
    rect = textNode.getBoundingClientRect();
  }

  const width = Number(rect.width);
  if (!Number.isFinite(width) || width <= 0) {
    textNode.style.transform = "scaleX(1)";
    return;
  }
  const fitScale = profile.targetWidth / Math.max(1e-6, width);
  const maxExpandScale = 1.4;
  let appliedScale = Math.max(0.04, Math.min(maxExpandScale, fitScale));
  textNode.style.transform = `scaleX(${appliedScale})`;

  let renderedWidth = Number(textNode.getBoundingClientRect().width);
  if (Number.isFinite(renderedWidth) && renderedWidth > profile.targetWidth + 0.25) {
    const overflowScale = profile.targetWidth / Math.max(1e-6, renderedWidth);
    appliedScale = Math.max(0.02, appliedScale * overflowScale);
    textNode.style.transform = `scaleX(${appliedScale})`;
    renderedWidth = Number(textNode.getBoundingClientRect().width);
  }
  if (Number.isFinite(renderedWidth) && renderedWidth > profile.targetWidth + 0.25) {
    const shrinkRatio = profile.targetWidth / Math.max(1e-6, renderedWidth);
    const currentFontSize = Number.parseFloat(textNode.style.fontSize) || profile.fontSize;
    const currentLineHeight = Number.parseFloat(textNode.style.lineHeight) || profile.lineHeight;
    textNode.style.fontSize = `${Math.max(5, currentFontSize * shrinkRatio)}px`;
    textNode.style.lineHeight = `${Math.max(5, currentLineHeight * shrinkRatio)}px`;
    textNode.style.transform = "scaleX(1)";
    const finalWidth = Number(textNode.getBoundingClientRect().width);
    if (Number.isFinite(finalWidth) && finalWidth > profile.targetWidth + 0.25) {
      const finalScale = Math.max(0.02, profile.targetWidth / Math.max(1e-6, finalWidth));
      textNode.style.transform = `scaleX(${finalScale})`;
    }
  }
}
