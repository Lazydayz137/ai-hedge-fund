"""The sealed out-of-sample window, and the record that it was opened.

Report 02's cautionary tale is a pre-registered pump.fun survival study that
scored AUROC 0.8594 in development and 0.4642 in validation — worse than a coin
flip, on data drawn fifteen days later. The gap between those two numbers is
the entire value of a holdout, and it only exists while nobody has looked.

So the returns here are not an attribute. They live behind `reveal()`, which
writes a Reveal into the validation store before it hands anything back, and
`score()` checks for earlier reveals before adding its own. Looking twice is
not forbidden — it cannot be, this is a library and the caller owns the
process — it is *recorded*, and a window that was already opened can no longer
report a verdict of "positive in a window that was not looked at". It reports
that its seal was broken, which is a FAIL rather than an UNKNOWN because that
is a fact the check successfully established.

Length rules come from report 02 §5.E item 2: the window must be at least 3x
the holding period and at least 60 days. A window shorter than that is an
UNKNOWN, not a FAIL: three days of forward data does not say the strategy is
bad, it says nobody has asked the question yet.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hedge_fund.validation import registry
from hedge_fund.validation.outcome import CheckResult, Verdict, unknown

CHECK = "out_of_sample"

# Report 02 §5.E item 2. Both floors, not either.
MIN_WINDOW_DAYS = 60
MIN_HOLDING_PERIOD_MULTIPLE = 3


class HoldoutWindow(BaseModel):
    """The bounds of the forward window, and what the returns in it include.

    `net_of_costs` is a claim the caller makes, and the check treats a False as
    disqualifying rather than as a detail. Report 02 budgets 3-6% round-trip
    friction on thin instruments; a gross-return holdout is not a weaker piece
    of evidence than a net one, it is evidence about a different strategy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: str = Field(description="YYYY-MM-DD, first day of the sealed window")
    end: str = Field(description="YYYY-MM-DD, last day of the sealed window")
    in_sample_end: str = Field(
        description="YYYY-MM-DD, last day the strategy was allowed to see"
    )
    holding_period_days: int = Field(gt=0)
    frequency: str
    net_of_costs: bool
    cost_model: str | None = Field(
        default=None, description="what 'net' meant: fees, spread, impact"
    )

    @model_validator(mode="after")
    def _ordered(self) -> "HoldoutWindow":
        for label, value in (
            ("start", self.start), ("end", self.end),
            ("in_sample_end", self.in_sample_end),
        ):
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{label}={value!r} is not YYYY-MM-DD") from exc
        if self.end < self.start:
            raise ValueError(f"window ends {self.end} before it starts {self.start}")
        return self

    @property
    def span_days(self) -> int:
        """Calendar days covered, inclusive of both endpoints."""
        return (
            date.fromisoformat(self.end) - date.fromisoformat(self.start)
        ).days + 1

    @property
    def required_days(self) -> int:
        """The longer of the two floors report 02 sets."""
        return max(
            MIN_WINDOW_DAYS,
            MIN_HOLDING_PERIOD_MULTIPLE * self.holding_period_days,
        )


class SealedHoldout:
    """Forward returns nobody has looked at yet.

    Not a pydantic model on purpose: a BaseModel would put the returns in
    `model_dump()`, in `__repr__`, and in every receipt anything serialized
    them into, which is the opposite of sealed. The only way out is `reveal`.
    """

    __slots__ = ("_strategy_id", "_window", "__returns", "_sealed_at")

    def __init__(
        self,
        *,
        strategy_id: str,
        window: HoldoutWindow,
        returns: Sequence[float],
        sealed_at: datetime,
    ) -> None:
        self._strategy_id = strategy_id
        self._window = window
        # Name-mangled and slotted: reachable as _SealedHoldout__returns by
        # someone who has decided to, which is the point. The API makes peeking
        # awkward and auditable; it cannot make it impossible, and pretending
        # otherwise would be the same theatre this package exists to call out.
        self.__returns = tuple(float(r) for r in returns)
        self._sealed_at = sealed_at

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def window(self) -> HoldoutWindow:
        return self._window

    @property
    def n_observations(self) -> int:
        """How many returns are sealed in here.

        Provenance, not data: the window bounds and the cadence already imply
        it, and a check that cannot say how big its sample was is exactly the
        number-without-provenance this package refuses to produce.
        """
        return len(self.__returns)

    @property
    def sealed_at(self) -> datetime:
        return self._sealed_at

    def prior_reveals(self) -> list[registry.Reveal]:
        """Every earlier unsealing of this strategy's holdout, from the store."""
        return registry.reveals(self._strategy_id)

    def reveal(self, *, reason: str, revealed_at: datetime) -> tuple[float, ...]:
        """Unseal the window, recording that it happened before handing it over.

        The write comes first. If recording the reveal fails, the caller does
        not get the returns — an unrecorded look is worse than no look, because
        the next verdict would certify a window that had already been seen.
        """
        registry.record_reveal(
            registry.Reveal(
                strategy_id=self._strategy_id,
                revealed_at=revealed_at,
                window_start=self._window.start,
                window_end=self._window.end,
                reason=reason,
            )
        )
        return self.__returns

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"SealedHoldout(strategy_id={self._strategy_id!r}, "
            f"window={self._window.start}..{self._window.end}, "
            f"n_observations={self.n_observations}, sealed)"
        )


