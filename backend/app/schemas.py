"""Shared Pydantic schemas for the CheapTrader backend.

These are the canonical wire types used by the REST API, the WebSocket
stream, and the MCP server. The frontend mirrors them in
``frontend/src/lib/types.ts``.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Timeframe(str, Enum):
    """Supported chart timeframes mapped to MT5 timeframe constants."""

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"
    MN1 = "MN1"


#: Seconds one bar covers (a month is a 30-day approximation).
TIMEFRAME_SECONDS: dict[Timeframe, int] = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.D1: 86400,
    Timeframe.W1: 604800,
    Timeframe.MN1: 2592000,
}


class Symbol(BaseModel):
    """A tradable instrument offered by the broker."""

    name: str
    description: str = ""
    path: str = ""
    digits: int = 5
    point: float = 0.00001
    spread: int = 0
    trade_mode: int = 0
    visible: bool = True
    trade_contract_size: float = 100_000.0
    #: What one price step (a "tick") is worth for one lot, in the account's currency, and the step itself.
    #: Together they say what a stop costs, which is what sizing a position by its risk needs.
    trade_tick_value: float = 0.0
    trade_tick_size: float = 0.0
    #: Smallest, largest and step of an order's volume, in lots.
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    #: How close (in points) a pending order or a stop may sit to the market.
    trade_stops_level: int = 0
    #: What a profit on this instrument is paid in ("USD").
    currency_profit: str = ""


class Bar(BaseModel):
    """A single OHLCV candle. ``time`` is a UTC epoch second."""

    time: int
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0
    spread: int = 0
    real_volume: int = 0


class Tick(BaseModel):
    """A single price tick. ``time`` is a UTC epoch second."""

    time: int
    bid: float
    ask: float
    last: float = 0.0
    volume: float = 0.0
    time_msc: int = 0
    flags: int = 0


class AccountInfo(BaseModel):
    login: int = 0
    server: str = ""
    currency: str = "USD"
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    margin_free: float = 0.0
    profit: float = 0.0
    leverage: int = 0
    name: str = ""
    # What else the broker tells about the account (MetaTrader's account_info). Empty or zero where it tells nothing.
    company: str = ""
    credit: float = 0.0
    margin_level: float = 0.0  # percent; 0 while no margin is in use
    margin_call_level: float = 0.0
    stop_out_level: float = 0.0
    stop_out_mode: str = ""  # "percent" | "money"
    trade_mode: str = ""  # "demo" | "contest" | "real"
    margin_mode: str = ""  # "netting" | "exchange" | "hedging"
    limit_orders: int = 0  # the most pending orders the broker allows (0: no limit)
    fifo_close: bool = False
    currency_digits: int = 2
    assets: float = 0.0
    liabilities: float = 0.0
    commission_blocked: float = 0.0


class Deal(BaseModel):
    """One line of the broker's history: a fill, or an operation on the balance (a deposit, a charge ...)."""

    ticket: int
    position_id: int = 0  # the position a fill belongs to (all of its fills share it)
    order: int = 0
    time: int  # seconds, in the broker's server time like every other time here
    time_msc: int = 0
    # buy | sell | balance | credit | charge | correction | bonus | commission | interest | dividend | tax | canceled | other
    kind: str
    entry: str = ""  # in | out | inout | out_by; empty for an operation on the balance
    symbol: str = ""
    volume: float = 0.0
    price: float = 0.0
    profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0
    # client | mobile | web | expert | sl | tp | so | rollover | vmargin | split, or empty
    reason: str = ""
    comment: str = ""
    magic: int = 0


