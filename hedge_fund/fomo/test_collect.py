"""A pass writes what it walked, admits what it missed, and invents nothing."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hedge_fund.fomo.client import SolanaError
from hedge_fund.fomo.collect import collect, collect_and_save, parse_transaction
from hedge_fund.fomo.models import GAS_SPONSOR
from hedge_fund.fomo.store import read_cursor

USER = "7KYjRhH6mp3dnN2PPEsaa3bVo1KYAMPhUaciufGPYJnn"

# Trimmed from a real getTransaction response captured 2026-09-20, keeping the
# shape every sampled transaction has: the sponsor as fee payer plus exactly
# one other signer.
def _payload(*, signers=(GAS_SPONSOR, USER), err=None, slot=448847587):
    return {
        "slot": slot,
        "blockTime": 1789938277,
        "transaction": {"message": {
            "accountKeys": [
                {"pubkey": s, "signer": True, "writable": True} for s in signers
            ] + [{"pubkey": "SomeMint1111", "signer": False, "writable": True}],
            "instructions": [
                {"programId": "ComputeBudget111111111111111111111111111111"},
                {"programId": "DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH"},
            ],
        }},
        "meta": {"fee": 410000, "err": err},
    }


class FakeClient:
    """Answers from a script. Never touches the network."""

    def __init__(self, signatures, *, fail: set[str] = frozenset(), payloads=None):
        self._pages = signatures
        self._fail = fail
        self._payloads = payloads or {}
        self.asked_until: list[str | None] = []

    def signatures(self, address, *, before=None, until=None, limit=1000):
        self.asked_until.append(until)
        if before is not None:
            return []
        return [{"signature": s} for s in self._pages][:limit]

    def transaction(self, signature):
        if signature in self._fail:
            raise SolanaError(f"getTransaction: {signature} returned null")
        return self._payloads.get(signature, _payload())


def test_the_non_sponsor_signer_is_the_user():
    tx = parse_transaction("sig1", _payload())
    assert tx.user == USER
    assert tx.signers == [GAS_SPONSOR, USER]


def test_an_unexpected_signer_shape_leaves_the_user_unnamed():
    """The wrong wallet on a trade is worse than no wallet: one is a gap, the
    other is a fact that is not true."""
    two_others = _payload(signers=(GAS_SPONSOR, USER, "OtherSigner111"))
    assert parse_transaction("sig1", two_others).user is None

    sponsor_only = _payload(signers=(GAS_SPONSOR,))
    assert parse_transaction("sig1", sponsor_only).user is None


def test_a_failed_transaction_is_recorded_not_dropped():
    """FOMO paid the fee either way, so it happened and belongs in the flow."""
    tx = parse_transaction("sig1", _payload(err={"InstructionError": [0, "X"]}))
    assert tx.failed is True
    assert tx.fee_lamports == 410000


def test_an_unreadable_transaction_costs_only_itself():
    result = collect(client=FakeClient(["a", "b", "c"], fail={"b"}), resume=False)
    assert [t.signature for t in result.transactions] == ["a", "c"]
    assert [e.signature for e in result.errors] == ["b"]


def test_the_pass_is_stamped_after_its_last_transaction():
    """Stamping the start would let an as-of read return rows that were not
    on-chain yet at that cutoff."""
    before = datetime.now(timezone.utc)
    result = collect(client=FakeClient(["a"]), resume=False)
    assert result.observed_at >= result.started_at >= before


def test_a_cap_below_one_is_refused():
    with pytest.raises(ValueError, match="at least 1"):
        collect(client=FakeClient(["a"]), max_transactions=0, resume=False)


def test_a_completed_pass_moves_the_cursor():
    result, _ = collect_and_save(client=FakeClient(["a", "b"]), resume=False)
    assert result.reached_cursor
    assert read_cursor().signature == "a"


def test_a_capped_pass_leaves_the_cursor_alone():
    """Advancing it would skip everything between the cap and the old cursor,
    and nothing would ever say the window was missing."""
    result, _ = collect_and_save(
        client=FakeClient(["a", "b", "c"]), max_transactions=2, resume=False
    )
    assert result.reached_cursor is False
    assert read_cursor() is None


def test_a_resumed_pass_asks_the_endpoint_to_stop_at_the_cursor():
    collect_and_save(client=FakeClient(["a", "b"]), resume=False)
    client = FakeClient(["z"])
    collect(client=client, resume=True)
    assert client.asked_until[0] == "a"
