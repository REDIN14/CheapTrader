"""Paper-trading profiles: a balance of your own choosing, several accounts to practise on, and none
of it lost when a replay ends or the program is restarted."""

from __future__ import annotations

import json
import math
import os
import time
import types

os.environ.setdefault("CT_BROKER", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.replay.paper as paper_module  # noqa: E402
import app.state as app_state  # noqa: E402
from app.main import app  # noqa: E402
from app.preferences import Preferences  # noqa: E402
from app.replay import profiles as profiles_module  # noqa: E402
from app.replay.paper import PaperPosition, PaperTradingEngine  # noqa: E402
from app.replay.profiles import ProfileError, ProfileStore  # noqa: E402
from app.schemas import Bar, OrderRequest, Symbol  # noqa: E402
from app.state import get_state  # noqa: E402

START = 1_000_000
STEP = 3600


def bar(i: int, close: float, high: float | None = None, low: float | None = None) -> Bar:
    return Bar(
        time=START + i * STEP,
        open=close,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
    )


def flat(n: int, price: float = 1.0) -> list[Bar]:
    return [bar(i, price) for i in range(n)]


def order(side: str = "BUY", volume: float = 1.0, sl: float | None = None, tp: float | None = None) -> OrderRequest:
    return OrderRequest(symbol="EURUSD", side=side, volume=volume, sl=sl, tp=tp)  # type: ignore[arg-type]


# -- the account itself ------------------------------------------------------------------------------
def test_an_account_survives_being_written_and_read_back() -> None:
    bars = flat(10)
    bars[3] = bar(3, 1.0, high=1.02)  # reaches the buy's target
    paper = PaperTradingEngine(initial_balance=5_000, profile_id="a1", name="Scalping", created_at=10, updated_at=20)
    paper.begin_session(bars[0], symbol="EURUSD")
    paper.place(order(tp=1.01), bars[0])
    paper.place(order("SELL"), bars[0])
    for b in bars[1:6]:
        paper.on_bar(b)

    copy = PaperTradingEngine.from_dict(json.loads(json.dumps(paper.to_dict())))

    assert (copy.profile_id, copy.name, copy.initial_balance) == ("a1", "Scalping", 5_000)
    assert copy.balance == pytest.approx(paper.balance)
    assert [t.model_dump() for t in copy.closed] == [t.model_dump() for t in paper.closed]
    assert list(copy.positions) == list(paper.positions) == [2]  # the sell is still open
    assert copy.positions[2].mark_price == paper.positions[2].mark_price
    assert copy.account(1.0).metrics == paper.account(1.0).metrics  # the running figures came along
    assert copy._next_ticket == paper._next_ticket == 3


@pytest.mark.parametrize(
    "broken",
    [
        {},
        {"initial_balance": "x", "balance": 1},
        {"initial_balance": 0, "balance": 0},
        {"initial_balance": -5, "balance": 10},
        {"initial_balance": 100, "balance": math.nan},
        {"initial_balance": 100, "balance": 100, "positions": [{"ticket": 1}]},
    ],
)
def test_a_file_that_is_not_an_account_is_refused(broken: dict) -> None:
    with pytest.raises(ValueError):
        PaperTradingEngine.from_dict(broken)


def test_positions_left_open_are_closed_where_they_were_last_marked() -> None:
    bars = flat(8)
    bars[5:] = [bar(i, 1.02) for i in range(5, 8)]
    paper = PaperTradingEngine()
    paper.begin_session(bars[0], symbol="EURUSD")
    paper.place(order(), bars[0])
    for b in bars[1:6]:
        paper.on_bar(b)  # the cursor got as far as bar 5

    made = paper.settle_all(None, "session")

    assert [(t.reason, t.exit_price, t.exit_time, t.symbol) for t in made] == [
        ("session", 1.02, bars[5].time, "EURUSD")
    ]
    assert paper.positions == {}
    assert paper.balance == pytest.approx(10_000 + 0.02 * 100_000)


def test_a_new_session_keeps_the_balance_the_history_and_the_figures() -> None:
    bars = flat(6)
    bars[3] = bar(3, 0.99)
    paper = PaperTradingEngine(initial_balance=10_000)
    paper.begin_session(bars[0], symbol="EURUSD")
    ticket = paper.place(order(), bars[0]).order_id
    for b in bars[1:4]:
        paper.on_bar(b)
    paper.close(ticket, bars[3])  # a loss of 1,000 and a drawdown with it
    paper.place(order("SELL"), bars[3])  # and one left open
    assert paper._max_dd_value == pytest.approx(1_000)

    paper.begin_session(bars[0], symbol="GBPUSD")

    assert paper.balance == pytest.approx(9_000)  # the open sell, still at its entry price, closed even
    assert [t.reason for t in paper.closed] == ["manual", "session"]
    assert paper._max_dd_value == pytest.approx(1_000)  # the worst drawdown is not forgotten either
    assert paper.symbol == "GBPUSD"
    assert [p["value"] for p in paper._equity_curve] == [pytest.approx(9_000)]  # only the curve starts again


def test_resetting_starts_over_with_the_same_or_a_new_balance() -> None:
    paper = PaperTradingEngine(initial_balance=2_000)
    bars = flat(4)
    paper.begin_session(bars[0], symbol="EURUSD")
    paper.place(order(), bars[0])
    paper.settle_all(bars[1])
    paper.reset()
    assert (paper.balance, paper.initial_balance, paper.closed, paper.positions) == (2_000, 2_000, [], {})
    paper.reset(7_500)
    assert (paper.balance, paper.initial_balance) == (7_500, 7_500)
    assert paper.metrics(1.0).total_return_pct == 0


def test_profit_is_in_the_account_currency_when_the_tick_value_is_known() -> None:
    """A yen pair is paid in yen: by the contract size 1 yen on 2 lots would be 200,000 "dollars"."""
    common = dict(ticket=1, symbol="USDJPY", volume=2.0, price_open=150.0, contract_size=100_000.0)
    buy = PaperPosition(side="BUY", tick_size=0.001, tick_value=0.64, **common)  # one yen is 1,000 ticks of 0.64
    sell = PaperPosition(side="SELL", tick_size=0.001, tick_value=0.64, **common)
    unknown = PaperPosition(side="BUY", **common)
    assert buy.pnl(151.0) == pytest.approx(2 * 640)
    assert sell.pnl(151.0) == pytest.approx(-2 * 640)
    assert unknown.pnl(151.0) == pytest.approx(2 * 100_000)  # no tick value: the contract size, as before


def test_profit_is_booked_in_cents_so_the_kept_balance_stays_clean() -> None:
    """A balance that lives for good must not collect float dust: 0.1 + 0.2 style tails, trade after trade."""
    paper = PaperTradingEngine(initial_balance=5_000)
    paper.begin_session(bar(0, 1.0), symbol="EURUSD")
    for i in range(1, 40):
        price = 1.0 + 0.00001234 * i  # prices that give profits with many decimals
        paper.place(order(volume=0.37), bar(i, price))
        paper.close(i, bar(i, price + 0.00003217 * i))
    assert all(t.pnl == round(t.pnl, 2) for t in paper.closed)
    assert paper.balance == round(paper.balance, 2)
    assert paper.balance == pytest.approx(5_000 + sum(t.pnl for t in paper.closed))
    assert json.loads(json.dumps(paper.to_dict()))["balance"] == paper.balance  # and it is stored as it is


def test_the_account_tells_its_keeper_when_it_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(paper_module, "time", types.SimpleNamespace(monotonic=lambda: clock[0], time=time.time))
    seen: list[int] = []
    paper = PaperTradingEngine()
    paper.on_change = lambda p: seen.append(len(p.positions))
    bars = flat(8)

    paper.begin_session(bars[0], symbol="EURUSD")
    ticket = paper.place(order(), bars[0]).order_id
    paper.modify(ticket, 0.9, None)
    assert len(seen) == 3  # a session began, a position was opened, its stop was set

    clock[0] += 0.5
    paper.on_bar(bars[1])  # the cursor moved: only the marks changed, and they were just kept
    assert len(seen) == 3
    clock[0] += 2.5
    paper.on_bar(bars[2])  # ...but not for ever
    assert len(seen) == 4

    paper.close(ticket, bars[2])
    assert len(seen) == 5 and seen[-1] == 0


def test_a_failing_keeper_does_not_stop_the_replay() -> None:
    paper = PaperTradingEngine()

    def boom(_: PaperTradingEngine) -> None:
        raise OSError("disk full")

    paper.on_change = boom
    assert paper.place(order(), bar(0, 1.0)).ok  # logged, not raised


# -- the store ---------------------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles", Preferences(tmp_path / "prefs.json"))


def test_the_first_use_makes_a_profile_with_ten_thousand(store: ProfileStore, tmp_path) -> None:
    listed = store.summaries()
    assert [(p.name, p.initial_balance, p.balance) for p in listed] == [("Paper account", 10_000, 10_000)]
    assert store.active_id() == listed[0].id
    assert (tmp_path / "profiles" / f"{listed[0].id}.json").is_file()


def test_a_profile_has_the_balance_it_was_made_with(store: ProfileStore) -> None:
    swing = store.create("Swing 5k", 5_000)
    assert (swing.initial_balance, swing.balance) == (5_000, 5_000)
    assert store.active_id() == swing.profile_id
    day = store.create("Day trading", 25_000.555, activate=False)
    assert day.initial_balance == 25_000.56  # to the cent
    assert store.active_id() == swing.profile_id  # not switched


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_a_profile_needs_a_sensible_name(store: ProfileStore, name: str) -> None:
    with pytest.raises(ProfileError) as caught:
        store.create(name, 1_000)
    assert caught.value.status == 422


def test_names_are_tidied_and_unique(store: ProfileStore) -> None:
    store.create("  Swing   trades ", 1_000)
    assert [p.name for p in store.summaries()] == ["Swing trades"]
    with pytest.raises(ProfileError) as caught:
        store.create("swing TRADES", 1_000)
    assert caught.value.status == 409


@pytest.mark.parametrize("balance", [0, -5, 0.5, math.nan, math.inf, 2e9, "abc", None])
def test_the_balance_has_to_be_sensible(store: ProfileStore, balance) -> None:
    with pytest.raises(ProfileError) as caught:
        store.create("Bad", balance)
    assert caught.value.status == 422
    assert store.engines() == []  # nothing half-made


def test_there_is_a_limit_to_the_number_of_profiles(store: ProfileStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profiles_module, "MAX_PROFILES", 3)
    for name in "abc":
        store.create(name, 100)
    with pytest.raises(ProfileError) as caught:
        store.create("d", 100)
    assert caught.value.status == 409


def test_profiles_come_back_after_a_restart(tmp_path) -> None:
    first = ProfileStore(tmp_path / "p", Preferences(tmp_path / "prefs.json"))
    swing = first.create("Swing", 5_000)
    bars = flat(8)
    swing.begin_session(bars[0], symbol="EURUSD")
    ticket = swing.place(order(), bars[0]).order_id
    swing.on_bar(bars[1])
    swing.close(ticket, bars[1])
    first.create("Scalp", 2_000, activate=False)
    first.set_active(swing.profile_id)

    # a new program: nothing is in memory, everything comes from the files
    second = ProfileStore(tmp_path / "p", Preferences(tmp_path / "prefs.json"))

    assert [(p.name, p.initial_balance) for p in second.summaries()] == [("Swing", 5_000), ("Scalp", 2_000)]
    assert second.active().name == "Swing"
    kept = second.get(swing.profile_id)
    assert kept.balance == pytest.approx(swing.balance)
    assert [(t.symbol, t.reason) for t in kept.closed] == [("EURUSD", "manual")]


def test_a_profile_can_be_renamed(store: ProfileStore) -> None:
    a = store.create("A", 100)
    store.create("B", 100)
    store.rename(a.profile_id, "Alpha")
    assert [p.name for p in store.summaries()] == ["Alpha", "B"]
    with pytest.raises(ProfileError) as caught:
        store.rename(a.profile_id, "b")
    assert caught.value.status == 409
    store.rename(a.profile_id, "ALPHA")  # its own name in other letters is fine
    assert store.get(a.profile_id).name == "ALPHA"


def test_resetting_clears_the_history_and_can_change_the_balance(store: ProfileStore) -> None:
    p = store.create("P", 1_000)
    bars = flat(6)
    p.begin_session(bars[0], symbol="EURUSD")
    ticket = p.place(order(), bars[0]).order_id
    p.on_bar(bars[1])
    p.close(ticket, bars[1])
    p.place(order(), bars[1])

    store.reset(p.profile_id)
    assert (p.balance, p.initial_balance, len(p.closed), p.positions) == (1_000, 1_000, 0, {})

    store.reset(p.profile_id, 7_500)
    assert (p.balance, p.initial_balance) == (7_500, 7_500)
    with pytest.raises(ProfileError):
        store.reset(p.profile_id, -1)
    assert p.initial_balance == 7_500


def test_deleting_the_active_profile_switches_to_another(store: ProfileStore, tmp_path) -> None:
    a = store.create("A", 100)
    b = store.create("B", 200)  # the active one

    assert store.delete(b.profile_id) == a.profile_id

    assert [p.name for p in store.summaries()] == ["A"]
    assert not (tmp_path / "profiles" / f"{b.profile_id}.json").exists()
    with pytest.raises(ProfileError) as caught:
        store.delete(b.profile_id)
    assert caught.value.status == 404
    # an account that was handed out earlier can no longer bring the file back
    b.place(order(), bar(0, 1.0))
    assert not (tmp_path / "profiles" / f"{b.profile_id}.json").exists()


def test_deleting_the_last_profile_leaves_a_fresh_one(store: ProfileStore) -> None:
    only = store.create("Only", 123)
    store.delete(only.profile_id)
    assert [(p.name, p.balance) for p in store.summaries()] == [("Paper account", 10_000)]


def test_an_unreadable_file_is_set_aside_not_fatal(tmp_path) -> None:
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "bad.json").write_text("{not json", encoding="utf-8")
    (folder / "odd.json").write_text(json.dumps({"initial_balance": -1, "balance": 0}), encoding="utf-8")
    store = ProfileStore(folder, Preferences(tmp_path / "prefs.json"))

    assert [p.name for p in store.summaries()] == ["Paper account"]
    assert (folder / "bad.corrupt").exists() and (folder / "odd.corrupt").exists()
    assert not (folder / "bad.json").exists()


