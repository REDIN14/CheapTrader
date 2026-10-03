"""Looking for a newer release on GitHub, and installing it.

What it does, and what it never does
------------------------------------
* A little after the program starts, and every six hours after that, it asks GitHub's public API for the latest
  release of its own repository (``GET /repos/<owner>/<name>/releases/latest``). That is the only connection the
  program makes to the internet by itself. Nothing goes with the request but what every request carries: the
  address of the computer and a ``User-Agent`` that says ``CheapTrader/<version>``. It can be switched off, in the
  About window or with ``CT_UPDATE_CHECK=false``.
* A newer release is only *shown*. Nothing is downloaded until the user clicks Install.
* Install: the release's installer (``CheapTrader-<version>-setup.exe``) is downloaded over HTTPS from GitHub, its
  SHA-256 is compared with the line for that file in the release's ``SHA256SUMS.txt``, and only then is it run:
  silently, after this program has closed. A small PowerShell script does that, because the program cannot wait
  for its own exit: it waits until ``CheapTrader.exe`` can be written to, runs the installer, records how that
  went and opens the program again. The installer replaces the program and leaves the data folder alone. While the
  script runs it holds a lock file, and a start of the program waits for it: a program that runs would keep the
  installer from replacing it (the user who opens CheapTrader again because nothing is showing is the usual cause). The script
  is started without the variables the one-file program's bootloader left in this process's environment
  (``procutil.fresh_start_environment``): the program it opens must unpack itself, not look for the temporary files
  of this one, which are gone by then.
* Only a copy that the installer set up (it has ``unins000.exe`` beside it) can install itself. A portable copy
  or one run from the source only shows the notice and points at the release page.
* The downloads are limited to GitHub's own hosts, and a redirect to any other host is refused.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app import __version__, paths, procutil
from app.preferences import Preferences

logger = logging.getLogger(__name__)

DEFAULT_API = "https://api.github.com"
#: The hosts a release's files come from (the download link of a release asset redirects to a CDN).
GITHUB_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
)
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

#: How soon after the program starts it looks, and how often after that.
FIRST_CHECK_AFTER = 20.0
CHECK_EVERY = 6 * 3600.0
HTTP_TIMEOUT = 20.0
#: What is read from GitHub, at most: the release description, the list of checksums, the installer.
MAX_API_BYTES = 512 * 1024
MAX_CHECKSUM_BYTES = 64 * 1024
MAX_INSTALLER_BYTES = 400 * 1024 * 1024
#: How much of the release's notes the page is given.
MAX_NOTES = 6000

INSTALLER_NAME = re.compile(r"^CheapTrader-(\d+\.\d+\.\d+)-setup\.exe$")
CHECKSUMS_NAME = "SHA256SUMS.txt"
VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
CHECKSUM_LINE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(\S.*?)\s*$")

#: What the installer is asked to do: no windows, no questions, no restart of Windows, close what uses its files.
INSTALLER_ARGS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS")
#: The program, opened again after the installer: it finds the window of the program it replaced.
RELAUNCH_ARGS = ("--reconnect",)
#: What the script writes as its very first act: the program closes only after it has seen this, so a script
#: that never runs (PowerShell blocked on this PC) cannot leave the user with a closed program and no update.
STARTED_NOTE = "update-started.flag"
#: How long the script is given to show that it is running.
SCRIPT_START_WITHIN = 20.0
#: The folder (in the data folder) that the files of an update are in.
UPDATES_FOLDER = "updates"
#: What the script holds open, and locked, for as long as it runs. The installer cannot replace the program while a
#: copy of it runs, and gives up (exit code 5) when it cannot; a user who starts the program again meanwhile (it has
#: closed, and nothing else is showing) did exactly that. A start finds this lock held and waits (``update_running``).
LOCK_NOTE = "installing.lock"


def update_running(folder: Path) -> bool:
    """Is the script that installs an update running? It holds ``installing.lock`` in ``folder`` for as long as it does.
    A lock that nobody holds is not mistaken for one that is: the system lets go of it when the script ends, however."""
    try:
        with (Path(folder) / LOCK_NOTE).open("r+b"):
            return False
    except PermissionError:  # someone holds it, and shares it with nobody
        return True
    except OSError:  # there is no such file: no update has been run
        return False


class UpdateError(Exception):
    """Something went wrong that the user can be told in a sentence."""


def parse_version(text: str) -> tuple[int, int, int] | None:
    """``"v0.1.2"`` / ``"0.1.2"`` -> ``(0, 1, 2)``; anything else (a pre-release, a word) -> None."""
    match = VERSION.match(text.strip()) if isinstance(text, str) else None
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    name: str
    notes: str
    page: str
    published: str
    installer: Asset | None
    checksums: Asset | None


def installed_by_setup() -> bool:
    """Was this copy put here by the installer (which leaves an uninstaller beside it)?"""
    if not paths.frozen():
        return False
    try:
        return any(paths.app_dir().glob("unins*.exe"))
    except OSError:
        return False


def release_from_json(data: Any) -> Release | None:
    """The newest *published* release of a GitHub reply, or None when it is not one we can use."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    parsed = parse_version(tag)
    if parsed is None:
        return None
    version = ".".join(str(n) for n in parsed)
    installer = checksums = None
    for item in data.get("assets") or []:
        if not isinstance(item, dict):
            continue
        name, url = str(item.get("name") or ""), str(item.get("browser_download_url") or "")
        size = item.get("size") if isinstance(item.get("size"), int) else 0
        match = INSTALLER_NAME.match(name)
        if match and match[1] == version and url:
            installer = Asset(name, url, size)
        elif name == CHECKSUMS_NAME and url:
            checksums = Asset(name, url, size)
    notes = str(data.get("body") or "").replace("\r\n", "\n").strip()
    return Release(
        version=version,
        tag=tag,
        name=str(data.get("name") or f"CheapTrader {version}"),
        notes=notes[:MAX_NOTES],
        page=str(data.get("html_url") or ""),
        published=str(data.get("published_at") or ""),
        installer=installer,
        checksums=checksums,
    )


