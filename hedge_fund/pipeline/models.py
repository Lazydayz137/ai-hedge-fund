"""Pipeline records — the serialized truth of every cycle.

A CycleRecord captures one tick of the fund end to end: what the analysts
saw, what they said, how views became weights, what risk clamped, what was
ordered and filled, and what the book looks like after. The ledger persists
these; `fund why AAPL` will answer from them alone.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from hedge_fund.brokers.models import Fill, Order
from hedge_fund.fund.spec import AuditFundSpec
from hedge_fund.models import Signal
from hedge_fund.risk.limits import ClampEvent


class TickerSkip(BaseModel):
    """A requested name that could not be traded this cycle, and why."""

    ticker: str
    reason: str


class StrategyRecord(BaseModel):
    """One strategy's slice of a cycle: its analysts' views and its sleeve."""

    name: str
    slice: float                        # normalized capital slice of the fund
    signals: list[Signal]               # this strategy's analysts x tradeable tickers
    convictions: dict[str, float]       # blended views, pre-scaling
    weights: dict[str, float]           # the sleeve, before netting across strategies


class CycleRecord(BaseModel):
    """One tick of the fund, fully serialized — every stage's inputs and
    outputs. `model_dump_json()` round-trips; nothing about a decision
    lives anywhere else.

    Receipts outlive the build that wrote them — a fund's book is resumed
    from its newest receipt — so a record this build cannot read costs that
    fund its entire history. `schema_version` names the shape, and the
    embedded mandate is the tolerant `AuditFundSpec`, not the strict
    load-time model.
    """

    # Bumped only when a change to this record's shape is NOT backward-
    # readable. Receipts written before the field existed validate as 1,
    # which is exactly what they are.
    schema_version: int = 1

    fund: str
    as_of: str
    spec: AuditFundSpec                 # self-contained audit copy
    universe: list[str]                 # the tickers this cycle was asked to trade
    marks: dict[str, float]             # ticker -> close used for sizing and NAV
    skipped: list[TickerSkip]
    strategies: list[StrategyRecord]    # every sleeve, incl. each thesis
    target_weights: dict[str, float]    # the NETTED book, pre-risk
    clamps: list[ClampEvent]
    final_weights: dict[str, float]     # post-risk
    equity_before: float
    cash_before: float
    orders: list[Order]
    fills: list[Fill]
    positions: dict[str, int]           # signed shares after fills
    cost_basis: dict[str, float] = {}   # weighted-average entry price per open name
    cash: float
    nav: float                          # cash + sum(shares * mark)
    realized_pnl: float = 0.0           # THIS cycle's realized gains, from its fills

    @field_validator("spec", mode="before")
    @classmethod
    def _spec_as_audit_copy(cls, value: object) -> object:
        """Accept a live FundSpec where the tolerant audit copy is declared.

        run_cycle hands over `fund.spec`, a strict FundSpec; pydantic will not
        accept a parent-class instance for a subclass field, so dump it and let
        AuditFundSpec re-validate. Receipts read back from JSON are already
        dicts and pass through untouched.
        """
        if isinstance(value, BaseModel):
            return value.model_dump()
        return value
