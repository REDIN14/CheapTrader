"""The updater: looking for a newer release, checking a download, handing over to the installer.

GitHub is played by a small server on this machine; nothing here reaches the real one, and nothing runs an
installer (the launch is checked by what it would start).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.updater as updater_module
from app.main import app
from app.preferences import Preferences
from app.state import get_state
from app.updater import (
    Asset,
    UpdateError,
    Updater,
    checksum_for,
    install_script,
    is_newer,
    parse_version,
    ps_quote,
    release_from_json,
)

REPO = "someone/CheapTrader"
INSTALLER = b"MZ-this-stands-for-an-installer" * 4000  # ~124 KB


def release_payload(version: str, base: str, size: int, *, with_installer: bool = True, draft: bool = False) -> dict:
    """What GitHub answers for `releases/latest`, trimmed to what the updater reads."""
    assets = [{"name": "SHA256SUMS.txt", "browser_download_url": f"{base}/dl/SHA256SUMS.txt", "size": 100}]
    if with_installer:
        assets.append({"name": f"CheapTrader-{version}-setup.exe", "browser_download_url": f"{base}/dl/CheapTrader-{version}-setup.exe", "size": size})
    return {
        "tag_name": f"v{version}",
        "name": f"CheapTrader {version}",
        "body": f"## Install\n\nRun the installer.\n\n## What is in {version}\n\n* A new thing.",
        "html_url": f"https://github.com/{REPO}/releases/tag/v{version}",
        "published_at": "2026-10-02T12:00:00Z",
        "draft": draft,
        "prerelease": False,
        "assets": assets,
    }


class FakeGitHub:
    """The bits of GitHub the updater talks to: a latest release, its files, and a few ways for them to go wrong."""

    def __init__(self) -> None:
        self.version = "0.2.0"
        self.installer = INSTALLER
        self.listed_hash: str | None = None  # None: the real hash of ``installer``
        self.list_installer = True
        self.api_status = 200
        self.api_body: bytes | None = None
        self.redirect_installer_to: str | None = None
        self.truncate_installer = False
        self.draft = False
        self.hits: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # quiet
                pass

            def _send(self, code: int, body: bytes, kind: str = "application/octet-stream", declared: int | None = None) -> None:
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body) if declared is None else declared))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                outer.hits.append(self.path)
                if self.path == f"/repos/{REPO}/releases/latest":
                    if outer.api_status != 200:
                        self._send(outer.api_status, b"{}", "application/json")
                    else:
                        self._send(200, outer.api_body if outer.api_body is not None else json.dumps(outer.release()).encode(), "application/json")
                elif self.path == f"/dl/CheapTrader-{outer.version}-setup.exe":
                    if outer.redirect_installer_to:
                        self.send_response(302)
                        self.send_header("Location", outer.redirect_installer_to)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    elif outer.truncate_installer:
                        self._send(200, outer.installer[: len(outer.installer) // 2], declared=len(outer.installer))
                    else:
                        self._send(200, outer.installer)
                elif self.path == "/dl/SHA256SUMS.txt":
                    digest = outer.listed_hash or hashlib.sha256(outer.installer).hexdigest()
                    line = f"{digest}  CheapTrader-{outer.version}-setup.exe\n" if outer.list_installer else "\n"
                    self._send(200, line.encode(), "text/plain")
                else:
                    self._send(404, b"not here")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def release(self) -> dict:
        return release_payload(self.version, self.base, len(self.installer), with_installer=self.list_installer, draft=self.draft)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def github():
    fake = FakeGitHub()
    yield fake
    fake.close()


@pytest.fixture
def prefs(tmp_path) -> Preferences:
    return Preferences(tmp_path / "preferences.json")


@pytest.fixture
def make(github, prefs, tmp_path):
    def build(**kw) -> Updater:
        options = {"repo": REPO, "api": github.base, "version": "0.1.1", "data_dir": lambda: tmp_path / "data"}
        options.update(kw)
        return Updater(prefs, **options)

    return build


# -- versions ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [("0.1.2", (0, 1, 2)), ("v10.20.30", (10, 20, 30)), (" v1.0.0 ", (1, 0, 0)), ("1.0", None), ("1.0.0-beta", None), ("latest", None), ("", None)],
)
def test_versions_are_read_strictly(text: str, expected) -> None:
    assert parse_version(text) == expected


def test_a_version_is_newer_by_its_numbers_not_its_letters() -> None:
    assert is_newer("0.1.10", "0.1.9")
    assert is_newer("v0.2.0", "0.1.99")
    assert not is_newer("0.1.1", "0.1.1")
    assert not is_newer("0.1.0", "0.1.1")
    assert not is_newer("nightly", "0.1.1")
    assert not is_newer("0.2.0", "dev")


# -- reading GitHub's answer ---------------------------------------------------------------------------------
def test_a_release_gives_its_installer_and_checksums() -> None:
    release = release_from_json(release_payload("0.3.0", "https://github.com/x", 1))
    assert release is not None and release.version == "0.3.0"
    assert release.installer == Asset("CheapTrader-0.3.0-setup.exe", "https://github.com/x/dl/CheapTrader-0.3.0-setup.exe", 1)
    assert release.checksums is not None and release.checksums.name == "SHA256SUMS.txt"
    assert release.notes.startswith("## Install")


@pytest.mark.parametrize(
    "change",
    [
        {"draft": True},
        {"prerelease": True},
        {"tag_name": "nightly"},
        {"tag_name": "v1.0.0-rc1"},
    ],
)
def test_drafts_pre_releases_and_odd_tags_are_not_offered(change: dict) -> None:
    data = {"tag_name": "v0.2.0", "draft": False, "prerelease": False, "assets": []}
    assert release_from_json({**data, **change}) is None


def test_only_the_installer_of_that_version_counts() -> None:
    data = {
        "tag_name": "v0.2.0",
        "assets": [
            {"name": "CheapTrader-0.1.0-setup.exe", "browser_download_url": "https://github.com/a", "size": 1},
            {"name": "CheapTrader-0.2.0-win64.zip", "browser_download_url": "https://github.com/b", "size": 1},
            {"name": "evil-setup.exe", "browser_download_url": "https://github.com/c", "size": 1},
        ],
    }
    release = release_from_json(data)
    assert release is not None and release.installer is None and release.checksums is None


@pytest.mark.parametrize("junk", [None, [], "x", 5, {"tag_name": None}])
def test_nonsense_is_not_a_release(junk) -> None:
    assert release_from_json(junk) is None


def test_checksums_are_found_by_file_name() -> None:
    listing = "\n".join(
        [
            f"{'a' * 64}  CheapTrader-0.2.0-win64.zip",
            f"{'B' * 64} *CheapTrader-0.2.0-setup.exe",
            "not a checksum line",
        ]
    )
    assert checksum_for(listing, "CheapTrader-0.2.0-setup.exe") == "b" * 64
    assert checksum_for(listing, "CheapTrader-0.3.0-setup.exe") is None
    assert checksum_for("", "x") is None


# -- looking ----------------------------------------------------------------------------------------------
def test_a_newer_release_is_reported_and_nothing_is_downloaded(make, github) -> None:
    status = make().check()
    assert (status["current"], status["latest"], status["available"]) == ("0.1.1", "0.2.0", True)
    assert status["notes"].startswith("## Install") and status["page"].endswith("/v0.2.0")
    assert status["size"] == len(INSTALLER) and status["error"] is None and status["checked_at"]
    assert github.hits == [f"/repos/{REPO}/releases/latest"]  # the installer itself was not asked for


def test_the_same_or_an_older_release_is_not_an_update(make, github) -> None:
    github.version = "0.1.1"
    status = make().check()
    assert status["latest"] == "0.1.1" and not status["available"] and status["notes"] == ""
    github.version = "0.1.0"
    assert not make().check()["available"]


@pytest.mark.parametrize(
    "code,words",
    [(404, "no release"), (403, "not answering"), (429, "not answering"), (500, "error (500)")],
)
def test_github_saying_no_is_told_in_words(make, github, code: int, words: str) -> None:
    github.api_status = code
    status = make().check()
    assert not status["available"] and words in status["error"]


def test_an_answer_that_is_not_json_is_not_fatal(make, github) -> None:
    github.api_body = b"<html>"
    status = make().check()
    assert status["error"] == "GitHub's answer could not be read." and status["latest"] is None


def test_an_answer_that_is_too_big_is_not_used(make, github, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updater_module, "MAX_API_BYTES", 100)
    assert "larger than expected" in make().check()["error"]


def test_no_connection_is_told_in_words(make, github) -> None:
    github.close()
    assert "Could not reach GitHub" in make().check()["error"]


def test_a_failed_look_keeps_what_was_known(make, github) -> None:
    updater = make()
    assert updater.check()["available"]
    github.api_status = 500
    status = updater.check()
    assert status["available"] and status["error"]  # the earlier answer still stands, and the failure is shown


def test_files_are_only_fetched_from_github(monkeypatch: pytest.MonkeyPatch, tmp_path, prefs) -> None:
    real = Updater(prefs, repo=REPO, version="0.1.1", data_dir=lambda: tmp_path)
    for bad in ("http://github.com/x", "https://example.com/x", "https://github.com.evil.example/x", "file:///C:/Windows", "ftp://github.com/x"):
        with pytest.raises(UpdateError):
            real._check_url(bad)
    for good in ("https://github.com/a/b/releases/download/v1/x.exe", "https://objects.githubusercontent.com/x", "https://api.github.com/repos/a/b"):
        real._check_url(good)


def test_a_redirect_to_another_host_is_refused(make, github) -> None:
    github.redirect_installer_to = "http://example.invalid/evil.exe"
    release = release_from_json(github.release())
    assert release is not None and release.installer and release.checksums
    with pytest.raises(UpdateError, match="not GitHub"):
        make().download(release.installer, release.checksums)


# -- what the user chose ---------------------------------------------------------------------------------------
def test_the_check_follows_the_settings_until_the_user_says_otherwise(make, prefs) -> None:
    on, off = make(default_enabled=True), make(default_enabled=False)
    assert on.enabled() and not off.enabled()
    off.set_enabled(True)
    assert on.enabled() and off.enabled()
    on.set_enabled(False)
    assert not on.enabled() and not off.enabled()  # one preference file, one answer


def test_a_skipped_version_is_hidden_but_the_next_one_is_not(make, github) -> None:
    updater = make()
    updater.check()
    updater.skip("0.2.0")
    assert updater.status()["skipped"] is True
    github.version = "0.3.0"
    status = updater.check()
    assert status["latest"] == "0.3.0" and status["skipped"] is False
    updater.skip("nonsense")
    assert updater.skipped() is None


def test_the_background_look_waits_and_respects_the_switch(make, github, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    updater = make(first_check_after=0.05, check_every=0.05, default_enabled=False)
    monkeypatch.setattr(updater, "check", lambda: calls.append(1) or {})
    updater.start()
    threading.Event().wait(0.3)
    assert calls == []  # switched off: no look
    updater.set_enabled(True)
    threading.Event().wait(0.3)
    updater.stop()
    assert calls  # switched on: it looks again by itself


# -- installing --------------------------------------------------------------------------------------------------
@pytest.fixture
def installable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(updater_module, "installed_by_setup", lambda: True)


def test_a_copy_that_was_not_set_up_by_the_installer_cannot_install_itself(make, github) -> None:
    updater = make()
    status = updater.check()
    assert status["available"] and not status["can_install"] and not status["installable_here"]
    with pytest.raises(UpdateError, match="not set up by the installer"):
        updater.install(lambda: None)


def test_a_release_without_what_is_needed_is_not_installed_from_here(make, github, installable) -> None:
    github.list_installer = False
    updater = make()
    status = updater.check()
    assert status["available"] and not status["can_install"]
    with pytest.raises(UpdateError, match="no installer"):
        updater.install(lambda: None)


def test_there_is_nothing_to_install_before_a_look(make, installable) -> None:
    with pytest.raises(UpdateError, match="no newer version"):
        make().install(lambda: None)


def test_the_download_is_checked_against_the_published_checksum(make, github, installable) -> None:
    updater = make()
    updater.check()
    release = updater._release
    setup = updater.download(release.installer, release.checksums)
    assert setup.read_bytes() == INSTALLER and setup.name == "CheapTrader-0.2.0-setup.exe"
    assert not list(setup.parent.glob("*.part"))
    assert updater.status()["done"] == updater.status()["total"] == len(INSTALLER)


def test_a_download_that_does_not_match_is_thrown_away(make, github, installable) -> None:
    github.listed_hash = "0" * 64
    updater = make()
    updater.check()
    with pytest.raises(UpdateError, match="does not match the checksum"):
        updater.download(updater._release.installer, updater._release.checksums)
    assert list(updater.folder().glob("*")) == []  # neither the file nor a half file is left


def test_a_checksum_list_without_the_installer_stops_before_downloading(make, github, installable) -> None:
    updater = make()
    updater.check()
    release = updater._release
    github.list_installer = False  # SHA256SUMS.txt now lists nothing
    with pytest.raises(UpdateError, match="does not list"):
        updater.download(release.installer, release.checksums)
    assert not any("setup.exe" in hit for hit in github.hits)


def test_a_cut_off_download_is_not_kept(make, github, installable) -> None:
    github.truncate_installer = True
    updater = make()
    updater.check()
    with pytest.raises(UpdateError, match="cut off"):
        updater.download(updater._release.installer, updater._release.checksums)
    assert list(updater.folder().glob("*")) == []


def test_an_installer_that_is_far_too_big_is_not_downloaded(make, github, installable, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updater_module, "MAX_INSTALLER_BYTES", 1000)
    updater = make()
    updater.check()
    with pytest.raises(UpdateError, match="larger than expected"):
        updater.download(updater._release.installer, updater._release.checksums)
    assert list(updater.folder().glob("*")) == []


def wait_for(updater: Updater, phases: set[str], seconds: float = 10.0) -> dict:
    deadline = threading.Event()
    for _ in range(int(seconds * 50)):
        status = updater.status()
        if status["phase"] in phases:
            return status
        deadline.wait(0.02)
    raise AssertionError(f"still {updater.status()['phase']!r}")


def test_installing_downloads_checks_launches_and_closes(make, github, installable, monkeypatch: pytest.MonkeyPatch) -> None:
    updater = make()
    updater.check()
    seen: list[tuple] = []
    monkeypatch.setattr(updater, "_launch", lambda setup, version, quit_app: (seen.append((setup.name, version)), quit_app()))
    closed: list[bool] = []
    first = updater.install(lambda: closed.append(True))
    assert first["phase"] == "downloading"
    deadline = threading.Event()
    for _ in range(500):
        if closed:
            break
        deadline.wait(0.02)
    assert seen == [("CheapTrader-0.2.0-setup.exe", "0.2.0")] and closed == [True]


def test_a_second_install_is_refused_while_one_is_running(make, github, installable, monkeypatch: pytest.MonkeyPatch) -> None:
    updater = make()
    updater.check()
    gate = threading.Event()
    monkeypatch.setattr(updater, "download", lambda *a: (gate.wait(5), Path("x"))[1])
    monkeypatch.setattr(updater, "_launch", lambda *a: None)
    updater.install(lambda: None)
    with pytest.raises(UpdateError, match="already being installed"):
        updater.install(lambda: None)
    gate.set()


def test_a_failed_install_says_why_and_can_be_tried_again(make, github, installable, monkeypatch: pytest.MonkeyPatch) -> None:
    github.listed_hash = "f" * 64
    updater = make()
    updater.check()
    closed: list[bool] = []
    updater.install(lambda: closed.append(True))
    status = wait_for(updater, {"failed"})
    assert "does not match" in status["message"] and closed == []  # the program is not closed for a bad download
    github.listed_hash = None
    monkeypatch.setattr(updater, "_launch", lambda *a: None)
    updater.install(lambda: None)
    assert updater.status()["phase"] in {"downloading", "verifying", "installing", "idle"}


class FakeProcess:
    """What subprocess.Popen returns, for the launch tests: still running, and it can be killed."""

    def __init__(self) -> None:
        self.killed = False

    def poll(self):
        return None

    def kill(self) -> None:
        self.killed = True


@pytest.mark.skipif(os.name != "nt", reason="the installer is a Windows program")
def test_the_launch_runs_a_script_and_then_closes_the_program(tmp_path, monkeypatch: pytest.MonkeyPatch, make) -> None:
    updater = make()
    monkeypatch.setattr(updater_module.paths, "app_dir", lambda: tmp_path / "Program Files" / "O'Brien's CheapTrader")
    started: list[dict] = []
    folder = tmp_path / "upd"
    folder.mkdir()

    def popen(cmd, **kw):
        started.append({"cmd": cmd, **kw})
        (folder / updater_module.STARTED_NOTE).write_text("1")  # the script's first act
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", popen)
    # what the one-file program's bootloader leaves in the environment of the running program
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", str(tmp_path / "_MEI123456"))
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", str(tmp_path / "CheapTrader.exe"))
    order: list[str] = []
    monkeypatch.setattr(updater, "folder", lambda: folder)
    setup = folder / "CheapTrader-0.2.0-setup.exe"
    updater._launch(setup, "0.2.0", lambda: order.append("closed" if started else "closed-too-early"))
    assert order == ["closed"]  # the script is on its way before the program closes
    [call] = started
    assert call["cmd"][0] == "powershell.exe" and "-Command" in call["cmd"] and "-NoProfile" in call["cmd"]
    assert "-ExecutionPolicy" not in call["cmd"] and "-WindowStyle" not in call["cmd"]  # nothing that looks like malware to a scanner
    script = call["cmd"][-1]
    assert "O''Brien''s CheapTrader" in script  # a quote in a path is doubled, not left to end the string
    assert "CheapTrader-0.2.0-setup.exe" in script and "'/SILENT'" in script and "'--reconnect'" in script
    assert script.splitlines()[0].startswith("Set-Content -LiteralPath") and updater_module.STARTED_NOTE in script.splitlines()[0]
    assert call["cwd"] == str(folder)
    # The program it opens again must unpack itself: with these it would look for the temporary files of the one
    # that has just closed, find them gone, and stop with "Failed to load Python DLL".
    assert not [name for name in call["env"] if name.upper().startswith("_PYI_")]
    assert "PATH" in {name.upper() for name in call["env"]}  # everything else is passed on
    assert call["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert updater.status()["phase"] == "installing"


@pytest.mark.skipif(os.name != "nt", reason="the installer is a Windows program")
def test_a_script_that_never_starts_leaves_the_program_open(tmp_path, monkeypatch: pytest.MonkeyPatch, make) -> None:
    """PowerShell may be forbidden on this PC: then the update stops, and the program stays as it is."""
    updater = make()
    monkeypatch.setattr(updater_module, "SCRIPT_START_WITHIN", 0.3)
    process = FakeProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: process)
    folder = tmp_path / "upd"
    folder.mkdir()
    monkeypatch.setattr(updater, "folder", lambda: folder)
    closed: list[bool] = []
    with pytest.raises(UpdateError, match="did not start"):
        updater._launch(folder / "CheapTrader-0.2.0-setup.exe", "0.2.0", lambda: closed.append(True))
    assert closed == [] and process.killed


@pytest.mark.skipif(os.name != "nt", reason="the installer is a Windows program")
def test_a_script_that_ends_at_once_without_starting_is_noticed_without_waiting(tmp_path, monkeypatch: pytest.MonkeyPatch, make) -> None:
    updater = make()
    folder = tmp_path / "upd"
    folder.mkdir()
    monkeypatch.setattr(updater, "folder", lambda: folder)

    class Dead(FakeProcess):
        def poll(self):
            return 1

    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: Dead())
    began = time.monotonic()
    with pytest.raises(UpdateError, match="did not start"):
        updater._launch(folder / "x.exe", "0.2.0", lambda: pytest.fail("closed"))
    assert time.monotonic() - began < 5  # it did not sit out the whole wait


@pytest.mark.skipif(os.name != "nt", reason="PowerShell")
def test_the_script_is_valid_powershell(tmp_path) -> None:
    script = install_script(Path(r"C:\Users\A B\AppData\Local\Programs\O'Brien\CheapTrader.exe"), tmp_path / "s'etup.exe", tmp_path / "r.json", "0.2.0")
    file = tmp_path / "check.ps1"
    file.write_text(script, encoding="utf-8")
    parse = (
        "$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"{ps_quote(str(file))}, [ref]$null, [ref]$e); if ($e.Count) {{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}"
    )
    done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", parse], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"

STUB_SOURCE = """
using System;
using System.IO;
using System.Reflection;
class Stub {
  static int Main(string[] args) {
    File.WriteAllText(Assembly.GetExecutingAssembly().Location + ".log", string.Join("|", args));
    int code;
    return int.TryParse(Environment.GetEnvironmentVariable("STUB_EXIT"), out code) ? code : 0;
  }
}
"""


@pytest.fixture(scope="module")
def stub_exe(tmp_path_factory) -> Path:
    """A tiny program that writes its arguments next to itself and exits with the code in STUB_EXIT: the stand-in
    for both the installer and the program in the test of the real script."""
    if os.name != "nt" or not CSC.exists():
        pytest.skip("needs Windows and its C# compiler")
    folder = tmp_path_factory.mktemp("stub")
    (folder / "stub.cs").write_text(STUB_SOURCE, encoding="utf-8")
    subprocess.run([str(CSC), "/nologo", f"/out:{folder / 'stub.exe'}", str(folder / "stub.cs")], check=True, capture_output=True, timeout=120)
    return folder / "stub.exe"


def run_script(tmp_path: Path, stub_exe: Path, *, installer_exit: int = 0, hold_exe_for: float = 0.0):
    """Run the real hand-over script. With ``hold_exe_for`` the 'program' keeps its file open for that long first."""
    exe = tmp_path / "CheapTrader.exe"
    setup = tmp_path / "CheapTrader-0.2.0-setup.exe"
    shutil.copy(stub_exe, exe)
    shutil.copy(stub_exe, setup)
    result = tmp_path / "updates" / "update-result.json"
    result.parent.mkdir()
    script = install_script(exe, setup, result, "0.2.0", result.parent / updater_module.STARTED_NOTE)
    env = {**os.environ, "STUB_EXIT": str(installer_exit)}
    holding = exe.open("r+b") if hold_exe_for else None
    process = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        env=env,
        cwd=str(tmp_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started_installer = setup.with_name(setup.name + ".log")
    if holding is not None:
        time.sleep(hold_exe_for)
        assert not started_installer.exists(), "the installer ran while the program still held its file"
        holding.close()
    process.wait(timeout=120)
    relaunched = exe.with_name(exe.name + ".log")
    for _ in range(100):  # the program is opened without being waited for
        if relaunched.exists():
            break
        time.sleep(0.05)
    return exe, setup, result


@pytest.mark.skipif(os.name != "nt", reason="PowerShell")
def test_the_script_runs_the_installer_notes_the_result_and_opens_the_program(tmp_path, stub_exe) -> None:
    exe, setup, result = run_script(tmp_path, stub_exe)
    assert setup.with_name(setup.name + ".log").read_text() == "/SILENT|/SUPPRESSMSGBOXES|/NORESTART|/CLOSEAPPLICATIONS"
    note = json.loads(result.read_text(encoding="utf-8-sig"))
    assert note["version"] == "0.2.0" and note["exit_code"] == 0 and note["finished"] > 0
    assert not setup.exists()  # the downloaded installer is cleared away
    assert (result.parent / updater_module.STARTED_NOTE).exists()  # the script said it had started
    assert exe.with_name(exe.name + ".log").read_text() == "--reconnect"  # and the program is opened again


@pytest.mark.skipif(os.name != "nt", reason="PowerShell")
def test_the_script_waits_until_the_program_has_let_go_of_its_file(tmp_path, stub_exe) -> None:
    exe, setup, result = run_script(tmp_path, stub_exe, hold_exe_for=2.0)
    assert json.loads(result.read_text(encoding="utf-8-sig"))["exit_code"] == 0
    assert exe.with_name(exe.name + ".log").exists()


@pytest.mark.skipif(os.name != "nt", reason="PowerShell")
def test_a_failing_installer_is_noted_and_the_program_is_still_opened(tmp_path, stub_exe) -> None:
    exe, setup, result = run_script(tmp_path, stub_exe, installer_exit=5)
    assert json.loads(result.read_text(encoding="utf-8-sig"))["exit_code"] == 5
    assert exe.with_name(exe.name + ".log").read_text() == "--reconnect"  # whatever is installed is opened, so the user is not left with nothing


# -- how the last install went ------------------------------------------------------------------------------------
def test_the_note_the_script_leaves_is_read_once(make, tmp_path) -> None:
    folder = tmp_path / "data" / "updates"
    folder.mkdir(parents=True)
    note = folder / "update-result.json"
    note.write_text(json.dumps({"version": "0.1.1", "exit_code": 0, "finished": 1}), encoding="utf-8-sig")  # PowerShell writes a BOM
    updater = make(version="0.1.1")
    assert updater.status()["result"] == {"version": "0.1.1", "ok": True, "message": "Updated to 0.1.1."}
    assert not note.exists()
    assert make(version="0.1.1").status()["result"] is None


@pytest.mark.parametrize(
    "note,ok,words",
    [
        ({"version": "0.2.0", "exit_code": 5, "finished": 1}, False, "did not finish (exit code 5)"),
        ({"version": "0.2.0", "exit_code": 0, "finished": 1}, False, "still version 0.1.1"),
    ],
)
def test_an_install_that_did_not_take_is_reported(make, tmp_path, note: dict, ok: bool, words: str) -> None:
    folder = tmp_path / "data" / "updates"
    folder.mkdir(parents=True)
    (folder / "update-result.json").write_text(json.dumps(note))
    result = make().status()["result"]
    assert result["ok"] is ok and words in result["message"]


def test_a_damaged_note_is_ignored(make, tmp_path) -> None:
    folder = tmp_path / "data" / "updates"
    folder.mkdir(parents=True)
    (folder / "update-result.json").write_text("{nope")
    assert make().status()["result"] is None


# -- the routes ----------------------------------------------------------------------------------------------------
@pytest.fixture
def client(github, tmp_path, monkeypatch: pytest.MonkeyPatch):
    with TestClient(app) as test_client:
        state = get_state()
        state.updater = Updater(
            Preferences(tmp_path / "prefs.json"),
            repo=REPO,
            api=github.base,
            version="0.1.1",
            data_dir=lambda: tmp_path / "data",
        )
        yield test_client


def test_the_routes_show_check_skip_and_switch(client: TestClient, github) -> None:
    first = client.get("/api/update").json()
    assert first["available"] is False and first["checked_at"] is None and first["current"] == "0.1.1"
    checked = client.post("/api/update/check").json()
    assert checked["available"] is True and checked["latest"] == "0.2.0"
    assert client.get("/api/update").json()["latest"] == "0.2.0"
    assert client.post("/api/update/skip", json={"version": "0.2.0"}).json()["skipped"] is True
    assert client.post("/api/update/enabled", json={"enabled": False}).json()["enabled"] is False
    assert client.post("/api/update/enabled", json={"enabled": True}).json()["enabled"] is True


def test_install_over_the_api_says_why_it_cannot(client: TestClient) -> None:
    client.post("/api/update/check")
    refused = client.post("/api/update/install")
    assert refused.status_code == 409 and "not set up by the installer" in refused.json()["detail"]


def test_another_web_page_cannot_start_an_install(client: TestClient) -> None:
    client.post("/api/update/check")
    for path, body in (("/api/update/install", None), ("/api/update/skip", {"version": "0.2.0"}), ("/api/update/enabled", {"enabled": False})):
        refused = client.post(path, json=body, headers={"Origin": "https://evil.example"})
        assert refused.status_code == 403, path
