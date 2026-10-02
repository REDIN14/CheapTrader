# CheapTrader Backend

FastAPI backend bridging MetaTrader 5, a sandboxed Python indicator engine,
replay/backtest engines, and an MCP server.

## Setup

```powershell
cd backend
uv sync --extra mt5 --extra dev
```

`--extra mt5` installs the Windows-only `MetaTrader5` package. Omit it to run
with the synthetic mock broker.

## Run

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/health

## Test

```powershell
uv run pytest
```
