// A small Markdown reader for the documentation shown in the app (docs/*.md).
//
// It understands what those documents use: headings, paragraphs, bold / italic / `code` / links,
// fenced code blocks, tables, bullet / numbered / check lists (nested), quotes and rules. It turns the
// text into plain data (no HTML strings), which components/Markdown.tsx draws, so a document can
// never inject markup into the page.

export type Inline =
  | { t: "text"; v: string }
  | { t: "code"; v: string }
  | { t: "strong"; c: Inline[] }
  | { t: "em"; c: Inline[] }
  | { t: "link"; href: string; c: Inline[] };

export interface ListItem {
  c: Inline[];
  /** For `- [ ]` / `- [x]` items. */
  checked?: boolean;
  /** Nested lists and further paragraphs belonging to the item. */
  sub: Block[];
}

export type Block =
  | { t: "heading"; level: number; id: string; text: string; c: Inline[] }
  | { t: "para"; c: Inline[] }
  | { t: "code"; lang: string; v: string }
  | { t: "list"; ordered: boolean; items: ListItem[] }
  | { t: "table"; head: Inline[][]; rows: Inline[][][] }
  | { t: "quote"; c: Block[] }
  | { t: "rule" };

// -- inline -----------------------------------------------------------------------------------
const PATTERNS: { re: RegExp; make: (m: RegExpExecArray) => Inline }[] = [
  { re: /`([^`]+)`/, make: (m) => ({ t: "code", v: m[1] }) },
  { re: /\\([\\`*_{}[\]()#+\-.!|<>~])/, make: (m) => ({ t: "text", v: m[1] }) },
  { re: /\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/, make: (m) => ({ t: "link", href: m[2], c: inline(m[1]) }) },
  { re: /\*\*([^*]+?)\*\*/, make: (m) => ({ t: "strong", c: inline(m[1]) }) },
  { re: /\*([^*\s][^*]*?)\*/, make: (m) => ({ t: "em", c: inline(m[1]) }) },
];

export function inline(source: string): Inline[] {
  const out: Inline[] = [];
  let rest = source;
  while (rest) {
    let best: { at: number; m: RegExpExecArray; make: (m: RegExpExecArray) => Inline } | null = null;
    for (const p of PATTERNS) {
      const m = p.re.exec(rest);
      if (m && (best === null || m.index < best.at)) best = { at: m.index, m, make: p.make };
    }
    if (!best) {
      out.push({ t: "text", v: rest });
      break;
    }
    if (best.at > 0) out.push({ t: "text", v: rest.slice(0, best.at) });
    out.push(best.make(best.m));
    rest = rest.slice(best.at + best.m[0].length);
  }
  return out;
}

/** The words of some inline text, without the markup. */
export function plain(parts: Inline[]): string {
  return parts
    .map((p) => (p.t === "text" || p.t === "code" ? p.v : plain(p.c)))
    .join("");
}

/** The anchor a heading gets (the way GitHub makes them): `## 3b. Rich dict` -> `3b-rich-dict`. */
export function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, "")
    .trim()
    .replace(/\s/g, "-");
}