class TerminalInfo(BaseModel):
    """What the trading terminal says about itself (MetaTrader 5), and whether it will take orders."""

    connected: bool = False
    name: str = ""  # "Fusion Markets MetaTrader 5"
    company: str = ""  # the broker: "Fusion Markets Pty Ltd"
    path: str = ""  # the install folder
    exe: str = ""  # the program inside it
    data_path: str = ""
    build: int = 0
    #: The terminal's own "Algo Trading" switch. Off: it refuses every order the app sends.
    algo_trading: bool = True
    #: MetaTrader's Python interface is not disabled.
    api_allowed: bool = True
    account_login: int = 0
    account_server: str = ""
    #: The account may trade at all (an investor, read-only login may not).
    account_trading: bool = True
    #: The account allows automated trading (the broker can switch it off).
    account_expert: bool = True


class OrderType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"


class OrderRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    volume: float = Field(gt=0)
    order_type: OrderType | None = None
    price: float | None = None
    sl: float | None = None
    tp: float | None = None
    comment: str = "cheaptrader"
    deviation: int = 20
    magic: int = 20261001


class OrderResult(BaseModel):
    ok: bool
    retcode: int = 0
    order_id: int = 0
    deal_id: int = 0
    volume: float = 0.0
    price: float = 0.0
    comment: str = ""
    error: str | None = None
    #: How long the broker took to answer (ms), measured around the trade call itself.
    latency_ms: int = 0


class Position(BaseModel):
    ticket: int
    symbol: str
    side: Literal["BUY", "SELL"]
    volume: float
    price_open: float
    price_current: float
    sl: float = 0.0
    tp: float = 0.0
    profit: float = 0.0
    time: int = 0
    comment: str = ""


class ModifyRequest(BaseModel):
    ticket: int
    sl: float | None = None
    tp: float | None = None


class PendingOrder(BaseModel):
    """An order waiting for the market to reach its price: a limit or a stop order."""

    ticket: int
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: OrderType
    volume: float
    #: The price it waits for.
    price: float
    sl: float = 0.0
    tp: float = 0.0
    #: The market price now (the ask for a buy, the bid for a sell).
    price_current: float = 0.0
    #: When it was placed (epoch seconds).
    time: int = 0
    comment: str = ""


class ModifyOrderRequest(BaseModel):
    """Move a pending order, or change its stop and target. What is left out stays as it is."""

    ticket: int
    price: float | None = None
    sl: float | None = None
    tp: float | None = None


class IndicatorSpec(BaseModel):
    """A user-authored Python indicator."""

    id: str
    name: str
    code: str
    overlay: bool = True
    pane: int = 0
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class IndicatorResult(BaseModel):
    """Output of running an indicator over a bar series."""

    id: str
    name: str
    overlay: bool
    pane: int
    plots: list[dict[str, Any]] = Field(default_factory=list)
    #: Shapes the indicator draws on the chart (see ``docs/DRAWINGS.md``), checked against ``app.drawings.Drawing``.
    drawings: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class SnapshotRequest(BaseModel):
    symbol: str
    timeframe: Timeframe = Timeframe.H1
    start: datetime
    end: datetime
    indicators: list[str] = Field(default_factory=list)
    #: Also draw the symbol's saved drawings (the shapes on the chart); an indicator's own shapes are always drawn.
    include_drawings: bool = True
    max_points_per_part: int = 400
    width: int = 1600
    height: int = 900


class SnapshotPart(BaseModel):
    index: int
    total: int
    start: datetime
    end: datetime
    image_base64: str
    mime: str = "image/png"


class SnapshotResponse(BaseModel):
    symbol: str
    timeframe: Timeframe
    parts: list[SnapshotPart]
    summary: str = ""


class BacktestRequest(BaseModel):
    symbol: str
    timeframe: Timeframe = Timeframe.H1
    start: datetime | None = None
    end: datetime | None = None
    bars: int = 5000
    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    initial_balance: float = 10_000.0
    risk_per_trade: float = 0.01


