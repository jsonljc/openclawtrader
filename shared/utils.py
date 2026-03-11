"""Shared utility functions for OpenClaw."""

import math


def round_to_tick(price: float, tick_size: float) -> float:
    """Snap a price to the nearest valid tick increment."""
    if tick_size <= 0:
        return round(price, 2)
    return round(round(price / tick_size) * tick_size, 10)