// -- blocks -----------------------------------------------------------------------------------
const FENCE = /^\s*```\s*([\w+-]*)\s*$/;
const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const BULLET = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
const QUOTE = /^\s*>\s?(.*)$/;
const TABLE_RULE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

const indentOf = (line: string) => line.length - line.trimStart().length;

/** The cells of a table row; `\|` is a pipe inside a cell. */
function cells(line: string): string[] {
  let text = line.trim();
  if (text.startsWith("|")) text = text.slice(1);
  if (text.endsWith("|") && !text.endsWith("\\|")) text = text.slice(0, -1);
  const out: string[] = [];
  let cell = "";
  for (let i = 0; i < text.length; i++) {
    if (text[i] === "\\" && text[i + 1] === "|") {
      cell += "\\|";
      i++;
    } else if (text[i] === "|") {
      out.push(cell.trim());
      cell = "";
    } else {
      cell += text[i];
    }
  }
  out.push(cell.trim());
  return out;
}

function startsBlock(line: string, next: string | undefined): boolean {
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    RULE.test(line) ||
    BULLET.test(line) ||
    QUOTE.test(line) ||
    (line.includes("|") && next !== undefined && TABLE_RULE.test(next))
  );
}

/** Lines of a list (and what hangs from it) starting at `from`; returns the lines and the index after them. */
function takeList(lines: string[], from: number): [string[], number] {
  const taken: string[] = [];
  let i = from;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") {
      // a blank line belongs to the list only if the list goes on after it
      let j = i + 1;
      while (j < lines.length && lines[j].trim() === "") j++;
      if (j < lines.length && (BULLET.test(lines[j]) || indentOf(lines[j]) >= 2)) {
        taken.push("");
        i++;
        continue;
      }
      break;
    }
    if (BULLET.test(line) || indentOf(line) >= 2) {
      taken.push(line);
      i++;
      continue;
    }
    break;
  }
  return [taken, i];
}

function parseList(lines: string[]): Block {
  const first = BULLET.exec(lines[0])!;
  const base = first[1].length;
  const ordered = /\d/.test(first[2]);
  const items: ListItem[] = [];
  let body: string[] = [];
  let head: RegExpExecArray | null = null;

  const flush = () => {
    if (!head) return;
    let text = head[3];
    let checked: boolean | undefined;
    const box = /^\[( |x|X)\]\s+(.*)$/.exec(text);
    if (box) {
      checked = box[1] !== " ";
      text = box[2];
    }
    // the item's text may go on over the next lines
    let k = 0;
    while (k < body.length && body[k].trim() !== "" && !startsBlock(body[k].trim(), undefined)) {
      text += ` ${body[k].trim()}`;
      k++;
    }
    // what hangs from the item (nested lists, code), de-indented by what it shares
    const rest = body.slice(k);
    const nested = rest.filter((l) => l.trim() !== "");
    const strip = nested.length ? Math.min(...nested.map(indentOf)) : 0;
    items.push({ c: inline(text), checked, sub: parseBlocks(rest.map((l) => l.slice(Math.min(strip, indentOf(l))))) });
    body = [];
  };

  for (const line of lines) {
    const m = BULLET.exec(line);
    if (m && m[1].length <= base) {
      flush();
      head = m;
    } else {
      body.push(line);
    }
  }
  flush();
  return { t: "list", ordered, items };
}

export function parseBlocks(lines: string[]): Block[] {
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") {
      i++;
      continue;
    }

    const fence = FENCE.exec(line);
    if (fence) {
      const code: string[] = [];
      const pad = indentOf(line);
      i++;
      while (i < lines.length && !FENCE.test(lines[i])) {
        code.push(lines[i].slice(Math.min(pad, indentOf(lines[i]))));
        i++;
      }
      i++; // the closing fence
      out.push({ t: "code", lang: fence[1], v: code.join("\n") });
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      const c = inline(heading[2]);
      const text = plain(c);
      out.push({ t: "heading", level: heading[1].length, id: slug(text), text, c });
      i++;
      continue;
    }

    if (RULE.test(line) && !BULLET.test(line)) {
      out.push({ t: "rule" });
      i++;
      continue;
    }

    if (line.includes("|") && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1])) {
      const head = cells(line).map(inline);
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim() !== "" && lines[i].includes("|")) {
        rows.push(cells(lines[i]).map(inline));
        i++;
      }
      out.push({ t: "table", head, rows });
      continue;
    }

    if (QUOTE.test(line)) {
      const inner: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i])) {
        inner.push(QUOTE.exec(lines[i])![1]);
        i++;
      }
      out.push({ t: "quote", c: parseBlocks(inner) });
      continue;
    }

    if (BULLET.test(line)) {
      const [taken, next] = takeList(lines, i);
      out.push(parseList(taken));
      i = next;
      continue;
    }

    // a paragraph runs until something else begins
    const words: string[] = [line.trim()];
    i++;
    while (i < lines.length && lines[i].trim() !== "" && !startsBlock(lines[i], lines[i + 1])) {
      words.push(lines[i].trim());
      i++;
    }
    out.push({ t: "para", c: inline(words.join(" ")) });
  }
  return out;
}

export function parseMarkdown(source: string): Block[] {
  const blocks = parseBlocks(source.replace(/\r\n?/g, "\n").split("\n"));
  // two headings with the same words get distinct anchors: "example", "example-1", ...
  const seen = new Map<string, number>();
  for (const b of blocks) {
    if (b.t !== "heading") continue;
    const n = seen.get(b.id) ?? 0;
    seen.set(b.id, n + 1);
    if (n > 0) b.id = `${b.id}-${n}`;
  }
  return blocks;
}

/** The headings of a document, for its table of contents. */
export function outline(blocks: Block[], maxLevel = 3): { level: number; id: string; text: string }[] {
  return blocks
    .filter((b): b is Extract<Block, { t: "heading" }> => b.t === "heading" && b.level > 1 && b.level <= maxLevel)
    .map((b) => ({ level: b.level, id: b.id, text: b.text }));
}

/**
 * Where a link in a document goes: another document (`DRAWINGS.md`, `docs/INDICATORS.md#7-limits`),
 * a place in this one (`#4-panes`), a web page, or nowhere the reader could follow (a path in the repository).
 */
export type LinkTarget =
  | { kind: "doc"; id: string; anchor: string | null }
  | { kind: "anchor"; id: string }
  | { kind: "web"; href: string }
  | { kind: "none" };

export function linkTarget(href: string): LinkTarget {
  if (/^https?:\/\//i.test(href)) return { kind: "web", href };
  if (href.startsWith("#")) return { kind: "anchor", id: href.slice(1) };
  const doc = /^(?:\.{0,2}\/)*(?:docs\/)?([\w-]+)\.md(?:#(.*))?$/i.exec(href);
  if (doc) return { kind: "doc", id: doc[1].toLowerCase(), anchor: doc[2] ?? null };
  return { kind: "none" };
}
