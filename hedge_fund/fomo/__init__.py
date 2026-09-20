"""FOMO's Solana flow, read from the chain rather than from FOMO.

FOMO pays the gas on every user transaction, so its sponsoring address is
the fee payer on all of them and the whole flow is enumerable from the
chain alone. Nothing here touches fomo.family: no API, no scraping, no key.
"""

from hedge_fund.fomo.models import CollectionResult, Cursor, SponsoredTx

__all__ = ["CollectionResult", "Cursor", "SponsoredTx"]
