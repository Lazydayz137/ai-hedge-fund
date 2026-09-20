"""Walk the sponsor's transactions, newest first, and write down what is there."""

from __future__ import annotations

from datetime import datetime, timezone

from hedge_fund.fomo.client import SIGNATURE_PAGE, SolanaClient, SolanaError
from hedge_fund.fomo.models import (
    COLLECTOR_VERSION,
    GAS_SPONSOR,
    CollectionResult,
    Cursor,
    SponsoredTx,
    TxError,
)
from hedge_fund.fomo.store import read_cursor, save_pass, write_cursor

# A bound on one pass, so a first run against a heavily-used address cannot
# walk for hours and finish nothing. Reaching it is recorded, never hidden:
# the pass stops, keeps what it got, and does NOT move the cursor, so the
# next run resumes from the same place rather than skipping the remainder.
DEFAULT_MAX_TRANSACTIONS = 2_000


def parse_transaction(signature: str, payload: dict) -> SponsoredTx:
    """Turn one getTransaction response into the row worth keeping."""
    message = payload["transaction"]["message"]
    keys = message["accountKeys"]
    signers = [k["pubkey"] for k in keys if k.get("signer")]
    others = [s for s in signers if s != GAS_SPONSOR]

    block_time = payload.get("blockTime")
    return SponsoredTx(
        signature=signature,
        slot=payload["slot"],
        block_time=(
            datetime.fromtimestamp(block_time, tz=timezone.utc)
            if block_time is not None else None
        ),
        # Exactly one non-sponsor signer is the shape every sampled
        # transaction has. Anything else and the user is left None rather
        # than picked, because the wrong wallet on a trade is worse than no
        # wallet: one is a gap, the other is a fact that is not true.
        user=others[0] if len(others) == 1 else None,
        signers=signers,
        fee_lamports=payload["meta"]["fee"],
        programs=sorted({
            i["programId"] for i in message.get("instructions", []) if "programId" in i
        }),
        failed=payload["meta"].get("err") is not None,
    )


def collect(
    *,
    client: SolanaClient | None = None,
    until: str | None = None,
    max_transactions: int = DEFAULT_MAX_TRANSACTIONS,
    resume: bool = True,
) -> CollectionResult:
    """One pass over the sponsor's flow, newest first.

    Resumes from the stored cursor by default, so a scheduled run walks only
    what arrived since the last one. A transaction that cannot be read costs
    that transaction and records an error in its place — never a gap the
    archive cannot account for later, and never an invented row.
    """
    if max_transactions < 1:
        # Otherwise the loop never runs and the pass writes an empty result
        # that looks exactly like a quiet hour on the chain.
        raise ValueError(f"max_transactions must be at least 1, got {max_transactions}")

    client = client or SolanaClient()
    started_at = datetime.now(timezone.utc)
    if until is None and resume:
        cursor = read_cursor()
        until = cursor.signature if cursor else None

    transactions: list[SponsoredTx] = []
    errors: list[TxError] = []
    newest_signature: str | None = None
    before: str | None = None
    reached_cursor = True

    while len(transactions) + len(errors) < max_transactions:
        page = client.signatures(
            GAS_SPONSOR, before=before, until=until,
            limit=min(SIGNATURE_PAGE, max_transactions - len(transactions) - len(errors)),
        )
        if not page:
            break

        for entry in page:
            signature = entry["signature"]
            if newest_signature is None:
                newest_signature = signature
            if len(transactions) + len(errors) >= max_transactions:
                reached_cursor = False
                break
            try:
                transactions.append(
                    parse_transaction(signature, client.transaction(signature))
                )
            except (SolanaError, KeyError, TypeError, ValueError) as exc:
                errors.append(TxError(signature=signature, error=str(exc)))

        before = page[-1]["signature"]
        if len(page) < SIGNATURE_PAGE:
            break

    # Hitting the cap means the window may be short, and there is no way to
    # tell "finished exactly at the cap" from "stopped one short of more".
    # The two are indistinguishable from here and they are not equally bad:
    # under-claiming costs a redundant re-walk, over-claiming advances the
    # cursor past transactions nobody will come back for.
    if len(transactions) + len(errors) >= max_transactions:
        reached_cursor = False

    return CollectionResult(
        started_at=started_at,
        # Stamped after the last transaction was read, not before the first:
        # a pass spans wall time, and stamping the start would let an as-of
        # read return rows that were not on-chain yet at that cutoff.
        observed_at=datetime.now(timezone.utc),
        collector_version=COLLECTOR_VERSION,
        newest_signature=newest_signature,
        until_signature=until,
        reached_cursor=reached_cursor,
        transactions=transactions,
        errors=errors,
    )


def collect_and_save(**kwargs) -> tuple[CollectionResult, object]:
    """Run a pass, archive it, and move the cursor only if the pass finished.

    A capped pass leaves the cursor where it was. Advancing it would skip
    every transaction between the cap and the old cursor, and nothing would
    ever say so — the archive would simply be missing a window.
    """
    result = collect(**kwargs)
    path = save_pass(result)
    if result.reached_cursor and result.newest_signature:
        write_cursor(Cursor(
            signature=result.newest_signature,
            slot=result.transactions[0].slot if result.transactions else 0,
            recorded_at=result.observed_at,
        ))
    return result, path
