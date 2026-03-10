#!/usr/bin/env python3
"""Fee model for futures paper trading.

Futures fees are per-contract (not bps of notional), charged on both
entry and exit legs (round-trip). The round-trip fee is stored in the
strategy registry as fee_per_contract_round_trip_usd.

When trading micro contracts (MES/MNQ), use micro_fee_per_contract_round_trip_usd
if available; otherwise fall back to the standard fee.
"""

from __future__ import annotations


def _resolve_fee(
    fee_per_contract_round_trip_usd: float,
    use_micro: bool = False,
    micro_fee_per_contract_round_trip_usd: float | None = None,
) -> float:
    """Pick the correct per-contract RT fee based on contract type."""
    if use_micro and micro_fee_per_contract_round_trip_usd is not None:
        return micro_fee_per_contract_round_trip_usd
    return fee_per_contract_round_trip_usd


def entry_fee_usd(
    contracts: int,
    fee_per_contract_round_trip_usd: float,
    use_micro: bool = False,
    micro_fee_per_contract_round_trip_usd: float | None = None,
) -> float:
    """Fee charged on order entry (half of round-trip)."""
    fee = _resolve_fee(fee_per_contract_round_trip_usd, use_micro, micro_fee_per_contract_round_trip_usd)
    return round(contracts * fee / 2.0, 4)


def exit_fee_usd(
    contracts: int,
    fee_per_contract_round_trip_usd: float,
    use_micro: bool = False,
    micro_fee_per_contract_round_trip_usd: float | None = None,
) -> float:
    """Fee charged on order exit / bracket close (half of round-trip)."""
    fee = _resolve_fee(fee_per_contract_round_trip_usd, use_micro, micro_fee_per_contract_round_trip_usd)
    return round(contracts * fee / 2.0, 4)


def round_trip_fee_usd(
    contracts: int,
    fee_per_contract_round_trip_usd: float,
    use_micro: bool = False,
    micro_fee_per_contract_round_trip_usd: float | None = None,
) -> float:
    """Total round-trip fee for a full open + close cycle."""
    fee = _resolve_fee(fee_per_contract_round_trip_usd, use_micro, micro_fee_per_contract_round_trip_usd)
    return round(contracts * fee, 4)