class BacktestTrade(BaseModel):
    entry_time: int
    exit_time: int
    side: Literal["BUY", "SELL"]
    entry_price: float
    exit_price: float
    volume: float
    pnl: float
    # "sl", "tp", "manual" or, for a position closed when its replay ended or was rewound, "session" / "rewind".
    reason: str = ""
    # The paper position this trade closed (0 for backtests, which have none).
    ticket: int = 0
    # The instrument: a paper profile's history spans every symbol it was used on.
    symbol: str = ""


class BacktestMetrics(BaseModel):
    initial_balance: float
    final_balance: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    win_rate: float
    trades: int
    profit_factor: float


class BacktestResult(BaseModel):
    metrics: BacktestMetrics
    trades: list[BacktestTrade]
    equity_curve: list[dict[str, float]]


class ReplayState(BaseModel):
    symbol: str
    timeframe: Timeframe
    playing: bool
    index: int
    total: int
    speed: float
    cursor_time: int
    # Time of the first and last bar of the loaded window (0 when it is empty), so
    # the UI can say what was loaded rather than only what is visible at the cursor.
    first_time: int = 0
    last_time: int = 0


class ReplayAccount(BaseModel):
    """The paper account as of the replay cursor."""

    initial_balance: float
    # Initial balance plus the profit of the trades closed so far.
    balance: float
    # Balance plus the floating profit of the open positions.
    equity: float
    realized: float
    unrealized: float
    positions: list[Position]
    metrics: BacktestMetrics
    trades_total: int = 0
    # Closed trades that made money / lost money (the rest closed even); with the
    # metrics' profit factor these tell "no losing trade yet" from "no trade at all".
    wins: int = 0
    losses: int = 0
    # The profile this account is (see replay/profiles.py); empty for an account that is not kept.
    profile_id: str = ""
    profile_name: str = ""


class ProfileSummary(BaseModel):
    """One paper-trading profile, as listed."""

    id: str
    name: str
    initial_balance: float
    balance: float
    # Balance minus what it began with, and as a percentage of it.
    realized: float
    return_pct: float
    trades: int
    wins: int
    losses: int
    open_positions: int
    created_at: int
    updated_at: int


class ProfilesView(BaseModel):
    """Every profile and which one the replay trades on."""

    active: str
    profiles: list[ProfileSummary]


class NewProfile(BaseModel):
    name: str
    balance: float = 10_000.0
    # Make it the one the replay trades on (the usual wish when making a profile).
    activate: bool = True


class RenameProfile(BaseModel):
    name: str


class ResetProfile(BaseModel):
    # The balance to begin again with; left out, the profile begins again with the one it began with.
    balance: float | None = None


class ReplayUpdate(BaseModel):
    """Everything that changed when the cursor moved, in one reply."""

    state: ReplayState
    # Bars the cursor revealed, oldest first. After a start these are the bars up to
    # and including the cursor.
    bars: list[Bar]
    account: ReplayAccount
    # Trades closed (by a stop or a target) while the cursor moved.
    closed: list[BacktestTrade] = Field(default_factory=list)
    # True when the cursor went backwards (or the replay was just started): `bars`
    # is then everything up to the cursor and replaces what the client has, and the
    # paper account began again.
    reset: bool = False


class EquityPoint(BaseModel):
    time: int
    value: float


class ReplaySummary(BaseModel):
    """The figures of a performance report, worked out from the closed trades."""

    net_profit: float
    gross_profit: float
    gross_loss: float  # a positive number
    trades: int
    wins: int
    losses: int
    win_rate: float  # percent
    profit_factor: float | None  # None while there is no losing trade
    avg_win: float
    avg_loss: float  # a positive number
    payoff_ratio: float | None  # avg_win / avg_loss
    largest_win: float
    largest_loss: float  # zero or negative
    avg_trade: float
    avg_duration: int  # seconds a trade stayed open, on average
    max_win_streak: int
    max_loss_streak: int
    max_drawdown: float  # in account units, positive
    max_drawdown_pct: float


