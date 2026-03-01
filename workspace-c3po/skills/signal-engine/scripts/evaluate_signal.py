#!/usr/bin/env python3
"""
evaluate_signal.py — trend_pullback_reclaim_v1
Checks 5 regime requirements (§3.1), then 6 entry conditions (§3.2).
All regime requirements must pass before entry conditions are checked.
All 6 entry conditions must pass → TRADE.

Stop  = entry ± 1.2 * ATR(14)     (§3.3)
TP1   = entry + 1R  (60% partial)  (§3.3)
TP2   = entry + 2R  (40% partial)  (§3.3)

Usage:
    python3 evaluate_signal.py --snapshot-file /tmp/c3po_snapshot.json \
                                --regime-file /tmp/c3po_regime.json \
                                --side LONG
    python3 evaluate_signal.py ... --out /tmp/c3po_eval.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone


# ── Math helpers ─────────────────────────────────────────────────────────────

def ema_series(values: list, period: int) -> list:
    """Compute EMA. Returns list aligned with input (None-padded at start)."""
    if len(values) < period:
        return [None] * len(values)
    k = 2.0 / (period + 1)
    result = [None] * (period - 1)
    seed = sum(values[:period]) / period
    result.append(seed)
    for v in values[period:]:
        result.append(result[-1] * (1 - k) + v * k)
    return result


def wilder_atr(candles: list, period: int = 14) -> float | None:
    """Wilder ATR(period) on candles list."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l = candles[i]["h"], candles[i]["l"]
        pc = candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def compute_adx_series(candles: list, period: int = 14) -> list:
    """
    Return a list of ADX values aligned to candle indices.
    Warmup = 2*period+1 bars; earlier values are None.
    """
    n = len(candles)
    if n < period * 2 + 1:
        return [None] * n

    dm_plus, dm_minus, trs = [], [], []
    for i in range(1, n):
        h, l = candles[i]["h"], candles[i]["l"]
        ph, pl, pc = candles[i-1]["h"], candles[i-1]["l"], candles[i-1]["c"]
        up = h - ph
        dn = pl - l
        dm_plus.append(up if up > dn and up > 0 else 0.0)
        dm_minus.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    def wilder_smooth(data, p):
        if len(data) < p:
            return []
        s = sum(data[:p])
        res = [s]
        for v in data[p:]:
            s = s - s / p + v
            res.append(s)
        return res

    str_ = wilder_smooth(trs, period)
    sdp  = wilder_smooth(dm_plus, period)
    sdm  = wilder_smooth(dm_minus, period)
    k    = min(len(str_), len(sdp), len(sdm))

    dx = []
    for i in range(k):
        if str_[i] == 0:
            dx.append(0.0)
            continue
        dip = 100 * sdp[i] / str_[i]
        dim = 100 * sdm[i] / str_[i]
        denom = dip + dim
        dx.append(100 * abs(dip - dim) / denom if denom else 0.0)

    adx_raw = wilder_smooth(dx, period)

    # adx_raw[0] aligns to candle index 2*period+1
    warmup = 2 * period + 1
    padding = [None] * warmup
    return padding + [round(v, 2) for v in adx_raw]


def get_last_valid(series: list):
    return next((v for v in reversed(series) if v is not None), None)


def percentile(data: list, pct: float) -> float:
    """Linear interpolation percentile (0–100 scale)."""
    valid = sorted(v for v in data if v is not None)
    if not valid:
        return 0.0
    idx = (pct / 100.0) * (len(valid) - 1)
    lo  = int(idx)
    hi  = min(lo + 1, len(valid) - 1)
    return valid[lo] + (valid[hi] - valid[lo]) * (idx - lo)


# ── §3.1 Regime requirements ─────────────────────────────────────────────────