def checksum_for(listing: str, filename: str) -> str | None:
    """The SHA-256 a ``SHA256SUMS.txt`` gives for ``filename`` (lower case), if it lists it."""
    for line in listing.splitlines():
        match = CHECKSUM_LINE.match(line.strip())
        if match and match[2] == filename:
            return match[1].lower()
    return None


def ps_quote(text: str) -> str:
    """A PowerShell single-quoted string (a quote inside is doubled)."""
    return "'" + text.replace("'", "''") + "'"


def install_script(exe: Path, setup: Path, result: Path, version: str, started: Path | None = None, lock: Path | None = None) -> str:
    """The script that runs the installer once the program has closed (see the module's docstring).
    The file named by lock is held, locked, for as long as the script runs, and the file named by started is written
    first of all, to show that the script is running (so, once that is seen, the lock is held)."""
    args = ",".join(ps_quote(a) for a in INSTALLER_ARGS)
    relaunch = ",".join(ps_quote(a) for a in RELAUNCH_ARGS)
    hold = (
        [
            "$lock = $null",
            f"try {{ $lock = [System.IO.File]::Open({ps_quote(str(lock))}, 'OpenOrCreate', 'ReadWrite', 'None') }} catch {{ }}",
        ]
        if lock
        else []
    )
    first = [*hold, *([f"Set-Content -LiteralPath {ps_quote(str(started))} -Value '1'"] if started else [])]
    return "\n".join(
        [
            *first,
            "$ErrorActionPreference = 'Continue'",
            f"$exe = {ps_quote(str(exe))}",
            f"$setup = {ps_quote(str(setup))}",
            f"$result = {ps_quote(str(result))}",
            # up to 90 s for the program to let go of its file (its helper processes close with it)
            "for ($i = 0; $i -lt 180; $i++) {",
            "  try { $f = [System.IO.File]::Open($exe, 'Open', 'ReadWrite', 'None'); $f.Close(); break }",
            "  catch { Start-Sleep -Milliseconds 500 }",
            "}",
            f"$p = Start-Process -FilePath $setup -ArgumentList {args} -Wait -PassThru",
            "$code = if ($p) { $p.ExitCode } else { -1 }",
            "$stamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()",
            f"$json = '{{\"version\":\"{version}\",\"exit_code\":' + $code + ',\"finished\":' + $stamp + '}}'",
            "Set-Content -LiteralPath $result -Value $json -Encoding UTF8",
            "Remove-Item -LiteralPath $setup -Force -ErrorAction SilentlyContinue",
            f"Start-Process -FilePath $exe -ArgumentList {relaunch}",
            "if ($lock) { $lock.Close() }",
        ]
    )


