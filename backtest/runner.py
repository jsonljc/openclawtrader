#!/usr/bin/env python3
"""BacktestRunner — bar-by-bar replay through the full pipeline.

Feeds real OHLCV bars (from CSV/Parquet snapshot files) through:
    Watchtower → C3PO (regime + health + signal) → Sentinel → SimulatedForge

Look-ahead bias prevention:
    - Only bars up to current_index are visible at each step
    - Indicators are computed on the visible window only
    - No future data leaks through snapshots

Usage:
    from backtest.runner import BacktestRunner
    runner = BacktestRunner(data_dir="data/bars/", symbol="ES", timeframe="4H")
    results = runner.run()
    runner.report()
"""

from __future__ import annotations

import csv
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "workspace-c3po"))
sys.path.insert(0, str(_ROOT / "workspace-sentinel"))
sys.path.insert(0, str(_ROOT / "workspace-forge"))

from shared.utils import round_to_tick


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_bars_csv(path: Path) -> list[dict]:
    """Load OHLCV bars from CSV. Expected columns: timestamp,o,h,l,c,v"""
    bars = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append({
                "timestamp": row.get("timestamp", row.get("date", "")),
                "o": float(row.get("o", row.get("open", 0))),
                "h": float(row.get("h", row.get("high", 0))),
                "l": float(row.get("l", row.get("low", 0))),
                "c": float(row.get("c", row.get("close", 0))),
                "v": int(float(row.get("v", row.get("volume", 0)))),
            })
    return bars


def load_bars_json(path: Path) -> list[dict]:
    """Load OHLCV bars from JSON array."""
    with open(path) as f:
        return json.load(f)


