"""Paper-trading profiles: named paper accounts that outlive a replay and a restart.

A profile is a paper account (see ``paper.py``) with a name and a starting balance of the user's
choosing. Each one is kept in its own file, ``<data folder>/replay/profiles/<id>.json``, written
whenever the account changes, so nothing is lost when a replay ends, the page is closed or the
program is stopped. Which profile the replay trades on is remembered in the preferences.

There is always at least one profile: the first time the replay is used, one called
"Paper account" with 10,000 is made, and deleting the last one makes a fresh one.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import uuid
from pathlib import Path

from app import paths
from app.preferences import Preferences, preferences
from app.replay.paper import PaperTradingEngine
from app.schemas import ProfileSummary

logger = logging.getLogger(__name__)

DEFAULT_NAME = "Paper account"
DEFAULT_BALANCE = 10_000.0
NAME_MAX = 40
MAX_PROFILES = 100
BALANCE_MIN = 1.0
BALANCE_MAX = 1_000_000_000.0
PREFERENCE = "replay_profile"


class ProfileError(Exception):
    """Something the user asked for cannot be done; ``status`` is the HTTP code that says so."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def clean_name(name: str) -> str:
    """The name as it will be kept: spaces tidied, 1 to ``NAME_MAX`` characters."""
    tidy = " ".join(str(name).split())
    if not tidy:
        raise ProfileError("Give the profile a name.")
    if len(tidy) > NAME_MAX:
        raise ProfileError(f"A profile name can have up to {NAME_MAX} characters.")
    return tidy


def check_balance(balance: float) -> float:
    try:
        value = float(balance)
    except (TypeError, ValueError):
        raise ProfileError("The starting balance has to be a number.") from None
    if not math.isfinite(value) or not BALANCE_MIN <= value <= BALANCE_MAX:
        raise ProfileError(
            f"The starting balance has to be between {BALANCE_MIN:,.0f} and {BALANCE_MAX:,.0f}."
        )
    return round(value, 2)


