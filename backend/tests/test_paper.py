"""Tests for the replay paper-trading engine."""

from __future__ import annotations

from app.broker.mock_adapter import MockAdapter
from app.replay.engine import ReplayEngine
from app.schemas import OrderRequest, Timeframe


def _engine(count: int = 200) -> ReplayEngine:
    broker = MockAdapter()
    broker.connect()
    return ReplayEngine.load(broker, "EURUSD", Timeframe.H1, count=count)


def test_place_and_close() -> None:
    engine = _engine()
    bar = engine.bars[10]
    result = engine.paper.place(OrderRequest(symbol="EURUSD", side="BUY", volume=1.0), bar)
    assert result.ok
    assert len(engine.paper.positions) == 1

    positions = engine.paper.positions_view(bar.close)
    assert positions[0].side == "BUY"

    closed = engine.paper.close(result.order_id, engine.bars[20])
    assert closed.ok
    assert len(engine.paper.positions) == 0
    assert len(engine.paper.closed) == 1


def test_sl_hit_closes_position() -> None:
    engine = _engine()
    bar = engine.bars[10]
    # Buy with a stop just below the entry; a later bar's low should trigger it.
    sl = bar.close - 0.0001
    engine.paper.place(
        OrderRequest(symbol="EURUSD", side="BUY", volume=1.0, sl=sl), bar
    )
    for i in range(11, 60):
        engine.paper.on_bar(engine.bars[i])
        if not engine.paper.positions:
            break
    assert len(engine.paper.closed) >= 1
    assert engine.paper.closed[0].reason in ("sl", "tp")


def test_step_processes_bars() -> None:
    engine = _engine()
    engine.seek(10)
    bar = engine.bars[10]
    engine.paper.place(
        OrderRequest(symbol="EURUSD", side="BUY", volume=1.0, sl=bar.close - 0.0001), bar
    )
    engine.step(50)
    # Either the SL was hit or the position is still open, but equity was tracked.
    assert engine.index == 60


def test_metrics_shape() -> None:
    engine = _engine()
    engine.seek(10)
    engine.paper.place(
        OrderRequest(symbol="EURUSD", side="BUY", volume=1.0), engine.bars[10]
    )
    engine.step(30)
    engine.paper.close(1, engine.bars[40])
    metrics = engine.paper.metrics(engine.bars[40].close)
    assert metrics.trades == 1
    assert metrics.initial_balance == 10_000.0
    assert metrics.final_balance != 0


def test_reset_account() -> None:
    engine = _engine()
    engine.paper.place(OrderRequest(symbol="EURUSD", side="SELL", volume=1.0), engine.bars[5])
    engine.paper.reset()
    assert engine.paper.balance == engine.paper.initial_balance
    assert not engine.paper.positions
    assert not engine.paper.closed


def test_invalid_sl_rejected() -> None:
    engine = _engine()
    bar = engine.bars[10]
    # SL above entry is invalid for a BUY.
    result = engine.paper.place(
        OrderRequest(symbol="EURUSD", side="BUY", volume=1.0, sl=bar.close + 0.01), bar
    )
    assert not result.ok
    assert "invalid SL" in (result.error or "")
    assert not engine.paper.positions


def test_invalid_tp_rejected() -> None:
    engine = _engine()
    bar = engine.bars[10]
    result = engine.paper.place(
        OrderRequest(symbol="EURUSD", side="SELL", volume=1.0, tp=bar.close + 0.01), bar
    )
    assert not result.ok
    assert "invalid TP" in (result.error or "")


def test_pnl_uses_contract_size() -> None:
    engine = _engine()
    bar = engine.bars[10]
    engine.paper.place(OrderRequest(symbol="EURUSD", side="BUY", volume=0.1), bar)
    pos = next(iter(engine.paper.positions.values()))
    # 0.1 lots * 100_000 contract * 0.0010 move = 10.0
    assert abs(pos.pnl(bar.close + 0.0010) - 10.0) < 1e-6
