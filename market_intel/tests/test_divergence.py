"""
Tests for divergence detector.
"""

import pytest
from market_intel.analytics.divergence import compute_divergences


def test_es_vix_divergence_bullish():
    """ES down, VIX also down -> bullish divergence (positive score)."""
    quotes = {
        "ES": {"last": 5200},
        "VIX": {"last": 16},
    }
    history = {
        "ES": [5400, 5300, 5200],  # Down 3.7%
        "VIX": [18, 17, 16],        # Down 11.1%
    }

    result = compute_divergences(quotes, history)

    assert "es_vix" in result
    # Both down = bullish divergence for ES
    assert result["es_vix"] > 0.3


def test_es_vix_normal():
    """ES up, VIX down -> normal inverse relationship (score ~0)."""
    quotes = {
        "ES": {"last": 5400},
        "VIX": {"last": 16},
    }
    history = {
        "ES": [5200, 5300, 5400],  # Up
        "VIX": [18, 17, 16],        # Down
    }

    result = compute_divergences(quotes, history)

    assert "es_vix" in result
    # Normal inverse relationship
    assert abs(result["es_vix"]) < 0.1


def test_cl_dxy_divergence():
    """CL up, DXY also up -> divergence (bearish for CL)."""
    quotes = {
        "CL": {"last": 75},
        "DXY": {"last": 104},
    }
    history = {
        "CL": [70, 72, 75],    # Up
        "DXY": [100, 102, 104], # Up
    }

    result = compute_divergences(quotes, history)

    assert "cl_dxy" in result
    # Both up = bearish divergence for CL
    assert result["cl_dxy"] < -0.3


def test_correlated_pair_divergence():
    """ES up, NQ down -> divergence (bearish for ES)."""
    quotes = {
        "ES": {"last": 5400},
        "NQ": {"last": 18000},
    }
    history = {
        "ES": [5200, 5300, 5400],  # Up
        "NQ": [18800, 18400, 18000], # Down
    }

    result = compute_divergences(quotes, history)

    assert "es_nq" in result
    # Opposite directions = bearish divergence
    assert result["es_nq"] < -0.3


def test_no_data_returns_zeros():
    """Missing symbols return 0.0."""
    quotes = {
        "ES": {"last": 5400},
    }
    history = {
        "ES": [5300, 5350, 5400],
    }

    result = compute_divergences(quotes, history)

    # All pairs involving missing symbols should be 0.0
    assert result["es_vix"] == 0.0
    assert result["cl_dxy"] == 0.0
    assert result["gc_dxy"] == 0.0


def test_all_pairs_computed():
    """Verify all 6 pairs are present in output."""
    quotes = {
        "ES": {"last": 5400},
        "VIX": {"last": 18},
        "NQ": {"last": 18500},
        "CL": {"last": 75},
        "GC": {"last": 2200},
        "DXY": {"last": 103},
        "TNX": {"last": 4.2},
        "HYG": {"last": 78},
    }
    history = {
        sym: [quotes[sym]["last"] - 10, quotes[sym]["last"] - 5, quotes[sym]["last"]]
        for sym in quotes
    }

    result = compute_divergences(quotes, history)

    expected_keys = ["es_vix", "es_nq", "cl_dxy", "gc_dxy", "gc_tnx", "es_hyg"]
    for key in expected_keys:
        assert key in result


def test_capped_at_bounds():
    """Extreme divergence values are capped at +/-1.0."""
    quotes = {
        "ES": {"last": 6000},
        "VIX": {"last": 40},
    }
    history = {
        "ES": [5000, 5500, 6000],  # Up 20%
        "VIX": [20, 30, 40],        # Up 100%
    }

    result = compute_divergences(quotes, history)

    # Should be capped at -1.0 (bearish divergence)
    assert result["es_vix"] >= -1.0
    assert result["es_vix"] <= 1.0


def test_flat_market_zero():
    """No movement in either symbol -> all zeros."""
    quotes = {
        "ES": {"last": 5400},
        "VIX": {"last": 18},
        "NQ": {"last": 18500},
        "CL": {"last": 75},
        "GC": {"last": 2200},
        "DXY": {"last": 103},
        "TNX": {"last": 4.2},
        "HYG": {"last": 78},
    }
    history = {
        sym: [quotes[sym]["last"], quotes[sym]["last"], quotes[sym]["last"]]
        for sym in quotes
    }

    result = compute_divergences(quotes, history)

    # All flat -> all zeros
    for score in result.values():
        assert score == 0.0
