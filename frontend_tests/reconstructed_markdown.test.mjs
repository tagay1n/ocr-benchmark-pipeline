import test from "node:test";
import assert from "node:assert/strict";

import {
  containsMarkdownTable,
  renderLatexInto,
  renderMarkdownInto,
} from "../app/static/js/reconstructed_markdown.mjs";

test("containsMarkdownTable detects standard markdown table syntax", () => {
  const markdown = [
    "| col1 | col2 |",
    "| --- | ---: |",
    "| a | b |",
  ].join("\n");
  assert.equal(containsMarkdownTable(markdown), true);
});

test("containsMarkdownTable ignores plain text with pipes", () => {
  const markdown = "a | b and c | d but no separator line";
  assert.equal(containsMarkdownTable(markdown), false);
});

test("containsMarkdownTable detects table without outer pipes", () => {
  const markdown = [
    "col1 | col2",
    "--- | :---:",
    "a | b",
  ].join("\n");
  assert.equal(containsMarkdownTable(markdown), true);
});

test("containsMarkdownTable ignores table-like lines inside fenced code blocks", () => {
  const markdown = [
    "```md",
    "| col1 | col2 |",
    "| --- | --- |",
    "| a | b |",
    "```",
  ].join("\n");
  assert.equal(containsMarkdownTable(markdown), false);
});

test("containsMarkdownTable ignores table-like lines inside tilde fences", () => {
  const markdown = [
    "~~~",
    "a | b",
    "--- | ---",
    "1 | 2",
    "~~~",
  ].join("\n");
  assert.equal(containsMarkdownTable(markdown), false);
});

test("containsMarkdownTable detects table after fenced block closes", () => {
  const markdown = [
    "```md",
    "| inside | fence |",
    "| --- | --- |",
    "| x | y |",
    "```",
    "",
    "| real | table |",
    "| --- | --- |",
    "| a | b |",
  ].join("\n");
  assert.equal(containsMarkdownTable(markdown), true);
});

test("containsMarkdownTable ignores empty values", () => {
  assert.equal(containsMarkdownTable(""), false);
  assert.equal(containsMarkdownTable(null), false);
});

test("renderer entry points do not throw for null containers", () => {
  assert.doesNotThrow(() => {
    renderMarkdownInto(null, "# heading");
  });
  assert.doesNotThrow(() => {
    renderLatexInto(null, "\\frac{1}{2}");
  });
});
