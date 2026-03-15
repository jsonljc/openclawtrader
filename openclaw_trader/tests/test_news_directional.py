"""Tests for NEWS_DIRECTIONAL setup scanner."""
import pytest
from datetime import datetime, timezone, timedelta

from workspace_c3po_setups_news_directional import detect


def _make_bar(o, h, l, c, volume=1000):
    return {"o": o, "h": h, "l": l, "c": c, "v": volume}


def _make_signal(direction="LONG", confirm_bars=1, event_type="FED_RATE_CUT_SURPRISE",
                 instruments=None, signal_id="sig_001"):
    return {
        "tier": f"DIRECTIONAL_{direction}",
        "direction": direction,
        "instruments": instruments or ["ES"],
        "event_type": event_type,
        "confirm_bars": confirm_bars,
        "signal_id": signal_id,
        "source_id": "FED_PRESS_RELEASES",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@pytest.fixture
def base_kwargs():
    return {
        "regime": {"regime_type": "NEUTRAL"},
        "session": {
            "session": "MORNING_DRIVE",
            "is_rth": True,
            "minutes_into_session": 60,
            "modifier": 1.0,
        },
        "structure": {"vwap": 5000.0},
        "snapshot": {
            "indicators": {"atr_14_1H": 20.0, "last_price": 5010.0},
        },
        "strategy": {
            "symbol": "ES",
            "tick_size": 0.25,
            "point_value_usd": 5.0,
        },
        "traded_signal_ids": set(),
    }


class TestConfirmationBar:
    def test_long_confirmed_by_bullish_bar(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [confirm_bar]
        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is not None
        assert result["side"] == "LONG"

    def test_long_rejected_by_bearish_bar(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5008, 4995, 4996, volume=1200)
        bars_5m = avg_bars + [confirm_bar]
        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_indecisive_bar_skipped(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5000, 5010, 5000, 5002, volume=1200)
        bars_5m = avg_bars + [confirm_bar]
        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_low_volume_skipped(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=1000)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=500)
        bars_5m = avg_bars + [confirm_bar]
        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_geo_event_needs_2_bars(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        bar1 = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [bar1]
        signal = _make_signal("LONG", confirm_bars=2, event_type="MIDDLE_EAST_ESCALATION")
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_geo_event_passes_with_2_bars(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        bar1 = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bar2 = _make_bar(5013, 5020, 5012, 5018, volume=1100)
        bars_5m = avg_bars + [bar1, bar2]
        signal = _make_signal("LONG", confirm_bars=2, event_type="MIDDLE_EAST_ESCALATION")
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is not None


class TestSizingAndStops:
    def test_sizing_50_pct(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [confirm_bar]
        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is not None
        assert result["sizing_modifier"] == 0.5

    def test_stop_075x_atr(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [confirm_bar]
        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is not None
        atr = 20.0
        expected_stop = result["entry_price"] - (0.75 * atr)
        assert result["stop_price"] == pytest.approx(expected_stop, abs=0.5)


class TestSessionAndDedup:
    def test_no_entry_within_30min_of_close(self, base_kwargs):
        base_kwargs["session"]["minutes_into_session"] = 370
        base_kwargs["session"]["session"] = "MOC_CLOSE"
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [confirm_bar]
        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_one_trade_per_signal_id(self, base_kwargs):
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [confirm_bar]
        signal = _make_signal("LONG", confirm_bars=1, signal_id="sig_already_traded")
        base_kwargs["traded_signal_ids"] = {"sig_already_traded"}
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_not_rth_no_entry(self, base_kwargs):
        base_kwargs["session"]["is_rth"] = False
        avg_bars = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 20
        confirm_bar = _make_bar(5005, 5015, 5004, 5013, volume=1200)
        bars_5m = avg_bars + [confirm_bar]
        signal = _make_signal("LONG", confirm_bars=1)
        result = detect(bars_5m=bars_5m, signals=[signal], **base_kwargs)
        assert result is None

    def test_no_signals_returns_none(self, base_kwargs):
        bars_5m = [_make_bar(5000, 5005, 4998, 5002, volume=800)] * 21
        result = detect(bars_5m=bars_5m, signals=[], **base_kwargs)
        assert result is None
