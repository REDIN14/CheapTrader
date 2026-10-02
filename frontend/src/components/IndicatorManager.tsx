import { useEffect, useMemo, useState } from "react";
import { indicatorApi } from "../lib/api";
import type { IndicatorSpec } from "../lib/types";
import { BookIcon, CheckIcon, CloseIcon, PlusIcon, SettingsIcon } from "./Icons";

interface Props {
  activeIds: string[];
  onToggle: (id: string) => void;
  onChanged: () => void;
  /** Open the documentation (how to write an indicator, and how to draw from one). */
  onDocs: () => void;
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
  name: string;
  code: string;
  overlay: boolean;
  params: { key: string; value: string }[];
};

const EMPTY_EDITOR: EditorState = {
  id: null,
  name: "",
  code: DEFAULT_CODE,
  overlay: true,
  params: [{ key: "period", value: "14" }],
};

export function IndicatorManager({ activeIds, onToggle, onChanged, onDocs }: Props) {
  const [indicators, setIndicators] = useState<IndicatorSpec[]>([]);
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      setIndicators(await indicatorApi.list());
    } catch (err) {
      setMessage((err as Error).message);
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

  const openNew = () => {
    setEditor({ ...EMPTY_EDITOR, params: [{ key: "period", value: "14" }] });
    setMessage(null);
  };

  const openEdit = (spec: IndicatorSpec) => {
    setEditor({
      id: spec.id,
      name: spec.name,
      code: spec.code,
      overlay: spec.overlay,
      params: Object.entries(spec.params ?? {}).map(([key, value]) => ({
        key,
        value: String(value),
      })),
    });
    setMessage(null);
  };

  const save = async () => {
    if (!editor) return;
    if (!editor.name.trim()) {
      setMessage("Name is required");
      return;
    }
    const params: Record<string, unknown> = {};
    for (const { key, value } of editor.params) {
      if (!key.trim()) continue;
      const num = Number(value);
      params[key.trim()] = value.trim() !== "" && !Number.isNaN(num) ? num : value;
    }
    setBusy(true);
    try {
      if (editor.id) {
        await indicatorApi.update(editor.id, {
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
      await refresh();
      onChanged();
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await indicatorApi.remove(id);
    } catch (err) {
      setMessage((err as Error).message);
      return;
    }
    if (editor?.id === id) setEditor(null);
    await refresh();
    onChanged();
  };

  const setParam = (index: number, patch: Partial<{ key: string; value: string }>) => {
    if (!editor) return;
    const params = editor.params.map((p, i) => (i === index ? { ...p, ...patch } : p));
    setEditor({ ...editor, params });
  };

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
        <div className="im-editor">
          <div className="im-editor-head">
            <span>{editor.id ? "Edit indicator" : "New indicator"}</span>
            <button className="im-icon" title="Close editor" onClick={() => setEditor(null)}>
              <CloseIcon size={20} />
            </button>
          </div>

          <label className="im-field">
            <span>Name</span>
            <input
              value={editor.name}
              placeholder="e.g. Momentum"
              onChange={(e) => setEditor({ ...editor, name: e.target.value })}
            />
          </label>

          <label className="im-field inline">
            <input
              type="checkbox"
              checked={editor.overlay}
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
                    onChange={(e) => setParam(i, { key: e.target.value })}
                  />
                  <input
                    placeholder="value"
                    value={p.value}
                    onChange={(e) => setParam(i, { value: e.target.value })}
                  />
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
                </div>
              ))}
              <button
                className="im-param-add"
                onClick={() =>
                  setEditor({ ...editor, params: [...editor.params, { key: "", value: "" }] })
                }
              >
                + Add parameter
              </button>
            </div>
          </div>

          <label className="im-field">
            <span>Python code</span>
            <textarea
              className="im-code"
              spellCheck={false}
              value={editor.code}
              onChange={(e) => setEditor({ ...editor, code: e.target.value })}
            />
          </label>

          <div className="im-editor-actions">
            <button className="im-save" disabled={busy} onClick={save}>
              {editor.id ? "Save" : "Create"}
            </button>
            <button className="im-cancel" onClick={() => setEditor(null)}>
              Cancel
            </button>
          </div>
          {message && <p className="im-message">{message}</p>}
        </div>
      )}
    </div>
  );
}
