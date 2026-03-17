"""Tests for book imbalance and absorption detection."""
from __future__ import annotations

import pytest

from market_intel.analytics.microstructure import book_imbalance, detect_absorption


# ── Book Imbalance ───────────────────────────────────────────────────────


class TestBookImbalance:
    def test_buy_pressure(self):
        """Bid sizes >> ask sizes -> positive value (buy pressure)."""
        dom = {
            "bid_sizes": [200, 180, 160, 140, 120],
            "ask_sizes": [50, 40, 30, 20, 10],
        }
        result = book_imbalance(dom)
        assert result > 0.0, f"Expected positive, got {result}"
        assert result <= 1.0

    def test_sell_pressure(self):
        """Ask sizes >> bid sizes -> negative value (sell pressure)."""
        dom = {
            "bid_sizes": [50, 40, 30, 20, 10],
            "ask_sizes": [200, 180, 160, 140, 120],
        }
        result = book_imbalance(dom)
        assert result < 0.0, f"Expected negative, got {result}"
        assert result >= -1.0

    def test_balanced(self):
        """Similar sizes on both sides -> near zero."""
        dom = {
            "bid_sizes": [100, 100, 100, 100, 100],
            "ask_sizes": [100, 100, 100, 100, 100],
        }
        result = book_imbalance(dom)
        assert -0.1 <= result <= 0.1, f"Expected near zero, got {result}"

    def test_empty_dom(self):
        """Empty or missing sizes -> 0.0."""
        assert book_imbalance({"bid_sizes": [], "ask_sizes": []}) == 0.0
        assert book_imbalance({}) == 0.0


# ── Absorption Detection ────────────────────────────────────────────────


class TestAbsorption:
    def test_absorption_detected(self):
        """Large resting bid absorbing many sell trades without price moving."""
        dom = {
            "bid_sizes": [500, 40, 30, 20, 10],  # top-of-book 500 vs avg 120
            "ask_sizes": [50, 40, 30, 20, 10],
            "bid_prices": [100.00, 99.75, 99.50, 99.25, 99.00],
            "ask_prices": [100.25, 100.50, 100.75, 101.00, 101.25],
        }
        ticks = [
            {"price": 100.00, "size": 20, "side": "SELL", "timestamp": "2026-03-17T10:30:00Z"},
            {"price": 100.00, "size": 15, "side": "SELL", "timestamp": "2026-03-17T10:30:01Z"},
            {"price": 100.00, "size": 25, "side": "SELL", "timestamp": "2026-03-17T10:30:02Z"},
            {"price": 100.00, "size": 30, "side": "SELL", "timestamp": "2026-03-17T10:30:03Z"},
            {"price": 100.00, "size": 18, "side": "SELL", "timestamp": "2026-03-17T10:30:04Z"},
        ]
        result = detect_absorption(ticks, dom)
        assert result["detected"] is True
        assert result["side"] == "BUY"
        assert result["level"] == 100.00
        assert result["strength"] > 0.0

    def test_no_absorption(self):
        """Normal trading — no large resting orders."""
        dom = {
            "bid_sizes": [40, 35, 30, 25, 20],
            "ask_sizes": [50, 40, 30, 20, 10],
            "bid_prices": [100.00, 99.75, 99.50, 99.25, 99.00],
            "ask_prices": [100.25, 100.50, 100.75, 101.00, 101.25],
        }
        ticks = [
            {"price": 100.00, "size": 10, "side": "SELL", "timestamp": "2026-03-17T10:30:00Z"},
            {"price": 100.25, "size": 5, "side": "BUY", "timestamp": "2026-03-17T10:30:01Z"},
        ]
        result = detect_absorption(ticks, dom)
        assert result["detected"] is False
        assert result["side"] is None
        assert result["level"] is None

    def test_absorption_sell_side(self):
        """Large resting ask absorbing many buy trades without price moving."""
        dom = {
            "bid_sizes": [50, 40, 30, 20, 10],
            "ask_sizes": [600, 40, 30, 20, 10],  # top-of-book 600 vs avg 140
            "bid_prices": [100.00, 99.75, 99.50, 99.25, 99.00],
            "ask_prices": [100.25, 100.50, 100.75, 101.00, 101.25],
        }
        ticks = [
            {"price": 100.25, "size": 25, "side": "BUY", "timestamp": "2026-03-17T10:30:00Z"},
            {"price": 100.25, "size": 30, "side": "BUY", "timestamp": "2026-03-17T10:30:01Z"},
            {"price": 100.25, "size": 20, "side": "BUY", "timestamp": "2026-03-17T10:30:02Z"},
            {"price": 100.25, "size": 35, "side": "BUY", "timestamp": "2026-03-17T10:30:03Z"},
        ]
        result = detect_absorption(ticks, dom)
        assert result["detected"] is True
        assert result["side"] == "SELL"
        assert result["level"] == 100.25

    def test_empty_ticks(self):
        """No ticks -> not detected."""
        dom = {
            "bid_sizes": [500, 40, 30, 20, 10],
            "ask_sizes": [50, 40, 30, 20, 10],
            "bid_prices": [100.00, 99.75, 99.50, 99.25, 99.00],
            "ask_prices": [100.25, 100.50, 100.75, 101.00, 101.25],
        }
        result = detect_absorption([], dom)
        assert result["detected"] is False
