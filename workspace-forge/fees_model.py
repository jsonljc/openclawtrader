#!/usr/bin/env python3
"""Fee model for futures paper trading.

Futures fees are per-contract (not bps of notional), charged on both
entry and exit legs (round-trip). The round-trip fee is stored in the
strategy registry as fee_per_contract_round_trip_usd.
"""

from __future__ import annotations


def entry_fee_usd(contracts: int, fee_per_contract_round_trip_usd: float) -> float:
    """Fee charged on order entry (half of round-trip)."""
    return round(contracts * fee_per_contract_round_trip_usd / 2.0, 4)


def exit_fee_usd(contracts: int, fee_per_contract_round_trip_usd: float) -> float:
    """Fee charged on order exit / bracket close (half of round-trip)."""
    return round(contracts * fee_per_contract_round_trip_usd / 2.0, 4)


def round_trip_fee_usd(contracts: int, fee_per_contract_round_trip_usd: float) -> float:
    """Total round-trip fee for a full open + close cycle."""
    return round(contracts * fee_per_contract_round_trip_usd, 4)
