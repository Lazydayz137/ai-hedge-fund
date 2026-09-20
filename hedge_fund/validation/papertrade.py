"""The paper-trade record: intended price against achieved price, every order.

Report 02 §5.E item 5 asks for at least thirty days of live paper trading that
logs the intended and the achieved fill price on every order. The length is not
the interesting part. The coverage is: a record that logs the orders that
filled well and omits the ones that did not is a record of the strategy you
wish you were running, and the omission is invisible in the summary statistics
it produces.

So `n_orders_placed` is declared separately from the fills, and a gap between
them is a FAIL rather than a footnote. Slippage is then measured off the fills
and reported in basis points with an adverse-positive sign convention, so a
positive mean means the book paid — for a buy, filling above the intended price
is adverse; for a sell, filling below it is.

This module measures. It does not gate on the magnitude unless asked: there is
no published threshold for acceptable slippage, and the number's job is to be
compared against live slippage later, which is item 6 of the bar.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hedge_fund.validation.outcome import CheckResult, Verdict, unknown

CHECK = "paper_trade"

MIN_DAYS = 30


class PaperFill(BaseModel):
    """One order's intended price and what it actually got."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    intended_price: float = Field(gt=0)
    achieved_price: float = Field(gt=0)
    placed_on: str = Field(description="YYYY-MM-DD")

    @model_validator(mode="after")
    def _dated(self) -> "PaperFill":
        try:
            date.fromisoformat(self.placed_on)
        except ValueError as exc:
            raise ValueError(f"placed_on={self.placed_on!r} is not YYYY-MM-DD") from exc
        return self

    @property
    def slippage_bps(self) -> float:
        """Adverse slippage in basis points of the intended price.

        Signed so that positive always means the book paid, on both sides. The
        alternative — signing by price direction — makes the mean across a
        two-sided book cancel toward zero and report a frictionless strategy.
        """
        if self.side == "buy":
            adverse = self.achieved_price - self.intended_price
        else:
            adverse = self.intended_price - self.achieved_price
        return adverse / self.intended_price * 10_000.0


class PaperTradeRecord(BaseModel):
    """A stretch of live paper trading, and every fill in it.

    `n_orders_placed` is the count the trading loop saw, not `len(fills)`. They
    are supposed to be equal; this model exists so that when they are not, the
    check can say so instead of averaging over whatever survived.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str
    started_on: str = Field(description="YYYY-MM-DD")
    ended_on: str = Field(description="YYYY-MM-DD")
    n_orders_placed: int = Field(ge=0)
    fills: list[PaperFill] = Field(default_factory=list)
    venue: str | None = None

    @model_validator(mode="after")
    def _ordered(self) -> "PaperTradeRecord":
        for label, value in (
            ("started_on", self.started_on), ("ended_on", self.ended_on),
        ):
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{label}={value!r} is not YYYY-MM-DD") from exc
        if self.ended_on < self.started_on:
            raise ValueError(
                f"record ends {self.ended_on} before it starts {self.started_on}"
            )
        return self

    @property
    def span_days(self) -> int:
        """Calendar days covered, inclusive of both endpoints."""
        return (
            date.fromisoformat(self.ended_on) - date.fromisoformat(self.started_on)
        ).days + 1


def score(
    record: PaperTradeRecord | None,
    *,
    min_days: int = MIN_DAYS,
    max_mean_slippage_bps: float | None = None,
) -> CheckResult:
    """Report 02 §5.E item 5: >= 30 days paper-traded, every order logged."""
    if record is None:
        return unknown(
            CHECK,
            "no paper-trade record; nothing has measured this strategy's "
            "real slippage, so the backtest's fill assumption is still the "
            "only estimate of it",
        )

    evidence = {
        "strategy_id": record.strategy_id,
        "started_on": record.started_on,
        "ended_on": record.ended_on,
        "span_days": record.span_days,
        "required_days": min_days,
        "n_orders_placed": record.n_orders_placed,
        "n_fills_logged": len(record.fills),
        "venue": record.venue,
    }

    if record.span_days < min_days:
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                f"the record spans {record.span_days} days against the "
                f"{min_days} required; this is a measured shortfall, not an "
                "inability to measure"
            ),
            evidence=evidence,
        )

    missing = record.n_orders_placed - len(record.fills)
    if missing > 0:
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                f"{missing} of {record.n_orders_placed} orders have no logged "
                "fill; slippage measured over the orders that happened to be "
                "recorded is a statistic about the recording, not the strategy"
            ),
            evidence=evidence,
        )
    if missing < 0:
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                f"{len(record.fills)} fills against {record.n_orders_placed} "
                "orders placed; the record does not reconcile with itself and "
                "neither number can be trusted as the denominator"
            ),
            evidence=evidence,
        )

    if not record.fills:
        return unknown(
            CHECK,
            f"{record.span_days} days elapsed with zero orders placed; a "
            "strategy that did not trade has not measured its slippage",
            **evidence,
        )

    slippages = [f.slippage_bps for f in record.fills]
    ordered = sorted(slippages)
    measured = {
        "mean_slippage_bps": statistics.fmean(slippages),
        "median_slippage_bps": statistics.median(ordered),
        "worst_slippage_bps": ordered[-1],
        "best_slippage_bps": ordered[0],
        # Nearest-rank, not interpolated: with a handful of fills an
        # interpolated p95 invents a value between two observations and reads
        # as if the tail were measured more finely than it was.
        "p95_slippage_bps": ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))],
        "max_mean_slippage_bps": max_mean_slippage_bps,
    }
    evidence = evidence | measured

    if (
        max_mean_slippage_bps is not None
        and measured["mean_slippage_bps"] > max_mean_slippage_bps
    ):
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                f"mean adverse slippage {measured['mean_slippage_bps']:.1f} bps "
                f"exceeds the {max_mean_slippage_bps:.1f} bps allowed"
            ),
            evidence=evidence,
        )

    return CheckResult(
        check=CHECK,
        verdict=Verdict.PASS,
        reason=(
            f"{record.span_days} days, {len(record.fills)} of "
            f"{record.n_orders_placed} orders logged with intended and "
            f"achieved price; mean adverse slippage "
            f"{measured['mean_slippage_bps']:.1f} bps, worst "
            f"{measured['worst_slippage_bps']:.1f} bps"
        ),
        evidence=evidence,
    )
