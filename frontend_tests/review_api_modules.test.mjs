import test from "node:test";
import assert from "node:assert/strict";

import {
  completeLayoutReview,
  createPageLayout,
  deleteLayout,
  detectPageLayouts,
  patchLayout,
  putCaptionBindings,
} from "../app/static/js/layout_review_api.mjs";
import {
  completeOcrReview,
  patchOcrOutput,
  reextractPageOcr,
} from "../app/static/js/ocr_review_api.mjs";

function makeJsonResponse(body, ok = true, status = 200) {
  return {
    ok,
    status,
    async json() {
      return body;
    },
  };
}

test("layout review API module sends expected routes, methods, and payloads", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return makeJsonResponse({ ok: true });
  };

  try {
    await detectPageLayouts(7, { replace_existing: true, confidence_threshold: 0.25 });
    await createPageLayout(7, { class_name: "text", bbox: { x1: 0.1, y1: 0.1, x2: 0.2, y2: 0.2 } });
    await patchLayout(11, { class_name: "section_header" });
    await deleteLayout(11);
    await putCaptionBindings(7, { bindings: [{ caption_layout_id: 1, target_layout_ids: [2] }] });
    await completeLayoutReview(7);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls.length, 6);
  assert.equal(calls[0].url, "/api/pages/7/layouts/detect");
  assert.equal(calls[0].options.method, "POST");
  assert.match(String(calls[0].options.body), /confidence_threshold/);

  assert.equal(calls[1].url, "/api/pages/7/layouts");
  assert.equal(calls[1].options.method, "POST");
  assert.match(String(calls[1].options.body), /class_name/);

  assert.equal(calls[2].url, "/api/layouts/11");
  assert.equal(calls[2].options.method, "PATCH");

  assert.equal(calls[3].url, "/api/layouts/11");
  assert.equal(calls[3].options.method, "DELETE");

  assert.equal(calls[4].url, "/api/pages/7/caption-bindings");
  assert.equal(calls[4].options.method, "PUT");
  assert.match(String(calls[4].options.body), /caption_layout_id/);

  assert.equal(calls[5].url, "/api/pages/7/layouts/review-complete");
  assert.equal(calls[5].options.method, "POST");
});

test("ocr review API module sends expected routes and propagates backend detail errors", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    if (url === "/api/pages/5/ocr/reextract") {
      return makeJsonResponse({ detail: "quota" }, false, 429);
    }
    return makeJsonResponse({ ok: true });
  };

  try {
    await patchOcrOutput(9, { content: "updated" });
    await completeOcrReview(5);
    await assert.rejects(
      () => reextractPageOcr(5, { layout_ids: [9], temperature: 0 }),
      /quota/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls.length, 3);
  assert.equal(calls[0].url, "/api/ocr-outputs/9");
  assert.equal(calls[0].options.method, "PATCH");
  assert.match(String(calls[0].options.body), /updated/);

  assert.equal(calls[1].url, "/api/pages/5/ocr/review-complete");
  assert.equal(calls[1].options.method, "POST");

  assert.equal(calls[2].url, "/api/pages/5/ocr/reextract");
  assert.equal(calls[2].options.method, "POST");
  assert.match(String(calls[2].options.body), /layout_ids/);
});