def load_bars(path: Path) -> list[dict]:
    """Auto-detect format and load bars."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_bars_csv(path)
    if suffix in (".json", ".jsonl"):
        return load_bars_json(path)
    raise ValueError(f"Unsupported bar file format: {suffix}")


# ---------------------------------------------------------------------------
# Indicator computation (no look-ahead)
# ---------------------------------------------------------------------------

def _compute_indicators(bars: list[dict]) -> dict:
    """Compute indicators from visible bars only (no look-ahead)."""
    if not bars:
        return {}

    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    last = closes[-1]

    # Simple MA
    ma20 = sum(closes[-20:]) / min(20, len(closes)) if closes else last
    ma50 = sum(closes[-50:]) / min(50, len(closes)) if len(closes) >= 2 else last

    # MA slope (last 5 bars)
    if len(closes) >= 6:
        ma_recent = sum(closes[-5:]) / 5
        ma_prior = sum(closes[-10:-5]) / 5 if len(closes) >= 10 else closes[-6]
        ma_slope = ma_recent - ma_prior
    else:
        ma_slope = 0.0

    # ATR (14-period)
    trs = []
    for i in range(1, min(15, len(bars))):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else (highs[-1] - lows[-1]) if bars else 1.0

    # ADX approximation (simplified: use directional movement)
    plus_dm = []
    minus_dm = []
    for i in range(1, min(15, len(bars))):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(max(up, 0) if up > down else 0)
        minus_dm.append(max(down, 0) if down > up else 0)
    if plus_dm and atr > 0:
        plus_di = (sum(plus_dm) / len(plus_dm)) / atr * 100
        minus_di = (sum(minus_dm) / len(minus_dm)) / atr * 100
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
        adx = dx  # Simplified
    else:
        adx = 25.0

    return {
        "last_price": last,
        "ma_20_value": round(ma20, 4),
        "ma_50_value": round(ma50, 4),
        "ma_20_slope": round(ma_slope, 6),
        "adx_14": round(adx, 2),
        "atr_14_4H": round(atr, 4),
        "atr_14_1H": round(atr / 4, 4),  # rough approximation
    }


# ---------------------------------------------------------------------------
# SimulatedFillEngine
# ---------------------------------------------------------------------------

@dataclass
class SimulatedFill:
    fill_price: float
    slippage_ticks: int = 1
    contracts_filled: int = 1
    fees_usd: float = 4.62


def simulate_fill(
    side: str,
    price: float,
    tick_size: float,
    contracts: int = 1,
    slippage_ticks: int = 1,
) -> SimulatedFill:
    """Deterministic fill simulation for backtest — no PRNG noise."""
    direction = 1 if side == "BUY" else -1
    fill_price = price + direction * slippage_ticks * tick_size
    return SimulatedFill(
        fill_price=round(fill_price, 6),
        slippage_ticks=slippage_ticks,
        contracts_filled=contracts,
        fees_usd=round(4.62 * contracts, 2),
    )


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    bar_index: int
    entry_bar_ts: str
    exit_bar_ts: str = ""
    side: str = "LONG"
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_price: float = 0.0
    tp_price: float = 0.0
    contracts: int = 1
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    fees_usd: float = 0.0
    bars_held: int = 0
    exit_reason: str = ""
    signal_name: str = ""


# ---------------------------------------------------------------------------
# BacktestRunner
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    symbol: str = "ES"
    timeframe: str = "4H"
    tick_size: float = 0.25
    point_value_usd: float = 50.0
    initial_equity: float = 20_000.0
    risk_budget_pct: float = 0.50
    max_risk_per_trade_pct: float = 1.5
    stop_atr_multiple: float = 1.5
    tp_atr_multiple: float = 1.5
    adx_min: float = 25.0
    max_hold_bars: int = 20
    slippage_ticks: int = 1
    warmup_bars: int = 50  # bars before signals can fire


class BacktestRunner:
    def __init__(
        self,
        bars: list[dict] | None = None,
        data_path: str | Path | None = None,
        config: BacktestConfig | None = None,
    ):
        self.config = config or BacktestConfig()
        if bars is not None:
            self.bars = bars
        elif data_path:
            self.bars = load_bars(Path(data_path))
        else:
            raise ValueError("Provide either bars or data_path")

        self.equity = self.config.initial_equity
        self.peak_equity = self.equity
        self.trades: list[TradeRecord] = []
        self.equity_curve: list[float] = []
        self._position: dict | None = None

    def run(self) -> list[TradeRecord]:
        """Run bar-by-bar backtest. Returns list of completed trades."""
        warmup = self.config.warmup_bars

        for i in range(warmup, len(self.bars)):
            bar = self.bars[i]
            visible_bars = self.bars[max(0, i - 200):i + 1]  # rolling window, inclusive

            # Check open position for exit
            if self._position is not None:
                self._check_exit(bar, i)

            # Record equity after exit check
            self.equity_curve.append(self.equity)

            # If no position, check for entry signal
            if self._position is None:
                indicators = _compute_indicators(visible_bars)
                signal = self._check_entry_signal(indicators, bar)
                if signal:
                    self._enter(signal, bar, i, indicators)

        # Force close any open position at end
        if self._position is not None:
            self._force_exit(self.bars[-1], len(self.bars) - 1, "END_OF_DATA")

        return self.trades

    def _check_entry_signal(self, ind: dict, bar: dict) -> dict | None:
        """Trend reclaim signal: price vs MA20 with ADX confirmation."""
        price = ind.get("last_price", 0)
        ma20 = ind.get("ma_20_value", 0)
        adx = ind.get("adx_14", 0)
        slope = ind.get("ma_20_slope", 0)
        atr = ind.get("atr_14_4H", 1.0)
        cfg = self.config

        if price <= 0 or ma20 <= 0:
            return None

        # LONG
        if price > ma20 and adx >= cfg.adx_min and slope > 0:
            stop_dist = atr * cfg.stop_atr_multiple
            tp_dist = atr * cfg.tp_atr_multiple
            return {
                "side": "BUY",
                "direction": "LONG",
                "stop_price": round_to_tick(price - stop_dist, cfg.tick_size),
                "tp_price": round_to_tick(price + tp_dist, cfg.tick_size),
                "stop_dist": stop_dist,
                "atr": atr,
            }

        # SHORT
        if price < ma20 and adx >= cfg.adx_min and slope < 0:
            stop_dist = atr * cfg.stop_atr_multiple
            tp_dist = atr * cfg.tp_atr_multiple
            return {
                "side": "SELL",
                "direction": "SHORT",
                "stop_price": round_to_tick(price + stop_dist, cfg.tick_size),
                "tp_price": round_to_tick(price - tp_dist, cfg.tick_size),
                "stop_dist": stop_dist,
                "atr": atr,
            }

        return None

    def _enter(self, signal: dict, bar: dict, index: int, ind: dict) -> None:
        """Enter a position with risk-budget sizing."""
        cfg = self.config
        fill = simulate_fill(
            signal["side"], bar["c"], cfg.tick_size,
            slippage_ticks=cfg.slippage_ticks,
        )

        # Size by risk budget
        risk_usd = self.equity * cfg.risk_budget_pct / 100.0
        risk_per_c = signal["stop_dist"] * cfg.point_value_usd
        contracts = max(1, math.floor(risk_usd / risk_per_c)) if risk_per_c > 0 else 0

        # Cap at max_risk_per_trade
        max_risk_usd = self.equity * cfg.max_risk_per_trade_pct / 100.0
        while contracts > 1 and (signal["stop_dist"] * cfg.point_value_usd * contracts) > max_risk_usd:
            contracts -= 1

        if contracts <= 0:
            return

        # Safety: don't risk more than 5% of equity on a single trade
        actual_risk = signal["stop_dist"] * cfg.point_value_usd * contracts
        if actual_risk > self.equity * 0.05:
            return

        self._position = {
            "entry_price": fill.fill_price,
            "stop_price": signal["stop_price"],
            "tp_price": signal["tp_price"],
            "side": signal["direction"],
            "contracts": contracts,
            "entry_bar": index,
            "entry_ts": bar.get("timestamp", ""),
            "fees_entry": fill.fees_usd * contracts,
        }

    def _check_exit(self, bar: dict, index: int) -> None:
        """Check stop/TP/time exit on current bar."""
        pos = self._position
        side = pos["side"]
        stop = pos["stop_price"]
        tp = pos["tp_price"]
        bars_held = index - pos["entry_bar"]

        exit_price = None
        exit_reason = None

        if side == "LONG":
            if bar["l"] <= stop:
                exit_price = stop
                exit_reason = "STOP"
            elif bar["h"] >= tp:
                exit_price = tp
                exit_reason = "TAKE_PROFIT"
        else:  # SHORT
            if bar["h"] >= stop:
                exit_price = stop
                exit_reason = "STOP"
            elif bar["l"] <= tp:
                exit_price = tp
                exit_reason = "TAKE_PROFIT"

        if exit_reason is None and bars_held >= self.config.max_hold_bars:
            exit_price = bar["c"]
            exit_reason = "TIME_EXIT"

        if exit_reason:
            self._record_exit(exit_price, exit_reason, bar, index)

    def _force_exit(self, bar: dict, index: int, reason: str) -> None:
        self._record_exit(bar["c"], reason, bar, index)

    def _record_exit(self, exit_price: float, reason: str, bar: dict, index: int) -> None:
        pos = self._position
        contracts = pos["contracts"]
        entry = pos["entry_price"]
        pv = self.config.point_value_usd
        fees_exit = 4.62 * contracts  # exit half of round-trip

        if pos["side"] == "LONG":
            raw_pnl = (exit_price - entry) * pv * contracts
        else:
            raw_pnl = (entry - exit_price) * pv * contracts

        total_fees = pos["fees_entry"] + fees_exit
        net_pnl = raw_pnl - total_fees
        pnl_pct = (net_pnl / self.equity * 100.0) if self.equity > 0 else 0.0

        self.equity += net_pnl
        self.peak_equity = max(self.peak_equity, self.equity)

        trade = TradeRecord(
            bar_index=pos["entry_bar"],
            entry_bar_ts=pos["entry_ts"],
            exit_bar_ts=bar.get("timestamp", ""),
            side=pos["side"],
            entry_price=entry,
            exit_price=exit_price,
            stop_price=pos["stop_price"],
            tp_price=pos["tp_price"],
            contracts=contracts,
            pnl_usd=round(net_pnl, 2),
            pnl_pct=round(pnl_pct, 4),
            fees_usd=round(total_fees, 2),
            bars_held=index - pos["entry_bar"],
            exit_reason=reason,
            signal_name="trend_reclaim",
        )
        self.trades.append(trade)
        self._position = None

    def report(self) -> dict[str, Any]:
        """Generate performance statistics from completed trades."""
        if not self.trades:
            return {"total_trades": 0, "note": "no trades generated"}

        wins = [t for t in self.trades if t.pnl_usd > 0]
        losses = [t for t in self.trades if t.pnl_usd <= 0]
        total_pnl = sum(t.pnl_usd for t in self.trades)
        total_fees = sum(t.fees_usd for t in self.trades)

        avg_win = sum(t.pnl_usd for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.pnl_usd for t in losses) / len(losses) if losses else 0
        hit_rate = len(wins) / len(self.trades) if self.trades else 0

        # Max drawdown from equity curve
        max_dd = 0.0
        peak = self.config.initial_equity
        for eq in self.equity_curve:
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100.0 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # Profit factor
        gross_profit = sum(t.pnl_usd for t in wins)
        gross_loss = abs(sum(t.pnl_usd for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Sharpe approximation (daily returns)
        returns = [t.pnl_pct for t in self.trades]
        if len(returns) >= 2:
            avg_ret = sum(returns) / len(returns)
            std_ret = (sum((r - avg_ret) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
            sharpe = (avg_ret / std_ret * (252 ** 0.5)) if std_ret > 0 else 0
        else:
            sharpe = 0.0

        avg_bars = sum(t.bars_held for t in self.trades) / len(self.trades)

        return {
            "total_trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "hit_rate": round(hit_rate, 4),
            "total_pnl_usd": round(total_pnl, 2),
            "total_fees_usd": round(total_fees, 2),
            "avg_win_usd": round(avg_win, 2),
            "avg_loss_usd": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 4),
            "max_drawdown_pct": round(max_dd, 4),
            "sharpe_approx": round(sharpe, 4),
            "avg_bars_held": round(avg_bars, 1),
            "final_equity": round(self.equity, 2),
            "initial_equity": self.config.initial_equity,
            "return_pct": round(
                (self.equity - self.config.initial_equity) / self.config.initial_equity * 100, 4
            ),
            "symbol": self.config.symbol,
            "timeframe": self.config.timeframe,
            "bars_total": len(self.bars),
        }
