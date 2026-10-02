"""Small helpers for the child processes the server starts (the live feed, the MetaTrader
reader and trader, the indicator sandbox)."""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
from typing import IO

from app import paths


def module_command(module: str, *args: str) -> list[str]:
    """The command line that runs ``module`` as a program in a child process.

    In development that is ``python -m module``. The built program has no ``python`` to
    hand ``-m`` to: it is run again with ``--worker module`` instead (see ``dispatch``).
    """
    if paths.frozen():
        return [sys.executable, "--worker", module, *args]
    return [sys.executable, "-m", module, *args]


def script_command(script: object, *args: str) -> list[str]:
    """The same for a script file (the indicator sandbox's runner)."""
    if paths.frozen():
        return [sys.executable, "--script", str(script), *args]
    return [sys.executable, str(script), *args]


def dispatch(argv: list[str]) -> bool:
    """Run the child a ``module_command`` / ``script_command`` asked for.

    Called first thing by the built program: ``CheapTrader.exe --worker app.stream.mt5_feed``
    is the live feed, ``--script runner.py a b`` the indicator sandbox. Returns False when
    ``argv`` is just a normal start of the program. (A worker ends with ``os._exit``.)
    """
    if len(argv) >= 3 and argv[1] == "--worker":
        sys.argv = [argv[2], *argv[3:]]
        runpy.run_module(argv[2], run_name="__main__", alter_sys=True)
        return True
    if len(argv) >= 3 and argv[1] == "--script":
        sys.argv = [argv[2], *argv[3:]]
        runpy.run_path(argv[2], run_name="__main__")
        return True
    return False


_child_log: IO[bytes] | None = None


def child_log() -> IO[bytes] | None:
    """Where a child process's own messages (its stderr) go.

    In development they appear in the terminal the server runs in (``None``: inherit). The
    built program has no terminal, so they are appended to ``logs/workers.log``.
    """
    global _child_log
    if not paths.frozen():
        return None
    if _child_log is None:
        _child_log = open(paths.logs_dir() / "workers.log", "ab")  # noqa: SIM115 - lives as long as we do
    return _child_log


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop a child process *and everything it started*, and let go of its pipes.

    On Windows a virtual environment's ``python.exe`` is only a launcher: the real
    interpreter is its child. ``Popen.kill()`` stops the launcher and leaves the
    interpreter running, still holding its end of the pipes and still talking to
    the terminal. Restart a few dozen times and a few dozen of those are polling
    MetaTrader at once. ``taskkill /T`` takes the whole tree.
    """
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
                check=False,
            )
        if proc.poll() is None:
            proc.kill()
    except (OSError, subprocess.SubprocessError):
        pass
    for stream in (proc.stdin, proc.stdout):
        try:
            if stream is not None:
                stream.close()
        except (OSError, ValueError):
            pass
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
