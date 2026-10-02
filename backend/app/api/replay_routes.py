"""Replay REST routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from app.performance import symbol_stats
from app.replay.engine import ReplayEngine
from app.schemas import (
    TIMEFRAME_SECONDS,
    BacktestMetrics,
    BacktestTrade,
    Bar,
    ModifyRequest,
    OrderRequest,
    OrderResult,
    Position,
    ProfilesView,
    ReplayAccount,
    ReplayReport,
    ReplayState,
    ReplayUpdate,
    Timeframe,
)
from app.state import get_state
from app.trading import is_pending

router = APIRouter(prefix="/api/replay", tags=["replay"])


def _engine() -> ReplayEngine:
    state = get_state()
    if state.replay is None:
        raise HTTPException(
            status_code=409, detail="No replay is running. Choose a bar to start one."
        )
    return state.replay


def _spec(symbol: str) -> dict[str, float]:
    """What the paper account needs to know about an instrument to work out a profit in the account's
    currency: its contract size and what one price step is worth (see PaperPosition.pnl)."""
    info = get_state().symbols.get(symbol)
    if info is None:
        return {"contract_size": 100_000.0}
    return {
        "contract_size": info.trade_contract_size or 100_000.0,
        "tick_size": info.trade_tick_size or 0.0,
        "tick_value": info.trade_tick_value or 0.0,
    }


def _parse_date(value: str, *, end_of_day: bool = False) -> datetime:
    """Parse an ISO date or epoch-seconds string into an aware UTC datetime.

    A bare date (``2026-10-01``) names a whole day, so used as the *end* of a
    window it runs to the last second of that day; otherwise choosing "today" as
    the end date would silently leave out all of today's bars.
    """
    value = value.strip()
    if value.isdigit():
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if end_of_day and len(value) <= 10:
        dt += timedelta(days=1) - timedelta(seconds=1)
    return dt


@router.post("/load", response_model=ReplayState)
def load(
    symbol: str,
    timeframe: Timeframe = Timeframe.H1,
    count: int = Query(default=2000, le=100_000),
    start: str | None = None,
    end: str | None = None,
) -> ReplayState:
    state = get_state()
    spec = _spec(symbol)
    try:
        if start is not None and end is not None:
            # Date-range replay: fetch only the missing parts of the window.
            bars = state.cache.ensure_range(
                state.broker.adapter,
                symbol,
                timeframe,
                _parse_date(start),
                _parse_date(end, end_of_day=True),
            )
            state.end_replay()  # the one that was running closes its positions and keeps the result
            engine = ReplayEngine.from_bars(
                symbol, timeframe, bars, paper=state.profiles.active(), **spec
            )
        else:
            bars = state.broker.adapter.get_bars(symbol, timeframe, count=count)
            state.end_replay()
            engine = ReplayEngine.from_bars(
                symbol, timeframe, bars, paper=state.profiles.active(), **spec
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    engine.begin(0)  # the paper account's session starts on the first bar
    state.replay = engine
    return engine.state()


#: Bars per day-of-calendar slack when sizing a window: markets close at weekends
#: and holidays, so a span of N bars covers more than N × the bar length.
_CALENDAR_SLACK = 1.6


@router.post("/start", response_model=ReplayUpdate)
def start(
    symbol: str,
    timeframe: Timeframe = Timeframe.H1,
    time: int = Query(description="Epoch second of the bar to start on (chart time)."),
    lookback: int = Query(
        default=1500, ge=0, le=20_000, description="Bars of history to keep before the start."
    ),
    lookahead: int = Query(
        default=60_000, ge=1, le=200_000, description="Most bars to load after the start."
    ),
) -> ReplayUpdate:
    """Start a replay on the bar nearest ``time``.

    The window is the history before that bar plus everything after it (up to the
    latest bar, capped at ``lookahead``), so the caller only has to say *where* to
    start. The reply carries the bars up to the cursor, ready to draw.
    """
    state = get_state()
    spec = _spec(symbol)
    step = TIMEFRAME_SECONDS[timeframe]

    first_ts = max(0, time - int(lookback * step * _CALENDAR_SLACK))
    newest_ts = int(datetime.now(timezone.utc).timestamp()) + 2 * 86_400
    last_ts = max(time + step, min(newest_ts, time + int(lookahead * step * _CALENDAR_SLACK)))
    try:
        bars = state.cache.ensure_range(
            state.broker.adapter,
            symbol,
            timeframe,
            datetime.fromtimestamp(first_ts, tz=timezone.utc),
            datetime.fromtimestamp(last_ts, tz=timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not bars:
        raise HTTPException(status_code=409, detail=f"No {symbol} bars to replay around that time.")

    # The window above was sized in calendar time, with room to spare for weekends;
    # trim it to exactly the bars asked for around the start.
    probe = ReplayEngine.from_bars(symbol, timeframe, bars, **spec)
    at = probe.nearest_index(time)
    bars = bars[max(0, at - lookback) : at + lookahead + 1]

    # The replay that was running is over: its paper account closes what is open and keeps the result.
    # The new one trades on the profile the user chose, balance and history included.
    state.end_replay()
    engine = ReplayEngine.from_bars(symbol, timeframe, bars, paper=state.profiles.active(), **spec)
    engine.begin(engine.nearest_index(time))
    state.replay = engine
    return _update(engine, engine.visible_bars(), [], reset=True)


@router.get("/state", response_model=ReplayState)
def get_state_route() -> ReplayState:
    return _engine().state()


@router.get("/bars", response_model=list[Bar])
def visible_bars() -> list[Bar]:
    return _engine().visible_bars()


@router.post("/advance", response_model=ReplayUpdate)
def advance(delta: int = Query(default=1, ge=-1_000_000, le=1_000_000)) -> ReplayUpdate:
    """Move the cursor ``delta`` bars and return what that changed, in one reply.

    A playing replay makes this call at its own pace, so one request has to carry
    everything the screen needs: the bars revealed, the positions marked to the new
    price, the headline numbers, and any trade a stop or target closed on the way.
    """
    engine = _engine()
    before = engine.index
    moved = engine.advance(delta)
    if engine.index < before:
        # Rewinding starts the paper account again, so hand over the whole picture.
        return _update(engine, engine.visible_bars(), [], reset=True)
    return _update(engine, moved.bars, moved.closed)


@router.post("/play", response_model=ReplayState)
async def play() -> ReplayState:
    engine = _engine()
    engine.play()
    engine.ensure_running()
    return engine.state()


@router.post("/pause", response_model=ReplayState)
def pause() -> ReplayState:
    return _engine().pause()


@router.post("/step", response_model=ReplayState)
def step(delta: int = 1) -> ReplayState:
    return _engine().step(delta)


@router.post("/seek", response_model=ReplayState)
def seek(index: int) -> ReplayState:
    return _engine().seek(index)


@router.post("/seek-time", response_model=ReplayState)
def seek_time(timestamp: int) -> ReplayState:
    return _engine().seek_time(timestamp)


@router.post("/speed", response_model=ReplayState)
def speed(value: float) -> ReplayState:
    return _engine().set_speed(value)


@router.post("/reset", response_model=ReplayState)
def reset() -> ReplayState:
    return _engine().reset()


# -- paper trading ---------------------------------------------------------
def _current_bar(engine: ReplayEngine) -> Bar:
    if not engine.bars:
        raise HTTPException(status_code=409, detail="Replay has no bars")
    return engine.bars[min(engine.index, engine.total - 1)]


@router.post("/orders", response_model=OrderResult)
def place_order(request: OrderRequest) -> OrderResult:
    engine = _engine()
    if engine.paper is None:
        raise HTTPException(status_code=409, detail="Paper engine unavailable")
    if is_pending(request.order_type):
        message = "Limit and stop orders are not available in a replay: every paper order fills at the bar close."
        return OrderResult(ok=False, retcode=10015, error=message, comment=message)
    return engine.paper.place(request, _current_bar(engine))


@router.patch("/positions", response_model=OrderResult)
def modify_position(request: ModifyRequest) -> OrderResult:
    engine = _engine()
    if engine.paper is None:
        raise HTTPException(status_code=409, detail="Paper engine unavailable")
    return engine.paper.modify(request.ticket, request.sl, request.tp)


@router.delete("/positions/{ticket}", response_model=OrderResult)
def close_position(ticket: int) -> OrderResult:
    engine = _engine()
    if engine.paper is None:
        raise HTTPException(status_code=409, detail="Paper engine unavailable")
    return engine.paper.close(ticket, _current_bar(engine))


@router.get("/positions", response_model=list[Position])
def positions() -> list[Position]:
    engine = _engine()
    if engine.paper is None:
        return []
    return engine.paper.positions_view(_current_bar(engine).close)


@router.get("/performance", response_model=BacktestMetrics)
def performance() -> BacktestMetrics:
    engine = _engine()
    if engine.paper is None:
        raise HTTPException(status_code=409, detail="Paper engine unavailable")
    return engine.paper.metrics(_current_bar(engine).close)


@router.get("/trades", response_model=list[BacktestTrade])
def trades() -> list[BacktestTrade]:
    engine = _engine()
    if engine.paper is None:
        return []
    return engine.paper.closed


@router.get("/account", response_model=ReplayAccount)
def account() -> ReplayAccount:
    """Balance, equity, open positions and headline metrics at the cursor."""
    engine = _engine()
    if engine.paper is None:
        raise HTTPException(status_code=409, detail="Paper engine unavailable")
    return engine.paper.account(_current_bar(engine).close)


@router.get("/report", response_model=ReplayReport)
def report(points: int = Query(default=400, ge=4, le=5000)) -> ReplayReport:
    """The performance report: account, summary figures, equity curve and every trade."""
    engine = _engine()
    if engine.paper is None:
        raise HTTPException(status_code=409, detail="Paper engine unavailable")
    price = _current_bar(engine).close
    return ReplayReport(
        account=engine.paper.account(price),
        summary=engine.paper.summary(price),
        equity=engine.paper.equity_points(points),
        trades=list(engine.paper.closed),
        symbols=symbol_stats(engine.paper.closed),
    )


@router.post("/reset-account", response_model=BacktestMetrics)
def reset_account() -> BacktestMetrics:
    """Start the profile in use over with the balance it began with (history and positions gone)."""
    engine = _engine()
    if engine.paper is None:
        raise HTTPException(status_code=409, detail="Paper engine unavailable")
    bar = _current_bar(engine)
    engine.paper.reset()
    engine.paper.mark(bar)  # the curve starts again from here
    return engine.paper.metrics(bar.close)


@router.post("/stop", response_model=ProfilesView)
def stop() -> ProfilesView:
    """Leave the replay: positions still open are closed at the price under the cursor and the result
    stays in the profile. Harmless when no replay is running."""
    state = get_state()
    state.end_replay()
    return ProfilesView(active=state.profiles.active_id(), profiles=state.profiles.summaries())


def _update(
    engine: ReplayEngine,
    bars: list[Bar],
    closed: list[BacktestTrade],
    *,
    reset: bool = False,
) -> ReplayUpdate:
    """Package a cursor move: state, the bars it revealed, the account, the trades it closed."""
    if engine.paper is None:
        raise HTTPException(status_code=409, detail="Paper engine unavailable")
    return ReplayUpdate(
        state=engine.state(),
        bars=bars,
        account=engine.paper.account(_current_bar(engine).close),
        closed=closed,
        reset=reset,
    )