def test_a_cut_off_replay_is_settled_at_the_next_start(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(paper_module, "time", types.SimpleNamespace(monotonic=lambda: clock[0], time=time.time))
    prefs = Preferences(tmp_path / "prefs.json")
    first = ProfileStore(tmp_path / "p", prefs)
    p = first.create("P", 10_000)
    bars = flat(8)
    bars[3:] = [bar(i, 1.01) for i in range(3, 8)]
    p.begin_session(bars[0], symbol="EURUSD")
    p.place(order(), bars[0])
    for b in bars[1:4]:
        clock[0] += 3  # the marks are kept every couple of seconds
        p.on_bar(b)  # the last one marks it at 1.01 and keeps that; then the program dies

    reopened = ProfileStore(tmp_path / "p", Preferences(tmp_path / "prefs.json"))
    assert len(reopened.get(p.profile_id).positions) == 1
    assert reopened.settle_interrupted() == 1

    again = ProfileStore(tmp_path / "p", Preferences(tmp_path / "prefs.json"))
    kept = again.get(p.profile_id)
    assert kept.positions == {}
    assert [(t.reason, t.exit_price) for t in kept.closed] == [("session", 1.01)]
    assert kept.balance == pytest.approx(10_000 + 0.01 * 100_000)
    assert again.settle_interrupted() == 0


def test_the_list_says_how_each_profile_is_doing(store: ProfileStore) -> None:
    p = store.create("P", 1_000)
    bars = flat(6)
    bars[2] = bar(2, 1.001)
    bars[4] = bar(4, 0.999)
    p.begin_session(bars[0], symbol="EURUSD")
    win = p.place(order(), bars[0]).order_id
    p.close(win, bars[2])  # +100
    lose = p.place(order(), bars[2]).order_id
    p.close(lose, bars[4])  # -200
    p.place(order(), bars[4])  # still open

    (s,) = store.summaries()

    assert (s.trades, s.wins, s.losses, s.open_positions) == (2, 1, 1, 1)
    assert s.balance == pytest.approx(1_000 + 100 - 200)
    assert s.realized == pytest.approx(-100)
    assert s.return_pct == pytest.approx(-10)


# -- through the API ---------------------------------------------------------------------------------
def begin(client: TestClient, back: int = 120, symbol: str = "EURUSD") -> dict:
    bars = client.get("/api/bars", params={"symbol": symbol, "timeframe": "H1", "count": 400}).json()
    reply = client.post(
        "/api/replay/start", params={"symbol": symbol, "timeframe": "H1", "time": bars[-back]["time"]}
    )
    assert reply.status_code == 200, reply.text
    return reply.json()


def buy(client: TestClient, volume: float = 1.0, symbol: str = "EURUSD", **extra) -> dict:
    reply = client.post(
        "/api/replay/orders", json={"symbol": symbol, "side": "BUY", "volume": volume, **extra}
    ).json()
    assert reply["ok"], reply
    return reply


def by_name(view: dict) -> dict:
    return {p["name"]: p for p in view["profiles"]}


def test_a_replay_trades_on_the_profile_with_its_own_balance() -> None:
    with TestClient(app) as client:
        first = client.get("/api/replay/profiles").json()
        assert [(p["name"], p["balance"]) for p in first["profiles"]] == [("Paper account", 10_000)]

        made = client.post("/api/replay/profiles", json={"name": "Swing", "balance": 5_000}).json()
        assert made["active"] == by_name(made)["Swing"]["id"]
        update = begin(client)

    assert update["account"]["initial_balance"] == update["account"]["balance"] == 5_000
    assert update["account"]["profile_name"] == "Swing"
    assert update["account"]["equity"] == 5_000 and update["account"]["trades_total"] == 0


def test_the_balance_and_history_survive_the_end_of_a_replay() -> None:
    with TestClient(app) as client:
        client.post("/api/replay/profiles", json={"name": "Swing", "balance": 5_000})
        begin(client)
        placed = buy(client)
        client.post("/api/replay/advance", params={"delta": 4})
        assert client.delete(f"/api/replay/positions/{placed['order_id']}").json()["ok"]
        traded = client.get("/api/replay/account").json()

        stopped = client.post("/api/replay/stop").json()
        assert client.get("/api/replay/account").status_code == 409  # no replay is running any more
        kept = by_name(stopped)["Swing"]
        assert kept["balance"] == pytest.approx(traded["balance"]) and kept["trades"] == 1

        again = begin(client)  # the next replay carries on from there
        trades = client.get("/api/replay/trades").json()
        report = client.get("/api/replay/report").json()

    assert again["account"]["initial_balance"] == 5_000
    assert again["account"]["balance"] == pytest.approx(traded["balance"])
    assert again["account"]["trades_total"] == 1
    assert [t["symbol"] for t in trades] == ["EURUSD"]
    assert report["summary"]["trades"] == 1  # the report counts every session of the profile
    assert report["equity"][0]["value"] == pytest.approx(traded["balance"])  # this session's curve starts at the balance


def test_positions_still_open_are_closed_when_the_replay_ends() -> None:
    with TestClient(app) as client:
        begin(client)
        buy(client)
        client.post("/api/replay/advance", params={"delta": 3})
        engine = get_state().replay
        price = engine.bars[engine.index].close
        stopped = client.post("/api/replay/stop").json()

    (profile,) = stopped["profiles"]
    assert (profile["open_positions"], profile["trades"]) == (0, 1)
    (trade,) = get_state().profiles.active().closed
    assert (trade.reason, trade.exit_price) == ("session", price)
    assert profile["balance"] == pytest.approx(10_000 + trade.pnl)


def test_starting_another_replay_closes_what_the_last_one_left_open() -> None:
    with TestClient(app) as client:
        begin(client)
        buy(client)
        client.post("/api/replay/advance", params={"delta": 3})
        second = begin(client, back=80)  # without leaving the first one

    assert second["account"]["positions"] == []
    assert second["account"]["trades_total"] == 1
    assert get_state().profiles.active().closed[0].reason == "session"


def test_switching_profile_in_a_running_replay_closes_the_open_positions_first() -> None:
    with TestClient(app) as client:
        default = client.get("/api/replay/profiles").json()["profiles"][0]
        view = client.post("/api/replay/profiles", json={"name": "Other", "balance": 2_000, "activate": False}).json()
        other = by_name(view)["Other"]
        assert view["active"] == default["id"]  # not switched yet
        begin(client)
        buy(client)
        client.post("/api/replay/advance", params={"delta": 2})

        switched = client.post(f"/api/replay/profiles/{other['id']}/select").json()
        now = client.get("/api/replay/account").json()
        client.post(f"/api/replay/profiles/{default['id']}/select")
        before = client.get("/api/replay/account").json()

    assert switched["active"] == other["id"]
    assert (now["profile_name"], now["balance"], now["positions"], now["trades_total"]) == ("Other", 2_000, [], 0)
    assert before["profile_name"] == "Paper account"
    assert before["positions"] == [] and before["trades_total"] == 1  # closed when it was switched away from


def test_deleting_the_profile_in_use_moves_a_running_replay_to_another() -> None:
    with TestClient(app) as client:
        default = client.get("/api/replay/profiles").json()["profiles"][0]
        swing = by_name(client.post("/api/replay/profiles", json={"name": "Swing", "balance": 5_000}).json())["Swing"]
        begin(client)
        buy(client)

        view = client.delete(f"/api/replay/profiles/{swing['id']}").json()
        account = client.get("/api/replay/account").json()

    assert view["active"] == default["id"] and [p["name"] for p in view["profiles"]] == ["Paper account"]
    assert (account["profile_name"], account["positions"]) == ("Paper account", [])
    assert not (get_state().profiles.folder / f"{swing['id']}.json").exists()


def test_a_profile_can_be_reset_with_a_new_balance_while_it_trades() -> None:
    with TestClient(app) as client:
        default = client.get("/api/replay/profiles").json()["profiles"][0]
        begin(client)
        placed = buy(client)
        client.post("/api/replay/advance", params={"delta": 3})
        client.delete(f"/api/replay/positions/{placed['order_id']}")

        view = client.post(f"/api/replay/profiles/{default['id']}/reset", json={"balance": 20_000}).json()
        account = client.get("/api/replay/account").json()
        report = client.get("/api/replay/report").json()

    assert by_name(view)["Paper account"]["initial_balance"] == 20_000
    assert (account["initial_balance"], account["balance"], account["trades_total"]) == (20_000, 20_000, 0)
    assert len(report["equity"]) == 1 and report["equity"][0]["value"] == 20_000


def test_resetting_one_profile_leaves_the_others_alone() -> None:
    with TestClient(app) as client:
        a = by_name(client.post("/api/replay/profiles", json={"name": "A", "balance": 1_000}).json())["A"]
        b = by_name(client.post("/api/replay/profiles", json={"name": "B", "balance": 3_000}).json())["B"]
        begin(client)
        buy(client)
        client.post("/api/replay/stop")  # B has a trade now
        view = client.post(f"/api/replay/profiles/{a['id']}/reset").json()

    kept = by_name(view)
    assert kept["B"]["trades"] == 1 and kept["B"]["initial_balance"] == 3_000
    assert kept["A"]["trades"] == 0 and kept["A"]["balance"] == 1_000
    assert b["id"] != a["id"]


def test_the_legacy_reset_resets_only_the_profile_in_use() -> None:
    with TestClient(app) as client:
        a = by_name(client.post("/api/replay/profiles", json={"name": "A", "balance": 1_000}).json())["A"]
        client.post("/api/replay/profiles", json={"name": "B", "balance": 3_000})
        begin(client)
        buy(client)
        client.post("/api/replay/reset-account")
        stopped = client.post("/api/replay/stop").json()

    kept = by_name(stopped)
    assert kept["B"]["trades"] == 0 and kept["B"]["balance"] == 3_000 and kept["A"]["id"] == a["id"]


def test_the_api_says_what_is_wrong() -> None:
    with TestClient(app) as client:
        made = client.post("/api/replay/profiles", json={"name": "Swing", "balance": 5_000}).json()
        swing = by_name(made)["Swing"]
        assert client.post("/api/replay/profiles", json={"name": "swing", "balance": 5_000}).status_code == 409
        assert client.post("/api/replay/profiles", json={"name": "", "balance": 5_000}).status_code == 422
        assert client.post("/api/replay/profiles", json={"name": "X", "balance": -1}).status_code == 422
        assert client.post("/api/replay/profiles", json={"name": "X", "balance": "lots"}).status_code == 422
        assert client.patch("/api/replay/profiles/nope", json={"name": "Y"}).status_code == 404
        assert client.post("/api/replay/profiles/nope/select").status_code == 404
        assert client.post("/api/replay/profiles/nope/reset").status_code == 404
        assert client.delete("/api/replay/profiles/nope").status_code == 404
        renamed = client.patch(f"/api/replay/profiles/{swing['id']}", json={"name": "  Swing   2 "}).json()
        assert "Swing 2" in by_name(renamed)
        assert client.post(f"/api/replay/profiles/{swing['id']}/reset", json={"balance": 0}).status_code == 422
        reason = client.post("/api/replay/profiles", json={"name": "swing 2", "balance": 100}).json()["detail"]
    assert "Swing 2" in reason


def test_closing_the_program_in_the_middle_of_a_replay_keeps_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(app) as client:
        begin(client)
        buy(client)
    # leaving that block shut the program down: the position was closed and written down

    monkeypatch.setattr(app_state, "_state", None)  # the next program knows nothing but the files
    with TestClient(app) as client:
        (profile,) = client.get("/api/replay/profiles").json()["profiles"]

    assert (profile["trades"], profile["open_positions"]) == (1, 0)


def test_a_replay_cut_off_by_a_crash_is_settled_when_the_program_starts_again(monkeypatch: pytest.MonkeyPatch) -> None:
    store = get_state().profiles
    paper = store.active()
    bars = flat(6)
    paper.begin_session(bars[0], symbol="EURUSD")
    paper.place(order(), bars[0])  # open when the program died: nothing settled it

    monkeypatch.setattr(app_state, "_state", None)
    with TestClient(app) as client:
        (profile,) = client.get("/api/replay/profiles").json()["profiles"]

    assert (profile["trades"], profile["open_positions"]) == (1, 0)


def test_the_profile_in_use_is_remembered_across_restarts(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(app) as client:
        client.get("/api/replay/profiles")
        swing = by_name(client.post("/api/replay/profiles", json={"name": "Swing", "balance": 5_000}).json())["Swing"]
    monkeypatch.setattr(app_state, "_state", None)
    with TestClient(app) as client:
        view = client.get("/api/replay/profiles").json()
    assert view["active"] == swing["id"]
    assert [p["name"] for p in view["profiles"]] == ["Paper account", "Swing"]


def test_profit_follows_the_instruments_tick_value() -> None:
    """USDJPY at 0.64 dollars a tick: 1 yen on 1 lot is 640, not the 100,000 the contract size says."""
    with TestClient(app) as client:
        symbols = get_state().symbols
        jpy = symbols.get("USDJPY")
        assert jpy is not None
        symbols._symbols["USDJPY"] = Symbol(**{**jpy.model_dump(), "trade_tick_size": 0.001, "trade_tick_value": 0.64})
        begin(client, symbol="USDJPY")
        placed = buy(client, symbol="USDJPY")
        moved = client.post("/api/replay/advance", params={"delta": 5}).json()

    (position,) = moved["account"]["positions"]
    last = moved["bars"][-1]["close"]
    assert position["profit"] == pytest.approx((last - placed["price"]) / 0.001 * 0.64)
