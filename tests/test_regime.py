#!/usr/bin/env python3
"""Unit tests for regime.py — per-instrument vol scoring, driver weights, risk multiplier.

Covers:
  - _vol_score(): ES/NQ VIX, CL/GC ATR ratio, ZB MOVE index + fallback
  - _score_atr_ratio(): ratio mapping to score
  - _trend_score(): ADX + slope scoring
  - _corr_score(): correlation stress
  - _cross_asset_score(): risk-off detection, equity-only application
  - _liquidity_score(): spread + depth
  - compute_regime(): full pipeline, per-instrument symbol routing
"""

from __future__ import annotations
import os
import sys
import json
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workspace-c3po"))

from shared import contracts as C
from shared import state_store as store


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    os.environ["OPENCLAW_DATA"] = str(data_dir)
    os.environ["OPENCLAW_STRATEGIES"] = str(tmp_path / "strategies")
    os.environ["OPENCLAW_PARAMS"] = str(params_dir)
    importlib.reload(store)
    with open(params_dir / "PV_0001.json", "w") as f:
        json.dump({
            "param_version": "PV_0001",
            "regime": {
                "weight_trend": 0.35, "weight_vol": 0.30, "weight_corr": 0.20,
                "weight_liquidity": 0.15, "sigmoid_steepness": 10,
                "risk_multiplier_floor": 0.30,
            },
            "health": {}, "sentinel": {}, "sizing": {}, "overnight": {}, "slippage": {},
        }, f)
    with open(data_dir / "portfolio.json", "w") as f:
        json.dump({
            "asof": "2026-03-14T12:00:00Z", "param_version": "PV_0001",
            "account": {"equity_usd": 100000.0, "peak_equity_usd": 100000.0,
                         "cash_usd": 100000.0, "margin_used_usd": 0.0,
                         "margin_available_usd": 100000.0, "margin_utilization_pct": 0.0},
            "pnl": {"unrealized_usd": 0.0, "realized_today_usd": 0.0, "total_today_usd": 0.0,
                    "total_today_pct": 0.0, "portfolio_dd_pct": 0.0},
            "positions": [], "heat": {"total_open_risk_usd": 0.0, "total_open_risk_pct": 0.0,
                                       "cluster_exposure": {}, "correlations_20d": {}},
            "sentinel_posture": "NORMAL",
        }, f)


from regime import (
    _sigmoid,
    _trend_score,
    _vol_score,
    _score_atr_ratio,
    _corr_score,
    _cross_asset_score,
    _liquidity_score,
    compute_regime,
)


def _snap(**kw):
    base = {
        "indicators": {"adx_14": 25.0, "ma_20_slope": 0.001, "atr_14_1H": 1.0,
                        "last_price": 5000.0, "ma_20_value": 5000.0},
        "external": {"vix_percentile_252d": 0.5},
        "microstructure": {"spread_ticks": 1, "avg_book_depth_contracts": 850,
                           "avg_book_depth_baseline": 850},
        "data_quality": {"is_stale": False, "last_bar_age_sec": 30},
        "bars": {},
    }
    base.update(kw)
    return base


def _portfolio(**kw):
    base = {"heat": {"correlations_20d": {}}}
    base.update(kw)
    return base


# ── _sigmoid ──

class TestSigmoid:
    def test_midpoint(self):
        assert abs(_sigmoid(0.5) - 0.5) < 0.01

    def test_extremes(self):
        assert _sigmoid(0.0) < 0.01
        assert _sigmoid(1.0) > 0.99

    def test_zero_steepness_is_identity(self):
        assert _sigmoid(0.3, steepness=0) == 0.3


# ── _vol_score by instrument ──

