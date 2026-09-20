"""Hyperliquid market-state collector.

An append-only sensor, not a strategy: each pass records the state of every
Hyperliquid market -- native perps, every HIP-3 builder-deployed perp DEX,
and spot -- so the history of funding, open interest, marks, and prices
starts existing. Nothing in this package places an order or reads a wallet.
"""

from __future__ import annotations
