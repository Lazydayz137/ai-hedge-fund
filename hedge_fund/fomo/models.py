"""What one sponsored transaction is worth writing down."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

COLLECTOR_VERSION = "1"

# Published in DeFiLlama's open-source adapter and confirmed live on mainnet:
# this address is accountKeys[0] — the fee payer — on every FOMO user
# transaction, which is what makes the flow enumerable without FOMO's help.
GAS_SPONSOR = "AgmLJBMDCqWynYnQiPCuj9ewsNNsBJXyzoUhD9LJzN51"


class SponsoredTx(BaseModel):
    """One transaction FOMO paid the fee for.

    `user` is the signer that is not the sponsor. Every transaction sampled
    from this address carries exactly two signers, and the non-sponsor one
    also appears among the token-balance owners — it is the trading party.
    When that shape does not hold, `user` is None and `signers` keeps whatever
    was actually there, because a guess here would silently misattribute a
    trade to the wrong wallet.
    """

    signature: str
    slot: int
    block_time: datetime | None       # None when the cluster has not stamped it
    user: str | None
    signers: list[str]
    fee_lamports: int
    programs: list[str]
    failed: bool                      # meta.err was set; the fee was still paid


class TxError(BaseModel):
    """A transaction that could not be read or parsed, and why.

    Recorded rather than dropped: a gap the archive cannot explain later is
    indistinguishable from a quiet day.
    """

    signature: str
    error: str


class CollectionResult(BaseModel):
    """One pass: what it walked, what it got, and where it stopped."""

    started_at: datetime
    observed_at: datetime             # when the LAST transaction was read
    collector_version: str = COLLECTOR_VERSION
    sponsor: str = GAS_SPONSOR
    newest_signature: str | None      # the cursor a later pass resumes from
    until_signature: str | None       # the cursor this pass was told to stop at
    reached_cursor: bool              # False means the window was capped short
    transactions: list[SponsoredTx]
    errors: list[TxError]


class Cursor(BaseModel):
    """The newest signature a completed pass saw, so the next one resumes."""

    signature: str
    slot: int
    recorded_at: datetime
