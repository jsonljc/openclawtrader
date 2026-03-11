#!/usr/bin/env python3
"""CME contract month calendar — Phase 3 rollover.

Month codes: F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun, N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec.
Quarterly: Mar(H), Jun(M), Sep(U), Dec(Z).
Bi-monthly (GC): Feb(G), Apr(J), Jun(M), Aug(Q), Oct(V), Dec(Z).
"""

from __future__ import annotations

_MONTH_CODES = "FGHJKMNQUVXZ"   # CME all months (H=Mar was missing)
_QUARTER_CODES = ("H", "M", "U", "Z")  # Mar, Jun, Sep, Dec — equity index listing
_BIMONTHLY_CODES = ("G", "J", "M", "Q", "V", "Z")  # Feb, Apr, Jun, Aug, Oct, Dec — gold listing

# Symbols using each contract cycle
_QUARTERLY_SYMBOLS = {"ES", "NQ", "MES", "MNQ", "ZB", "ZN", "ZF", "ZT", "YM", "RTY"}
_BIMONTHLY_SYMBOLS = {"GC", "MGC"}
# Everything else (CL, etc.) uses monthly


def next_contract_month(symbol: str, contract_month: str) -> str:
    """
    Return the next listed contract month after the given one.
    ES/NQ/ZB use quarterly (H, M, U, Z).
    GC uses bi-monthly (G, J, M, Q, V, Z).
    Other symbols (CL, etc.) use all months.
    """
    if not contract_month or len(contract_month) < 3:
        return contract_month + "_NEXT"
    # Known 2-char and 3-char symbol prefixes for CME futures
    _KNOWN_PREFIXES = ("ES", "NQ", "CL", "GC", "SI", "HG", "NG", "ZB", "ZN",
                       "ZF", "ZT", "YM", "RTY", "MES", "MNQ", "MCL", "MGC", "MBT")
    upper = contract_month.upper()
    prefix_len = 1
    for pfx in sorted(_KNOWN_PREFIXES, key=len, reverse=True):
        if upper.startswith(pfx) and len(upper) > len(pfx):
            prefix_len = len(pfx)
            break
    rest = upper[prefix_len:]
    if len(rest) < 2:
        return contract_month + "_NEXT"
    month_code = rest[0]
    try:
        year_int = int(rest[1:])
    except ValueError:
        return contract_month + "_NEXT"
    prefix = contract_month[:prefix_len].upper()

    # Quarterly symbols (ES, NQ, ZB, etc.)
    if prefix in _QUARTERLY_SYMBOLS and month_code in _QUARTER_CODES:
        qi = _QUARTER_CODES.index(month_code)
        next_qi = (qi + 1) % 4
        next_year = year_int if next_qi > qi else year_int + 1
        return f"{prefix}{_QUARTER_CODES[next_qi]}{next_year}"

    # Bi-monthly symbols (GC, MGC)
    if prefix in _BIMONTHLY_SYMBOLS and month_code in _BIMONTHLY_CODES:
        bi = _BIMONTHLY_CODES.index(month_code)
        next_bi = (bi + 1) % 6
        next_year = year_int if next_bi > bi else year_int + 1
        return f"{prefix}{_BIMONTHLY_CODES[next_bi]}{next_year}"

    # Monthly (CL, MCL, etc.)
    try:
        mi = _MONTH_CODES.index(month_code)
    except ValueError:
        return contract_month + "_NEXT"
    next_mi = (mi + 1) % len(_MONTH_CODES)
    next_year = year_int if next_mi > mi else year_int + 1
    return f"{prefix}{_MONTH_CODES[next_mi]}{next_year}"
