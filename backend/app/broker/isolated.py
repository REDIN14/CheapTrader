"""MetaTrader 5 with every call made in a process of its own.

MetaTrader's Python package holds Python's global lock for as long as each call takes,
so a slow call anywhere in the server freezes the whole server: every price on every
screen, every other request. A trade waits for the broker (about 100 ms on the demo); a
read normally takes microseconds, but when another program is working the terminal hard
it can take seconds. So the server makes no MetaTrader call at all. ``IsolatedMT5Adapter``
is the ``MT5Adapter`` it uses, and it hands every call to a worker process
(``trade_worker``) and waits for the answer on the calling thread only:

* the *trader* places, modifies and closes trades, and takes pending orders back or moves them;
* the *reader* answers everything else (bars, symbols, ticks, the account, the positions, the pending orders),
  and asks the terminal only once when several requests want the same thing at the same
  moment (a page that polls while the terminal is slow must not queue up behind itself).

They are two processes so that a slow chart read can never hold an order up. The live
feed (``app.stream``) has a third of its own. The server's event loop and every other
request carry on meanwhile.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import subprocess
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime

from app import paths
from app.broker.base import BrokerError
from app.broker.mt5_adapter import MT5Adapter, bars_from_rows
from app.config import Settings
from app.procutil import child_log, kill_tree, module_command
from app.schemas import (
    AccountInfo,
    Bar,
    ModifyOrderRequest,
    ModifyRequest,
    OrderRequest,
    OrderResult,
    PendingOrder,
    Position,
    Symbol,
    TerminalInfo,
    Tick,
    Timeframe,
)

logger = logging.getLogger(__name__)

#: How long a call may take before we stop waiting. (A trade may still go through, so its
#: message tells the user to look at the terminal rather than just try again.)
CALL_TIMEOUT = 30.0
#: How long a worker may take to open its terminal session. Usually half a second; when
#: something else is working the terminal hard (a big history download by another
#: program) a new connection can take twenty seconds or more.
START_TIMEOUT = 90.0


def mt5_settings(settings: Settings) -> dict:
    """The terminal settings a child process needs to open its own session."""
    keys = ("mt5_login", "mt5_password", "mt5_server", "mt5_path")
    return {key: getattr(settings, key) for key in keys if getattr(settings, key)}


def backend_root() -> str:
    """The folder `app` lives in: where `python -m app...` has to be run from (the exe's, once built)."""
    return str(paths.app_dir())


class TradeProcess:
    """Makes MetaTrader calls in a child process and brings back the answers.

    ``role`` is "trader" (orders) or "reader" (everything else); the worker is the same,
    the role only decides how it is named in the process list and what its errors say.
    """

    def __init__(
        self,
        settings: Settings,
        command: list[str] | None = None,
        env: dict | None = None,
        role: str = "trader",
    ) -> None:
        self._settings = settings
        self._role = role
        self._command = command or module_command("app.broker.trade_worker", "--role", role)
        self._env = env
        self._proc: subprocess.Popen | None = None
        self._write_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending: dict[int, Future] = {}
        self._pending_lock = threading.Lock()
        self._ready = threading.Event()
        self._fatal: str | None = None
        self._generation = 0

    @property
    def _service(self) -> str:
        return "trading service" if self._role == "trader" else "MetaTrader reading service"

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        with self._start_lock:
            if self._alive():
                return
            self._ready.clear()
            self._fatal = None
            flags = 0
            if os.name == "nt":  # no console window, and Ctrl+C in ours must not hit the child
                flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **(self._env or {})}
            proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=child_log(),
                cwd=backend_root(),
                env=env,
                creationflags=flags,
            )
            self._proc = proc
            self._generation += 1
            threading.Thread(
                target=self._read, args=(proc, self._generation), name=f"{self._role}-read", daemon=True
            ).start()
            self._write({"settings": mt5_settings(self._settings)})
            if not self._ready.wait(START_TIMEOUT):
                self._kill()
                raise BrokerError(self._fatal or f"The {self._service} did not start in time")
            if self._fatal:
                self._kill()
                raise BrokerError(self._fatal)

    def start_in_background(self) -> None:
        """Bring the process up without making the caller wait for the terminal.

        The server can start even when the terminal is slow to answer; a trade made
        meanwhile waits for the process (see ``call``), and a start that fails is retried
        by the next trade.
        """

        def run() -> None:
            try:
                self.start()
            except BrokerError as exc:
                logger.error("the %s did not start: %s", self._service, exc)

        threading.Thread(target=run, name=f"{self._role}-start", daemon=True).start()

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()  # it stops when its input ends
            proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass
        kill_tree(proc)
        self._proc = None

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and self._ready.is_set() and not self._fatal

    def _kill(self) -> None:
        if self._proc is not None:
            kill_tree(self._proc)

    # -- talking to it --------------------------------------------------------
    def _write(self, message: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise BrokerError(f"The {self._service} is not running")
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self._write_lock:
                proc.stdin.write(data)
                proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise BrokerError(f"The {self._service} stopped; try again") from exc

    def _read(self, proc: subprocess.Popen, generation: int) -> None:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            try:
                message = json.loads(raw)
            except ValueError:
                logger.warning("the %s printed %r", self._service, raw[:200])
                continue
            kind = message.get("type")
            if kind == "ready":
                self._ready.set()
            elif kind == "fatal":
                self._fatal = str(message.get("error") or f"The {self._service} could not start")
                self._ready.set()
            elif "id" in message:
                with self._pending_lock:
                    future = self._pending.pop(message["id"], None)
                if future is not None:
                    future.set_result(message)
        # The process is gone: whoever is still waiting will not get an answer.
        if generation == self._generation:
            self._ready.clear()
        with self._pending_lock:
            waiting, self._pending = self._pending, {}
        if self._role == "trader":
            lost = (
                "The trading service stopped before it answered. "
                "Check the terminal before trying again: the trade may have gone through."
            )
        else:
            lost = f"The {self._service} stopped before it answered; try again"
        for future in waiting.values():
            future.set_exception(BrokerError(lost))

    def call(self, method: str, args: dict, timeout: float = CALL_TIMEOUT) -> object:
        """Run one call and return the answer's ``r`` part."""
        if not self._alive():
            self.start()
        ident = next(self._ids)
        future: Future = Future()
        with self._pending_lock:
            self._pending[ident] = future
        try:
            self._write({"id": ident, "m": method, "a": args})
            answer = future.result(timeout)
        except FutureTimeout as exc:
            with self._pending_lock:
                self._pending.pop(ident, None)
            if self._role == "trader":
                raise BrokerError(
                    f"The broker did not answer within {timeout:.0f} s. "
                    "Check the terminal before trying again: the trade may have gone through."
                ) from exc
            raise BrokerError(
                f"MetaTrader did not answer within {timeout:.0f} s. "
                "It may be busy with another program; try again in a moment."
            ) from exc
        except BaseException:
            with self._pending_lock:
                self._pending.pop(ident, None)
            raise
        if not answer.get("ok"):
            raise BrokerError(str(answer.get("error") or "The MetaTrader call failed"))
        return answer.get("r")


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


class IsolatedMT5Adapter(MT5Adapter):
    """The ``MT5Adapter`` the server uses: it makes no MetaTrader call itself.

    Orders go to the trader process, everything else to the reader process.
    """

    def __init__(
        self,
        settings: Settings,
        trader: TradeProcess | None = None,
        reader: TradeProcess | None = None,
    ) -> None:
        super().__init__(settings)
        self._trader = trader or TradeProcess(settings, role="trader")
        self._reader = reader or TradeProcess(settings, role="reader")
        self._flights: dict[str, Future] = {}
        self._flights_lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> None:
        # The reader has to be up before the server is (it reads the symbol list); the trader
        # only has to be by the time of the first trade, so a slow terminal does not hold the
        # server back for it.
        self._reader.start()
        self._connected = True
        self._trader.start_in_background()
        logger.info("MetaTrader 5: reading and trading in processes of their own")

    def disconnect(self) -> None:
        self._trader.stop()
        self._reader.stop()
        self._connected = False

    def _require(self) -> None:
        if not self._connected:
            raise BrokerError("MT5 adapter is not connected")

    # -- reads: the reader process ---------------------------------------------
    def _ask(self, method: str, args: dict) -> object:
        """One read. Requests for exactly the same thing that arrive while one is on its way
        share its answer, so a slow terminal never makes them queue up one behind another."""
        self._require()
        key = f"{method}:{json.dumps(args, sort_keys=True)}"
        with self._flights_lock:
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = self._flights[key] = Future()
        assert flight is not None
        if not leader:
            return flight.result()
        try:
            answer = self._reader.call(method, args)
        except BaseException as exc:
            flight.set_exception(exc)
            raise
        else:
            flight.set_result(answer)
            return answer
        finally:
            with self._flights_lock:
                self._flights.pop(key, None)

    def list_symbols(self) -> list[Symbol]:
        return [Symbol(**s) for s in self._ask("list_symbols", {})]  # type: ignore[union-attr]

    def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int = 500,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        rows = self._ask(
            "get_bars",
            {"symbol": symbol, "timeframe": timeframe.value, "count": count, "start": _iso(start), "end": _iso(end)},
        )
        return bars_from_rows(rows)  # type: ignore[arg-type]

    def get_tick(self, symbol: str) -> Tick | None:
        tick = self._ask("get_tick", {"symbol": symbol})
        return Tick(**tick) if tick else None  # type: ignore[arg-type]

    def get_ticks(self, symbol: str, start: datetime, count: int = 1000) -> list[Tick]:
        rows = self._ask("get_ticks", {"symbol": symbol, "start": _iso(start), "count": count})
        return [Tick(**t) for t in rows]  # type: ignore[union-attr]

    def get_terminal(self) -> TerminalInfo:
        return TerminalInfo(**self._ask("get_terminal", {}))  # type: ignore[arg-type]

    def get_account(self) -> AccountInfo:
        return AccountInfo(**self._ask("get_account", {}))  # type: ignore[arg-type]

    def get_positions(self, symbol: str | None = None, *, strict: bool = False) -> list[Position]:
        rows = self._ask("get_positions", {"symbol": symbol, "strict": strict})
        return [Position(**p) for p in rows]  # type: ignore[union-attr]

    def get_orders(self, symbol: str | None = None, *, strict: bool = False) -> list[PendingOrder]:
        rows = self._ask("get_orders", {"symbol": symbol, "strict": strict})
        return [PendingOrder(**o) for o in rows]  # type: ignore[union-attr]

    def get_symbol(self, name: str) -> Symbol | None:
        row = self._ask("get_symbol", {"symbol": name})
        return Symbol(**row) if row else None  # type: ignore[arg-type]

    # -- trading: the trader process -----------------------------------------------
    def _trade(self, method: str, args: dict) -> OrderResult:
        self._require()
        try:
            return OrderResult(**self._trader.call(method, args))  # type: ignore[arg-type]
        except BrokerError as exc:
            return OrderResult(ok=False, error=str(exc))

    def place_order(self, request: OrderRequest) -> OrderResult:
        return self._trade("place_order", request.model_dump(mode="json"))

    def modify_position(self, request: ModifyRequest) -> OrderResult:
        return self._trade("modify_position", request.model_dump(mode="json"))

    def close_position(self, ticket: int) -> OrderResult:
        return self._trade("close_position", {"ticket": ticket})

    def cancel_order(self, ticket: int) -> OrderResult:
        return self._trade("cancel_order", {"ticket": ticket})

    def modify_order(self, request: ModifyOrderRequest) -> OrderResult:
        return self._trade("modify_order", request.model_dump(mode="json"))
