// The documentation, read inside the app: how to write an indicator, and how to draw on the chart
// (by hand, from a script, or from an indicator). The pages are the Markdown files of the docs
// folder, served by the backend, so what is read here is what is in the repository.
//
// Opened from the book button of the drawing toolbar, from the indicator panel, and from the
// "?" menu. Esc, the X and a click outside close it.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { docsApi } from "../lib/api";
import { outline, parseMarkdown, type Block } from "../lib/markdown";
import type { DocInfo } from "../lib/types";
import { Blocks, headingDomId } from "./Markdown";
import { BookIcon, CloseIcon } from "./Icons";

interface Props {
  /** The page to open on: "getting_started", "indicators", "drawings" or "credits". */
  initial: string;
  onClose: () => void;
}

/** The names on the tabs (the pages' own titles are long). */
const TAB_NAMES: Record<string, string> = {
  getting_started: "Getting started",
  indicators: "Indicators",
  drawings: "Drawings",
  credits: "Credits",
};

export function DocsDialog({ initial, onClose }: Props) {
  const [list, setList] = useState<DocInfo[]>([]);
  const [current, setCurrent] = useState(initial);
  const [pages, setPages] = useState<Record<string, Block[]>>({});
  const [failed, setFailed] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLElement>(null);
  /** A heading to scroll to once its page is on screen. */
  const wanted = useRef<string | null>(null);

  useEffect(() => {
    dialogRef.current?.focus();
    let live = true;
    docsApi
      .list()
      .then((docs) => live && setList(docs))
      .catch((err: Error) => live && setFailed(err.message));
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (pages[current]) return;
    let live = true;
    setFailed(null);
    docsApi
      .read(current)
      .then((doc) => live && setPages((all) => ({ ...all, [current]: parseMarkdown(doc.markdown) })))
      .catch((err: Error) => live && setFailed(err.message));
    return () => {
      live = false;
    };
  }, [current, pages]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  const blocks = pages[current];

  const scrollTo = useCallback((id: string) => {
    document.getElementById(headingDomId(id))?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, []);

  // A new page starts at its top, or at the heading a link asked for.
  useEffect(() => {
    if (!blocks) return;
    const id = wanted.current;
    wanted.current = null;
    if (id) scrollTo(id);
    else bodyRef.current?.scrollTo({ top: 0 });
  }, [blocks, current, scrollTo]);

  const open = useCallback(
    (id: string, anchor: string | null) => {
      wanted.current = anchor;
      if (id === current) {
        if (anchor) scrollTo(anchor);
        wanted.current = null;
      } else {
        setCurrent(id);
      }
    },
    [current, scrollTo],
  );

  const nav = useMemo(() => ({ onDoc: open, onAnchor: scrollTo }), [open, scrollTo]);
  const toc = useMemo(() => (blocks ? outline(blocks) : []), [blocks]);
  const tabs: DocInfo[] = list.length ? list : [{ id: current, title: current }];

  return (
    <div className="tv-modal-backdrop docs-backdrop" onClick={onClose}>
      <div
        ref={dialogRef}
        className="docs-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Documentation"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="docs-head">
          <BookIcon size={24} />
          <span className="docs-title">Documentation</span>
          <div className="docs-tabs" role="tablist">
            {tabs.map((doc) => (
              <button
                key={doc.id}
                role="tab"
                aria-selected={doc.id === current}
                className={doc.id === current ? "docs-tab active" : "docs-tab"}
                onClick={() => open(doc.id, null)}
              >
                {TAB_NAMES[doc.id] ?? doc.title}
              </button>
            ))}
          </div>
          <button className="tv-icon-btn" title="Close (Esc)" aria-label="Close" onClick={onClose}>
            <CloseIcon size={22} />
          </button>
        </div>

        <div className="docs-main">
          {toc.length > 0 && (
            <nav className="docs-toc" aria-label="Contents">
              {toc.map((h) => (
                <button key={h.id} className={h.level > 2 ? "sub" : undefined} onClick={() => scrollTo(h.id)}>
                  {h.text}
                </button>
              ))}
            </nav>
          )}
          <article className="docs-body" ref={bodyRef}>
            {blocks ? (
              <Blocks blocks={blocks} nav={nav} />
            ) : failed ? (
              <p className="docs-empty">Could not load the documentation: {failed}</p>
            ) : (
              <p className="docs-empty">Loading…</p>
            )}
          </article>
        </div>
      </div>
    </div>
  );
}