class TestVolScore:
    def test_es_uses_vix(self):
        snap = _snap(external={"vix_percentile_252d": 0.2})
        score, detail = _vol_score(snap, "ES")
        assert detail["vol_source"] == "VIX"
        assert score == pytest.approx(0.8, abs=0.01)

    def test_nq_uses_vix(self):
        snap = _snap(external={"vix_percentile_252d": 0.7})
        score, detail = _vol_score(snap, "NQ")
        assert detail["vol_source"] == "VIX"
        assert score == pytest.approx(0.3, abs=0.01)

    def test_mes_uses_vix(self):
        score, detail = _vol_score(_snap(external={"vix_percentile_252d": 0.5}), "MES")
        assert detail["vol_source"] == "VIX"

    def test_cl_uses_atr_ratio(self):
        bars = [{"h": 72.0, "l": 71.0}] * 20
        snap = _snap(indicators={"atr_14_1H": 1.0, "adx_14": 25.0, "ma_20_slope": 0.0},
                     bars={"1H": bars})
        score, detail = _vol_score(snap, "CL")
        assert detail["vol_source"] == "ATR_RATIO"

    def test_gc_uses_atr_ratio(self):
        bars = [{"h": 2000.0, "l": 1990.0}] * 20
        snap = _snap(indicators={"atr_14_1H": 10.0, "adx_14": 25.0, "ma_20_slope": 0.0},
                     bars={"1H": bars})
        score, detail = _vol_score(snap, "GC")
        assert detail["vol_source"] == "ATR_RATIO"

    def test_zb_uses_move_when_available(self):
        snap = _snap(external={"move_percentile_252d": 0.3})
        score, detail = _vol_score(snap, "ZB")
        assert detail["vol_source"] == "MOVE"
        assert score == pytest.approx(0.7, abs=0.01)

    def test_zb_falls_back_to_atr_ratio(self):
        bars = [{"h": 120.0, "l": 119.0}] * 20
        snap = _snap(external={},
                     indicators={"atr_14_1H": 1.0, "adx_14": 25.0, "ma_20_slope": 0.0},
                     bars={"1H": bars})
        score, detail = _vol_score(snap, "ZB")
        assert detail["vol_source"] == "ATR_RATIO"

    def test_vix_high_gives_low_score(self):
        snap = _snap(external={"vix_percentile_252d": 0.95})
        score, _ = _vol_score(snap, "ES")
        assert score < 0.1

    def test_vix_low_gives_high_score(self):
        snap = _snap(external={"vix_percentile_252d": 0.05})
        score, _ = _vol_score(snap, "ES")
        assert score > 0.9


# ── _score_atr_ratio ──

class TestScoreAtrRatio:
    def test_neutral_ratio(self):
        bars = [{"h": 10.0, "l": 9.0}] * 20
        snap = _snap(indicators={"atr_14_1H": 1.0}, bars={"1H": bars})
        score, detail = _score_atr_ratio(snap, "CL")
        assert 0.4 < score < 0.8
        assert detail["ratio"] == pytest.approx(1.0, abs=0.01)

    def test_high_ratio_low_score(self):
        bars = [{"h": 10.0, "l": 9.0}] * 20
        snap = _snap(indicators={"atr_14_1H": 2.0}, bars={"1H": bars})
        score, _ = _score_atr_ratio(snap, "CL")
        assert score < 0.2

    def test_low_ratio_high_score(self):
        bars = [{"h": 10.0, "l": 9.0}] * 20
        snap = _snap(indicators={"atr_14_1H": 0.5}, bars={"1H": bars})
        score, _ = _score_atr_ratio(snap, "CL")
        assert score > 0.8

    def test_no_bars_returns_neutral(self):
        snap = _snap(indicators={"atr_14_1H": 1.0}, bars={})
        score, detail = _score_atr_ratio(snap, "CL")
        assert score == 0.5
        assert "no data" in detail.get("note", "")

    def test_zero_atr_returns_neutral(self):
        snap = _snap(indicators={"atr_14_1H": 0.0}, bars={"1H": [{"h": 10, "l": 9}] * 20})
        score, _ = _score_atr_ratio(snap, "CL")
        assert score == 0.5


# ── _trend_score ──

class TestTrendScore:
    def test_high_adx_trending(self):
        snap = _snap(indicators={"adx_14": 50.0, "ma_20_slope": 0.01, "atr_14_1H": 1.0})
        score, _ = _trend_score(snap)
        assert score > 0.7

    def test_low_adx_ranging(self):
        snap = _snap(indicators={"adx_14": 10.0, "ma_20_slope": 0.0, "atr_14_1H": 1.0})
        score, _ = _trend_score(snap)
        assert score < 0.4


# ── _corr_score ──

class TestCorrScore:
    def test_no_data_neutral(self):
        score, _ = _corr_score(_snap(), {})
        assert score == 0.5

    def test_high_corr_low_score(self):
        port = {"heat": {"correlations_20d": {"ES_NQ": 0.95}}}
        score, _ = _corr_score(_snap(), port)
        assert score < 0.1

    def test_low_corr_high_score(self):
        port = {"heat": {"correlations_20d": {"ES_CL": 0.1}}}
        score, _ = _corr_score(_snap(), port)
        assert score > 0.85


# ── _cross_asset_score ──

class TestCrossAssetScore:
    def test_no_data_neutral(self):
        score, _ = _cross_asset_score(_snap(), None)
        assert score == 0.5

    def test_dual_risk_off(self):
        snaps = {
            "ZB": {"indicators": {"ma_20_slope": 0.1, "atr_14_1H": 1.0}},
            "GC": {"indicators": {"ma_20_slope": 0.1, "atr_14_1H": 1.0}},
        }
        score, detail = _cross_asset_score(_snap(), snaps)
        assert score < 0.5
        assert detail["signal"] == "RISK_OFF_DUAL"

    def test_single_haven_mild(self):
        snaps = {
            "ZB": {"indicators": {"ma_20_slope": 0.1, "atr_14_1H": 1.0}},
            "GC": {"indicators": {"ma_20_slope": -0.1, "atr_14_1H": 1.0}},
        }
        score, detail = _cross_asset_score(_snap(), snaps)
        assert detail["signal"] == "RISK_OFF_MILD"
        assert score == pytest.approx(0.65, abs=0.01)