class PerformanceSummary(ReplaySummary):
    """The replay's figures and what a broker's own report adds to them (see performance.py)."""

    recovery_factor: float | None = None  # net profit / the largest drawdown; None without a drawdown
    sharpe: float | None = None  # mean / spread of the trades' returns; None below three trades
    long_trades: int = 0
    long_wins: int = 0
    short_trades: int = 0
    short_wins: int = 0
    avg_win_streak: float = 0.0
    avg_loss_streak: float = 0.0
    max_win_streak_amount: float = 0.0  # what the longest winning streak made
    max_loss_streak_amount: float = 0.0  # what the longest losing streak lost (zero or negative)
    best_win_streak_amount: float = 0.0  # the winning streak that made the most, and its length
    best_win_streak_amount_trades: int = 0
    worst_loss_streak_amount: float = 0.0  # the losing streak that lost the most (zero or negative), and its length
    worst_loss_streak_amount_trades: int = 0
    longest_duration: int = 0  # seconds
    shortest_duration: int = 0
    total_volume: float = 0.0  # lots traded
    commission: float = 0.0  # what the closed trades cost, in account units (zero or negative)
    swap: float = 0.0
    fees: float = 0.0
    drawdown_absolute: float = 0.0  # how far the balance stood below the money put in, at the most


class SymbolStats(BaseModel):
    """What the closed trades of one instrument made."""

    symbol: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    net_profit: float
    volume: float


class ReplayReport(BaseModel):
    account: ReplayAccount
    summary: PerformanceSummary
    equity: list[EquityPoint]
    trades: list[BacktestTrade]
    symbols: list[SymbolStats] = []


class ClosedTrade(BacktestTrade):
    """A position of the broker's account that is closed: its fills put together (see performance.py).

    ``pnl`` is what the position made after its costs; ``profit`` is the price result alone.
    """

    profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0
    comment: str = ""


class AccountFlows(BaseModel):
    """Money that moved without being trading: what was put in and taken out, and what the broker booked."""

    deposits: float = 0.0
    withdrawals: float = 0.0  # a positive number
    credit: float = 0.0  # credit the broker gave (it is no part of the balance)
    bonus: float = 0.0
    corrections: float = 0.0
    charges: float = 0.0  # fees, interest, dividends and taxes booked to the account (negative: it paid)
    operations: int = 0


class AccountReport(BaseModel):
    """The account's performance report, worked out from the broker's own history."""

    account: AccountInfo
    summary: PerformanceSummary
    #: The account's level after each deal that moved it (without deposits and withdrawals), then as it is now.
    equity: list[EquityPoint]
    #: The newest closed trades, oldest first; ``trades_total`` says how many there are.
    trades: list[ClosedTrade]
    trades_total: int
    symbols: list[SymbolStats]
    flows: AccountFlows
    #: The level the curve starts from: the money first put in (or the balance before the history).
    initial_balance: float
    #: Net profit as a share of that, in percent (None when there is nothing to measure it by).
    return_pct: float | None
    #: Profit that is still open, and the share of the level it makes.
    open_profit: float
    deals: int
    first_time: int
    last_time: int


class UpdateResult(BaseModel):
    """How the last attempt to install an update ended (read once, when the new version starts)."""

    version: str
    ok: bool
    message: str


class UpdateStatus(BaseModel):
    """Whether a newer release exists on GitHub, and how installing it is going (see app/updater.py)."""

    # The check is switched on (in the About window, or by the settings).
    enabled: bool
    current: str
    # The newest release GitHub told about, newer or not; None before the first look.
    latest: str | None
    available: bool
    # The user chose "skip this version" for the one that is available.
    skipped: bool
    # This copy can install the release by itself (it was set up by the installer, and the release has what it needs).
    can_install: bool
    installable_here: bool
    notes: str
    page: str
    published: str
    # Bytes of the installer.
    size: int
    checked_at: int | None
    error: str | None
    # idle | downloading | verifying | installing | failed
    phase: str
    message: str
    done: int
    total: int
    result: UpdateResult | None
