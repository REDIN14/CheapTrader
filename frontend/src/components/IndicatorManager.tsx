import { useEffect, useMemo, useRef, useState } from "react";
import { indicatorApi } from "../lib/api";
import { paramsFromRows, rowsFromParams, sameParams, type ParamRow } from "../lib/indicatorParams";
import type { IndicatorSpec } from "../lib/types";
import { BookIcon, CheckIcon, CloseIcon, PlusIcon, SettingsIcon } from "./Icons";

interface Props {
  activeIds: string[];
  onToggle: (id: string) => void;
  onChanged: () => void;
  /** Open the documentation (how to write an indicator, and how to draw from one). */
  onDocs: () => void;
  /** Open the settings of this indicator (the gear of its row in the chart's legend); a new `seq` opens it again. */
  editRequest?: { id: string; seq: number } | null;
}

const DEFAULT_CODE = `"""Custom indicator.

Return a dict of {plot_name: values}. "values" is a list or pandas Series
aligned to the bars. Available columns: time, open, high, low, close,
tick_volume, spread, real_volume. numpy / pandas are importable (import them).

To draw shapes on the chart as well (boxes, lines, labels), return
{"plots": [...], "drawings": [...]}; the Documentation button shows how.
"""


def compute(df, params):
    period = int(params.get("period", 14))
    return {"MyLine": df["close"].rolling(period).mean()}
`;

type EditorState = {
  id: string | null;
  /** A built-in: only its parameters can be changed (its code is part of the program). */
  builtin: boolean;
  name: string;
  code: string;
  overlay: boolean;
  params: ParamRow[];
  /** A built-in's own parameters, which "Reset to defaults" puts back. */
  defaults: Record<string, unknown> | null;
};

const EMPTY_EDITOR: EditorState = {
  id: null,
  builtin: false,
  name: "",
  code: DEFAULT_CODE,
  overlay: true,
  params: [{ key: "period", value: "14" }],
  defaults: null,
};

type Message = { text: string; error: boolean };