class ProfileStore:
    def __init__(self, folder: Path | None = None, prefs: Preferences | None = None) -> None:
        self._folder = folder
        self._prefs = prefs or preferences
        # Two locks, never taken the other way round: ``_lock`` guards the list of profiles and is
        # held by whatever the user asks for (create, rename, reset, delete); ``_io`` only guards a
        # file being written. An account that changes holds its own lock and then calls ``save``, so
        # ``save`` must not wait for ``_lock`` (a rename holds that and waits for the account).
        self._lock = threading.RLock()
        self._io = threading.Lock()
        self._engines: dict[str, PaperTradingEngine] | None = None

    @property
    def folder(self) -> Path:
        # resolved late: the data folder may be redirected (tests, CT_DATA_DIR) after import
        return self._folder or paths.data_dir() / "replay" / "profiles"

    # -- the files -----------------------------------------------------------------
    def _path(self, profile_id: str) -> Path:
        return self.folder / f"{profile_id}.json"

    def _write(self, engine: PaperTradingEngine) -> None:
        target = self._path(engine.profile_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(engine.to_dict(), separators=(",", ":"))
        tmp = target.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        for attempt in range(4):
            try:
                os.replace(tmp, target)
                return
            except PermissionError:  # an antivirus scan may hold the file for a moment (Windows)
                if attempt == 3:
                    raise
                time.sleep(0.03)

    def save(self, engine: PaperTradingEngine) -> None:
        """Keep the account as it is now. The accounts call this themselves whenever they change."""
        if not engine.profile_id:
            return
        with self._io:
            self._write(engine)

    def _load(self) -> dict[str, PaperTradingEngine]:
        with self._lock:
            if self._engines is not None:
                return self._engines
            found: dict[str, PaperTradingEngine] = {}
            folder = self.folder
            if folder.is_dir():
                for path in sorted(folder.glob("*.json")):
                    try:
                        engine = PaperTradingEngine.from_dict(json.loads(path.read_text(encoding="utf-8")))
                        if not engine.profile_id:
                            engine.profile_id = path.stem
                    except (OSError, ValueError) as exc:
                        # keep what cannot be read where the user can still find it, and carry on
                        logger.warning("paper profile %s is unreadable (%s)", path.name, exc)
                        try:
                            path.replace(path.with_suffix(".corrupt"))
                        except OSError:
                            pass
                        continue
                    engine.on_change = self.save
                    found[engine.profile_id] = engine
            self._engines = found
            return found

    # -- the profiles ----------------------------------------------------------------
    def engines(self) -> list[PaperTradingEngine]:
        """Every profile's account, oldest first."""
        with self._lock:
            return sorted(self._load().values(), key=lambda e: (e.seq, e.created_at, e.name.casefold()))

    def get(self, profile_id: str) -> PaperTradingEngine:
        engine = self._load().get(profile_id)
        if engine is None:
            raise ProfileError("That profile does not exist (any more).", 404)
        return engine

    def _unique(self, name: str, *, besides: str = "") -> None:
        wanted = name.casefold()
        for engine in self._load().values():
            if engine.profile_id != besides and engine.name.casefold() == wanted:
                raise ProfileError(f"There already is a profile called “{engine.name}”.", 409)

    def _make(self, name: str, balance: float) -> PaperTradingEngine:
        now = int(time.time())
        engine = PaperTradingEngine(
            initial_balance=balance,
            profile_id=uuid.uuid4().hex[:12],
            name=name,
            created_at=now,
            updated_at=now,
            seq=max([e.seq for e in self._load().values()] + [0]) + 1,
        )
        engine.on_change = self.save
        self._write(engine)
        self._load()[engine.profile_id] = engine
        return engine

    def create(self, name: str, balance: float = DEFAULT_BALANCE, *, activate: bool = True) -> PaperTradingEngine:
        with self._lock:
            profiles = self._load()
            name, balance = clean_name(name), check_balance(balance)
            if len(profiles) >= MAX_PROFILES:
                raise ProfileError(f"That is enough profiles ({MAX_PROFILES}). Delete one you no longer use.", 409)
            self._unique(name)
            engine = self._make(name, balance)
            if activate:
                self._prefs.set(PREFERENCE, engine.profile_id)
            logger.info("paper profile %r created with %s", name, balance)
            return engine

    def rename(self, profile_id: str, name: str) -> PaperTradingEngine:
        with self._lock:
            engine = self.get(profile_id)
            name = clean_name(name)
            self._unique(name, besides=profile_id)
            with engine._lock:
                engine.name = name
                engine._changed()
            return engine

    def reset(self, profile_id: str, balance: float | None = None) -> PaperTradingEngine:
        """Begin the profile again: no positions, no history, ``balance`` (or its old starting balance)."""
        with self._lock:
            engine = self.get(profile_id)
            engine.reset(None if balance is None else check_balance(balance))
            return engine

    def delete(self, profile_id: str) -> str:
        """Remove a profile and its history for good. Returns the id of the one that is active now."""
        with self._lock:
            self.get(profile_id)
            profiles = self._load()
            engine = profiles.pop(profile_id)
            engine.on_change = None
            try:
                self._path(profile_id).unlink(missing_ok=True)
            except OSError as exc:
                profiles[profile_id] = engine  # still there: say so rather than pretend
                engine.on_change = self.save
                raise ProfileError(f"The profile's file could not be removed: {exc}", 500) from exc
            logger.info("paper profile %r deleted", engine.name)
            return self.active_id()

    # -- which one is in use ------------------------------------------------------------
    def active_id(self) -> str:
        with self._lock:
            profiles = self._load()
            chosen = self._prefs.get(PREFERENCE)
            if chosen in profiles:
                return chosen
            if profiles:
                chosen = max(profiles.values(), key=lambda e: (e.updated_at, e.created_at)).profile_id
            else:
                chosen = self._make(DEFAULT_NAME, DEFAULT_BALANCE).profile_id
            self._prefs.set(PREFERENCE, chosen)
            return chosen

    def active(self) -> PaperTradingEngine:
        with self._lock:
            return self._load()[self.active_id()]

    def set_active(self, profile_id: str) -> PaperTradingEngine:
        with self._lock:
            engine = self.get(profile_id)
            self._prefs.set(PREFERENCE, profile_id)
            return engine

    # -- listing and cleaning up ---------------------------------------------------------
    def summaries(self) -> list[ProfileSummary]:
        self.active_id()  # makes the first profile when there is none
        out: list[ProfileSummary] = []
        for engine in self.engines():
            closed = list(engine.closed)
            out.append(
                ProfileSummary(
                    id=engine.profile_id,
                    name=engine.name,
                    initial_balance=engine.initial_balance,
                    balance=engine.balance,
                    realized=round(engine.balance - engine.initial_balance, 2),
                    return_pct=round((engine.balance - engine.initial_balance) / engine.initial_balance * 100, 4),
                    trades=len(closed),
                    wins=sum(1 for t in closed if t.pnl > 0),
                    losses=sum(1 for t in closed if t.pnl < 0),
                    open_positions=len(engine.positions),
                    created_at=engine.created_at,
                    updated_at=engine.updated_at,
                )
            )
        return out

    def settle_interrupted(self) -> int:
        """Positions still open when the program starts belong to a replay that was cut off (the
        program was closed or crashed): close them where they were last marked. Returns how many."""
        count = 0
        for engine in self.engines():
            if engine.positions:
                count += len(engine.settle_all(None, "session"))
        if count:
            logger.info("closed %d paper position(s) left open by an interrupted replay", count)
        return count
