// The paper-trading profiles, in one menu: which one the replay trades on, and making, renaming,
// starting over and deleting them.
//
//   [ ▣ Paper account  10,250.00  ▾ ]
//
// Each profile has a starting balance of its own and keeps its balance and history for good: when a
// replay ends, when another one starts, and when the program is restarted. Switching away from a
// profile (or deleting it) in a running replay closes its open positions at the price under the
// cursor, so that is asked before it is done.

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { formatMoney } from "../lib/format";
import {
  DEFAULT_BALANCE,
  NAME_MAX,
  balanceProblem,
  historyLabel,
  nameProblem,
  nextProfileName,
  parseBalance,
  returnLabel,
  tidyName,
} from "../lib/profiles";
import type { ReplayProfile, ReplayProfiles } from "../lib/types";
import { ChevronDown, PencilIcon, PlusIcon, ResetIcon, TrashIcon, WalletIcon } from "./Icons";

interface Props {
  view: ReplayProfiles | null;
  busy: boolean;
  /** Why the last thing asked for did not work (in the backend's words). */
  error: string | null;
  onClearError: () => void;
  /** The menu is being opened: read the profiles again, so the numbers shown are current. */
  onOpen: () => void;
  /** A replay is running: switching profile closes the open positions of the one left. */
  running: boolean;
  /** The profile in use as it is right now (it moves with every bar of a running replay). */
  live: { balance: number; openPositions: number } | null;
  /** "pill" sits in a toolbar, "field" fills the width of a panel. */
  variant: "pill" | "field";
  onCreate: (name: string, balance: number) => Promise<boolean>;
  onSelect: (id: string) => Promise<boolean>;
  onRename: (id: string, name: string) => Promise<boolean>;
  onReset: (id: string, balance: number) => Promise<boolean>;
  onDelete: (id: string) => Promise<boolean>;
}

type Pending = { id: string; kind: "rename" | "reset" | "delete" | "switch" } | null;

const tone = (v: number) => (v > 0.005 ? "pos" : v < -0.005 ? "neg" : "");

const WIDTH = 410;

