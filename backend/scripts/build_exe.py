"""Build CheapTrader.exe.

    cd backend
    uv sync --extra mt5 --extra dev          # once
    uv pip install pyinstaller               # once (the build tool)
    uv run python scripts/build_exe.py       # -> ../release/CheapTrader/CheapTrader.exe

    --onefile      one CheapTrader.exe instead of a folder (slower to start)
    --skip-ui      do not rebuild the page (frontend/dist) first
    --public       the build that is given to other people: its .env starts with CT_BROKER=auto and
                   CT_ALLOW_LIVE_ORDERS=false whatever backend/.env says, and any .env already in the output
                   folder is replaced. (Without it the two settings are copied from backend/.env, which is
                   right for the build you run yourself.)
    --out DIR      build into DIR instead of ../release. A running CheapTrader.exe cannot be replaced (and
                   rebuilding it under a running program breaks that program), so build elsewhere
                   meanwhile, e.g. --out ../release/next, and copy the new exe over the old one after quitting.

What it does: builds the page with Vite, draws the icon, runs PyInstaller on
``cheaptrader.spec``, and writes ``release/CheapTrader/.env`` (only if there is none) with the two
settings that decide what the program may do, copied from ``backend/.env``: ``CT_BROKER`` and
``CT_ALLOW_LIVE_ORDERS``. Nothing else of ``backend/.env`` is copied (it may hold a login).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
FRONTEND = REPO / "frontend"
RELEASE = REPO / "release"
WORK = BACKEND / "build"


def run(command: list[str], cwd: Path, env: dict | None = None) -> None:
    print("  $", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def build_page() -> None:
    print("1/4 the page (Vite)")
    vite = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
    node = shutil.which("node")
    if node is None or not vite.is_file():
        raise SystemExit("node and frontend/node_modules are needed to build the page (cd frontend; npm install)")
    run([node, str(vite), "build"], FRONTEND)
    leftover = FRONTEND / "tsconfig.tsbuildinfo"
    if leftover.exists():
        leftover.unlink()


def draw_icon(target: Path) -> Path | None:
    """The app's icon (the same blue tile with two candles as the page's favicon)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    k = 256 / 28
    base = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle([1 * k, 1 * k, 27 * k, 27 * k], radius=6.5 * k, fill="#2962ff")
    for x, y0, y1 in ((10.5, 5.8, 9.7), (10.5, 19.2, 22.2), (17.5, 4.8, 8.8), (17.5, 15.6, 20.2)):
        draw.line([x * k, y0 * k, x * k, y1 * k], fill="white", width=round(1.7 * k))
    draw.rounded_rectangle([8.2 * k, 9.7 * k, 12.8 * k, 19.2 * k], radius=1.1 * k, fill="white")
    draw.rounded_rectangle([15.2 * k, 9 * k, 19.8 * k, 15.6 * k], radius=1.1 * k, fill=(169, 192, 255, 255))  # white at 60%
    target.parent.mkdir(parents=True, exist_ok=True)
    base.save(target, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return target


def app_version() -> str:
    """The version in app/__init__.py (read as text: this script does not import the app)."""
    found = re.search(r'__version__\s*=\s*"([^"]+)"', (BACKEND / "app" / "__init__.py").read_text(encoding="utf-8"))
    return found.group(1) if found else "0.0.0"


def write_version_info(target: Path) -> Path:
    """The details Windows shows for the program (Properties, Details): name, version, licence."""
    version = app_version()
    numbers = [int(n) for n in re.findall(r"\d+", version)[:3]]
    quad = tuple(numbers + [0] * (4 - len(numbers)))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={quad}, prodvers={quad}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'CheapTrader'),
        StringStruct('FileDescription', 'CheapTrader - trading platform for MetaTrader 5'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'CheapTrader'),
        StringStruct('LegalCopyright', 'MIT licence. TradingView Lightweight Charts (c) TradingView, Inc.'),
        StringStruct('OriginalFilename', 'CheapTrader.exe'),
        StringStruct('ProductName', 'CheapTrader'),
        StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return target


def settings_to_carry() -> dict[str, str]:
    """The two switches from backend/.env that say what the program may do (not the rest)."""
    found: dict[str, str] = {}
    env = BACKEND / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in ("CT_BROKER", "CT_ALLOW_LIVE_ORDERS"):
                found[key.strip()] = value.strip()
    return found


def write_settings(folder: Path, public: bool = False) -> None:
    target = folder / ".env"
    if target.exists() and not public:
        print("   keeping the existing", target)
        return
    # A build for other people never inherits the developer's switches: MetaTrader if there is one, no orders.
    carried = {"CT_BROKER": "auto", "CT_ALLOW_LIVE_ORDERS": "false"} if public else settings_to_carry()
    lines = [
        "# CheapTrader settings (this file sits next to CheapTrader.exe).",
        "# MetaTrader 5 must be installed and logged in; the program uses that account.",
        f"CT_BROKER={carried.get('CT_BROKER', 'auto')}",
        "# Orders are sent to the account the terminal is logged in to only when this is true.",
        f"CT_ALLOW_LIVE_ORDERS={carried.get('CT_ALLOW_LIVE_ORDERS', 'false')}",
        "# The port the program serves on (8765 when not set):",
        "# CT_PORT=8765",
        "# Where the terminal is, if it is not found by itself:",
        "# CT_MT5_PATH=C:\\Program Files\\MetaTrader 5\\terminal64.exe",
        "",
    ]
    target.write_text("\n".join(lines), encoding="utf-8")
    print("   wrote", target, "with", ", ".join(f"{k}={v}" for k, v in carried.items()) or "defaults")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--onefile", action="store_true")
    parser.add_argument("--skip-ui", action="store_true")
    parser.add_argument("--public", action="store_true", help="the build for other people: orders off, MetaTrader if present")
    parser.add_argument("--out", help="build into this folder instead of ../release")
    args = parser.parse_args()
    release = Path(args.out).resolve() if args.out else RELEASE

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("PyInstaller is not installed: uv pip install pyinstaller") from None

    if not args.skip_ui:
        build_page()
    print("2/4 the icon")
    icon = draw_icon(WORK / "cheaptrader.ico")
    print("  ", icon or "(Pillow is missing: no icon)")

    print("3/4 PyInstaller (a few minutes)")
    env = {**os.environ, "CT_ONEFILE": "1" if args.onefile else "0"}
    env["CT_VERSION_FILE"] = str(write_version_info(WORK / "version_info.txt"))
    if icon:
        env["CT_ICON"] = str(icon)
    run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(release),
         "--workpath", str(WORK), "cheaptrader.spec"],
        BACKEND,
        env,
    )

    print("4/4 settings")
    folder = release if args.onefile else release / "CheapTrader"
    write_settings(folder, public=args.public)
    exe = folder / "CheapTrader.exe"
    size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) if not args.onefile else exe.stat().st_size
    print(f"\ndone: {exe}  ({size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
