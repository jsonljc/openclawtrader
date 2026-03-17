"""
Options intelligence — GEX, skew, unusual flow, term structure.

Four analytics:
1. GEX (gamma exposure) — dealer positioning
2. Skew — put vs call implied volatility
3. Unusual flow — volume spikes
4. Term structure — front vs back month IV
"""

import numpy as np
from typing import Dict, List


def compute_gex(chain: List[dict], spot: float = None) -> float:
    """
    Compute gamma exposure (GEX).

    GEX = sum of (OI × gamma × multiplier × spot) for calls minus puts

    Positive GEX = heavy call gamma near spot -> mean-reversion regime
    Negative GEX = heavy put gamma -> trend-following regime

    Args:
        chain: List of option entries with keys: strike, call_oi, put_oi
               Optional: call_gamma, put_gamma (defaults to simplified approximation)
        spot: Current underlying price (defaults to ATM strike approximation)

    Returns:
        GEX score normalized to [-100, +100]
    """
    if not chain:
        return 0.0

    # Approximate spot from chain if not provided
    if spot is None:
        strikes = [opt["strike"] for opt in chain]
        spot = np.median(strikes)

    # Contract multiplier (standard for equity options = 100)
    multiplier = 100

    call_gex_total = 0.0
    put_gex_total = 0.0

    for opt in chain:
        strike = opt["strike"]
        call_oi = opt.get("call_oi", 0)
        put_oi = opt.get("put_oi", 0)

        # Simplified gamma approximation (actual gamma requires more inputs)
        # Gamma peaks ATM and decays with distance from spot
        # Use normalized distance: gamma ∝ exp(-0.5 * ((K-S)/S)^2 / sigma^2)
        # Simplified: gamma ∝ 1 / (1 + abs(K - S) / S)
        moneyness = abs(strike - spot) / spot
        gamma_approx = 1.0 / (1.0 + moneyness * 5.0)  # Decay factor = 5

        # GEX contribution
        call_gex_total += call_oi * gamma_approx * multiplier * spot
        put_gex_total += put_oi * gamma_approx * multiplier * spot

    # Net GEX (calls are positive for dealers = negative gamma for market)
    # Dealers are short calls, long puts typically
    # Positive net call OI = dealers short gamma = suppresses vol
    net_gex = call_gex_total - put_gex_total

    # Normalize to [-100, +100] range
    # Typical GEX magnitude is in billions for SPX
    # For ES options, scale to ~1B as typical
    scale_factor = 1e9
    normalized = (net_gex / scale_factor) * 100.0

    return np.clip(normalized, -100.0, 100.0)


def compute_skew(chain: List[dict], historical_skew: float) -> Dict[str, float]:
    """
    Compute put/call IV skew.

    Skew = 25-delta put IV - 25-delta call IV (approximate using strikes ~2 away from ATM)

    Args:
        chain: List of option entries with keys: strike, call_iv, put_iv
        historical_skew: Historical average skew for comparison

    Returns:
        {"skew": current_skew, "skew_shift": current - historical}
    """
    if not chain or len(chain) < 3:
        return {"skew": 0.0, "skew_shift": 0.0}

    # Sort by strike
    sorted_chain = sorted(chain, key=lambda x: x["strike"])

    # Find ATM (middle strike)
    mid_idx = len(sorted_chain) // 2

    # Approximate 25-delta options as +/-2 strikes from ATM
    put_idx = max(0, mid_idx - 2)
    call_idx = min(len(sorted_chain) - 1, mid_idx + 2)

    put_iv = sorted_chain[put_idx].get("put_iv", 0.0)
    call_iv = sorted_chain[call_idx].get("call_iv", 0.0)

    # Skew = put IV - call IV (typically positive, puts trade at premium)
    current_skew = put_iv - call_iv

    # Skew shift = current - historical
    skew_shift = current_skew - historical_skew

    return {
        "skew": current_skew,
        "skew_shift": skew_shift,
    }


def detect_unusual_flow(chain: List[dict]) -> List[dict]:
    """
    Detect unusual option flow (volume spikes relative to open interest).

    Flags strikes where volume/OI > 2.0.

    Args:
        chain: List of option entries with keys: strike, call_vol, call_oi, put_vol, put_oi

    Returns:
        List of unusual flow alerts:
        [{"strike": float, "type": "call"|"put", "vol_oi_ratio": float, "volume": int}, ...]
    """
    unusual = []

    for opt in chain:
        strike = opt["strike"]

        # Check calls
        call_vol = opt.get("call_vol", 0)
        call_oi = opt.get("call_oi", 0)
        if call_oi > 0:
            call_ratio = call_vol / call_oi
            if call_ratio > 2.0:
                unusual.append({
                    "strike": strike,
                    "type": "call",
                    "vol_oi_ratio": round(call_ratio, 2),
                    "volume": call_vol,
                })

        # Check puts
        put_vol = opt.get("put_vol", 0)
        put_oi = opt.get("put_oi", 0)
        if put_oi > 0:
            put_ratio = put_vol / put_oi
            if put_ratio > 2.0:
                unusual.append({
                    "strike": strike,
                    "type": "put",
                    "vol_oi_ratio": round(put_ratio, 2),
                    "volume": put_vol,
                })

    # Sort by vol/OI ratio descending
    unusual.sort(key=lambda x: x["vol_oi_ratio"], reverse=True)

    return unusual


def compute_term_structure(front_iv: float, back_iv: float) -> Dict[str, any]:
    """
    Compute IV term structure.

    Slope = front IV - back IV
    - Negative slope (contango): normal market, mean-reversion regime
    - Positive slope (backwardation): fear/uncertainty, trend-following regime
    - Flat: neutral

    Args:
        front_iv: Front month (near expiry) implied volatility
        back_iv: Back month (far expiry) implied volatility

    Returns:
        {"slope": float, "state": "contango"|"backwardation"|"flat"}
    """
    slope = front_iv - back_iv

    # Classify state
    if slope < -1.0:
        state = "contango"
    elif slope > 1.0:
        state = "backwardation"
    else:
        state = "flat"

    return {
        "slope": round(slope, 2),
        "state": state,
    }
