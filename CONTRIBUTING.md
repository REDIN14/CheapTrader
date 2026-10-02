# Contributing to CheapTrader

Thank you for wanting to help. Bug reports, ideas, documentation fixes and code are all welcome.

## Before anything else

* **Never test on a live account.** Use the built-in synthetic market, the replay, or a MetaTrader *demo*
  account. Code that can send an order must only ever do so because the user asked for it.
* Never post a MetaTrader login or password in an issue, a pull request or a screenshot.

## Set up

You need Windows 10/11 (the MetaTrader package is Windows-only; the tests use a stand-in for it),
[uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org/) 22.

```powershell
git clone https://github.com/REDIN14/CheapTrader.git
cd CheapTrader

# the program (Python)
cd backend
uv sync --extra mt5 --extra dev
copy .env.example .env          # optional: the settings
uv run uvicorn app.main:app --reload --port 8000

# the page (in a second terminal)
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

Without MetaTrader (or with `CT_BROKER=mock` in `.env`) the app runs on a synthetic market, which is
enough for almost every change.

The dev page talks to the program through Vite's proxy (`frontend/vite.config.ts`). The program refuses
requests from other web pages (`backend/app/security.py`), so that proxy must pass the page's own `Host`
header on (`changeOrigin: false`, already set). If you serve the page some other way and see *"Another web page
may not use CheapTrader"*, list its address in `CT_ALLOWED_ORIGINS` in `backend/.env`.

## Test

```powershell
cd backend ; uv run pytest            # about 330 tests; they never touch your real MetaTrader or data folder
cd frontend ; npm run lint ; npm test # type check, and the logic of the page
```

The backend tests drive the real feed / reader / trader *processes* against a stand-in `MetaTrader5`
package (`backend/tests/fake_mt5`). If you add something that talks to the terminal, extend the stand-in
and test it there.

## Style

* The page is TypeScript with React; keep the logic you can test in `frontend/src/lib/*.ts` (plain functions,
  tested in `frontend/tests`) and keep the components thin.
* Match what is there: comments explain *why*, names say what a thing is, no dead controls (every button does
  something, every switch is real).
* The look follows TradingView's dark theme; take the colours and sizes from the `:root` variables in
  `frontend/src/styles.css`.
* Python: type hints, `ruff` (line length 100).

## Pull requests

Small and focused is best. Say what changed and why, and how you tested it. The template has a checklist.

## Releasing (maintainers)

1. Update `__version__` in `backend/app/__init__.py` and the version in `frontend/package.json` and
   `backend/pyproject.toml`; add the changes to `CHANGELOG.md`.
2. Commit, then `git tag v0.2.0` and `git push --tags`.
3. The *Release* workflow builds `CheapTrader.exe` (`scripts/build_exe.py --onefile --public`), a portable
   zip, the installer (Inno Setup) and the SHA-256 checksums, and attaches them to a new release.
   `--public` makes the settings file start with **orders switched off**.
4. To build by hand: `cd backend ; uv sync --extra mt5 --extra build ; uv run python scripts/build_exe.py --onefile --public --out ../dist-release`.
   A running `CheapTrader.exe` cannot be replaced, so build next to it, never over it.

### Support and sponsorship

* `.github/FUNDING.yml` decides what the repository's **Sponsor** button shows. GitHub Sponsors must be set up
  and approved first (<https://github.com/sponsors>); Ko-fi, Liberapay and the like need only an account.
* `frontend/src/lib/project.ts` holds the same addresses for the app's *About* window and the welcome tour.
  An entry with an empty address is not shown anywhere.