def check_regime_requirements(candles_15m: list, candles_1h: list,
                               candles_4h: list, regime: dict, side: str) -> dict:
    """
    All 5 regime conditions must pass before entry conditions are evaluated.
    Returns {"pass": bool, "requirements": {name: {"pass": bool, "detail": str}}}
    """
    reqs = {}
    closes_15m = [c["c"] for c in candles_15m] if candles_15m else []
    closes_1h  = [c["c"] for c in candles_1h]  if candles_1h  else []

    # R1: 15m EMA21 > EMA55  (LONG) / EMA21 < EMA55  (SHORT)
    if len(closes_15m) < 55:
        reqs["ema21_vs_ema55"] = {
            "pass": False,
            "detail": f"Insufficient 15m candles: {len(closes_15m)} (need 55)"
        }
    else:
        ema21 = get_last_valid(ema_series(closes_15m, 21))
        ema55 = get_last_valid(ema_series(closes_15m, 55))
        if ema21 is None or ema55 is None:
            reqs["ema21_vs_ema55"] = {"pass": False, "detail": "EMA computation failed"}
        else:
            ok = ema21 > ema55 if side == "LONG" else ema21 < ema55
            reqs["ema21_vs_ema55"] = {
                "pass": ok,
                "detail": (f"15m EMA21={ema21:.1f} {'>' if side=='LONG' else '<'} "
                           f"EMA55={ema55:.1f} → {'PASS' if ok else 'FAIL'}"),
                "ema21": round(ema21, 2),
                "ema55": round(ema55, 2),
            }

    # R2: 15m ADX(14) > 30th percentile of recent ADX history
    if len(candles_15m) < 60:
        reqs["adx_above_30th_pct"] = {
            "pass": False,
            "detail": f"Insufficient 15m candles: {len(candles_15m)} (need 60)"
        }
    else:
        adx_vals = compute_adx_series(candles_15m, 14)
        current_adx = get_last_valid(adx_vals)
        if current_adx is None:
            reqs["adx_above_30th_pct"] = {"pass": False, "detail": "ADX computation failed"}
        else:
            hist_adx = [v for v in adx_vals[-100:] if v is not None]
            p30 = percentile(hist_adx, 30)
            ok = current_adx > p30
            reqs["adx_above_30th_pct"] = {
                "pass": ok,
                "detail": (f"15m ADX={current_adx:.1f} vs 30th pct={p30:.1f} "
                           f"→ {'PASS' if ok else 'FAIL'}"),
                "adx": round(current_adx, 2),
                "p30": round(p30, 2),
            }

    # R3: 1H price > EMA200  (LONG) / 1H price < EMA200  (SHORT)
    if len(closes_1h) < 200:
        reqs["htf_1h_ema200"] = {
            "pass": False,
            "detail": f"Insufficient 1H candles: {len(closes_1h)} (need 200)"
        }
    else:
        ema200 = get_last_valid(ema_series(closes_1h, 200))
        last_1h = closes_1h[-1]
        if ema200 is None:
            reqs["htf_1h_ema200"] = {"pass": False, "detail": "EMA200 computation failed"}
        else:
            ok = last_1h > ema200 if side == "LONG" else last_1h < ema200
            reqs["htf_1h_ema200"] = {
                "pass": ok,
                "detail": (f"1H close={last_1h:.1f} vs EMA200={ema200:.1f} "
                           f"→ {'PASS' if ok else 'FAIL'}"),
                "close_1h": round(last_1h, 2),
                "ema200": round(ema200, 2),
            }

    # R4: 1H volatility regime != EXTREME (already hard-gated in brain.py, double-checked here)
    vol_regime = regime.get("volatility_regime", {}).get("regime", "UNKNOWN")
    ok = vol_regime != "EXTREME"
    reqs["vol_not_extreme"] = {
        "pass": ok,
        "detail": f"1H vol regime={vol_regime} → {'PASS' if ok else 'EXTREME — FAIL'}"
    }

    # R5: 4H trend != TREND_DOWN (LONG) or != TREND_UP (SHORT); RANGE is allowed with score cap
    htf_class = (regime.get("trend_classification", {})
                       .get("classifications", {})
                       .get("4h", {}))
    htf_type = htf_class.get("type", "UNKNOWN")
    if side == "LONG":
        ok = htf_type != "TREND_DOWN"
    else:
        ok = htf_type != "TREND_UP"
    reqs["htf_4h_not_counter_trend"] = {
        "pass": ok,
        "detail": (f"4H type={htf_type}, side={side} "
                   f"→ {'PASS' if ok else 'counter-trend FAIL'}"),
        "htf_4h_type": htf_type,
    }

    all_pass = all(v["pass"] for v in reqs.values())
    return {"pass": all_pass, "requirements": reqs}


# ── §3.2 Entry conditions (all 6 required) ───────────────────────────────────

