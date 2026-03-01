#!/usr/bin/env python3
"""CME contract month calendar — Phase 3 rollover.

Month codes: F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun, N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec.
Quarterly: Mar(H), Jun(M), Sep(U), Dec(Z).
"""

from __future__ import annotations

_MONTH_CODES = "FGJKMNQUVXZ"   # CME all months
_QUARTER_CODES = ("H", "M", "U", "Z")  # Mar, Jun, Sep, Dec — equity index listing


def next_contract_month(symbol: str, contract_month: str) -> str:
    """
    Return the next listed contract month after the given one.
    ES/NQ use quarterly (H, M, U, Z). Other symbols use all months.
    """
    if not contract_month or len(contract_month) < 4:
        return contract_month + "_NEXT"
    prefix_len = 2 if contract_month[:2].upper() in ("ES", "NQ") else 1
    rest = contract_month[prefix_len:].upper()
    if len(rest) < 2:
        return contract_month + "_NEXT"
    month_code = rest[0]
    try:
        year_int = int(rest[1:])
    except ValueError:
        return contract_month + "_NEXT"
    prefix = contract_month[:prefix_len].upper()
    # Equity index (ES/NQ): next quarter
    if prefix in ("ES", "NQ") and month_code in _QUARTER_CODES:
        qi = _QUARTER_CODES.index(month_code)
        next_qi = (qi + 1) % 4
        next_year = year_int if next_qi > qi else year_int + 1
        return f"{prefix}{_QUARTER_CODES[next_qi]}{next_year}"
    try:
        mi = _MONTH_CODES.index(month_code)
    except ValueError:
        return contract_month + "_NEXT"
    next_mi = (mi + 1) % len(_MONTH_CODES)
    next_year = year_int if next_mi > mi else year_int + 1
    return f"{prefix}{_MONTH_CODES[next_mi]}{next_year}"