export function ProfileMenu({
  view,
  busy,
  error,
  onClearError,
  onOpen,
  running,
  live,
  variant,
  onCreate,
  onSelect,
  onRename,
  onReset,
  onDelete,
}: Props) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<Pending>(null);
  const [adding, setAdding] = useState(false);
  const [place, setPlace] = useState({ left: 8, top: 40, width: WIDTH, room: 400 });
  const button = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);

  const profiles = view?.profiles ?? [];
  const active = profiles.find((p) => p.id === view?.active) ?? null;

  const close = () => {
    setOpen(false);
    setPending(null);
    setAdding(false);
    onClearError();
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!pop.current?.contains(target) && !button.current?.contains(target)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // Esc closes this menu and nothing else: it must not also end a replay
      e.stopPropagation();
      close();
    };
    const onResize = () => close();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!view || !active) return null;

  const toggle = () => {
    if (open) {
      close();
      return;
    }
    const r = button.current?.getBoundingClientRect();
    if (r) {
      const width = variant === "field" ? Math.max(WIDTH, r.width) : WIDTH;
      setPlace({
        left: Math.max(8, Math.min(r.left, window.innerWidth - width - 8)),
        top: r.bottom + 6,
        width,
        room: window.innerHeight - r.bottom - 16,
      });
    }
    setOpen(true);
    onOpen();
  };

  const balanceOf = (p: ReplayProfile) => (p.id === active.id && live ? live.balance : p.balance);
  const returnOf = (p: ReplayProfile) => ((balanceOf(p) - p.initial_balance) / p.initial_balance) * 100;
  const openOf = (p: ReplayProfile) => (p.id === active.id && live ? live.openPositions : p.open_positions);

  const pick = async (p: ReplayProfile, confirmed = false) => {
    if (p.id === active.id) {
      close();
      return;
    }
    if (!confirmed && running && live && live.openPositions > 0) {
      setPending({ id: p.id, kind: "switch" }); // asks first: it closes what is open
      return;
    }
    if (await onSelect(p.id)) close();
  };

  const toggleAction = (id: string, kind: "rename" | "reset" | "delete") => {
    onClearError();
    setAdding(false);
    setPending((now) => (now?.id === id && now.kind === kind ? null : { id, kind }));
  };

  const finish = async (work: Promise<boolean>) => {
    if (await work) setPending(null);
  };

  const shown = balanceOf(active);

  return (
    <>
      <button
        ref={button}
        type="button"
        className={`pm-trigger ${variant}${open ? " open" : ""}`}
        onClick={toggle}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={`Paper-trading profile: ${active.name}. Choose, make or delete profiles.`}
      >
        <WalletIcon size={18} />
        <span className="pm-name">{active.name}</span>
        <span className="pm-bal">{formatMoney(shown)}</span>
        <ChevronDown size={16} />
      </button>

      {open &&
        createPortal(
          <div
            ref={pop}
            className="pm-pop"
            role="dialog"
            aria-label="Paper-trading profiles"
            style={{ left: place.left, top: place.top, width: place.width, maxHeight: Math.max(240, place.room) }}
          >
            <div className="pm-head">
              <b>Paper-trading profiles</b>
              <small>
                Each profile has its own starting balance and keeps its balance and history when a replay ends and
                when the program is restarted.
              </small>
            </div>

            <ul className="pm-list">
              {profiles.map((p) => {
                const isActive = p.id === active.id;
                const mine = pending?.id === p.id ? pending.kind : null;
                const money = balanceOf(p);
                return (
                  <li key={p.id} className={isActive ? "pm-row active" : "pm-row"}>
                    <div className="pm-line">
                      <button
                        type="button"
                        className="pm-pick"
                        onClick={() => void pick(p)}
                        disabled={busy}
                        aria-current={isActive ? "true" : undefined}
                        title={isActive ? "The replay trades on this profile" : `Trade on “${p.name}”`}
                      >
                        <span className="pm-dot" aria-hidden="true" />
                        <span className="pm-text">
                          <b>{p.name}</b>
                          <small>{historyLabel({ ...p, open_positions: openOf(p) })}</small>
                        </span>
                        <span className="pm-money">
                          <b>{formatMoney(money)}</b>
                          <small className={tone(returnOf(p))}>{returnLabel(returnOf(p))}</small>
                        </span>
                      </button>
                      <span className="pm-actions">
                        <button
                          type="button"
                          className={mine === "rename" ? "on" : undefined}
                          title="Rename"
                          aria-label={`Rename ${p.name}`}
                          disabled={busy}
                          onClick={() => toggleAction(p.id, "rename")}
                        >
                          <PencilIcon size={17} />
                        </button>
                        <button
                          type="button"
                          className={mine === "reset" ? "on" : undefined}
                          title="Start over (and choose the balance)"
                          aria-label={`Start ${p.name} over`}
                          disabled={busy}
                          onClick={() => toggleAction(p.id, "reset")}
                        >
                          <ResetIcon size={17} />
                        </button>
                        <button
                          type="button"
                          className={mine === "delete" ? "on danger" : "danger"}
                          title="Delete"
                          aria-label={`Delete ${p.name}`}
                          disabled={busy}
                          onClick={() => toggleAction(p.id, "delete")}
                        >
                          <TrashIcon size={17} />
                        </button>
                      </span>
                    </div>

                    {mine === "switch" && (
                      <Confirm
                        busy={busy}
                        yes="Switch"
                        no="Stay"
                        onYes={() => void pick(p, true)}
                        onNo={() => setPending(null)}
                      >
                        {live?.openPositions === 1 ? "The open position of" : "The open positions of"} “{active.name}” will be
                        closed at the current replay price when you switch.
                      </Confirm>
                    )}
                    {mine === "rename" && (
                      <RenameForm
                        profile={p}
                        profiles={profiles}
                        busy={busy}
                        onSubmit={(name) => finish(onRename(p.id, name))}
                        onCancel={() => setPending(null)}
                      />
                    )}
                    {mine === "reset" && (
                      <ResetForm
                        profile={p}
                        busy={busy}
                        dropped={isActive && running ? openOf(p) : 0}
                        onSubmit={(balance) => finish(onReset(p.id, balance))}
                        onCancel={() => setPending(null)}
                      />
                    )}
                    {mine === "delete" && (
                      <Confirm
                        busy={busy}
                        yes="Delete for good"
                        no="Keep it"
                        danger
                        onYes={() => void finish(onDelete(p.id))}
                        onNo={() => setPending(null)}
                      >
                        Delete “{p.name}”
                        {p.trades > 0 ? ` and its ${p.trades} ${p.trades === 1 ? "trade" : "trades"}` : ""}? This cannot be
                        undone.
                        {profiles.length === 1 && " A new empty profile is made, because a replay always needs one."}
                        {isActive && running && openOf(p) > 0 && " Its open positions go with it."}
                      </Confirm>
                    )}
                  </li>
                );
              })}
            </ul>

            <div className="pm-foot">
              {adding ? (
                <NewForm
                  profiles={profiles}
                  busy={busy}
                  closes={running && live && live.openPositions > 0 ? { name: active.name, count: live.openPositions } : null}
                  onSubmit={async (name, balance) => {
                    if (await onCreate(name, balance)) close();
                  }}
                  onCancel={() => setAdding(false)}
                />
              ) : (
                <button
                  type="button"
                  className="pm-add"
                  disabled={busy}
                  onClick={() => {
                    onClearError();
                    setPending(null);
                    setAdding(true);
                  }}
                >
                  <PlusIcon size={18} />
                  New profile…
                </button>
              )}
              {error && (
                <p className="pm-error" role="alert">
                  {error}
                </p>
              )}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

// -- the small forms -------------------------------------------------------------------------------------
function Confirm({
  children,
  yes,
  no,
  danger,
  busy,
  onYes,
  onNo,
}: {
  children: ReactNode;
  yes: string;
  no: string;
  danger?: boolean;
  busy: boolean;
  onYes: () => void;
  onNo: () => void;
}) {
  return (
    <div className="pm-form">
      <p>{children}</p>
      <div className="pm-buttons">
        <button type="button" className={danger ? "pm-go danger" : "pm-go"} disabled={busy} onClick={onYes}>
          {yes}
        </button>
        <button type="button" onClick={onNo}>
          {no}
        </button>
      </div>
    </div>
  );
}

function RenameForm({
  profile,
  profiles,
  busy,
  onSubmit,
  onCancel,
}: {
  profile: ReplayProfile;
  profiles: ReplayProfile[];
  busy: boolean;
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(profile.name);
  const problem = nameProblem(name, profiles, profile.id);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!problem) onSubmit(tidyName(name));
  };
  return (
    <form className="pm-form" onSubmit={submit}>
      <label>
        Name
        <input value={name} maxLength={NAME_MAX} autoFocus onChange={(e) => setName(e.target.value)} />
      </label>
      {problem && <small className="pm-problem">{problem}</small>}
      <div className="pm-buttons">
        <button type="submit" className="pm-go" disabled={busy || !!problem}>
          Save
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function ResetForm({
  profile,
  busy,
  dropped,
  onSubmit,
  onCancel,
}: {
  profile: ReplayProfile;
  busy: boolean;
  /** Open positions of a running replay that starting over drops. */
  dropped: number;
  onSubmit: (balance: number) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState(String(profile.initial_balance));
  const problem = balanceProblem(text);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const value = parseBalance(text);
    if (!problem && value !== null) onSubmit(value);
  };
  return (
    <form className="pm-form" onSubmit={submit}>
      <p>
        {profile.trades > 0
          ? `Start “${profile.name}” over: its ${profile.trades} ${profile.trades === 1 ? "trade is" : "trades are"} erased and the balance goes back to the one you choose. This cannot be undone.`
          : `Start “${profile.name}” over with the balance you choose.`}
        {dropped > 0 && ` Its ${dropped} open ${dropped === 1 ? "position is" : "positions are"} dropped too.`}
      </p>
      <label>
        Starting balance
        <input value={text} inputMode="decimal" autoFocus onChange={(e) => setText(e.target.value)} />
      </label>
      {problem && <small className="pm-problem">{problem}</small>}
      <div className="pm-buttons">
        <button type="submit" className="pm-go danger" disabled={busy || !!problem}>
          Start over
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function NewForm({
  profiles,
  busy,
  closes,
  onSubmit,
  onCancel,
}: {
  profiles: ReplayProfile[];
  busy: boolean;
  /** A running replay has positions open on this profile, and moving to the new one closes them. */
  closes: { name: string; count: number } | null;
  onSubmit: (name: string, balance: number) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(() => nextProfileName(profiles.map((p) => p.name)));
  const [text, setText] = useState(String(DEFAULT_BALANCE));
  const nameIssue = nameProblem(name, profiles);
  const balanceIssue = balanceProblem(text);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const value = parseBalance(text);
    if (!nameIssue && !balanceIssue && value !== null) onSubmit(tidyName(name), value);
  };
  return (
    <form className="pm-form new" onSubmit={submit}>
      <label>
        Name
        <input value={name} maxLength={NAME_MAX} autoFocus onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        Starting balance
        <input value={text} inputMode="decimal" onChange={(e) => setText(e.target.value)} />
      </label>
      {(nameIssue || balanceIssue) && <small className="pm-problem">{nameIssue ?? balanceIssue}</small>}
      {closes && (
        <small className="pm-note">
          {closes.count === 1 ? "The open position of" : "The open positions of"} “{closes.name}” will be closed at the
          current replay price, because the replay moves to the new profile.
        </small>
      )}
      <div className="pm-buttons">
        <button type="submit" className="pm-go" disabled={busy || !!nameIssue || !!balanceIssue}>
          Create and use it
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