def evaluate_conditions(candles_15m: list, candles_1h: list,
                        candles_4h: list, regime: dict, side: str) -> dict:
    """Run all 6 entry conditions. Returns {name: {"pass": bool, "detail": str}}."""
    results = {}
    closes = [c["c"] for c in candles_15m] if candles_15m else []
    highs  = [c["h"] for c in candles_15m] if candles_15m else []
    lows   = [c["l"] for c in candles_15m] if candles_15m else []
    vols   = [c.get("v", 0) for c in candles_15m] if candles_15m else []

    if len(candles_15m) < 60:
        for name in ("prior_close_below_ema21", "reclaim_above_ema21", "close_above_ema55",
                     "ema21_slope_positive", "body_ratio_above_40pct", "volume_above_70th_pct"):
            results[name] = {
                "pass": False,
                "detail": f"Insufficient 15m candles: {len(candles_15m)} (need 60)"
            }
        return results

    ema21_vals = ema_series(closes, 21)
    ema55_vals = ema_series(closes, 55)
    ema21_now  = ema21_vals[-1]
    ema55_now  = ema55_vals[-1]
    close_now  = closes[-1]

    # ── Cond 1: Any close BELOW EMA21 within the last 6 bars (before current) ──
    prior_below = False
    for i in range(-7, -1):
        c   = closes[i]
        e21 = ema21_vals[i]
        if e21 is None:
            continue
        if (side == "LONG" and c < e21) or (side == "SHORT" and c > e21):
            prior_below = True
            break
    results["prior_close_below_ema21"] = {
        "pass": prior_below,
        "detail": (f"{'Found' if prior_below else 'No'} close "
                   f"{'below' if side == 'LONG' else 'above'} EMA21 in last 6 bars — "
                   f"{'pullback confirmed' if prior_below else 'no pullback'}"),
    }

    # ── Cond 2: Current candle CLOSE above EMA21 (reclaim) ────────────────────
    if ema21_now is None:
        results["reclaim_above_ema21"] = {"pass": False, "detail": "EMA21 unavailable"}
    else:
        ok = close_now > ema21_now if side == "LONG" else close_now < ema21_now
        results["reclaim_above_ema21"] = {
            "pass": ok,
            "detail": (f"close={close_now:.1f} vs EMA21={ema21_now:.1f} "
                       f"→ {'reclaim' if ok else 'no reclaim'}"),
            "close": round(close_now, 2),
            "ema21": round(ema21_now, 2),
        }

    # ── Cond 3: Current close > EMA55 ─────────────────────────────────────────
    if ema55_now is None:
        results["close_above_ema55"] = {"pass": False, "detail": "EMA55 unavailable"}
    else:
        ok = close_now > ema55_now if side == "LONG" else close_now < ema55_now
        results["close_above_ema55"] = {
            "pass": ok,
            "detail": (f"close={close_now:.1f} {'>' if side=='LONG' else '<'} "
                       f"EMA55={ema55_now:.1f} → {'PASS' if ok else 'FAIL'}"),
            "ema55": round(ema55_now, 2),
        }

    # ── Cond 4: EMA21 slope positive (current > value 3 bars ago) ─────────────
    ema21_3ago = ema21_vals[-4] if len(ema21_vals) >= 4 else None
    if ema21_now is None or ema21_3ago is None:
        results["ema21_slope_positive"] = {"pass": False, "detail": "Insufficient EMA21 history"}
    else:
        ok = ema21_now > ema21_3ago if side == "LONG" else ema21_now < ema21_3ago
        results["ema21_slope_positive"] = {
            "pass": ok,
            "detail": (f"EMA21 now={ema21_now:.1f} vs 3-bar-ago={ema21_3ago:.1f} "
                       f"→ {'positive' if ok else 'flat/negative'} slope"),
            "ema21_3ago": round(ema21_3ago, 2),
        }

    # ── Cond 5: Entry candle body > 40% of range ──────────────────────────────
    open_now  = candles_15m[-1].get("o", close_now)
    high_now  = highs[-1]
    low_now   = lows[-1]
    c_range   = high_now - low_now
    body      = abs(close_now - open_now)
    if c_range <= 0:
        results["body_ratio_above_40pct"] = {"pass": False, "detail": "Zero range candle"}
    else:
        ratio = body / c_range
        ok = ratio >= 0.40
        results["body_ratio_above_40pct"] = {
            "pass": ok,
            "detail": f"body={body:.1f} / range={c_range:.1f} = {ratio:.2f} (need ≥0.40)",
            "body_pct": round(ratio * 100, 1),
        }

    # ── Cond 6: Entry candle volume >= 70th percentile of last 20 bars ────────
    if len(vols) < 21:
        results["volume_above_70th_pct"] = {"pass": False, "detail": "Insufficient volume data"}
    else:
        last_20 = vols[-21:-1]
        current_vol = vols[-1]
        p70 = percentile(last_20, 70)
        ok = current_vol >= p70
        results["volume_above_70th_pct"] = {
            "pass": ok,
            "detail": f"vol={current_vol:.0f} vs 70th pct={p70:.0f} → {'PASS' if ok else 'FAIL'}",
            "volume": current_vol,
            "p70": round(p70, 2),
        }

    return results


# ── §3.3 Exit levels ─────────────────────────────────────────────────────────

