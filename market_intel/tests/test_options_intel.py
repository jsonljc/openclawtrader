"""
Tests for options intelligence analytics.
"""

import pytest
from market_intel.analytics.options_intel import (
    compute_gex,
    compute_skew,
    detect_unusual_flow,
    compute_term_structure,
)


def test_positive_gex():
    """More call OI near ATM -> positive GEX."""
    chain = [
        {"strike": 5300, "call_oi": 100, "put_oi": 50},
        {"strike": 5350, "call_oi": 500, "put_oi": 100},  # ATM
        {"strike": 5400, "call_oi": 200, "put_oi": 80},
    ]

    gex = compute_gex(chain, spot=5350)

    # Net positive call OI -> positive GEX
    assert gex > 0


def test_negative_gex():
    """More put OI -> negative GEX."""
    chain = [
        {"strike": 5300, "call_oi": 50, "put_oi": 300},
        {"strike": 5350, "call_oi": 100, "put_oi": 500},  # ATM
        {"strike": 5400, "call_oi": 80, "put_oi": 200},
    ]

    gex = compute_gex(chain, spot=5350)

    # Net positive put OI -> negative GEX
    assert gex < 0


def test_gex_empty_chain():
    """Empty chain returns 0.0."""
    gex = compute_gex([])
    assert gex == 0.0


def test_skew_normal():
    """Puts slightly higher IV than calls -> positive skew."""
    chain = [
        {"strike": 5200, "call_iv": 14.0, "put_iv": 21.0},
        {"strike": 5250, "call_iv": 15.0, "put_iv": 19.0},
        {"strike": 5300, "call_iv": 16.0, "put_iv": 18.0},
        {"strike": 5350, "call_iv": 17.0, "put_iv": 17.0},
        {"strike": 5400, "call_iv": 18.0, "put_iv": 15.0},
    ]
    historical_skew = 3.0

    result = compute_skew(chain, historical_skew)

    # Put IV > call IV at OTM strikes
    assert result["skew"] > 2.0


def test_skew_shift_positive():
    """Skew higher than historical -> positive shift."""
    chain = [
        {"strike": 5200, "call_iv": 13.0, "put_iv": 23.0},
        {"strike": 5250, "call_iv": 15.0, "put_iv": 21.0},
        {"strike": 5300, "call_iv": 16.0, "put_iv": 20.0},
        {"strike": 5350, "call_iv": 17.0, "put_iv": 19.0},
        {"strike": 5400, "call_iv": 18.0, "put_iv": 17.0},
    ]
    historical_skew = 3.0

    result = compute_skew(chain, historical_skew)

    # Current skew ~5, historical 3 -> shift ~+2
    assert result["skew_shift"] > 1.0


def test_unusual_flow_detected():
    """Strike with vol/OI > 2 flagged."""
    chain = [
        {"strike": 5300, "call_vol": 100, "call_oi": 200, "put_vol": 50, "put_oi": 100},
        {"strike": 5350, "call_vol": 500, "call_oi": 100, "put_vol": 60, "put_oi": 120},  # Unusual call flow
        {"strike": 5400, "call_vol": 80, "call_oi": 150, "put_vol": 300, "put_oi": 100},  # Unusual put flow
    ]

    unusual = detect_unusual_flow(chain)

    # Should detect 2 unusual strikes
    assert len(unusual) == 2

    # Check call flow at 5350
    call_alert = next((u for u in unusual if u["strike"] == 5350 and u["type"] == "call"), None)
    assert call_alert is not None
    assert call_alert["vol_oi_ratio"] == 5.0

    # Check put flow at 5400
    put_alert = next((u for u in unusual if u["strike"] == 5400 and u["type"] == "put"), None)
    assert put_alert is not None
    assert put_alert["vol_oi_ratio"] == 3.0


def test_no_unusual_flow():
    """All normal activity -> empty list."""
    chain = [
        {"strike": 5300, "call_vol": 100, "call_oi": 200, "put_vol": 50, "put_oi": 100},
        {"strike": 5350, "call_vol": 150, "call_oi": 200, "put_vol": 60, "put_oi": 120},
        {"strike": 5400, "call_vol": 80, "call_oi": 150, "put_vol": 100, "put_oi": 200},
    ]

    unusual = detect_unusual_flow(chain)

    # No vol/OI > 2.0
    assert len(unusual) == 0


def test_term_structure_contango():
    """Front < back -> contango (mean-reversion regime)."""
    front_iv = 15.0
    back_iv = 18.0

    result = compute_term_structure(front_iv, back_iv)

    assert result["slope"] < 0
    assert result["state"] == "contango"


def test_term_structure_backwardation():
    """Front > back -> backwardation (fear/trend regime)."""
    front_iv = 22.0
    back_iv = 16.0

    result = compute_term_structure(front_iv, back_iv)

    assert result["slope"] > 0
    assert result["state"] == "backwardation"


def test_term_structure_flat():
    """Front ~= back -> flat."""
    front_iv = 17.5
    back_iv = 17.0

    result = compute_term_structure(front_iv, back_iv)

    assert result["state"] == "flat"
