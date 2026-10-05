"""Parent-side indicator sandbox.

Runs user indicator code in an isolated subprocess with:

- a restricted import set (see ``_runner.BLOCKED_MODULES``),
- a wall-clock timeout,
- a memory cap (Windows Job Object),
- no inherited environment secrets.

The subprocess prints a single JSON object which the parent parses.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import ValidationError

from app import paths
from app.config import Settings, get_settings
from app.drawings import Drawing
from app.procutil import script_command
from app.schemas import Bar, IndicatorResult

logger = logging.getLogger(__name__)

_RUNNER = Path(__file__).with_name("_runner.py")


class SandboxError(RuntimeError):
    pass


def _apply_memory_limit(process: subprocess.Popen, limit_mb: int) -> None:
    """Best-effort memory cap via a Windows Job Object."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
        JobObjectExtendedLimitInformation = 9

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.ProcessMemoryLimit = limit_mb * 1024 * 1024
        kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle))  # noqa: SLF001
    except Exception:  # noqa: BLE001 - memory cap is best-effort
        logger.debug("Could not apply memory limit", exc_info=True)


def run_indicator(
    indicator_id: str,
    name: str,
    code: str,
    bars: list[Bar],
    params: dict | None = None,
    overlay: bool = True,
    pane: int = 0,
    settings: Settings | None = None,
    show_from: int | None = None,
) -> IndicatorResult:
    """Execute an indicator over ``bars`` and return its plots.

    With ``show_from`` (an epoch second) only the points of the lines from that bar on come back: the bars before it
    are there to warm the indicator up (see ``needs.py``).
    """
    settings = settings or get_settings()

    with tempfile.TemporaryDirectory(prefix="ct_ind_") as tmp:
        tmp_path = Path(tmp)
        code_path = tmp_path / "indicator.py"
        payload_path = tmp_path / "payload.json"
        code_path.write_text(code, encoding="utf-8")
        payload_path.write_text(
            json.dumps(
                {
                    "bars": [b.model_dump() for b in bars],
                    "params": params or {},
                    "show_from": show_from,
                }
            ),
            encoding="utf-8",
        )

        cmd = script_command(_RUNNER, str(code_path), str(payload_path))
        flags = subprocess.CREATE_NO_WINDOW if paths.frozen() and sys.platform == "win32" else 0
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(tmp_path),
                creationflags=flags,
            )
        except OSError as exc:
            raise SandboxError(f"failed to start sandbox: {exc}") from exc

        _apply_memory_limit(process, settings.indicator_memory_mb)

        try:
            stdout, stderr = process.communicate(timeout=settings.indicator_timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return IndicatorResult(
                id=indicator_id,
                name=name,
                overlay=overlay,
                pane=pane,
                error=(
                    f"Indicator timed out after {settings.indicator_timeout}s over {len(bars):,} bars "
                    "(a loop over the bars is slow: work on the whole series at once, or raise CT_INDICATOR_TIMEOUT)"
                ),
            )

    if not stdout.strip():
        return IndicatorResult(
            id=indicator_id,
            name=name,
            overlay=overlay,
            pane=pane,
            error=f"Indicator produced no output. stderr: {stderr.strip()[:4000]}",
        )

    try:
        payload = json.loads(stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return IndicatorResult(
            id=indicator_id,
            name=name,
            overlay=overlay,
            pane=pane,
            error=f"Invalid sandbox output: {stdout.strip()[:500]}",
        )

    if not payload.get("ok"):
        return IndicatorResult(
            id=indicator_id,
            name=name,
            overlay=overlay,
            pane=pane,
            error=payload.get("error", "unknown error"),
        )

    drawings: list[dict] = []
    for i, raw in enumerate(payload.get("drawings", []), start=1):
        try:
            drawings.append(Drawing.model_validate(raw).model_dump(exclude_none=True))
        except ValueError as exc:
            errors = exc.errors() if isinstance(exc, ValidationError) else []
            problem = str(errors[0]["msg"]).removeprefix("Value error, ") if errors else str(exc)
            return IndicatorResult(
                id=indicator_id,
                name=name,
                overlay=overlay,
                pane=pane,
                error=f"drawing #{i} ({raw.get('type', '?')}): {problem}",
            )

    return IndicatorResult(
        id=indicator_id,
        name=name,
        overlay=overlay,
        pane=pane,
        plots=payload.get("plots", []),
        drawings=drawings,
    )
