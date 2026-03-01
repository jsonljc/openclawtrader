#!/usr/bin/env python3
"""
score_signal.py
Scores a passing signal 0–100 and assigns a confidence tier with size multiplier.

Scoring model (max 100):
  htf_alignment     max 25  — 4H trend alignment quality
  adx_strength      max 20  — 15m ADX level relative to history
  volatility_regime max 15  — NORMAL=15, ELEVATED=10, other=0
  pullback_quality  max 15  — pullback depth and reclaim cleanness
  entry_quality     max 10  — body ratio + volume confluence
  session_quality   max 15  — trading session window

Confidence tiers (§4.2):
  HIGH  70–100  size_multiplier 1.00  (full size per posture)
  MED   50–69   size_multiplier 0.50  (half size)
  BLOCK  <50    size_multiplier 0.00  → NO_TRADE, never sent to Sentinel

4H RANGE cap: if 4H type is RANGE, score is capped at 69 (forces MED at best).

Usage:
    python3 score_signal.py --eval-file /tmp/c3po_eval.json \
                             --regime-file /tmp/c3po_regime.json
    python3 score_signal.py ... --out /tmp/c3po_score.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone


# Tier thresholds per spec §4.2 (SPEC_RULES.md)
TIER_THRESHOLDS = {
    "TIER_A": 80,
    "TIER_B": 65,
    "TIER_C": 50,
    "BLOCK":  0,
}

SIZE_MULTIPLIERS = {
    "TIER_A": 1.0,
    "TIER_B": 0.75,
    "TIER_C": 0.5,
    "BLOCK":  0.0,
}


def score_htf_alignment(regime_reqs: dict, side: str) -> tuple[int, str]:
    """
    25 points — 4H trend alignment.
    TREND aligned:  25
    RANGE (neutral): 15 (full signal possible but capped to MED later)
    FAIL:             0
    """
    cond = regime_reqs.get("htf_4h_not_counter_trend", {})
    if not cond.get("pass"):
        return 0, "4H counter-trend — 0 pts"
    htf_type = cond.get("htf_4h_type", "UNKNOWN")
    if htf_type == "RANGE":
        return 15, f"4H RANGE — neutral, score capped to MED tier (15 pts)"
    return 25, f"4H type={htf_type} aligned with side={side} — 25 pts"


def score_adx_strength(regime_reqs: dict) -> tuple[int, str]:
    """
    20 points — 15m ADX strength relative to its 30th percentile.
    The higher above p30, the more points.
    """
    cond = regime_reqs.get("adx_above_30th_pct", {})
    if not cond.get("pass"):
        return 0, "15m ADX below 30th pct — 0 pts"
    adx = cond.get("adx")
    p30 = cond.get("p30", 0)
    if adx is None:
        return 10, "ADX above p30 but value unknown — 10 pts"
    margin = adx - p30
    if margin >= 15:
        return 20, f"ADX={adx:.1f} far above p30={p30:.1f} — strong trend"
    elif margin >= 8:
        return 15, f"ADX={adx:.1f} moderately above p30={p30:.1f}"
    else:
        return 10, f"ADX={adx:.1f} marginally above p30={p30:.1f}"


def score_volatility_regime(regime: dict) -> tuple[int, str]:
    """15 points — volatility regime quality."""
    vol = regime.get("volatility_regime", {}).get("regime", "UNKNOWN")
    if vol == "NORMAL":
        return 15, "NORMAL volatility — optimal"
    elif vol == "ELEVATED":
        return 10, "ELEVATED volatility — acceptable"
    elif vol == "LOW":
        return 5,  "LOW volatility — reduced moves"
    else:
        return 0,  f"Regime {vol} — not scoreable"


def score_pullback_quality(conditions: dict, side: str) -> tuple[int, str]:
    """
    15 points — pullback + reclaim quality.
    prior_close_below_ema21 confirms pullback occurred.
    reclaim_above_ema21 confirms current bar is reclaiming.
    """
    pullback = conditions.get("prior_close_below_ema21", {})
    reclaim  = conditions.get("reclaim_above_ema21", {})

    if not pullback.get("pass"):
        return 0, "No prior pullback below EMA21 — 0 pts"
    if not reclaim.get("pass"):
        return 5, "Pullback present but no reclaim — 5 pts"

    # Proximity of current close to EMA21 from reclaim condition
    close = reclaim.get("close")
    ema21 = reclaim.get("ema21")
    if close is None or ema21 is None or ema21 == 0:
        return 10, "Pullback + reclaim confirmed — 10 pts (proximity unknown)"

    dist_pct = abs(close - ema21) / ema21 * 100
    if dist_pct <= 0.05:
        return 15, f"Clean EMA21 touch + reclaim (dist={dist_pct:.3f}%)"
    elif dist_pct <= 0.20:
        return 12, f"Good pullback + reclaim (dist={dist_pct:.2f}%)"
    else:
        return 8,  f"Pullback + reclaim present (dist={dist_pct:.2f}%)"


def score_entry_quality(conditions: dict) -> tuple[int, str]:
    """
    10 points — body ratio and volume confluence.
    body_ratio_above_40pct and volume_above_70th_pct both contribute.
    """
    body   = conditions.get("body_ratio_above_40pct", {})
    volume = conditions.get("volume_above_70th_pct", {})
    pts = 0
    reasons = []

    if body.get("pass"):
        body_pct = body.get("body_pct", 0)
        if body_pct >= 65:
            pts += 6
            reasons.append(f"strong body={body_pct:.0f}%")
        elif body_pct >= 50:
            pts += 5
            reasons.append(f"good body={body_pct:.0f}%")
        else:
            pts += 4
            reasons.append(f"body={body_pct:.0f}%")
    else:
        reasons.append("weak body")

    if volume.get("pass"):
        pts += 4
        reasons.append("volume above 70th pct")
    else:
        reasons.append("low volume")

    return pts, " | ".join(reasons)


def score_session_quality() -> tuple[int, str]:
    """
    15 points — session window quality per spec §8.
    Preferred: 07-12, 13-17 UTC → full score
    Allowed:   12-13 UTC → -5 penalty
    Allowed:   17-00 UTC → -10 penalty
    Avoid:     00-07 UTC → -10 penalty
    """
    now_hour = datetime.now(timezone.utc).hour
    if 7 <= now_hour < 12:
        return 15, "07-12 UTC london — preferred"
    elif 13 <= now_hour < 17:
        return 15, "13-17 UTC london/ny overlap — preferred"
    elif 12 <= now_hour < 13:
        return 10, "12-13 UTC transition — allowed (-5)"
    elif 17 <= now_hour < 24:
        return 5,  "17-00 UTC ny/off-hours — allowed (-10)"
    else:  # 0-7
        return 5,  "00-07 UTC asian — avoid (-10)"


def get_tier(score: int) -> str:
    if score >= TIER_THRESHOLDS["TIER_A"]:
        return "TIER_A"
    elif score >= TIER_THRESHOLDS["TIER_B"]:
        return "TIER_B"
    elif score >= TIER_THRESHOLDS["TIER_C"]:
        return "TIER_C"
    else:
        return "BLOCK"


def main():
    parser = argparse.ArgumentParser(description="Score trend_pullback_reclaim_v1 signal 0–100")
    parser.add_argument("--eval-file",   required=True)
    parser.add_argument("--regime-file", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    try:
        with open(args.eval_file) as f:
            eval_result = json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": f"Eval file not found: {args.eval_file}"}), file=sys.stderr)
        sys.exit(2)

    try:
        with open(args.regime_file) as f:
            regime = json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": f"Regime file not found: {args.regime_file}"}), file=sys.stderr)
        sys.exit(2)

    if not eval_result.get("pass"):
        output = {
            "score": 0,
            "tier": "BLOCK",
            "size_multiplier": 0.0,
            "pass": False,
            "reason": (f"Signal evaluation failed "
                       f"({eval_result.get('conditions_met', 0)}/6 conditions)"),
        }
        print(json.dumps(output, indent=2))
        sys.exit(1)

    conditions   = eval_result.get("conditions", {})
    regime_reqs  = eval_result.get("regime_requirements", {})
    side         = eval_result.get("side", "LONG")

    htf_pts,  htf_reason  = score_htf_alignment(regime_reqs, side)
    adx_pts,  adx_reason  = score_adx_strength(regime_reqs)
    vol_pts,  vol_reason  = score_volatility_regime(regime)
    pb_pts,   pb_reason   = score_pullback_quality(conditions, side)
    eq_pts,   eq_reason   = score_entry_quality(conditions)
    ses_pts,  ses_reason  = score_session_quality()

    total = htf_pts + adx_pts + vol_pts + pb_pts + eq_pts + ses_pts

    # 4H RANGE cap: if 4H = RANGE, score cannot exceed 69 (forces MED at best)
    htf_type = regime_reqs.get("htf_4h_not_counter_trend", {}).get("htf_4h_type", "UNKNOWN")
    range_capped = False
    if htf_type == "RANGE" and total > 69:
        total = 69
        range_capped = True

    tier       = get_tier(total)
    multiplier = SIZE_MULTIPLIERS[tier]

    output = {
        "score": total,
        "tier": tier,
        "size_multiplier": multiplier,
        "pass": tier != "BLOCK",
        "side": side,
        "range_capped": range_capped,
        "breakdown": {
            "htf_alignment":     {"points": htf_pts,  "max": 25, "reason": htf_reason},
            "adx_strength":      {"points": adx_pts,  "max": 20, "reason": adx_reason},
            "volatility_regime": {"points": vol_pts,  "max": 15, "reason": vol_reason},
            "pullback_quality":  {"points": pb_pts,   "max": 15, "reason": pb_reason},
            "entry_quality":     {"points": eq_pts,   "max": 10, "reason": eq_reason},
            "session_quality":   {"points": ses_pts,  "max": 15, "reason": ses_reason},
        },
        "scored_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }

    print(json.dumps(output, indent=2))

    if args.out:
        try:
            with open(args.out, "w") as f:
                json.dump(output, f, indent=2)
        except OSError as e:
            print(f"[score-signal] Warning: could not write {args.out}: {e}", file=sys.stderr)

    if tier == "BLOCK":
        print(f"[score-signal] BLOCKED: score={total} < 50", file=sys.stderr)
        sys.exit(1)

    print(f"[score-signal] {tier} score={total} multiplier={multiplier}"
          f"{' (4H RANGE cap)' if range_capped else ''}", file=sys.stderr)


if __name__ == "__main__":
    main()