def derive_levels(candles_15m: list, side: str) -> dict:
    """
    Entry = current close (MARKET order).
    Stop  = entry ± 1.2 * ATR(14)        [§3.3]
    TP1   = entry + 1R  (60% partial)    [§3.3]
    TP2   = entry + 2R  (40% partial)    [§3.3]
    """
    if len(candles_15m) < 21:
        return {}

    closes = [c["c"] for c in candles_15m]
    atr    = wilder_atr(candles_15m, 14) or 0.0
    entry  = round(closes[-1], 1)

    if side == "LONG":
        stop = round(entry - 1.2 * atr, 1)
        risk = entry - stop           # 1R = 1.2 * ATR
        t1   = round(entry + 1.0 * risk, 1)
        t2   = round(entry + 2.0 * risk, 1)
        stop_logic = f"Entry {entry} - 1.2×ATR({atr:.1f}) = {stop}"
    else:
        stop = round(entry + 1.2 * atr, 1)
        risk = stop - entry
        t1   = round(entry - 1.0 * risk, 1)
        t2   = round(entry - 2.0 * risk, 1)
        stop_logic = f"Entry {entry} + 1.2×ATR({atr:.1f}) = {stop}"

    return {
        "entry_price": entry,
        "stop_price":  stop,
        "stop_logic":  stop_logic,
        "target_1":    t1,
        "target_2":    t2,
        "atr_15m":     round(atr, 2),
        "risk_pts":    round(abs(entry - stop), 2),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate trend_pullback_reclaim_v1 — regime + entry conditions"
    )
    parser.add_argument("--snapshot-file", required=True)
    parser.add_argument("--regime-file",   required=True)
    parser.add_argument("--side", required=True, choices=["LONG", "SHORT"])
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    try:
        with open(args.snapshot_file) as f:
            snapshot = json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": f"Snapshot not found: {args.snapshot_file}"}), file=sys.stderr)
        sys.exit(2)

    try:
        with open(args.regime_file) as f:
            regime = json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": f"Regime file not found: {args.regime_file}"}), file=sys.stderr)
        sys.exit(2)

    if snapshot.get("stale"):
        print(json.dumps({"error": "STALE_SNAPSHOT"}), file=sys.stderr)
        sys.exit(2)

    candles_15m = snapshot.get("timeframes", {}).get("15m", [])
    candles_1h  = snapshot.get("timeframes", {}).get("1h",  [])
    candles_4h  = snapshot.get("timeframes", {}).get("4h",  [])

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    # ── Phase 1: Regime requirements (§3.1) ──────────────────────────────────
    regime_check = check_regime_requirements(
        candles_15m, candles_1h, candles_4h, regime, args.side
    )

    if not regime_check["pass"]:
        failed = [k for k, v in regime_check["requirements"].items() if not v["pass"]]
        output = {
            "side": args.side,
            "strategy": "trend_pullback_reclaim_v1",
            "pass": False,
            "regime_pass": False,
            "conditions_met": 0,
            "conditions_required": 6,
            "regime_requirements": regime_check["requirements"],
            "regime_failed": failed,
            "evaluated_at": now_str,
        }
        print(json.dumps(output, indent=2))
        if args.out:
            try:
                with open(args.out, "w") as f:
                    json.dump(output, f, indent=2)
            except OSError:
                pass
        print(f"[evaluate-signal] REGIME FAIL ({args.side}): {failed}", file=sys.stderr)
        sys.exit(1)

    # ── Phase 2: Entry conditions (§3.2) ─────────────────────────────────────
    conditions = evaluate_conditions(
        candles_15m, candles_1h, candles_4h, regime, args.side
    )
    levels = derive_levels(candles_15m, args.side)

    conditions_met = sum(1 for v in conditions.values() if v.get("pass"))
    all_pass       = conditions_met == 6

    output = {
        "side": args.side,
        "strategy": "trend_pullback_reclaim_v1",
        "pass": all_pass,
        "regime_pass": True,
        "conditions_met": conditions_met,
        "conditions_required": 6,
        "regime_requirements": regime_check["requirements"],
        "conditions": conditions,
        **levels,
        "evaluated_at": now_str,
    }

    print(json.dumps(output, indent=2))

    if args.out:
        try:
            with open(args.out, "w") as f:
                json.dump(output, f, indent=2)
        except OSError as e:
            print(f"[evaluate-signal] Warning: could not write {args.out}: {e}", file=sys.stderr)

    if not all_pass:
        failed = [k for k, v in conditions.items() if not v.get("pass")]
        print(
            f"[evaluate-signal] FAIL ({args.side}): {conditions_met}/6 entry conds. "
            f"Failed: {failed}",
            file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
