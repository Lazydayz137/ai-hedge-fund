"""Execution-lag robustness: what the result looks like when you are late and small.

`SimBroker` fills 100% of every order at the order's own reference price — the
same as-of close that priced the decision — with zero default commission. That
is a market-on-close order that always fills at the print with no impact, and
every backtest number in this repo inherits it. Report 02 §5.D asks for the
opposite experiment: re-run with the signal acted on a bar (or five minutes)
late, and with fills capped at a fraction of the bar's real volume.

This module does not run that experiment — the backtester does. What it does is
insist the experiment happened, and report the *degradation* rather than a bare
verdict. "Survived" and "survived, with the Sharpe down 71%" are different
findings and a gate that collapses them is a gate that hides the interesting
one. `cap_fill` is the one piece of arithmetic here, small enough to be reused
by whatever runs the scenarios.

A run with zero lag and uncapped fills is the baseline, not a robustness test.
Supplying only that is an UNKNOWN: the protection would otherwise be present,
configured, and measuring nothing.
"""

from __future__ import annotations

import math
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from hedge_fund.validation.outcome import CheckResult, Verdict, unknown

CHECK = "execution_lag"


class FillCap(BaseModel):
    """How much of a desired order the bar's volume could actually absorb."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    desired: int
    filled: int
    unfilled: int
    bar_volume: float
    participation_cap: float


def cap_fill(
    desired_shares: int, bar_volume: float, participation_cap: float
) -> FillCap:
    """Cap an order at *participation_cap* of *bar_volume*.

    The unfilled remainder is returned rather than carried forward, because
    where it goes is the caller's policy and a fill model that silently
    completes the order tomorrow at tomorrow's price is how a capacity
    constraint turns back into free execution.

    Volume itself deserves a haircut before it reaches here: report 02 cites
    70%+ wash trading on unregulated venues. This function takes the number it
    is given and records it, so a receipt shows what depth was assumed.
    """
    if desired_shares < 0:
        raise ValueError(f"desired_shares={desired_shares} must be non-negative")
    if bar_volume < 0:
        raise ValueError(f"bar_volume={bar_volume} must be non-negative")
    if not 0 < participation_cap <= 1:
        raise ValueError(
            f"participation_cap={participation_cap} must be in (0, 1]; a cap "
            "of zero means no trading and a cap above one means trading "
            "volume that did not exist"
        )
    allowed = int(math.floor(bar_volume * participation_cap))
    filled = min(desired_shares, allowed)
    return FillCap(
        desired=desired_shares,
        filled=filled,
        unfilled=desired_shares - filled,
        bar_volume=bar_volume,
        participation_cap=participation_cap,
    )


class Scenario(BaseModel):
    """One re-scoring of the strategy under degraded execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1)
    lag_bars: int = Field(ge=0)
    participation_cap: float | None = Field(
        default=None,
        description="fraction of bar volume the fill model allowed; None "
        "means fills were uncapped",
    )
    sharpe: float = Field(description="per-observation, matching dsr.moments")
    total_return: float
    n_observations: int = Field(gt=0)

    @property
    def is_degraded(self) -> bool:
        """Whether this scenario actually degraded anything."""
        return self.lag_bars > 0 or (
            self.participation_cap is not None and self.participation_cap < 1.0
        )


def score(
    baseline: Scenario | None,
    scenarios: Sequence[Scenario] = (),
    *,
    max_sharpe_degradation: float | None = None,
) -> CheckResult:
    """Report 02 §5.E item 3: survives injected lag and volume-capped fills.

    PASS requires every degraded scenario to stay positive on both total return
    and Sharpe, and requires at least one scenario to inject lag and at least
    one to cap fills — report 02 asks for both, and a suite that ran only the
    lag half has not answered the capacity question.

    *max_sharpe_degradation* optionally also gates on the size of the fall (0.5
    = the Sharpe may lose half). Left None, degradation is measured and
    reported but does not decide: there is no published threshold, and
    inventing one here would dress a judgement call as a finding.
    """
    if baseline is None:
        return unknown(
            CHECK,
            "no baseline scenario; degradation is a comparison and there is "
            "nothing to compare against",
        )
    degraded = [s for s in scenarios if s.is_degraded]
    if not degraded:
        return unknown(
            CHECK,
            "no scenario injected lag or capped fills; a re-run at zero lag "
            "with uncapped fills is the baseline again, not a robustness test",
            baseline_sharpe=baseline.sharpe,
            n_scenarios=len(scenarios),
        )

    has_lag = any(s.lag_bars > 0 for s in degraded)
    has_cap = any(
        s.participation_cap is not None and s.participation_cap < 1.0
        for s in degraded
    )
    if not (has_lag and has_cap):
        missing = "a volume-capped fill model" if has_lag else "injected lag"
        return unknown(
            CHECK,
            f"no scenario supplied {missing}; report 02 §5.D asks for both, "
            "and half the experiment cannot report the other half's result",
            baseline_sharpe=baseline.sharpe,
            has_lag=has_lag,
            has_volume_cap=has_cap,
        )

    rows = []
    for s in degraded:
        # Relative to |baseline|, so a baseline Sharpe of -0.2 does not report
        # a fall to -0.4 as an improvement. A zero baseline has no proportional
        # degradation to report, and says so rather than dividing.
        if baseline.sharpe != 0:
            fall = (baseline.sharpe - s.sharpe) / abs(baseline.sharpe)
        else:
            fall = None
        rows.append({
            "label": s.label,
            "lag_bars": s.lag_bars,
            "participation_cap": s.participation_cap,
            "sharpe": s.sharpe,
            "total_return": s.total_return,
            "n_observations": s.n_observations,
            "sharpe_degradation": fall,
        })

    evidence = {
        "baseline_label": baseline.label,
        "baseline_sharpe": baseline.sharpe,
        "baseline_total_return": baseline.total_return,
        "baseline_n_observations": baseline.n_observations,
        "scenarios": rows,
        "max_sharpe_degradation": max_sharpe_degradation,
    }

    dead = [r for r in rows if r["total_return"] <= 0 or r["sharpe"] <= 0]
    if dead:
        names = ", ".join(str(r["label"]) for r in dead)
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                f"{len(dead)} of {len(rows)} degraded scenario(s) went "
                f"non-positive ({names}); the edge does not survive being "
                "late or size-capped"
            ),
            evidence=evidence,
        )

    if max_sharpe_degradation is not None:
        too_far = [
            r for r in rows
            if r["sharpe_degradation"] is not None
            and r["sharpe_degradation"] > max_sharpe_degradation
        ]
        if too_far:
            worst = max(r["sharpe_degradation"] for r in too_far)
            return CheckResult(
                check=CHECK,
                verdict=Verdict.FAIL,
                reason=(
                    f"worst Sharpe degradation {worst:.1%} exceeds the "
                    f"{max_sharpe_degradation:.1%} allowed, though every "
                    "scenario stayed positive"
                ),
                evidence=evidence,
            )

    falls = [r["sharpe_degradation"] for r in rows if r["sharpe_degradation"] is not None]
    worst_text = f"{max(falls):.1%}" if falls else "not measurable (baseline Sharpe is 0)"
    return CheckResult(
        check=CHECK,
        verdict=Verdict.PASS,
        reason=(
            f"all {len(rows)} degraded scenario(s) stayed positive; worst "
            f"Sharpe degradation {worst_text}"
        ),
        evidence=evidence,
    )
