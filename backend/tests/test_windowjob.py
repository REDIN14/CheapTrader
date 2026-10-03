"""A window must not outlive the program: the job that ends the processes of the windows together with the program.

These run real processes in a real Windows job (a child that sleeps), so they show what the system does, not what a
stand-in says it does."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from app.windowjob import WindowJob

pytestmark = pytest.mark.skipif(os.name != "nt", reason="a Windows job object")

#: The interpreter itself: a virtual environment's python.exe may be a launcher that starts the real one as a child.
PYTHON = getattr(sys, "_base_executable", sys.executable)


def start(code: str) -> subprocess.Popen:
    return subprocess.Popen(
        [PYTHON, "-c", code],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def sleeper(seconds: float = 90.0) -> subprocess.Popen:
    """A process that does nothing for a while: the stand-in for a browser window."""
    return start(f"import time; time.sleep({seconds})")


def ended_within(process: subprocess.Popen, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return True
        time.sleep(0.05)
    return process.poll() is not None


def running(pid: int) -> bool:
    """Is that process still running? (``os.kill(pid, 0)`` would end it on Windows.)"""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenProcess(0x00100000, 0, pid)  # SYNCHRONIZE
    if not handle:
        return False  # it is gone
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT: it has not ended
    finally:
        kernel32.CloseHandle(handle)


@pytest.fixture
def processes():
    started: list[subprocess.Popen] = []
    yield started
    for process in started:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def test_a_process_in_the_job_ends_when_the_program_lets_go_of_the_job(processes) -> None:
    """What happens when the program is ended by force: the system closes its handles, the job's included."""
    job = WindowJob()
    window = sleeper()
    processes.append(window)
    assert job.add(window)
    time.sleep(0.3)
    assert window.poll() is None and job.active() >= 1
    job.close()
    assert ended_within(window, 10), "the window outlived the program"


def test_what_the_window_starts_is_in_the_job_too(processes, tmp_path) -> None:
    job = WindowJob()
    note = tmp_path / "child.pid"
    parent = start(
        "import subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)']); "
        f"open({str(note)!r}, 'w').write(str(child.pid)); time.sleep(90)"
    )
    processes.append(parent)
    assert job.add(parent)
    deadline = time.monotonic() + 15
    while not note.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    time.sleep(0.2)
    child = int(note.read_text())
    assert running(child)
    job.close()  # the program ends by force
    assert ended_within(parent, 10)
    deadline = time.monotonic() + 10
    while running(child) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not running(child), "what the window had started was left behind"


def test_a_released_job_lets_the_window_stay_open(processes) -> None:
    """An update: the window is meant to stay while the new version is installed."""
    job = WindowJob()
    window = sleeper()
    processes.append(window)
    assert job.add(window)
    job.release()
    job.close()
    assert not ended_within(window, 1.5)


def test_ending_in_the_way_the_program_means_to_leaves_the_browser_alone(processes) -> None:
    """The window was closed, or Quit was pressed: a page the user opened from the program (a donation page) goes on."""
    job = WindowJob()
    window = sleeper()
    processes.append(window)
    assert job.add(window)
    job.end()
    assert not ended_within(window, 1.5)


def test_a_job_that_was_never_used_is_harmless() -> None:
    job = WindowJob()
    assert job.active() == 0
    job.release()
    job.end()
    job.close()


def test_a_released_job_takes_no_more_windows(processes) -> None:
    job = WindowJob()
    job.release()
    window = sleeper()
    processes.append(window)
    assert not job.add(window)
