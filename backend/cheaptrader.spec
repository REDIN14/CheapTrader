# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for CheapTrader.exe. Run it through scripts/build_exe.py (which builds the page first).
#
#   CT_ONEFILE=1   one CheapTrader.exe instead of a folder (slower to start: it unpacks itself on every start)
#   CT_ICON=path   the .ico for the exe
#   CT_VERSION_FILE=path   the version details Windows shows for it (scripts/build_exe.py writes them)
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)  # noqa: F821 - provided by PyInstaller
PAGE = ROOT.parent / "frontend" / "dist"
ONEFILE = os.environ.get("CT_ONEFILE") == "1"
ICON = os.environ.get("CT_ICON") or None
VERSION = os.environ.get("CT_VERSION_FILE") or None

if not (PAGE / "index.html").is_file():
    raise SystemExit(f"the page is not built: {PAGE}\\index.html is missing (run scripts/build_exe.py)")

# Modules the program starts by name (a helper process is "CheapTrader.exe --worker app.stream.mt5_feed"),
# so nothing imports them statically.
hidden = collect_submodules("app") + collect_submodules("uvicorn") + collect_submodules("websockets")
mt5_datas, mt5_binaries, mt5_hidden = collect_all("MetaTrader5")

a = Analysis(  # noqa: F821
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=mt5_binaries,
    datas=[
        (str(PAGE), "web"),
        # the documentation the page shows (docs/*.md), served by app/api/docs_routes.py
        (str(ROOT.parent / "docs"), "docs"),
        # run by path inside the program: the indicator sandbox
        (str(ROOT / "app" / "indicators" / "_runner.py"), "app/indicators"),
        *mt5_datas,
    ],
    hiddenimports=hidden + mt5_hidden,
    excludes=[
        # not used by the app (the MCP server is not built yet), and large
        "fastmcp", "mcp", "kaleido", "plotly",
        # development only
        "pytest", "ruff", "IPython", "jupyter", "notebook",
        # no GUI toolkit is used: matplotlib only draws to files (Agg)
        "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    ],
)
pyz = PYZ(a.pure)  # noqa: F821

if ONEFILE:
    exe = EXE(  # noqa: F821
        pyz, a.scripts, a.binaries, a.datas, [],
        name="CheapTrader", console=False, icon=ICON, version=VERSION, upx=False,
    )
else:
    exe = EXE(  # noqa: F821
        pyz, a.scripts, [],
        exclude_binaries=True, name="CheapTrader", console=False, icon=ICON, version=VERSION, upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="CheapTrader", upx=False)  # noqa: F821
