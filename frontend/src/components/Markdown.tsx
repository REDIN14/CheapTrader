// Draws a document read by lib/markdown.ts. Links to another document or to a heading are followed
// inside the dialog (the parent decides how); web links open in a new tab.

import { Fragment, useState } from "react";
import { copyText } from "../lib/clipboard";
import { linkTarget, type Block, type Inline } from "../lib/markdown";

export const headingDomId = (id: string) => `docs-${id}`;

interface Nav {
  onDoc: (id: string, anchor: string | null) => void;
  onAnchor: (id: string) => void;
}

function Inlines({ parts, nav }: { parts: Inline[]; nav: Nav }) {
  return (
    <>
      {parts.map((p, i) => {
        switch (p.t) {
          case "text":
            return <Fragment key={i}>{p.v}</Fragment>;
          case "code":
            return <code key={i}>{p.v}</code>;
          case "strong":
            return (
              <strong key={i}>
                <Inlines parts={p.c} nav={nav} />
              </strong>
            );
          case "em":
            return (
              <em key={i}>
                <Inlines parts={p.c} nav={nav} />
              </em>
            );
          case "link": {
            const target = linkTarget(p.href);
            if (target.kind === "web") {
              return (
                <a key={i} href={target.href} target="_blank" rel="noreferrer noopener">
                  <Inlines parts={p.c} nav={nav} />
                </a>
              );
            }
            if (target.kind === "none") {
              // a path in the repository: nothing here to open, so it is just text
              return (
                <span key={i}>
                  <Inlines parts={p.c} nav={nav} />
                </span>
              );
            }
            return (
              <a
                key={i}
                href={`#${target.id}`}
                onClick={(e) => {
                  e.preventDefault();
                  if (target.kind === "doc") nav.onDoc(target.id, target.anchor);
                  else nav.onAnchor(target.id);
                }}
              >
                <Inlines parts={p.c} nav={nav} />
              </a>
            );
          }
        }
      })}
    </>
  );
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="docs-code">
      <div className="docs-code-bar">
        <span>{lang}</span>
        <button
          onClick={() => {
            void copyText(code).then((ok) => {
              if (!ok) return;
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            });
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

export function Blocks({ blocks, nav }: { blocks: Block[]; nav: Nav }) {
  return (
    <>
      {blocks.map((b, i) => {
        switch (b.t) {
          case "heading": {
            const Tag = `h${Math.min(6, b.level)}` as "h1";
            return (
              <Tag key={i} id={headingDomId(b.id)}>
                <Inlines parts={b.c} nav={nav} />
              </Tag>
            );
          }
          case "para":
            return (
              <p key={i}>
                <Inlines parts={b.c} nav={nav} />
              </p>
            );
          case "code":
            return <CodeBlock key={i} lang={b.lang} code={b.v} />;
          case "rule":
            return <hr key={i} />;
          case "quote":
            return (
              <blockquote key={i}>
                <Blocks blocks={b.c} nav={nav} />
              </blockquote>
            );
          case "list": {
            const Tag = b.ordered ? "ol" : "ul";
            return (
              <Tag key={i}>
                {b.items.map((item, k) => (
                  <li key={k} className={item.checked === undefined ? undefined : "task"}>
                    {item.checked !== undefined && <input type="checkbox" checked={item.checked} readOnly tabIndex={-1} />}
                    <Inlines parts={item.c} nav={nav} />
                    {item.sub.length > 0 && <Blocks blocks={item.sub} nav={nav} />}
                  </li>
                ))}
              </Tag>
            );
          }
          case "table":
            return (
              <div key={i} className="docs-table">
                <table>
                  <thead>
                    <tr>
                      {b.head.map((cell, k) => (
                        <th key={k}>
                          <Inlines parts={cell} nav={nav} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, r) => (
                      <tr key={r}>
                        {row.map((cell, k) => (
                          <td key={k}>
                            <Inlines parts={cell} nav={nav} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
        }
      })}
    </>
  );
}
