"""The MetaTrader feed process: ``python -m app.stream.mt5_feed``.

MetaTrader's Python package holds Python's global lock for the whole of every call.
Run inside the server, one slow call (an order waiting for the broker, a long history
read) would freeze the server and with it every price on every screen. So the feed
lives here instead, in a process with nothing else to do, and the server only relays
what it prints.

The conversation is JSON lines, one message per line:

* the server's first line to us: ``{"settings": {...}, "interval": 0.005, "state_interval": 0.05}``
* then commands: ``{"c": "sub", "s": "XAUUSD"}``, ``{"c": "unsub", "s": ...}``,
  ``{"c": "kick"}`` (read the positions now), ``{"c": "quit"}``
* what we print: the events of ``app.stream.loop`` (``ready``, ``ticks``, ``state``,
  ``hb``, ``error``), or ``{"type": "fatal", "error": ...}`` just before we give up.

When the server goes away, its end of our stdin closes and we stop.
"""

from __future__ import annotations

import json
import os
import sys
import threading

from app.stream.loop import FeedLoop


def main() -> int:
    protocol = sys.stdout
    sys.stdout = sys.stderr  # anything printed by accident must not corrupt the protocol
    write_lock = threading.Lock()

    def emit(message: dict) -> None:
        line = json.dumps(message, separators=(",", ":")) + "\n"
        with write_lock:
            protocol.write(line)
            protocol.flush()

    try:
        init = json.loads(sys.stdin.readline())
        from app.broker.mt5_adapter import MT5Adapter
        from app.config import Settings
        from app.stream.sources import Mt5Source

        adapter = MT5Adapter(Settings(_env_file=None, **init.get("settings", {})))
        adapter.connect()
    except Exception as exc:  # noqa: BLE001
        emit({"type": "fatal", "error": f"{type(exc).__name__}: {exc}"})
        return 2

    loop = FeedLoop(
        Mt5Source(adapter),
        emit,
        interval=float(init.get("interval", 0.005)),
        state_interval=float(init.get("state_interval", 0.05)),
    )

    def commands() -> None:
        for line in sys.stdin:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            kind = message.get("c")
            if kind == "sub":
                loop.subscribe(str(message.get("s")))
            elif kind == "unsub":
                loop.unsubscribe(str(message.get("s")))
            elif kind == "kick":
                loop.kick()
            elif kind == "quit":
                break
        loop.stop()  # told to quit, or the server is gone

    threading.Thread(target=commands, name="commands", daemon=True).start()
    try:
        loop.run()
    finally:
        adapter.disconnect()
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)  # the commands thread may still be blocked reading stdin
