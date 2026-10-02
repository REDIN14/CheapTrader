"""Keeps other web pages out of the program.

CheapTrader listens on ``127.0.0.1`` only, so no other computer can reach it. A web page in the user's own
browser can, though, and that is how a program on localhost gets attacked:

* a page of another site that sends requests to ``http://127.0.0.1:8765/...`` (the browser adds an
  ``Origin`` header to such a request: it names the other site);
* *DNS rebinding*: a page whose domain is made to point at ``127.0.0.1`` (the request then carries that
  domain in its ``Host`` header).

Either could place an order. Both are refused here. Programs that do not run in a browser (scripts, curl, an
AI agent) send neither header and are not affected.

Settings, as environment variables (comma separated lists):

* ``CT_ALLOWED_HOSTS``    more host names that may be used to reach the program (e.g. a development proxy);
* ``CT_ALLOWED_ORIGINS``  web pages that may use it from another address (e.g. ``http://localhost:5173``
  when the page is not served through the same port); these also get the usual CORS headers.
"""

from __future__ import annotations

import json
import os

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
#: A request with one of these methods changes something: it must come from the page itself.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _listed(name: str) -> set[str]:
    return {item.strip().lower().rstrip("/") for item in os.environ.get(name, "").split(",") if item.strip()}


def allowed_hosts() -> set[str]:
    return set(LOCAL_HOSTS) | _listed("CT_ALLOWED_HOSTS")


def allowed_origins() -> set[str]:
    return _listed("CT_ALLOWED_ORIGINS")


def hostname(host: str) -> str:
    """``127.0.0.1:8765`` -> ``127.0.0.1``; ``[::1]:8765`` -> ``[::1]``."""
    host = host.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    return host.rsplit(":", 1)[0] if ":" in host else host


def same_site(origin: str, host: str) -> bool:
    """Does this ``Origin`` name the program's own address (or a page the user allowed)?"""
    origin = origin.strip().lower().rstrip("/")
    if origin in allowed_origins():
        return True
    scheme, sep, rest = origin.partition("://")
    return bool(sep) and scheme in ("http", "https") and rest == host.strip().lower()


class LocalOnly:
    """ASGI middleware: refuses requests from other sites and for other host names (see the module)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        if hostname(host) not in allowed_hosts():
            await self._refuse(scope, receive, send, 400, "CheapTrader answers on 127.0.0.1 only.")
            return
        origin = headers.get("origin")
        changes_things = scope["type"] == "websocket" or scope["method"] not in SAFE_METHODS
        if origin is not None and changes_things and not same_site(origin, host):
            await self._refuse(scope, receive, send, 403, "Another web page may not use CheapTrader.")
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(scope, receive, send, status: int, why: str) -> None:
        if scope["type"] == "websocket":
            await receive()  # the handshake; closing before accepting answers it with a refusal
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"detail": why}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})
