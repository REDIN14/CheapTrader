import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { inline, linkTarget, outline, parseMarkdown, plain, slug, type Block, type Inline } from "../src/lib/markdown";

const docs = join(process.cwd(), "..", "docs"); // `npm test` runs in the frontend folder

test("headings get GitHub-style anchors, and repeated ones are told apart", () => {
  const blocks = parseMarkdown("# Title\n\n## 3b. Rich dict — `{\"plots\": [...]}` (recommended)\n\n## Example\n\n## Example\n\n## Example");
  const ids = blocks.filter((b) => b.t === "heading").map((b) => (b as { id: string }).id);
  assert.deepEqual(ids, ["title", "3b-rich-dict--plots--recommended", "example", "example-1", "example-2"]);
  assert.equal(slug("Überblick: Größe & Lage"), "überblick-größe--lage");
});

test("the lines of a paragraph run together", () => {
  const [p] = parseMarkdown("one\ntwo\n  three\n\nnext") as Extract<Block, { t: "para" }>[];
  assert.equal(plain(p.c), "one two three");
});

test("inline markup", () => {
  const parts = inline("a **bold** and *slanted* word, `code with * star`, [a link](DRAWINGS.md#x) and \\| a pipe");
  const kinds = parts.map((p) => p.t);
  assert.deepEqual(kinds.filter((k) => k !== "text"), ["strong", "em", "code", "link"]);
  const code = parts.find((p) => p.t === "code") as Extract<Inline, { t: "code" }>;
  assert.equal(code.v, "code with * star");
  assert.equal(plain(parts), "a bold and slanted word, code with * star, a link and | a pipe");
  assert.equal((parts.find((p) => p.t === "link") as Extract<Inline, { t: "link" }>).href, "DRAWINGS.md#x");
});

test("a fenced block keeps its text exactly, blank lines and all", () => {
  const [code] = parseMarkdown("```python\ndef f():\n\n    return 1  # | not a table\n```\n\nafter") as Extract<Block, { t: "code" }>[];
  assert.equal(code.t, "code");
  assert.equal(code.lang, "python");
  assert.equal(code.v, "def f():\n\n    return 1  # | not a table");
});

test("tables, with a pipe escaped inside a cell", () => {
  const [table] = parseMarkdown("| Field | Values |\n| --- | :-: |\n| `type` | `\"line\"` \\| `\"histogram\"` |\n| `color` | hex |\n\nafter") as Extract<Block, { t: "table" }>[];
  assert.equal(table.t, "table");
  assert.deepEqual(table.head.map(plain), ["Field", "Values"]);
  assert.equal(table.rows.length, 2);
  assert.equal(plain(table.rows[0][1]), "\"line\" | \"histogram\"");
});

test("lists: nested, numbered, continued over lines, with check boxes", () => {
  const [list] = parseMarkdown(
    ["- first item", "  goes on here", "  - nested a", "  - nested b", "- second", "", "  ```", "  code in the item", "  ```", "- [ ] todo", "- [x] done"].join("\n"),
  ) as Extract<Block, { t: "list" }>[];
  assert.equal(list.t, "list");
  assert.equal(list.items.length, 4);
  assert.equal(plain(list.items[0].c), "first item goes on here");
  const nested = list.items[0].sub[0] as Extract<Block, { t: "list" }>;
  assert.deepEqual(nested.items.map((i) => plain(i.c)), ["nested a", "nested b"]);
  assert.equal(list.items[1].sub[0].t, "code");
  assert.deepEqual(list.items.slice(2).map((i) => i.checked), [false, true]);

  const [numbered] = parseMarkdown("1. one\n2. two\n3. three") as Extract<Block, { t: "list" }>[];
  assert.equal(numbered.ordered, true);
  assert.equal(numbered.items.length, 3);
});

test("quotes and rules", () => {
  const blocks = parseMarkdown("> A drawing is a picture.\n> It never sends an order.\n\n---\n\ntext");
  assert.deepEqual(blocks.map((b) => b.t), ["quote", "rule", "para"]);
  const quote = blocks[0] as Extract<Block, { t: "quote" }>;
  assert.equal(plain((quote.c[0] as Extract<Block, { t: "para" }>).c), "A drawing is a picture. It never sends an order.");
});

test("a paragraph ends where a list, a table or a heading begins", () => {
  const blocks = parseMarkdown("intro text\n- a list\n\nmore\n| a | b |\n| - | - |\n| 1 | 2 |\n# Heading");
  assert.deepEqual(blocks.map((b) => b.t), ["para", "list", "para", "table", "heading"]);
});

test("links lead to a document, a heading, the web, or nowhere", () => {
  assert.deepEqual(linkTarget("DRAWINGS.md"), { kind: "doc", id: "drawings", anchor: null });
  assert.deepEqual(linkTarget("docs/INDICATORS.md#7-limits"), { kind: "doc", id: "indicators", anchor: "7-limits" });
  assert.deepEqual(linkTarget("../docs/Drawings.md#5-recipes"), { kind: "doc", id: "drawings", anchor: "5-recipes" });
  assert.deepEqual(linkTarget("#4-panes"), { kind: "anchor", id: "4-panes" });
  assert.deepEqual(linkTarget("https://example.com/a"), { kind: "web", href: "https://example.com/a" });
  assert.deepEqual(linkTarget("backend/app/drawings.py"), { kind: "none" });
});

test("the outline lists the headings under the title", () => {
  const blocks = parseMarkdown("# T\n## A\n### A1\n#### deep\n## B");
  assert.deepEqual(outline(blocks).map((h) => [h.level, h.text]), [[2, "A"], [3, "A1"], [2, "B"]]);
});

for (const name of ["INDICATORS.md", "DRAWINGS.md", "GETTING_STARTED.md", "CREDITS.md"]) {
  test(`the real ${name} reads cleanly`, () => {
    const source = readFileSync(join(docs, name), "utf8");
    const blocks = parseMarkdown(source);
    const headings = blocks.filter((b): b is Extract<Block, { t: "heading" }> => b.t === "heading");
    assert.equal(headings[0].level, 1);
    assert.equal(new Set(headings.map((h) => h.id)).size, headings.length, "every heading has its own anchor");
    // as many code blocks as the source has pairs of fences
    const fences = source.split(/\r?\n/).filter((l) => /^\s*```/.test(l)).length;
    const walk = (bs: Block[]): Block[] => bs.flatMap((b) => (b.t === "list" ? [b, ...b.items.flatMap((i) => walk(i.sub))] : b.t === "quote" ? [b, ...walk(b.c)] : [b]));
    const all = walk(blocks);
    assert.equal(all.filter((b) => b.t === "code").length * 2, fences, "every fence was understood");
    // nothing of the markup is left lying about in the text
    const text = JSON.stringify(all.filter((b) => b.t === "para" || b.t === "table" || b.t === "list"));
    assert.ok(!text.includes("```"), "no stray fence");
    assert.ok(!/"t":"text","v":"[^"]*\*\*[^"]*"/.test(text), "no bold left unparsed");
    // every table row has as many cells as its header
    for (const b of all) if (b.t === "table") for (const row of b.rows) assert.equal(row.length, b.head.length, plain(row[0]));
  });
}
