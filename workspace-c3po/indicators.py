#!/usr/bin/env python3
"""Pure-Python technical indicator computation.

IB provides raw OHLCV bars; brain.py expects pre-computed indicators.
This module bridges the gap with zero external dependencies (no numpy/pandas).

Functions:
    sma(closes, period)           -> float
    atr(highs, lows, closes, period) -> float
    adx(highs, lows, closes, period) -> float
    slope(values, window)         -> float
"""

from __future__ import annotations


def sma(closes: list[float], period: int) -> float:
    """Simple Moving Average over the last `period` closes.

    Args:
        closes: List of closing prices (oldest first).
        period: Number of periods to average.

    Returns:
        SMA value. Returns the mean of available data if len(closes) < period.
    """
    if not closes:
        return 0.0
    window = closes[-period:]
    return sum(window) / len(window)


def _true_range(high: float, low: float, prev_close: float) -> float:
    """Single-bar True Range."""
    return max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close),
    )


def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float:
    """Average True Range using Wilder's smoothing.

    Requires at least `period + 1` bars for a stable reading.

    Args:
        highs:  List of high prices (oldest first).
        lows:   List of low prices (oldest first).
        closes: List of close prices (oldest first).
        period: ATR period (default 14).

    Returns:
        ATR value. Returns 0.0 if insufficient data.
    """
    n = len(closes)
    if n < 2 or len(highs) != n or len(lows) != n:
        return 0.0

    # Compute true ranges
    tr_values: list[float] = []
    for i in range(1, n):
        tr_values.append(_true_range(highs[i], lows[i], closes[i - 1]))

    if len(tr_values) < period:
        # Not enough data — return simple average of what we have
        return sum(tr_values) / len(tr_values) if tr_values else 0.0

    # Initial ATR: SMA of first `period` true ranges
    atr_val = sum(tr_values[:period]) / period

    # Wilder's smoothing for remaining
    for i in range(period, len(tr_values)):
        atr_val = (atr_val * (period - 1) + tr_values[i]) / period

    return round(atr_val, 4)


def adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float:
    """Average Directional Index using Wilder's smoothing.

    Algorithm:
        1. Compute +DM and -DM from consecutive highs/lows
        2. Wilder-smooth +DM, -DM, and TR over `period`
        3. Compute +DI and -DI
        4. Compute DX = |+DI - -DI| / (+DI + -DI) * 100
        5. ADX = Wilder-smoothed DX over `period`

    Requires ~2 * period bars for a stable reading.

    Args:
        highs:  List of high prices (oldest first).
        lows:   List of low prices (oldest first).
        closes: List of close prices (oldest first).
        period: ADX period (default 14).

    Returns:
        ADX value (0-100). Returns 0.0 if insufficient data.
    """
    n = len(closes)
    if n < period + 1 or len(highs) != n or len(lows) != n:
        return 0.0

    # Step 1: Compute +DM, -DM, TR for each bar
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    tr_values: list[float] = []

    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        pdm = up_move if up_move > down_move and up_move > 0 else 0.0
        mdm = down_move if down_move > up_move and down_move > 0 else 0.0

        plus_dm.append(pdm)
        minus_dm.append(mdm)
        tr_values.append(_true_range(highs[i], lows[i], closes[i - 1]))

    if len(tr_values) < period:
        return 0.0

    # Step 2: Initial Wilder-smoothed values (SMA of first `period`)
    smoothed_pdm = sum(plus_dm[:period]) / period
    smoothed_mdm = sum(minus_dm[:period]) / period
    smoothed_tr = sum(tr_values[:period]) / period

    dx_values: list[float] = []

    # First DI and DX
    plus_di = (smoothed_pdm / smoothed_tr * 100.0) if smoothed_tr > 0 else 0.0
    minus_di = (smoothed_mdm / smoothed_tr * 100.0) if smoothed_tr > 0 else 0.0
    di_sum = plus_di + minus_di
    dx = abs(plus_di - minus_di) / di_sum * 100.0 if di_sum > 0 else 0.0
    dx_values.append(dx)

    # Step 3: Continue Wilder's smoothing for remaining bars
    for i in range(period, len(tr_values)):
        smoothed_pdm = (smoothed_pdm * (period - 1) + plus_dm[i]) / period
        smoothed_mdm = (smoothed_mdm * (period - 1) + minus_dm[i]) / period
        smoothed_tr = (smoothed_tr * (period - 1) + tr_values[i]) / period

        plus_di = (smoothed_pdm / smoothed_tr * 100.0) if smoothed_tr > 0 else 0.0
        minus_di = (smoothed_mdm / smoothed_tr * 100.0) if smoothed_tr > 0 else 0.0
        di_sum = plus_di + minus_di
        dx = abs(plus_di - minus_di) / di_sum * 100.0 if di_sum > 0 else 0.0
        dx_values.append(dx)

    if len(dx_values) < period:
        # Not enough DX values for ADX smoothing — return average
        return round(sum(dx_values) / len(dx_values), 1)

    # Step 4: ADX = Wilder-smoothed DX
    adx_val = sum(dx_values[:period]) / period
    for i in range(period, len(dx_values)):
        adx_val = (adx_val * (period - 1) + dx_values[i]) / period

    return round(adx_val, 1)


def ema(closes: list[float], period: int) -> float:
    """Exponential Moving Average over the last `period` closes.

    Uses the standard EMA formula:
        multiplier = 2 / (period + 1)
        EMA_today = close * multiplier + EMA_yesterday * (1 - multiplier)

    Initial value is the SMA of the first `period` closes.

    Args:
        closes: List of closing prices (oldest first).
        period: Number of periods for EMA smoothing.

    Returns:
        EMA value. Returns 0.0 if insufficient data.
    """
    if not closes or period <= 0:
        return 0.0
    if len(closes) < period:
        return sum(closes) / len(closes)

    # Initial EMA = SMA of first `period` values
    ema_val = sum(closes[:period]) / period
    mult = 2.0 / (period + 1)

    for i in range(period, len(closes)):
        ema_val = closes[i] * mult + ema_val * (1 - mult)

    return round(ema_val, 4)


def slope(values: list[float], window: int = 5) -> float:
    """Linear regression slope of the last `window` values.

    Uses the least-squares formula:
        slope = (n * sum(x*y) - sum(x) * sum(y)) / (n * sum(x^2) - sum(x)^2)

    where x = 0, 1, ..., n-1 (bar index).

    The result is per-bar slope (i.e., the change in value per bar).
    Divide by the mean value for a normalized slope if needed.

    Args:
        values: List of values (oldest first).
        window: Number of recent values to use (default 5).

    Returns:
        Slope (per-bar change). Returns 0.0 if insufficient data.
    """
    data = values[-window:]
    n = len(data)
    if n < 2:
        return 0.0

    # x = 0, 1, ..., n-1
    sum_x = n * (n - 1) / 2.0
    sum_x2 = n * (n - 1) * (2 * n - 1) / 6.0
    sum_y = sum(data)
    sum_xy = sum(i * y for i, y in enumerate(data))

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.0

    return round((n * sum_xy - sum_x * sum_y) / denom, 6)
