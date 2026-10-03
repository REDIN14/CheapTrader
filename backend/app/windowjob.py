"""A window must not outlive the program it shows.

``CheapTrader.exe`` opens its window as an Edge (or Chrome) process of its own and ends a few seconds after that window
is closed. The other way round there was no care: ending the program by force (Task Manager's "End task",
``taskkill``, a crash) left the window open, showing a page that nothing serves any more, and the browser's "this page
is not reachable (connection refused)" as soon as the window was reloaded.

On Windows the system can see to it. A *job* is a group of processes; with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` the
system ends every process in it when the last handle to the job is closed, and that happens when the program that holds
the handle ends, however it ends. The program puts the processes of its windows in such a job.

The program lets go of the job by hand (``release``) when it ends in the way it means to: an update, because the window
is meant to stay open while the new version is installed, and the ordinary end after its window was closed (or Quit),
because what is left of the browser may be showing a page that the user opened from the program and is using (the
links to Ko-fi, GitHub and the release page open in the same browser). Only ending the program by force ends the browser.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import threading
from ctypes import wintypes

logger = logging.getLogger(__name__)

_KILL_ON_JOB_CLOSE = 0x2000
_BASIC_ACCOUNTING_INFORMATION = 1
_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = ctypes.c_void_p
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k.OpenProcess.restype = ctypes.c_void_p
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.AssignProcessToJobObject.restype = wintypes.BOOL
    k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k.SetInformationJobObject.restype = wintypes.BOOL
    k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.QueryInformationJobObject.restype = wintypes.BOOL
    k.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    k.CloseHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


class WindowJob:
    """The processes of the windows a program opened, ended together with the program (see the module's docstring).

    Every method is safe to call from any thread, and every one does nothing (and says so by its result) off Windows or
    when the system refuses: a window that is not in the job is simply what it was before.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._api = None
        self._handle: int | None = None
        self._broken = False
        self._released = False

    # -- the job itself ------------------------------------------------------------------------------
    def _job(self):
        """The job's handle; made when it is first needed. ``None`` when there is none to have."""
        if os.name != "nt" or self._broken:
            return None
        if self._handle is None:
            try:
                api = _kernel32()
                handle = api.CreateJobObjectW(None, None)
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                limits = _ExtendedLimits()
                limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
                if not api.SetInformationJobObject(handle, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)):
                    error = ctypes.WinError(ctypes.get_last_error())
                    api.CloseHandle(handle)
                    raise error
            except OSError as exc:
                logger.warning("windows are not tied to the program (no job object: %s)", exc)
                self._broken = True
                return None
            self._api, self._handle = api, handle
        return self._handle

    def add(self, process: subprocess.Popen) -> bool:
        """Put a process, and what it starts from now on, in the job. False: that did not work."""
        with self._lock:
            handle = self._job()
            if handle is None or self._released:
                return False
            opened = self._api.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, process.pid)
            if not opened:
                return False
            try:
                if self._api.AssignProcessToJobObject(handle, opened):
                    return True
                logger.warning("a window could not be tied to the program (%s)", ctypes.WinError(ctypes.get_last_error()))
                return False
            finally:
                self._api.CloseHandle(opened)

    def active(self) -> int:
        """How many processes of the job are running."""
        with self._lock:
            if self._handle is None:
                return 0
            info = _Accounting()
            if not self._api.QueryInformationJobObject(self._handle, _BASIC_ACCOUNTING_INFORMATION, ctypes.byref(info), ctypes.sizeof(info), None):
                return 0
            return int(info.ActiveProcesses)

    def release(self) -> None:
        """Let the processes of the job go on when the program ends (an update: the window stays open while the new
        version is installed and finds it by itself)."""
        with self._lock:
            if self._handle is None or self._released:
                self._released = True
                return
            limits = _ExtendedLimits()  # no flags: nothing is ended when the job is closed
            self._api.SetInformationJobObject(self._handle, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits))
            self._released = True

    def close(self) -> None:
        """Let go of the job. What is still in it is ended by the system, unless the job was released."""
        with self._lock:
            if self._handle is not None:
                self._api.CloseHandle(self._handle)
                self._handle = None

    def end(self) -> None:
        """The program ends in the way it means to (its window was closed, or Quit): what is left of the browser stays as it
        is. It may be showing a page that the user opened from the program and is using, a donation page say."""
        self.release()
        self.close()