class Updater:
    """Knows what the newest release is, and installs it when asked. Every method is safe to call from any thread."""

    def __init__(
        self,
        prefs: Preferences,
        *,
        repo: str,
        api: str = DEFAULT_API,
        default_enabled: bool = True,
        version: str = __version__,
        first_check_after: float = FIRST_CHECK_AFTER,
        check_every: float = CHECK_EVERY,
        data_dir=None,
    ) -> None:
        self.prefs = prefs
        self.repo = repo.strip().strip("/")
        self.api = api.rstrip("/")
        self.default_enabled = default_enabled
        self.version = version
        self.first_check_after = first_check_after
        self.check_every = check_every
        self._data_dir = data_dir  # a function giving the folder (the data folder can move: tests, CT_DATA_DIR)
        self._lock = threading.RLock()
        self._release: Release | None = None
        self._checked_at: float | None = None
        self._error: str | None = None
        self._phase = "idle"  # idle | downloading | verifying | installing | failed
        self._message = ""
        self._progress = (0, 0)
        self._result: dict[str, Any] | None = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._timer: threading.Thread | None = None
        host = urlsplit(self.api).hostname or ""
        #: Where files may come from. With the real API: GitHub. With another one (tests, a fork's mirror): that host.
        self.hosts = GITHUB_HOSTS if self.api == DEFAULT_API else frozenset({host})
        self._read_result()

    # -- what the user chose -------------------------------------------------------------------
    def enabled(self) -> bool:
        chosen = self.prefs.get("check_updates")
        return self.default_enabled if chosen is None else bool(chosen)

    def set_enabled(self, enabled: bool) -> None:
        self.prefs.set("check_updates", bool(enabled))

    def skipped(self) -> str | None:
        value = self.prefs.get("update_skipped")
        return value if isinstance(value, str) else None

    def skip(self, version: str) -> None:
        self.prefs.set("update_skipped", version if parse_version(version) else None)

    # -- where things are ----------------------------------------------------------------------
    def folder(self) -> Path:
        base = self._data_dir() if self._data_dir else paths.data_dir()
        return Path(base) / UPDATES_FOLDER

    def _result_file(self) -> Path:
        return self.folder() / "update-result.json"

    def can_install(self) -> bool:
        return installed_by_setup()

    # -- looking --------------------------------------------------------------------------------
    def _check_url(self, url: str) -> None:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if host not in self.hosts:
            raise UpdateError(f"A download was sent to {host or 'an unknown address'}, which is not GitHub. It was not followed.")
        if parts.scheme != "https" and not (parts.scheme == "http" and host in LOOPBACK and self.api != DEFAULT_API):
            raise UpdateError("A download was not offered over HTTPS and was not followed.")

    def _opener(self) -> urllib.request.OpenerDirector:
        updater = self

        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
                updater._check_url(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        return urllib.request.build_opener(Redirect)

    def _open(self, url: str, accept: str):
        self._check_url(url)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": accept,
                "User-Agent": f"CheapTrader/{self.version}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            return self._opener().open(request, timeout=HTTP_TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                raise UpdateError("GitHub is not answering requests from this address for now. It will be tried again later.") from exc
            if exc.code == 404:
                raise UpdateError("GitHub has no release of CheapTrader to offer yet.") from exc
            raise UpdateError(f"GitHub answered with an error ({exc.code}).") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise UpdateError("Could not reach GitHub. Check the internet connection.") from exc

    def _read_limited(self, url: str, accept: str, limit: int) -> bytes:
        with self._open(url, accept) as response:
            body = response.read(limit + 1)
        if len(body) > limit:
            raise UpdateError("GitHub's answer was larger than expected and was not used.")
        return body

    def check(self) -> dict[str, Any]:
        """Ask GitHub for the latest release now. Never raises: a failure is part of the status."""
        try:
            body = self._read_limited(f"{self.api}/repos/{self.repo}/releases/latest", "application/vnd.github+json", MAX_API_BYTES)
            try:
                release = release_from_json(json.loads(body))
            except ValueError as exc:
                raise UpdateError("GitHub's answer could not be read.") from exc
            with self._lock:
                self._release, self._error = release, None
        except UpdateError as exc:
            logger.info("update check failed: %s", exc)
            with self._lock:
                self._error = str(exc)
        except Exception:  # noqa: BLE001 - a check must never take the program down
            logger.exception("update check failed")
            with self._lock:
                self._error = "The check for a new version failed."
        finally:
            with self._lock:
                self._checked_at = time.time()
        return self.status()

    # -- the background look ----------------------------------------------------------------------
    def start(self) -> None:
        if self._timer is not None:
            return
        self._stop.clear()
        self._timer = threading.Thread(target=self._loop, name="update-check", daemon=True)
        self._timer.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if self._stop.wait(self.first_check_after):
            return
        while True:
            if self.enabled():
                self.check()
            if self._stop.wait(self.check_every):
                return

    # -- what the page is told ------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            release = self._release
            available = bool(release and is_newer(release.version, self.version))
            done, total = self._progress
            return {
                "enabled": self.enabled(),
                "current": self.version,
                "latest": release.version if release else None,
                "available": available,
                "skipped": bool(available and release and release.version == self.skipped()),
                "can_install": bool(available and release and release.installer and release.checksums and self.can_install()),
                "installable_here": self.can_install(),
                "notes": release.notes if (release and available) else "",
                "page": release.page if release else "",
                "published": release.published if release else "",
                "size": release.installer.size if (release and release.installer) else 0,
                "checked_at": int(self._checked_at) if self._checked_at else None,
                "error": self._error,
                "phase": self._phase,
                "message": self._message,
                "done": done,
                "total": total,
                "result": self._result,
            }

    # -- installing -----------------------------------------------------------------------------------
    def install(self, quit_app) -> dict[str, Any]:
        """Start downloading the newest release and installing it. ``quit_app`` closes the program once the
        installer is on its way. Raises ``UpdateError`` (with the reason) when it cannot be done."""
        with self._lock:
            release = self._release
            if release is None or not is_newer(release.version, self.version):
                raise UpdateError("There is no newer version to install.")
            if not self.can_install():
                raise UpdateError("This copy of CheapTrader was not set up by the installer, so it cannot install itself. Download the new version from the release page.")
            if release.installer is None or release.checksums is None:
                raise UpdateError("The release has no installer with a list of checksums, so it is not installed from here. Download it from the release page.")
            if self._worker is not None and self._worker.is_alive():
                raise UpdateError("An update is already being installed.")
            self._phase, self._message, self._progress, self._result = "downloading", "", (0, release.installer.size), None
            self._worker = threading.Thread(target=self._run_install, args=(release, quit_app), name="update-install", daemon=True)
            self._worker.start()
        return self.status()

    def _fail(self, text: str) -> None:
        with self._lock:
            self._phase, self._message = "failed", text
        logger.warning("update failed: %s", text)

    def _run_install(self, release: Release, quit_app) -> None:
        try:
            assert release.installer is not None and release.checksums is not None
            setup = self.download(release.installer, release.checksums)
            self._launch(setup, release.version, quit_app)
        except UpdateError as exc:
            self._fail(str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("installing the update failed")
            self._fail("The update could not be installed. The details are in the log.")

    def download(self, installer: Asset, checksums: Asset) -> Path:
        """Fetch the installer and prove it is the published one; returns where it is."""
        wanted = checksum_for(self._read_limited(checksums.url, "text/plain", MAX_CHECKSUM_BYTES).decode("utf-8", "replace"), installer.name)
        if wanted is None:
            raise UpdateError(f"{CHECKSUMS_NAME} does not list {installer.name}, so the download cannot be checked and was not made.")
        folder = self.folder()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / installer.name
        part = folder / (installer.name + ".part")
        digest = hashlib.sha256()
        done = 0
        try:
            with self._open(installer.url, "application/octet-stream") as response, part.open("wb") as out:
                total = int(response.headers.get("Content-Length") or installer.size or 0)
                if total > MAX_INSTALLER_BYTES:
                    raise UpdateError("The installer is larger than expected and was not downloaded.")
                with self._lock:
                    self._progress = (0, total)
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if done > MAX_INSTALLER_BYTES:
                        raise UpdateError("The download is larger than expected and was stopped.")
                    with self._lock:
                        self._progress = (done, total)
            if total and done != total:
                raise UpdateError("The download was cut off. Try again.")
            with self._lock:
                self._phase = "verifying"
            if digest.hexdigest() != wanted:
                raise UpdateError(f"The download does not match the checksum published with the release ({installer.name}), so it was thrown away.")
            os.replace(part, target)
            return target
        except UpdateError:
            part.unlink(missing_ok=True)
            raise
        except http.client.HTTPException as exc:  # a connection that ended before the file did
            part.unlink(missing_ok=True)
            raise UpdateError("The download was cut off. Try again.") from exc
        except OSError as exc:
            part.unlink(missing_ok=True)
            raise UpdateError(f"The installer could not be downloaded or saved ({exc.strerror or exc}).") from exc

    def _launch(self, setup: Path, version: str, quit_app) -> None:
        """Hand over to the script that installs once this program has closed, then close it."""
        if os.name != "nt":
            raise UpdateError("Installing an update works on Windows only.")
        exe = Path(paths.app_dir()) / "CheapTrader.exe"
        started = self.folder() / STARTED_NOTE
        started.unlink(missing_ok=True)
        script = install_script(exe, setup, self._result_file(), version, started, self.folder() / LOCK_NOTE)
        with self._lock:
            self._phase, self._message = "installing", f"Closing CheapTrader to install {version}."
        # -Command takes the script as text, so it does not matter that Windows may forbid running .ps1 files
        process = subprocess.Popen(  # noqa: S603 - a fixed command with quoted paths
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            cwd=str(self.folder()),
            env=procutil.fresh_start_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        if not self._script_is_running(started, process):
            try:
                process.kill()
            except OSError:
                pass
            raise UpdateError(
                "The program that installs the update did not start (PowerShell may be blocked on this PC), so nothing was "
                "changed and CheapTrader stays open. Download the new version from the release page."
            )
        logger.info("update %s downloaded and verified; closing to install it", version)
        if quit_app is not None:
            quit_app()

    def _script_is_running(self, started: Path, process, within: float | None = None) -> bool:
        """Wait for the script's first act; False when it ended without it or never got round to it."""
        deadline = time.monotonic() + (SCRIPT_START_WITHIN if within is None else within)
        while time.monotonic() < deadline:
            if started.exists():
                return True
            if process.poll() is not None:
                return started.exists()
            time.sleep(0.05)
        return started.exists()

    # -- how the last install went ---------------------------------------------------------------------
    def _read_result(self) -> None:
        """The script leaves a note about the installer's exit code; it is read once, on the next start."""
        try:
            note = json.loads(self._result_file().read_text(encoding="utf-8-sig"))
            self._result_file().unlink(missing_ok=True)
        except (OSError, ValueError):
            return
        if not isinstance(note, dict):
            return
        version, code = str(note.get("version") or ""), note.get("exit_code")
        ok = code == 0 and version == self.version
        if ok:
            message = f"Updated to {version}."
        elif code == 0:
            message = f"The installer finished, but this is still version {self.version}."
        else:
            message = f"The installer for {version} did not finish (exit code {code}). The previous version is still in use."
        self._result = {"version": version, "ok": ok, "message": message}
