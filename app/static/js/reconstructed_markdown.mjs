function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function normalizeLatexForRender(latexSource) {
  let text = String(latexSource ?? "").trim();
  if (!text) {
    return "";
  }
  const lines = text.split(/\r?\n/);
  if (lines.length >= 2) {
    const opening = lines[0].trim();
    const closing = lines[lines.length - 1].trim();
    if ((opening.startsWith("```") && closing === "```") || (opening.startsWith("~~~") && closing === "~~~")) {
      text = lines.slice(1, -1).join("\n").trim();
    }
  }
  if (text.startsWith("\\[") && text.endsWith("\\]") && text.length > 4) {
    text = text.slice(2, -2).trim();
  }
  if (text.startsWith("$$") && text.endsWith("$$") && text.length > 4) {
    text = text.slice(2, -2).trim();
  }
  if (text.startsWith("$") && text.endsWith("$") && text.length > 2) {
    text = text.slice(1, -1).trim();
  }
  return text;
}

function latexDisplayWrapper(latex) {
  const text = String(latex ?? "").trim();
  if (!text) {
    return "";
  }
  return `$$\n${text}\n$$`;
}

export function containsMarkdownTable(markdown) {
  const text = String(markdown ?? "");
  if (!text) {
    return false;
  }
  const lines = text.split(/\r?\n/);
  let insideFence = false;
  for (let index = 0; index < lines.length - 1; index += 1) {
    const header = lines[index];
    const separator = lines[index + 1];
    const trimmed = header.trim();
    if (/^(```|~~~)/.test(trimmed)) {
      insideFence = !insideFence;
      continue;
    }
    if (insideFence) {
      continue;
    }
    if (!header.includes("|")) {
      continue;
    }
    const headerCells = header.split("|");
    if (headerCells.length < 2) {
      continue;
    }
    if (/^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(separator)) {
      return true;
    }
  }
  return false;
}

let rendererDepsPromise = null;

async function loadRendererDeps() {
  if (rendererDepsPromise !== null) {
    return rendererDepsPromise;
  }
  rendererDepsPromise = (async () => {
    if (typeof window === "undefined") {
      return null;
    }
    try {
      const [markedModule, domPurifyModule, katexModule] = await Promise.all([
        import("https://esm.sh/marked@13.0.3?bundle"),
        import("https://esm.sh/dompurify@3.1.6?bundle"),
        import("https://esm.sh/katex@0.16.11?bundle"),
      ]);

      const markedApi =
        markedModule?.marked ??
        markedModule?.default?.marked ??
        markedModule?.default ??
        null;
      if (!markedApi) {
        return null;
      }

      const domPurifyFactory = domPurifyModule?.default ?? domPurifyModule;
      const domPurify =
        typeof domPurifyFactory === "function"
          ? domPurifyFactory(window)
          : domPurifyModule?.DOMPurify ?? null;
      if (!domPurify || typeof domPurify.sanitize !== "function") {
        return null;
      }

      const katexApi = katexModule?.default ?? katexModule;
      return {
        marked: markedApi,
        domPurify,
        katex: katexApi,
      };
    } catch {
      return null;
    }
  })();
  return rendererDepsPromise;
}

function renderFallbackMarkdown(container, markdown) {
  if (!container) {
    return;
  }
  const normalized = String(markdown ?? "");
  container.innerHTML = escapeHtml(normalized).replace(/\r?\n/g, "<br>");
}

function sanitizeMarkdownHtml(dompurify, html) {
  return dompurify.sanitize(html, {
    ALLOWED_TAGS: [
      "a",
      "abbr",
      "b",
      "blockquote",
      "br",
      "code",
      "del",
      "em",
      "h1",
      "h2",
      "h3",
      "h4",
      "h5",
      "h6",
      "hr",
      "i",
      "li",
      "ol",
      "p",
      "pre",
      "s",
      "small",
      "span",
      "strong",
      "sub",
      "sup",
      "table",
      "tbody",
      "td",
      "th",
      "thead",
      "tr",
      "u",
      "ul",
    ],
    ALLOWED_ATTR: ["href", "title", "target", "rel"],
    ALLOW_DATA_ATTR: false,
  });
}

function normalizeLinks(container) {
  if (!container) {
    return;
  }
  const links = container.querySelectorAll("a[href]");
  for (const link of links) {
    const href = String(link.getAttribute("href") || "").trim();
    if (!/^https?:\/\//i.test(href) && !/^mailto:/i.test(href)) {
      link.removeAttribute("href");
      continue;
    }
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noopener noreferrer nofollow");
  }
}

export function renderMarkdownInto(container, markdown, { onRendered } = {}) {
  renderFallbackMarkdown(container, markdown);
  void loadRendererDeps().then((deps) => {
    if (!deps || !container) {
      return;
    }
    const markdownText = String(markdown ?? "");
    const rawHtml = deps.marked.parse(markdownText, {
      gfm: true,
      breaks: true,
      headerIds: false,
      mangle: false,
    });
    const safeHtml = sanitizeMarkdownHtml(deps.domPurify, rawHtml);
    container.innerHTML = safeHtml;
    container.classList.add("markdown-rendered");
    normalizeLinks(container);
    if (typeof onRendered === "function") {
      onRendered();
    }
  });
}

export function renderMarkdownInlineInto(container, markdown, { onRendered } = {}) {
  renderFallbackMarkdown(container, markdown);
  void loadRendererDeps().then((deps) => {
    if (!deps || !container) {
      return;
    }
    const markdownText = String(markdown ?? "");
    const inlineHtml =
      typeof deps.marked.parseInline === "function"
        ? deps.marked.parseInline(markdownText, {
            gfm: true,
            breaks: true,
            headerIds: false,
            mangle: false,
          })
        : deps.marked.parse(markdownText, {
            gfm: true,
            breaks: true,
            headerIds: false,
            mangle: false,
          });
    const safeHtml = sanitizeMarkdownHtml(deps.domPurify, inlineHtml);
    container.innerHTML = safeHtml;
    container.classList.add("markdown-rendered");
    normalizeLinks(container);
    if (typeof onRendered === "function") {
      onRendered();
    }
  });
}

export function renderLatexInto(container, latexSource, { onRendered } = {}) {
  if (!container) {
    return;
  }
  const latex = normalizeLatexForRender(latexSource);
  const fallbackText = latexDisplayWrapper(latex);
  container.textContent = fallbackText;
  void loadRendererDeps().then((deps) => {
    if (!deps || !deps.katex || typeof deps.katex.render !== "function") {
      return;
    }
    try {
      container.textContent = "";
      deps.katex.render(latex, container, {
        displayMode: true,
        throwOnError: false,
        strict: "ignore",
        trust: false,
      });
      container.classList.add("latex-rendered");
      if (typeof onRendered === "function") {
        onRendered();
      }
    } catch {
      container.textContent = fallbackText;
    }
  });
}