export function IndicatorManager({ activeIds, onToggle, onChanged, onDocs, editRequest }: Props) {
  const [indicators, setIndicators] = useState<IndicatorSpec[]>([]);
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [message, setMessage] = useState<Message | null>(null);
  const [busy, setBusy] = useState(false);
  // Grows every time the settings open, so they are scrolled into view even when the list is long.
  const [opened, setOpened] = useState(0);
  const editorRef = useRef<HTMLDivElement>(null);
  const handledRequest = useRef(0);

  const refresh = async () => {
    try {
      setIndicators(await indicatorApi.list());
    } catch (err) {
      setMessage({ text: (err as Error).message, error: true });
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return indicators;
    return indicators.filter((i) => i.name.toLowerCase().includes(q));
  }, [indicators, query]);

  const open = (next: EditorState, note: Message | null = null) => {
    setEditor(next);
    setMessage(note);
    setOpened((n) => n + 1);
  };

  const openNew = () => open({ ...EMPTY_EDITOR, params: [{ key: "period", value: "14" }] });

  const openEdit = (spec: IndicatorSpec) =>
    open({
      id: spec.id,
      builtin: spec.id.startsWith("builtin."),
      name: spec.name,
      code: spec.code,
      overlay: spec.overlay,
      params: rowsFromParams(spec.params),
      defaults: spec.defaults ?? null,
    });

  // The gear of an indicator's row in the chart's legend opens its settings here.
  useEffect(() => {
    if (!editRequest || editRequest.seq === handledRequest.current) return;
    const spec = indicators.find((s) => s.id === editRequest.id);
    if (!spec) return; // the list is still on its way: this runs again when it is here
    handledRequest.current = editRequest.seq;
    setQuery("");
    openEdit(spec);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editRequest, indicators]);

  useEffect(() => {
    if (opened) editorRef.current?.scrollIntoView({ block: "nearest" });
  }, [opened]);

  /** A new indicator of the user's own, with this one's code and settings: the way to change a built-in's code. */
  const copy = () => {
    if (!editor) return;
    open(
      { ...editor, id: null, builtin: false, name: `${editor.name} (copy)`, params: editor.params.map((p) => ({ ...p })), defaults: null },
      { text: "A copy of your own: change anything, then Create.", error: false },
    );
  };

  const save = async () => {
    if (!editor) return;
    if (!editor.name.trim()) {
      setMessage({ text: "Name is required", error: true });
      return;
    }
    const params = paramsFromRows(editor.params);
    setBusy(true);
    try {
      if (editor.id && editor.builtin) {
        await indicatorApi.update(editor.id, { params }); // a built-in takes new parameters only
      } else if (editor.id) {
        await indicatorApi.update(editor.id, {
          id: editor.id,
          name: editor.name,
          code: editor.code,
          overlay: editor.overlay,
          params,
        });
      } else {
        await indicatorApi.create({
          id: "",
          name: editor.name,
          code: editor.code,
          overlay: editor.overlay,
          params,
        });
      }
      setEditor(null);
      setMessage(null);
      await refresh();
      onChanged();
    } catch (err) {
      setMessage({ text: (err as Error).message, error: true });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await indicatorApi.remove(id);
    } catch (err) {
      setMessage({ text: (err as Error).message, error: true });
      return;
    }
    if (editor?.id === id) setEditor(null);
    await refresh();
    onChanged();
  };

  const setParam = (index: number, patch: Partial<ParamRow>) => {
    if (!editor) return;
    const params = editor.params.map((p, i) => (i === index ? { ...p, ...patch } : p));
    setEditor({ ...editor, params });
  };

  const changedFromDefaults = editor?.builtin && editor.defaults && !sameParams(paramsFromRows(editor.params), editor.defaults);

  return (
    <div className="im">
      <div className="im-toolbar">
        <input
          className="im-search"
          placeholder="Search indicators…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="im-add" onClick={openNew} title="Create an indicator">
          <PlusIcon size={22} />
        </button>
        <button className="im-add quiet" onClick={onDocs} title="Documentation: writing indicators and drawing from them">
          <BookIcon size={22} />
        </button>
      </div>

      <ul className="im-list">
        {filtered.map((spec) => {
          const active = activeIds.includes(spec.id);
          const builtin = spec.id.startsWith("builtin.");
          return (
            <li key={spec.id} className={active ? "im-row active" : "im-row"}>
              <button
                className="im-row-main"
                onClick={() => onToggle(spec.id)}
                title={active ? "Remove from chart" : "Add to chart"}
              >
                <span className={active ? "im-check on" : "im-check"}>
                  {active && <CheckIcon size={14} />}
                </span>
                <span className="im-row-name">{spec.name}</span>
                <span className="im-row-tag">{spec.overlay ? "overlay" : "pane"}</span>
              </button>
              <button className="im-icon" onClick={() => openEdit(spec)} title="Settings">
                <SettingsIcon size={20} />
              </button>
              {!builtin && (
                <button className="im-icon danger" onClick={() => remove(spec.id)} title="Delete">
                  <CloseIcon size={20} />
                </button>
              )}
            </li>
          );
        })}
        {filtered.length === 0 && <li className="im-empty">No indicators match.</li>}
      </ul>

      {editor && (
        <div className="im-editor" ref={editorRef}>
          <div className="im-editor-head">
            <span>{editor.id ? `Settings: ${editor.name}` : "New indicator"}</span>
            <button className="im-icon" title="Close editor" onClick={() => setEditor(null)}>
              <CloseIcon size={20} />
            </button>
          </div>

          {editor.builtin && (
            <p className="im-note">
              A built-in indicator: its parameters can be changed here, its code cannot. To change the code,{" "}
              <button className="im-link" onClick={copy}>
                make a copy
              </button>{" "}
              of your own.
            </p>
          )}

          <label className="im-field">
            <span>Name</span>
            <input
              value={editor.name}
              placeholder="e.g. Momentum"
              readOnly={editor.builtin}
              onChange={(e) => setEditor({ ...editor, name: e.target.value })}
            />
          </label>

          <label className="im-field inline">
            <input
              type="checkbox"
              checked={editor.overlay}
              disabled={editor.builtin}
              onChange={(e) => setEditor({ ...editor, overlay: e.target.checked })}
            />
            <span>Overlay on price</span>
          </label>

          <div className="im-field">
            <span>Parameters</span>
            <div className="im-params">
              {editor.params.map((p, i) => (
                <div key={i} className="im-param-row">
                  <input
                    placeholder="name"
                    value={p.key}
                    readOnly={editor.builtin}
                    aria-label="Parameter name"
                    onChange={(e) => setParam(i, { key: e.target.value })}
                  />
                  <input
                    placeholder="value"
                    value={p.value}
                    aria-label={`Value of ${p.key || "the parameter"}`}
                    onChange={(e) => setParam(i, { value: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void save();
                    }}
                  />
                  {editor.builtin ? (
                    <span />
                  ) : (
                    <button
                      className="im-icon"
                      title="Remove parameter"
                      onClick={() =>
                        setEditor({
                          ...editor,
                          params: editor.params.filter((_, idx) => idx !== i),
                        })
                      }
                    >
                      <CloseIcon size={18} />
                    </button>
                  )}
                </div>
              ))}
              {editor.builtin ? (
                changedFromDefaults && (
                  <button
                    className="im-param-add"
                    onClick={() => setEditor({ ...editor, params: rowsFromParams(editor.defaults) })}
                  >
                    Reset to defaults
                  </button>
                )
              ) : (
                <button
                  className="im-param-add"
                  onClick={() =>
                    setEditor({ ...editor, params: [...editor.params, { key: "", value: "" }] })
                  }
                >
                  + Add parameter
                </button>
              )}
            </div>
          </div>

          <label className="im-field">
            <span>{editor.builtin ? "Python code (built in: read only)" : "Python code"}</span>
            <textarea
              className="im-code"
              spellCheck={false}
              readOnly={editor.builtin}
              value={editor.code}
              onChange={(e) => setEditor({ ...editor, code: e.target.value })}
            />
          </label>

          <div className="im-editor-actions">
            <button className="im-save" disabled={busy} onClick={save}>
              {editor.id ? "Save" : "Create"}
            </button>
            {editor.id && (
              <button className="im-cancel" title="A new indicator of your own with this one's code and settings" onClick={copy}>
                Copy
              </button>
            )}
            <button className="im-cancel" onClick={() => setEditor(null)}>
              Cancel
            </button>
          </div>
          {message && <p className={message.error ? "im-message error" : "im-message"}>{message.text}</p>}
        </div>
      )}
      {!editor && message?.error && <p className="im-message error">{message.text}</p>}
    </div>
  );
}
