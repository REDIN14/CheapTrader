"""Chart drawings: the model, the store, the REST API, the live notice, indicators that draw, the docs."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone

os.environ["CT_BROKER"] = "mock"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import paths  # noqa: E402
from app.broker.mock_adapter import MockAdapter  # noqa: E402
from app.drawings import MAX_PER_SYMBOL, Drawing, DrawingPatch, DrawingStore, as_epoch  # noqa: E402
from app.indicators.registry import BUILTIN_INDICATORS  # noqa: E402
from app.indicators.sandbox import run_indicator  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import IndicatorResult, Timeframe  # noqa: E402


def shape(kind: str, n: int, **style) -> dict:
    return {"type": kind, "points": [{"time": 1_790_000_000 + 3600 * i, "price": 1.1 + 0.01 * i} for i in range(n)], "style": style}


def bars(count: int = 120):
    broker = MockAdapter()
    broker.connect()
    return broker.get_bars("EURUSD", Timeframe.H1, count=count)


# -- the model ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind,n",
    [("trendline", 2), ("rectangle", 2), ("channel", 3), ("long", 3), ("short", 3), ("hline", 1), ("vline", 1), ("polyline", 2), ("polyline", 500), ("text", 1)],
)
def test_each_kind_takes_its_own_number_of_points(kind, n) -> None:
    assert Drawing.model_validate(shape(kind, n)).type == kind


@pytest.mark.parametrize(
    "kind,n",
    [("trendline", 1), ("trendline", 3), ("rectangle", 0), ("channel", 2), ("long", 2), ("short", 4), ("hline", 2), ("polyline", 1), ("polyline", 501), ("text", 0)],
)
def test_a_wrong_number_of_points_is_refused_and_says_so(kind, n) -> None:
    with pytest.raises(ValueError, match=rf"a {kind} takes"):
        Drawing.model_validate(shape(kind, n))


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError):
        Drawing.model_validate(shape("squiggle", 2))


@pytest.mark.parametrize(
    "value,expected",
    [
        (1_790_000_000, 1_790_000_000),
        (1_790_000_000.9, 1_790_000_000),
        ("1790000000", 1_790_000_000),
        ("2026-10-01T09:30:00", int(datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc).timestamp())),
        ("2026-10-01T09:30:00Z", int(datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc).timestamp())),
        (datetime(2026, 10, 1, 9, 30), int(datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc).timestamp())),
        (datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc), int(datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc).timestamp())),
    ],
)
def test_a_time_can_be_written_in_the_usual_ways(value, expected) -> None:
    assert as_epoch(value) == expected


@pytest.mark.parametrize("value", [True, "yesterday", None, [1]])
def test_a_time_that_is_not_one_is_refused(value) -> None:
    with pytest.raises(ValueError):
        as_epoch(value)


def test_a_price_must_be_a_number() -> None:
    with pytest.raises(ValueError):
        Drawing.model_validate({"type": "hline", "points": [{"time": 0, "price": True}]})
    with pytest.raises(ValueError):
        Drawing.model_validate({"type": "hline", "points": [{"time": 0, "price": "high"}]})


@pytest.mark.parametrize(
    "style",
    [{"width": 0}, {"width": 9}, {"fill_opacity": 1.5}, {"fill_opacity": -0.1}, {"dash": "wavy"}, {"font_size": 5}, {"font_size": 73}, {"text": "x" * 201}, {"color": "c" * 33}],
)
def test_style_values_stay_in_bounds(style) -> None:
    with pytest.raises(ValueError):
        Drawing.model_validate(shape("trendline", 2, **style))


def test_the_rectangle_needs_no_style_to_be_complete() -> None:
    d = Drawing.model_validate(shape("rectangle", 2))
    assert d.style.extend_right is None  # unset here: the page's default (to the right) applies


# -- the store ---------------------------------------------------------------------------------------------
def test_drawings_come_back_after_a_restart(tmp_path) -> None:
    saved = DrawingStore(tmp_path).add("EURUSD", Drawing.model_validate(shape("rectangle", 2, extend_right=True, color="#ff9800")))
    again = DrawingStore(tmp_path).for_symbol("EURUSD")  # a new store reading the same folder is a restart
    assert [d.id for d in again] == [saved.id] and saved.id
    assert again[0].style.extend_right is True and again[0].style.color == "#ff9800"
    assert again[0].created > 0
    assert again[0].points == saved.points


def test_each_symbol_has_its_own_drawings(tmp_path) -> None:
    store = DrawingStore(tmp_path)
    store.add("EURUSD", Drawing.model_validate(shape("trendline", 2)))
    store.add("GBPUSD", Drawing.model_validate(shape("hline", 1)))
    assert [d.type for d in store.for_symbol("EURUSD")] == ["trendline"]
    assert [d.type for d in store.for_symbol("GBPUSD")] == ["hline"]
    assert store.for_symbol("USDJPY") == []


def test_a_symbol_name_cannot_reach_outside_the_folder(tmp_path) -> None:
    store = DrawingStore(tmp_path / "drawings")
    store.add("../../evil", Drawing.model_validate(shape("hline", 1)))
    store.add("EUR/USD", Drawing.model_validate(shape("hline", 1)))
    files = sorted(p.name for p in (tmp_path / "drawings").iterdir())
    assert all(p.suffix == ".json" for p in (tmp_path / "drawings").iterdir())
    assert len(files) == 2 and not (tmp_path / "evil.json").exists()
    assert len(store.for_symbol("EUR/USD")) == 1


def test_an_id_is_made_when_none_is_given_and_kept_when_it_is(tmp_path) -> None:
    store = DrawingStore(tmp_path)
    made = store.add("EURUSD", Drawing.model_validate(shape("hline", 1)))
    chosen = store.add("EURUSD", Drawing.model_validate({**shape("hline", 1), "id": "mine"}))
    assert made.id and made.id != "mine" and chosen.id == "mine"
    with pytest.raises(KeyError, match="mine"):
        store.add("EURUSD", Drawing.model_validate({**shape("hline", 1), "id": "mine"}))


def test_replace_keeps_the_id_and_the_birth_time(tmp_path) -> None:
    store = DrawingStore(tmp_path)
    old = store.add("EURUSD", Drawing.model_validate(shape("trendline", 2)))
    new = store.replace("EURUSD", old.id, Drawing.model_validate({**shape("rectangle", 2), "id": "ignored", "created": 5}))
    assert new.id == old.id and new.created == old.created and new.type == "rectangle"
    with pytest.raises(KeyError):
        store.replace("EURUSD", "missing", Drawing.model_validate(shape("hline", 1)))


def test_a_patch_moves_the_points_and_merges_the_style(tmp_path) -> None:
    store = DrawingStore(tmp_path)
    d = store.add("EURUSD", Drawing.model_validate(shape("rectangle", 2, color="#2962ff", extend_right=True)))
    moved = store.patch("EURUSD", d.id, DrawingPatch.model_validate({"style": {"extend_right": False}}))
    assert moved.style.extend_right is False and moved.style.color == "#2962ff"  # the colour was not lost
    assert moved.points == d.points
    pts = [{"time": 5, "price": 2.0}, {"time": 9, "price": 1.0}]
    moved = store.patch("EURUSD", d.id, DrawingPatch.model_validate({"points": pts}))
    assert [(p.time, p.price) for p in moved.points] == [(5, 2.0), (9, 1.0)] and moved.style.extend_right is False
    with pytest.raises(ValueError, match="takes"):
        store.patch("EURUSD", d.id, DrawingPatch.model_validate({"points": pts[:1]}))
    assert [(p.time, p.price) for p in store.for_symbol("EURUSD")[0].points] == [(5, 2.0), (9, 1.0)]  # the bad patch changed nothing
    with pytest.raises(KeyError):
        store.patch("EURUSD", "missing", DrawingPatch())


def test_remove_and_clear(tmp_path) -> None:
    store = DrawingStore(tmp_path)
    a = store.add("EURUSD", Drawing.model_validate(shape("hline", 1)))
    store.add("EURUSD", Drawing.model_validate(shape("vline", 1)))
    assert store.remove("EURUSD", a.id) is True
    assert store.remove("EURUSD", a.id) is False
    assert store.clear("EURUSD") == 1
    assert store.clear("EURUSD") == 0
    assert store.for_symbol("EURUSD") == []


def test_a_damaged_file_or_item_does_not_take_the_others_down(tmp_path) -> None:
    store = DrawingStore(tmp_path)
    good = store.add("EURUSD", Drawing.model_validate(shape("hline", 1)))
    file = next(tmp_path.glob("*.json"))
    data = json.loads(file.read_text(encoding="utf-8"))
    data["drawings"].append({"type": "rectangle", "points": []})  # not valid any more
    file.write_text(json.dumps(data), encoding="utf-8")
    assert [d.id for d in store.for_symbol("EURUSD")] == [good.id]
    file.write_text("{ this is not json", encoding="utf-8")
    assert store.for_symbol("EURUSD") == []
    store.add("EURUSD", Drawing.model_validate(shape("vline", 1)))  # and it can be written again
    assert len(store.for_symbol("EURUSD")) == 1


def test_writing_leaves_no_temporary_files(tmp_path) -> None:
    store = DrawingStore(tmp_path)
    for _ in range(5):
        store.add("EURUSD", Drawing.model_validate(shape("hline", 1)))
    assert [p.suffix for p in tmp_path.iterdir()] == [".json"]


def test_a_symbol_holds_a_limited_number(tmp_path, monkeypatch) -> None:
    import app.drawings as module

    monkeypatch.setattr(module, "MAX_PER_SYMBOL", 3)
    store = DrawingStore(tmp_path)
    for _ in range(3):
        store.add("EURUSD", Drawing.model_validate(shape("hline", 1)))
    with pytest.raises(ValueError, match="at most|the most"):
        store.add("EURUSD", Drawing.model_validate(shape("hline", 1)))
    assert MAX_PER_SYMBOL >= 1000  # generous in real life


def test_the_default_store_follows_the_data_folder(tmp_path, monkeypatch) -> None:
    from app.drawings import store

    monkeypatch.setenv("CT_DATA_DIR", str(tmp_path / "somewhere"))
    store.add("EURUSD", Drawing.model_validate(shape("hline", 1)))
    assert (tmp_path / "somewhere" / "drawings" / "EURUSD.json").is_file()


# -- REST ---------------------------------------------------------------------------------------------------
def test_the_rest_api_adds_lists_changes_and_removes() -> None:
    with TestClient(app) as client:
        assert client.get("/api/drawings", params={"symbol": "EURUSD"}).json() == []

        r = client.post("/api/drawings", params={"symbol": "EURUSD"}, json=shape("rectangle", 2, extend_right=True))
        assert r.status_code == 201
        body = r.json()
        assert body["id"] and body["type"] == "rectangle" and body["created"] > 0
        assert body["style"] == {"extend_right": True}  # nothing but what was set: no nulls

        # the symbol may be in the body instead
        r2 = client.post("/api/drawings", json={**shape("hline", 1), "symbol": "GBPUSD"})
        assert r2.status_code == 201
        assert [d["type"] for d in client.get("/api/drawings", params={"symbol": "GBPUSD"}).json()] == ["hline"]

        listed = client.get("/api/drawings", params={"symbol": "EURUSD"}).json()
        assert [d["id"] for d in listed] == [body["id"]]

        patched = client.patch(f"/api/drawings/{body['id']}", params={"symbol": "EURUSD"}, json={"style": {"color": "#f23645"}})
        assert patched.status_code == 200
        assert patched.json()["style"] == {"extend_right": True, "color": "#f23645"}

        replaced = client.put(f"/api/drawings/{body['id']}", params={"symbol": "EURUSD"}, json=shape("trendline", 2))
        assert replaced.status_code == 200 and replaced.json()["id"] == body["id"] and replaced.json()["type"] == "trendline"

        assert client.delete(f"/api/drawings/{body['id']}", params={"symbol": "EURUSD"}).json() == {"ok": True}
        assert client.get("/api/drawings", params={"symbol": "EURUSD"}).json() == []

        client.post("/api/drawings", params={"symbol": "EURUSD"}, json=shape("hline", 1))
        client.post("/api/drawings", params={"symbol": "EURUSD"}, json=shape("vline", 1))
        cleared = client.delete("/api/drawings", params={"symbol": "EURUSD"}).json()
        assert cleared == {"ok": True, "removed": 2, "kept_locked": 0}
        assert client.get("/api/drawings", params={"symbol": "EURUSD"}).json() == []


def test_the_rest_api_says_what_is_wrong() -> None:
    with TestClient(app) as client:
        bad = client.post("/api/drawings", params={"symbol": "EURUSD"}, json=shape("rectangle", 1))
        assert bad.status_code == 422
        assert "a rectangle takes 2 point(s), not 1" in bad.json()["detail"]
        assert "pydantic" not in bad.json()["detail"] and "errors.pydantic.dev" not in bad.json()["detail"]

        unknown = client.post("/api/drawings", params={"symbol": "EURUSD"}, json=shape("squiggle", 2))
        assert unknown.status_code == 422 and "type" in unknown.json()["detail"]

        no_symbol = client.post("/api/drawings", json=shape("hline", 1))
        assert no_symbol.status_code == 422 and "symbol" in no_symbol.json()["detail"]
        assert client.get("/api/drawings").status_code == 422

        first = client.post("/api/drawings", params={"symbol": "EURUSD"}, json={**shape("hline", 1), "id": "same"})
        assert first.status_code == 201
        again = client.post("/api/drawings", params={"symbol": "EURUSD"}, json={**shape("hline", 1), "id": "same"})
        assert again.status_code == 409 and "same" in again.json()["detail"]

        for call in (
            lambda: client.delete("/api/drawings/nope", params={"symbol": "EURUSD"}),
            lambda: client.patch("/api/drawings/nope", params={"symbol": "EURUSD"}, json={"style": {"width": 2}}),
            lambda: client.put("/api/drawings/nope", params={"symbol": "EURUSD"}, json=shape("hline", 1)),
        ):
            assert call().status_code == 404

        patched = client.patch("/api/drawings/same", params={"symbol": "EURUSD"}, json={"points": []})
        assert patched.status_code == 422 and "takes" in patched.json()["detail"]


def test_times_may_be_written_as_text_in_the_rest_api() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/api/drawings",
            params={"symbol": "EURUSD"},
            json={"type": "vline", "points": [{"time": "2026-10-01T09:30:00Z", "price": 0}]},
        )
        assert r.status_code == 201
        assert r.json()["points"][0]["time"] == int(datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc).timestamp())


def test_open_screens_hear_when_the_drawings_of_a_symbol_change() -> None:
    def next_notice(ws, limit: float = 5.0) -> dict:
        end = time.monotonic() + limit
        while time.monotonic() < end:
            message = ws.receive_json()
            if message.get("type") == "drawings":
                return message
        raise AssertionError("no notice")

    with TestClient(app) as client, client.websocket_connect("/ws/stream") as ws:
        ws.send_json({"type": "subscribe", "symbol": "EURUSD"})
        made = client.post("/api/drawings", params={"symbol": "GBPUSD"}, json=shape("hline", 1)).json()
        assert next_notice(ws) == {"type": "drawings", "symbol": "GBPUSD"}
        client.patch(f"/api/drawings/{made['id']}", params={"symbol": "GBPUSD"}, json={"style": {"width": 3}})
        assert next_notice(ws) == {"type": "drawings", "symbol": "GBPUSD"}
        client.delete(f"/api/drawings/{made['id']}", params={"symbol": "GBPUSD"})
        assert next_notice(ws) == {"type": "drawings", "symbol": "GBPUSD"}
        client.delete("/api/drawings", params={"symbol": "GBPUSD"})  # nothing left to remove: nothing to announce
        client.post("/api/drawings", params={"symbol": "EURUSD"}, json=shape("vline", 1))
        assert next_notice(ws) == {"type": "drawings", "symbol": "EURUSD"}


# -- indicators that draw --------------------------------------------------------------------------------------------
def run(code: str, count: int = 120, params: dict | None = None) -> IndicatorResult:
    return run_indicator("t", "Draws", code, bars(count), params=params or {})


def test_an_indicator_returns_shapes_beside_its_lines() -> None:
    result = run(
        '''
from ct_draw import hline, rectangle, trendline, channel, polyline, text, vline, long, short

def compute(df, params):
    t0, t1, t2 = int(df["time"].iloc[-30]), int(df["time"].iloc[-20]), int(df["time"].iloc[-10])
    hi, lo = float(df["high"].max()), float(df["low"].min())
    return {
        "plots": [{"name": "Mid", "values": (df["high"] + df["low"]) / 2}],
        "drawings": [
            trendline((t0, lo), (t1, hi), color="#ff9800", width=3),
            rectangle((t0, hi), (t2, lo), extend_right=True, fill_opacity=0.2),
            channel((t0, lo), (t1, hi), (t2, lo)),
            polyline([(t0, lo), (t1, hi), (t2, lo)], dash="dotted"),
            text((t1, hi), "peak", font_size=14),
            hline(hi, text="top"),
            vline(t1),
            long((t0, lo), (t2, hi), lo - 0.001),
            short((t0, hi), (t2, lo), hi + 0.001),
        ],
    }
'''
    )
    assert result.error is None, result.error
    assert [p["name"] for p in result.plots] == ["Mid"]
    kinds = [d["type"] for d in result.drawings]
    assert kinds == ["trendline", "rectangle", "channel", "polyline", "text", "hline", "vline", "long", "short"]
    by = {d["type"]: d for d in result.drawings}
    assert by["trendline"]["style"] == {"color": "#ff9800", "width": 3}
    assert by["rectangle"]["style"]["extend_right"] is True
    assert by["text"]["style"]["text"] == "peak"
    assert by["hline"]["points"][0]["time"] == 0 and by["hline"]["style"]["text"] == "top"
    assert by["long"]["points"][1]["time"] == by["long"]["points"][2]["time"]  # the target and the stop end together
    assert by["long"]["points"][2]["price"] < by["long"]["points"][0]["price"]
    assert all(isinstance(p["time"], int) for d in result.drawings for p in d["points"])
    assert all(v is not None for d in result.drawings for v in d["style"].values())  # no empty values


def test_an_indicator_may_draw_and_nothing_else() -> None:
    result = run(
        '''
from ct_draw import hline

def compute(df, params):
    return {"drawings": [hline(1.1)]}
'''
    )
    assert result.error is None and result.plots == [] and len(result.drawings) == 1


def test_shapes_come_with_the_simple_return_form_too() -> None:
    result = run(
        '''
from ct_draw import hline

def compute(df, params):
    return {"SMA": df["close"].rolling(5).mean(), "drawings": [hline(1.1)]}
'''
    )
    assert result.error is None
    assert [p["name"] for p in result.plots] == ["SMA"] and len(result.drawings) == 1


def test_times_may_be_numpy_numbers_datetimes_text_or_pandas_timestamps() -> None:
    result = run(
        '''
import pandas as pd
from datetime import datetime, timezone
from ct_draw import trendline

def compute(df, params):
    first = df["time"].iloc[0]                      # a numpy integer
    return {"drawings": [
        trendline((first, 1.1), (pd.Timestamp("2026-10-01 09:30"), 1.2)),
        trendline(("2026-10-01T09:30:00Z", 1.1), (datetime(2026, 10, 2, tzinfo=timezone.utc), 1.2)),
        {"type": "trendline", "points": [{"time": first, "price": 1.1}, [first + 60, 1.2]]},
    ]}
'''
    )
    assert result.error is None, result.error
    assert result.drawings[0]["points"][1]["time"] == int(datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc).timestamp())
    assert result.drawings[1]["points"][0]["time"] == int(datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc).timestamp())
    assert len(result.drawings[2]["points"]) == 2


@pytest.mark.parametrize(
    "drawing,message",
    [
        ('{"type": "rectangle", "points": [[1, 2]]}', "drawing #1 (rectangle): a rectangle takes 2 point(s), not 1"),
        ('{"type": "box", "points": [[1, 2], [3, 4]]}', "drawing #1: unknown type 'box'"),
        ('{"type": "hline", "points": [[0, float("nan")]]}', "drawing #1: a price is not a number"),
        ('{"type": "hline", "points": [[0, float("inf")]]}', "drawing #1: a price is not a number"),
        ('"hline"', "drawing #1: a drawing is a dict"),
        ('{"type": "text", "points": [["yesterday", 1.0]]}', "drawing #1"),
    ],
)
def test_a_wrong_shape_is_reported_by_number_and_nothing_is_drawn(drawing, message) -> None:
    result = run(f'def compute(df, params):\n    return {{"drawings": [{drawing}]}}\n')
    assert result.error is not None and message in result.error, result.error
    assert result.drawings == [] and result.plots == []


def test_the_number_of_the_wrong_drawing_is_given() -> None:
    result = run(
        '''
from ct_draw import hline

def compute(df, params):
    return {"drawings": [hline(1.1), hline(1.2), {"type": "trendline", "points": [(1, 2)]}]}
'''
    )
    assert result.error is not None and "drawing #3 (trendline): a trendline takes 2 point(s), not 1" in result.error


def test_drawings_must_be_a_list() -> None:
    result = run('def compute(df, params):\n    return {"drawings": {"type": "hline"}}\n')
    assert result.error is not None and "'drawings' must be a list" in result.error


def test_an_indicator_may_draw_a_limited_number_of_shapes() -> None:
    from app.indicators._runner import MAX_DRAWINGS

    ok = run(f'from ct_draw import hline\n\ndef compute(df, params):\n    return {{"drawings": [hline(1.0 + i / 1e5) for i in range({MAX_DRAWINGS})]}}\n')
    assert ok.error is None and len(ok.drawings) == MAX_DRAWINGS
    too_many = run(f'from ct_draw import hline\n\ndef compute(df, params):\n    return {{"drawings": [hline(1.0)] * {MAX_DRAWINGS + 1}}}\n')
    assert too_many.error is not None and "too many drawings" in too_many.error and str(MAX_DRAWINGS) in too_many.error


def test_an_indicator_without_shapes_reports_an_empty_list() -> None:
    result = run('def compute(df, params):\n    return {"x": df["close"]}\n')
    assert result.error is None and result.drawings == []
    assert IndicatorResult(id="a", name="b", overlay=True, pane=0).drawings == []


def test_the_range_box_example_draws_a_box_and_a_line() -> None:
    spec = next(b for b in BUILTIN_INDICATORS if b["id"] == "builtin.rangebox")
    result = run_indicator(spec["id"], spec["name"], spec["code"], bars(200), params=spec["params"])
    assert result.error is None, result.error
    assert [d["type"] for d in result.drawings] == ["rectangle", "hline"]
    assert result.drawings[0]["style"]["extend_right"] is True and result.plots == []


def test_the_indicator_routes_return_the_shapes() -> None:
    with TestClient(app) as client:
        r = client.post("/api/indicators/builtin.rangebox/run", params={"symbol": "EURUSD", "timeframe": "H1", "count": 100})
        assert r.status_code == 200
        body = r.json()
        assert body["error"] is None and [d["type"] for d in body["drawings"]] == ["rectangle", "hline"]
        plain = client.post("/api/indicators/builtin.sma/run", params={"symbol": "EURUSD", "timeframe": "H1", "count": 100}).json()
        assert plain["drawings"] == []


# -- the documentation ------------------------------------------------------------------------------------------------------
def test_the_documentation_is_listed_and_can_be_read() -> None:
    with TestClient(app) as client:
        docs = client.get("/api/docs").json()
        assert [d["id"] for d in docs][:3] == ["getting_started", "indicators", "drawings"]
        assert docs[0]["title"].startswith("Getting Started")
        assert docs[2]["title"].startswith("Drawing on the Chart")
        assert "credits" in [d["id"] for d in docs]
        page = client.get("/api/docs/drawings").json()
        assert page["id"] == "drawings" and page["markdown"].startswith("# Drawing on the Chart")
        assert client.get("/api/docs/Indicators").json()["id"] == "indicators"  # not case sensitive
        assert client.get("/api/docs/nothing").status_code == 404
        assert client.get("/api/docs/..%2F..%2Fsecret").status_code in (404, 422)


def test_a_missing_docs_folder_gives_an_empty_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(paths, "docs_dir", lambda: tmp_path / "nowhere")
    with TestClient(app) as client:
        assert client.get("/api/docs").json() == []


def test_other_documents_in_the_folder_are_listed_after_the_guides(monkeypatch, tmp_path) -> None:
    (tmp_path / "zebra.md").write_text("# The Zebra\n\nstripes", encoding="utf-8")
    (tmp_path / "indicators.md").write_text("# I\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not markdown", encoding="utf-8")
    monkeypatch.setattr(paths, "docs_dir", lambda: tmp_path)
    with TestClient(app) as client:
        assert [(d["id"], d["title"]) for d in client.get("/api/docs").json()] == [("indicators", "I"), ("zebra", "The Zebra")]


def test_the_built_program_reads_the_docs_from_its_bundle(monkeypatch, tmp_path) -> None:
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    assert paths.docs_dir() == tmp_path / "_internal" / "docs"


def test_the_exe_recipe_bundles_the_docs() -> None:
    spec = (paths.backend_root() / "cheaptrader.spec").read_text(encoding="utf-8")
    assert '"docs"' in spec and "ROOT.parent / \"docs\"" in spec


# The documents are read in the app, where a link that leads nowhere is a dead control.
def slug(text: str) -> str:
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text.lower()).strip())


def doc_text(name: str) -> str:
    return (paths.docs_dir() / name).read_text(encoding="utf-8")


def headings(text: str) -> set[str]:
    out: dict[str, int] = {}
    ids = set()
    for match in re.finditer(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.sub(r"```.*?```", "", text, flags=re.S), flags=re.M):
        base = slug(re.sub(r"[`*]", "", match.group(1)))
        n = out.get(base, 0)
        out[base] = n + 1
        ids.add(base if n == 0 else f"{base}-{n}")
    return ids


DOCS = ["INDICATORS.md", "DRAWINGS.md", "GETTING_STARTED.md", "CREDITS.md"]


@pytest.mark.parametrize("name", DOCS)
def test_every_link_in_the_docs_leads_somewhere(name) -> None:
    text = doc_text(name)
    own = headings(text)
    for target in re.findall(r"\]\(([^)\s]+)\)", re.sub(r"```.*?```", "", text, flags=re.S)):
        if target.startswith("http"):
            continue
        file, _, anchor = target.partition("#")
        if file:
            assert (paths.docs_dir() / file).is_file(), f"{name}: {target} points at a file that is not there"
            assert not anchor or anchor in headings(doc_text(file)), f"{name}: {target} has no such heading"
        else:
            assert anchor in own, f"{name}: #{anchor} has no such heading"


@pytest.mark.parametrize("name", ["INDICATORS.md", "DRAWINGS.md"])  # (the others have no indicators in them)
def test_every_example_in_the_docs_runs(name) -> None:
    ran = 0
    for code in re.findall(r"```python\n(.*?)```", doc_text(name), flags=re.S):
        if "def compute" not in code or "..." in code:
            continue  # a sketch, or not an indicator
        result = run_indicator("doc", "doc", code, bars(200), params={})
        assert result.error is None, f"{name}: {result.error}\n{code}"
        ran += 1
    assert ran >= 3


# -- locking and bulk removal ------------------------------------------------------------------------------
def lock(store: DrawingStore, symbol: str, drawing_id: str, locked: bool = True) -> Drawing:
    return store.patch(symbol, drawing_id, DrawingPatch.model_validate({"locked": locked}))


def test_a_locked_drawing_cannot_be_moved_replaced_or_removed(tmp_path) -> None:
    from app.drawings import LockedError

    store = DrawingStore(tmp_path)
    d = store.add("EURUSD", Drawing.model_validate(shape("rectangle", 2, color="#2962ff")))
    assert d.locked is False
    assert lock(store, "EURUSD", d.id).locked is True

    new_points = [{"time": 5, "price": 2.0}, {"time": 9, "price": 1.0}]
    with pytest.raises(LockedError, match="locked"):
        store.patch("EURUSD", d.id, DrawingPatch.model_validate({"points": new_points}))
    with pytest.raises(LockedError):
        store.replace("EURUSD", d.id, Drawing.model_validate(shape("trendline", 2)))
    with pytest.raises(LockedError):
        store.remove("EURUSD", d.id)
    assert store.for_symbol("EURUSD")[0].points == d.points  # nothing moved

    # its look (and the size of the trade a box stands for) can still be changed, and the lock lifted
    styled = store.patch("EURUSD", d.id, DrawingPatch.model_validate({"style": {"color": "#f23645"}}))
    assert styled.locked and styled.style.color == "#f23645"
    assert lock(store, "EURUSD", d.id, False).locked is False
    moved = store.patch("EURUSD", d.id, DrawingPatch.model_validate({"points": new_points}))
    assert [(p.time, p.price) for p in moved.points] == [(5, 2.0), (9, 1.0)]
    assert store.remove("EURUSD", d.id) is True


def test_a_drawing_can_be_born_locked_and_stays_locked_after_a_restart(tmp_path) -> None:
    saved = DrawingStore(tmp_path).add("EURUSD", Drawing.model_validate({**shape("hline", 1), "locked": True}))
    assert saved.locked
    assert DrawingStore(tmp_path).for_symbol("EURUSD")[0].locked is True


def test_clearing_a_symbol_leaves_the_locked_drawings_unless_told_otherwise(tmp_path) -> None:
    store = DrawingStore(tmp_path)
    keep = store.add("EURUSD", Drawing.model_validate(shape("hline", 1)))
    lock(store, "EURUSD", keep.id)
    for _ in range(2):
        store.add("EURUSD", Drawing.model_validate(shape("vline", 1)))
    assert store.clear("EURUSD") == 2  # the default: not the locked one
    assert [d.id for d in store.for_symbol("EURUSD")] == [keep.id]
    assert store.clear("EURUSD", "exclude") == 0
    store.add("EURUSD", Drawing.model_validate(shape("vline", 1)))
    assert store.clear("EURUSD", "only") == 1  # just the locked ones
    assert [d.type for d in store.for_symbol("EURUSD")] == ["vline"]
    lock(store, "EURUSD", store.for_symbol("EURUSD")[0].id)
    store.add("EURUSD", Drawing.model_validate(shape("hline", 1)))
    assert store.clear("EURUSD", "include") == 2
    assert store.for_symbol("EURUSD") == []


def test_every_symbols_drawings_can_be_counted_and_cleared_at_once(tmp_path) -> None:
    store = DrawingStore(tmp_path)
    eur = store.add("EURUSD", Drawing.model_validate(shape("hline", 1)))
    store.add("EURUSD", Drawing.model_validate(shape("vline", 1)))
    gbp = store.add("GBPUSD", Drawing.model_validate(shape("hline", 1)))
    store.add("EUR/USD", Drawing.model_validate(shape("hline", 1)))  # (a name that is not safe as a file name)
    lock(store, "EURUSD", eur.id)
    lock(store, "GBPUSD", gbp.id)
    assert set(store.symbols()) == {"EURUSD", "GBPUSD", "EUR/USD"}
    assert store.summary() == {
        "EURUSD": {"total": 2, "locked": 1},
        "GBPUSD": {"total": 1, "locked": 1},
        "EUR/USD": {"total": 1, "locked": 0},
    }
    assert store.clear_all() == {"EURUSD": 1, "EUR/USD": 1}  # the locked ones stay
    assert store.summary() == {"EURUSD": {"total": 1, "locked": 1}, "GBPUSD": {"total": 1, "locked": 1}}
    assert store.clear_all("only") == {"EURUSD": 1, "GBPUSD": 1}
    assert store.summary() == {} and store.clear_all("include") == {}


def test_the_size_of_the_trade_a_box_stands_for_is_part_of_its_style() -> None:
    d = Drawing.model_validate(shape("long", 3, risk_mode="percent", risk_percent=1.5, lots=0.3, risk_amount=50))
    assert d.style.risk_mode == "percent" and d.style.risk_percent == 1.5 and d.style.lots == 0.3 and d.style.risk_amount == 50
    for bad in ({"risk_mode": "kilos"}, {"risk_percent": 0}, {"risk_percent": 101}, {"risk_amount": -1}, {"lots": 0}):
        with pytest.raises(ValueError):
            Drawing.model_validate(shape("long", 3, **bad))


def test_a_locked_drawing_answers_423_over_rest_and_bulk_deletes_spare_it() -> None:
    with TestClient(app) as client:
        def add(symbol: str, kind: str, n: int, **extra) -> dict:
            r = client.post("/api/drawings", params={"symbol": symbol}, json={**shape(kind, n), **extra})
            assert r.status_code == 201, r.text
            return r.json()

        kept = add("EURUSD", "rectangle", 2, locked=True)
        assert kept["locked"] is True
        loose = add("EURUSD", "trendline", 2)
        other = add("GBPUSD", "hline", 1)
        locked_other = add("GBPUSD", "vline", 1, locked=True)

        for call in (
            lambda: client.delete(f"/api/drawings/{kept['id']}", params={"symbol": "EURUSD"}),
            lambda: client.put(f"/api/drawings/{kept['id']}", params={"symbol": "EURUSD"}, json=shape("trendline", 2)),
            lambda: client.patch(f"/api/drawings/{kept['id']}", params={"symbol": "EURUSD"},
                                 json={"points": [{"time": 1, "price": 1.0}, {"time": 2, "price": 2.0}]}),
        ):
            r = call()
            assert r.status_code == 423 and "locked" in r.json()["detail"]
        assert client.get("/api/drawings", params={"symbol": "EURUSD"}).json()[0]["points"] == kept["points"]

        # a look can be changed while locked, and the lock lifted
        r = client.patch(f"/api/drawings/{kept['id']}", params={"symbol": "EURUSD"}, json={"style": {"color": "#f23645"}})
        assert r.status_code == 200 and r.json()["locked"] is True and r.json()["style"]["color"] == "#f23645"

        summary = client.get("/api/drawings/summary").json()
        assert summary == {"EURUSD": {"total": 2, "locked": 1}, "GBPUSD": {"total": 2, "locked": 1}}

        done = client.delete("/api/drawings", params={"symbol": "EURUSD"}).json()
        assert done == {"ok": True, "removed": 1, "kept_locked": 1}
        assert [d["id"] for d in client.get("/api/drawings", params={"symbol": "EURUSD"}).json()] == [kept["id"]]
        assert loose["id"] not in [d["id"] for d in client.get("/api/drawings", params={"symbol": "EURUSD"}).json()]

        everywhere = client.delete("/api/drawings", params={"all_symbols": "true"}).json()
        assert everywhere["removed"] == 1 and everywhere["symbols"] == {"GBPUSD": 1} and everywhere["kept_locked"] == 2
        assert client.get("/api/drawings", params={"symbol": "GBPUSD"}).json()[0]["id"] == locked_other["id"]
        assert other["id"] not in [d["id"] for d in client.get("/api/drawings", params={"symbol": "GBPUSD"}).json()]

        only = client.delete("/api/drawings", params={"symbol": "EURUSD", "locked": "only"}).json()
        assert only["removed"] == 1 and only["kept_locked"] == 0
        every_locked = client.delete("/api/drawings", params={"all_symbols": "true", "locked": "only"}).json()
        assert every_locked["removed"] == 1 and every_locked["symbols"] == {"GBPUSD": 1}
        assert client.get("/api/drawings/summary").json() == {}


def test_a_drawing_is_unlocked_with_a_patch_and_can_then_be_removed() -> None:
    with TestClient(app) as client:
        made = client.post("/api/drawings", params={"symbol": "EURUSD"}, json={**shape("hline", 1), "locked": True}).json()
        assert client.delete(f"/api/drawings/{made['id']}", params={"symbol": "EURUSD"}).status_code == 423
        r = client.patch(f"/api/drawings/{made['id']}", params={"symbol": "EURUSD"}, json={"locked": False})
        assert r.status_code == 200 and r.json()["locked"] is False
        assert client.delete(f"/api/drawings/{made['id']}", params={"symbol": "EURUSD"}).status_code == 200


def test_bulk_removal_needs_to_know_which_symbols() -> None:
    with TestClient(app) as client:
        r = client.delete("/api/drawings")
        assert r.status_code == 422 and "symbol" in r.json()["detail"]
        assert client.delete("/api/drawings", params={"symbol": "EURUSD", "locked": "maybe"}).status_code == 422


def test_the_pages_hear_about_every_symbol_a_bulk_removal_touched() -> None:
    def notices(ws, count: int, limit: float = 5.0) -> list[dict]:
        got: list[dict] = []
        end = time.monotonic() + limit
        while len(got) < count and time.monotonic() < end:
            message = ws.receive_json()
            if message.get("type") == "drawings":
                got.append(message)
        return got

    with TestClient(app) as client, client.websocket_connect("/ws/stream") as ws:
        ws.send_json({"type": "subscribe", "symbol": "EURUSD"})
        client.post("/api/drawings", params={"symbol": "EURUSD"}, json=shape("hline", 1))
        client.post("/api/drawings", params={"symbol": "GBPUSD"}, json=shape("hline", 1))
        notices(ws, 2)
        client.delete("/api/drawings", params={"all_symbols": "true"})
        assert sorted(n["symbol"] for n in notices(ws, 2)) == ["EURUSD", "GBPUSD"]