# ── _liquidity_score ──

class TestLiquidityScore:
    def test_tight_spread_deep_book(self):
        snap = _snap(microstructure={"spread_ticks": 1, "avg_book_depth_contracts": 1000,
                                      "avg_book_depth_baseline": 850})
        score, _ = _liquidity_score(snap)
        assert score > 0.8

    def test_wide_spread_thin_book(self):
        snap = _snap(microstructure={"spread_ticks": 4, "avg_book_depth_contracts": 200,
                                      "avg_book_depth_baseline": 850})
        score, _ = _liquidity_score(snap)
        assert score < 0.3


# ── compute_regime full pipeline ──

class TestComputeRegime:
    def test_returns_required_fields(self):
        snap = _snap()
        port = _portfolio()
        result = compute_regime(snap, port, symbol="ES")
        assert "effective_regime_score" in result
        assert "risk_multiplier" in result
        assert "drivers" in result
        assert "mode_hint" in result

    def test_risk_multiplier_bounded(self):
        snap = _snap()
        port = _portfolio()
        result = compute_regime(snap, port, symbol="ES")
        assert 0.30 <= result["risk_multiplier"] <= 1.0

    def test_es_symbol_routes_vix(self):
        snap = _snap(external={"vix_percentile_252d": 0.5})
        port = _portfolio()
        result = compute_regime(snap, port, symbol="ES")
        assert result["drivers"]["vol_percentile"]["detail"]["vol_source"] == "VIX"

    def test_cl_symbol_routes_atr(self):
        bars = [{"h": 72.0, "l": 71.0}] * 20
        snap = _snap(indicators={"atr_14_1H": 1.0, "adx_14": 25.0, "ma_20_slope": 0.0},
                     bars={"1H": bars})
        port = _portfolio()
        result = compute_regime(snap, port, symbol="CL")
        assert result["drivers"]["vol_percentile"]["detail"]["vol_source"] == "ATR_RATIO"

    def test_zb_symbol_routes_move(self):
        snap = _snap(external={"move_percentile_252d": 0.4})
        port = _portfolio()
        result = compute_regime(snap, port, symbol="ZB")
        assert result["drivers"]["vol_percentile"]["detail"]["vol_source"] == "MOVE"

    def test_cross_asset_neutral_for_non_equity(self):
        snaps = {
            "ZB": {"indicators": {"ma_20_slope": 0.1, "atr_14_1H": 1.0}},
            "GC": {"indicators": {"ma_20_slope": 0.1, "atr_14_1H": 1.0}},
        }
        snap = _snap()
        port = _portfolio()
        result = compute_regime(snap, port, symbol="CL", all_snapshots=snaps)
        assert result["drivers"]["cross_asset"]["raw"] == pytest.approx(0.5, abs=0.01)

    def test_cross_asset_applied_for_equity(self):
        snaps = {
            "ZB": {"indicators": {"ma_20_slope": 0.1, "atr_14_1H": 1.0}},
            "GC": {"indicators": {"ma_20_slope": 0.1, "atr_14_1H": 1.0}},
        }
        snap = _snap()
        port = _portfolio()
        result = compute_regime(snap, port, symbol="ES", all_snapshots=snaps)
        assert result["drivers"]["cross_asset"]["weight"] > 0

    def test_stale_data_lowers_confidence(self):
        snap = _snap(data_quality={"is_stale": True, "last_bar_age_sec": 300})
        port = _portfolio()
        result = compute_regime(snap, port, symbol="ES")
        assert result["confidence"] == pytest.approx(0.60, abs=0.01)

    def test_fresh_data_higher_confidence(self):
        snap = _snap(data_quality={"is_stale": False, "last_bar_age_sec": 30})
        port = _portfolio()
        result = compute_regime(snap, port, symbol="ES")
        assert result["confidence"] == pytest.approx(0.85, abs=0.01)

    def test_mode_hint_risk_off(self):
        snap = _snap(
            external={"vix_percentile_252d": 0.95},
            indicators={"adx_14": 5.0, "ma_20_slope": -0.01, "atr_14_1H": 1.0},
            microstructure={"spread_ticks": 4, "avg_book_depth_contracts": 200,
                           "avg_book_depth_baseline": 850},
        )
        port = _portfolio(heat={"correlations_20d": {"ES_NQ": 0.9}})
        result = compute_regime(snap, port, symbol="ES")
        assert result["mode_hint"] in ("RISK_OFF", "NEUTRAL")