def score(
    holdout: SealedHoldout | None,
    *,
    revealed_at: datetime,
    min_observations: int = 20,
) -> CheckResult:
    """Report 02 §5.E item 2: positive net-of-cost return in an unlooked window.

    *min_observations* guards the degenerate case of a nominally long window
    holding three data points — a quarterly-sampled quarter. It is deliberately
    lower than the DSR's floor: this check asks whether the sum of the window
    is positive, which needs far less sample than asking whether a Sharpe is
    distinguishable from noise.
    """
    if holdout is None:
        return unknown(
            CHECK,
            "no holdout was supplied; a forward window that does not exist "
            "cannot be positive in it",
        )

    window = holdout.window
    evidence = {
        "window_start": window.start,
        "window_end": window.end,
        "in_sample_end": window.in_sample_end,
        "span_days": window.span_days,
        "required_days": window.required_days,
        "holding_period_days": window.holding_period_days,
        "frequency": window.frequency,
        "net_of_costs": window.net_of_costs,
        "cost_model": window.cost_model,
        "n_observations": holdout.n_observations,
    }

    earlier = holdout.prior_reveals()
    if earlier:
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                f"the window was already unsealed {len(earlier)} time(s), "
                f"first at {earlier[0].revealed_at.isoformat()} for "
                f"{earlier[0].reason!r}; whatever it shows now, it is no "
                "longer a window that was not looked at"
            ),
            evidence=evidence | {
                "prior_reveals": len(earlier),
                "first_reveal_at": earlier[0].revealed_at.isoformat(),
                "first_reveal_reason": earlier[0].reason,
            },
        )

    if window.start <= window.in_sample_end:
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                f"the window opens {window.start}, on or before the last "
                f"in-sample day {window.in_sample_end}; it overlaps the data "
                "the strategy was fitted on and is not forward"
            ),
            evidence=evidence,
        )

    if not window.net_of_costs:
        return unknown(
            CHECK,
            "the window's returns are not attested net of costs; report 02 "
            "budgets 3-6% round-trip friction, which is larger than most of "
            "the edges this bar is meant to screen",
            **evidence,
        )

    if window.span_days < window.required_days:
        return unknown(
            CHECK,
            f"the window spans {window.span_days} days against a required "
            f"{window.required_days} (max of 60 and 3x the "
            f"{window.holding_period_days}-day holding period); too short to "
            "answer the question, which is not the same as answering it no",
            **evidence,
        )

    if holdout.n_observations < min_observations:
        return unknown(
            CHECK,
            f"the window holds {holdout.n_observations} return observations "
            f"against a required {min_observations}; a long window sampled "
            "this thinly is a short window wearing long dates",
            **evidence,
        )

    returns = holdout.reveal(
        reason="scored by hedge_fund.validation.holdout.score",
        revealed_at=revealed_at,
    )
    # Compounded, not summed: the check is whether a book run through this
    # window ends above where it started, and summing per-period returns
    # answers a slightly different and slightly more flattering question.
    growth = 1.0
    for r in returns:
        growth *= 1.0 + r
    total = growth - 1.0
    evidence = evidence | {
        "total_return": total,
        "revealed_at": revealed_at.isoformat(),
    }

    if total > 0:
        return CheckResult(
            check=CHECK,
            verdict=Verdict.PASS,
            reason=(
                f"net-of-cost return {total:.4%} over {window.span_days} "
                f"sealed days ({holdout.n_observations} observations, "
                f"{window.frequency}), first look"
            ),
            evidence=evidence,
        )
    return CheckResult(
        check=CHECK,
        verdict=Verdict.FAIL,
        reason=(
            f"net-of-cost return {total:.4%} over {window.span_days} sealed "
            "days is not positive"
        ),
        evidence=evidence,
    )
