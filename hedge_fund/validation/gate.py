"""The gate: report 02 §5.E, composed, with UNKNOWN as a first-class answer.

The six items of the bar map onto this module as five checks and the verdict
that item 6 describes:

  1. pre-registered, trial count logged   -> `score_preregistration`
     Deflated Sharpe at that trial count  -> `score_deflated_sharpe`
  2. unlooked-at forward window           -> `holdout.score`
  3. injected lag + volume-capped fills   -> `execution.score`
  4. survivorship-free universe           -> `universe.score`
  5. >= 30 days paper-traded              -> `papertrade.score`
  6. only then, money                     -> `ValidationReport.permits_risk`

Every argument to `evaluate` is optional and every one of them defaults to
None, which yields a report of UNKNOWNs and an overall UNKNOWN. That is the
correct answer for a strategy nobody has validated, and it is deliberately the
*easiest* answer to get: a caller who wires up nothing gets "I cannot tell",
never "fine".

Nothing here reads the wall clock, opens a socket, or calls a model. The only
writes are into the validation store `registry.py` defines — the trial ledger
and the record of holdout reveals — and both happen because recording them is
what the check is checking.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from hedge_fund.validation import execution, holdout, papertrade, registry, universe
from hedge_fund.validation.dsr import (
    MIN_OBSERVATIONS,
    deflated_sharpe_ratio,
)
from hedge_fund.validation.outcome import (
    CheckResult,
    DegenerateInput,
    Verdict,
    combine,
    unknown,
)

PREREGISTRATION = "preregistration"
DEFLATED_SHARPE = "deflated_sharpe"

# The default confidence the Deflated Sharpe must clear.
#
# Report 02 words item 1 as "Deflated Sharpe > 0". Taken literally that is
# vacuous: the DSR is a probability, so every strategy with any track at all
# scores above zero and the gate passes everything. The intended reading is the
# paper's — the deflated statistic clears its threshold — so this asks for two
# things: the observed Sharpe above the false-strategy threshold, and the
# probability of that being real at or above this level. A protection that is
# present but not in force is the failure this whole package is about, and a
# literal ">" against zero would have been one.
DEFAULT_CONFIDENCE = 0.95


class ValidationReport(BaseModel):
    """Every check's conclusion, and the one verdict they fold into."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str
    verdict: Verdict
    checks: list[CheckResult] = Field(default_factory=list)

    @property
    def permits_risk(self) -> bool:
        """Report 02 §5.E item 6. True only on a clean sweep."""
        return self.verdict is Verdict.PASS

    def by_check(self, name: str) -> CheckResult | None:
        for result in self.checks:
            if result.check == name:
                return result
        return None

    def summary(self) -> str:
        """One line per check, for a terminal or a CI log."""
        lines = [f"{self.strategy_id}: {self.verdict.value}"]
        for result in self.checks:
            lines.append(f"  {result.verdict.value:<7} {result.check}: {result.reason}")
        return "\n".join(lines)


def returns_from_nav(capital: float, nav: Sequence[float]) -> list[float]:
    """Per-period returns from a NAV curve that starts at *capital*.

    The starting capital is prepended so the first cycle's move counts, which
    matches how `backtesting/fund.py` builds its own curve. Kept here rather
    than imported from there so this package stays callable from a CI gate
    that has no backtester in scope.
    """
    if capital <= 0:
        raise ValueError(f"capital={capital} must be positive")
    curve = [float(capital), *(float(v) for v in nav)]
    out = []
    for previous, current in zip(curve, curve[1:]):
        if previous <= 0:
            raise DegenerateInput(
                "NAV reached zero or below; period returns are undefined past "
                "a wiped book and a curve that continues past one is fiction"
            )
        out.append(current / previous - 1.0)
    return out


def score_preregistration(strategy_id: str) -> CheckResult:
    """Report 02 §5.E item 1, first half: declared first, trials counted.

    A missing declaration is a FAIL, not an UNKNOWN. The store was consulted
    and it has no record — that is a measurement, and its answer is no.
    """
    try:
        registered = registry.is_registered(strategy_id)
    except registry.BadStrategyId as exc:
        return unknown(PREREGISTRATION, str(exc), strategy_id=strategy_id)

    if not registered:
        return CheckResult(
            check=PREREGISTRATION,
            verdict=Verdict.FAIL,
            reason=(
                f"{strategy_id} has no pre-registration in the validation "
                "store; a hypothesis written after the result is not a "
                "hypothesis, and without one the trial count has nothing to "
                "attach to"
            ),
            evidence={"strategy_id": strategy_id, "registered": False},
        )

    prereg = registry.registration(strategy_id)
    logged = registry.trials(strategy_id)
    variance = registry.trial_sharpe_variance(strategy_id)
    evidence = {
        "strategy_id": strategy_id,
        "registered": True,
        "declared_at": prereg.declared_at.isoformat(),
        "hypothesis": prereg.hypothesis,
        "success_threshold": prereg.success_threshold,
        "horizon_days": prereg.horizon_days,
        "universe_size": len(prereg.universe),
        "n_trials": len(logged),
        "trial_sharpe_variance": variance,
        "n_abandoned": sum(1 for t in logged if t.abandoned),
    }

    if not logged:
        return CheckResult(
            check=PREREGISTRATION,
            verdict=Verdict.FAIL,
            reason=(
                f"{strategy_id} is declared but has zero logged trials. Either "
                "it has never been evaluated, or something evaluated it "
                "without recording the trial — and an unrecorded trial lowers "
                "the count that every Deflated Sharpe here is deflated by"
            ),
            evidence=evidence,
        )

    first = min(t.evaluated_at for t in logged)
    if prereg.declared_at > first:
        return CheckResult(
            check=PREREGISTRATION,
            verdict=Verdict.FAIL,
            reason=(
                f"declared {prereg.declared_at.isoformat()}, but the earliest "
                f"logged trial is {first.isoformat()}; the declaration came "
                "after the strategy had already been tested"
            ),
            evidence=evidence | {"first_trial_at": first.isoformat()},
        )

    return CheckResult(
        check=PREREGISTRATION,
        verdict=Verdict.PASS,
        reason=(
            f"declared {prereg.declared_at.date().isoformat()} before the "
            f"first of {len(logged)} logged trial(s); abandon threshold on "
            "record"
        ),
        evidence=evidence | {"first_trial_at": first.isoformat()},
    )


def score_deflated_sharpe(
    strategy_id: str,
    returns: Sequence[float] | None,
    *,
    frequency: str,
    confidence: float = DEFAULT_CONFIDENCE,
    n_trials: int | None = None,
    trial_sharpe_variance: float | None = None,
    min_observations: int = MIN_OBSERVATIONS,
) -> CheckResult:
    """Report 02 §5.E item 1, second half: DSR at the *logged* trial count.

    `n_trials` and `trial_sharpe_variance` default to whatever the store holds
    for this strategy. Passing them explicitly is for callers scoring a track
    that does not live in the store; passing a trial count lower than the
    logged one is how a deflation gets quietly undone, so the evidence records
    both the value used and the value on file.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence={confidence} must be in (0, 1)")
    if returns is None:
        return unknown(
            DEFLATED_SHARPE,
            "no return series; there is no Sharpe to deflate",
            strategy_id=strategy_id,
        )

    try:
        logged_trials = registry.trial_count(strategy_id)
        logged_variance = registry.trial_sharpe_variance(strategy_id)
    except registry.BadStrategyId as exc:
        return unknown(DEFLATED_SHARPE, str(exc), strategy_id=strategy_id)

    trials = logged_trials if n_trials is None else n_trials
    variance = logged_variance if trial_sharpe_variance is None else trial_sharpe_variance
    evidence = {
        "strategy_id": strategy_id,
        "frequency": frequency,
        "confidence": confidence,
        "n_trials_used": trials,
        "n_trials_logged": logged_trials,
        "trial_sharpe_variance_used": variance,
        "trial_sharpe_variance_logged": logged_variance,
        "n_returns_supplied": len(returns),
    }

    if trials < 1:
        return unknown(
            DEFLATED_SHARPE,
            f"{strategy_id} has no logged trials, so there is no trial count "
            "to deflate at. Report 02: if you do not know your trial count, "
            "your p-value does not exist",
            **evidence,
        )
    if trials > 1 and variance is None:
        return unknown(
            DEFLATED_SHARPE,
            f"{trials} trials are logged but their Sharpe variance is "
            "unknown; the deflation is made of that variance and defaulting "
            "it to zero would deflate by nothing",
            **evidence,
        )

    try:
        result = deflated_sharpe_ratio(
            returns,
            frequency=frequency,
            n_trials=trials,
            trial_sharpe_variance=0.0 if variance is None else variance,
            min_observations=min_observations,
        )
    except DegenerateInput as exc:
        return unknown(DEFLATED_SHARPE, str(exc), **evidence)

    evidence = evidence | {
        "psr": result.psr,
        "observed_sharpe": result.observed_sharpe,
        "threshold_sharpe": result.threshold_sharpe,
        "n_observations": result.moments.n_observations,
        "skew": result.moments.skew,
        "kurtosis": result.moments.kurtosis,
        "stdev": result.moments.stdev,
        "moment_estimator": result.moments.estimator,
    }

    if trials < logged_trials:
        return CheckResult(
            check=DEFLATED_SHARPE,
            verdict=Verdict.FAIL,
            reason=(
                f"scored at {trials} trials while {logged_trials} are on "
                "record; deflating by fewer trials than were run is the "
                "selection bias this statistic exists to remove"
            ),
            evidence=evidence,
        )

    if result.observed_sharpe <= result.threshold_sharpe:
        return CheckResult(
            check=DEFLATED_SHARPE,
            verdict=Verdict.FAIL,
            reason=(
                f"observed Sharpe {result.observed_sharpe:.4f} "
                f"({frequency}, n={result.moments.n_observations}) is at or "
                f"below the {result.threshold_sharpe:.4f} a zero-skill "
                f"strategy reaches as best of {trials} trials"
            ),
            evidence=evidence,
        )
    if result.psr < confidence:
        return CheckResult(
            check=DEFLATED_SHARPE,
            verdict=Verdict.FAIL,
            reason=(
                f"deflated Sharpe {result.psr:.4f} is below the required "
                f"{confidence:.2f} at {trials} trials (observed "
                f"{result.observed_sharpe:.4f} vs threshold "
                f"{result.threshold_sharpe:.4f}, n="
                f"{result.moments.n_observations}, skew "
                f"{result.moments.skew:.3f}, kurtosis "
                f"{result.moments.kurtosis:.3f})"
            ),
            evidence=evidence,
        )

    return CheckResult(
        check=DEFLATED_SHARPE,
        verdict=Verdict.PASS,
        reason=(
            f"deflated Sharpe {result.psr:.4f} >= {confidence:.2f} at "
            f"{trials} logged trials (observed {result.observed_sharpe:.4f} "
            f"vs threshold {result.threshold_sharpe:.4f}, n="
            f"{result.moments.n_observations})"
        ),
        evidence=evidence,
    )


def evaluate(
    strategy_id: str,
    *,
    returns: Sequence[float] | None = None,
    frequency: str = "unspecified",
    sealed_holdout: holdout.SealedHoldout | None = None,
    revealed_at: datetime | None = None,
    execution_baseline: execution.Scenario | None = None,
    execution_scenarios: Sequence[execution.Scenario] = (),
    universe_manifest: universe.UniverseManifest | None = None,
    paper_record: papertrade.PaperTradeRecord | None = None,
    confidence: float = DEFAULT_CONFIDENCE,
    max_sharpe_degradation: float | None = None,
    min_instruments: int = universe.MIN_INSTRUMENTS,
    min_observations: int = MIN_OBSERVATIONS,
) -> ValidationReport:
    """Run the whole bar and fold it into one verdict.

    *revealed_at* is required only if a holdout is supplied, and is an argument
    rather than `datetime.now()` for the same reason every other timestamp here
    is: a verdict that changes with the hour it was computed cannot be
    re-derived from its own receipt.
    """
    checks = [
        score_preregistration(strategy_id),
        score_deflated_sharpe(
            strategy_id,
            returns,
            frequency=frequency,
            confidence=confidence,
            min_observations=min_observations,
        ),
    ]

    if sealed_holdout is not None and revealed_at is None:
        checks.append(unknown(
            holdout.CHECK,
            "a sealed holdout was supplied without a revealed_at timestamp; "
            "unsealing it without recording when would leave the store unable "
            "to say the window had been looked at",
        ))
    else:
        checks.append(holdout.score(
            sealed_holdout,
            # Only reached with a holdout present, where revealed_at is set.
            revealed_at=revealed_at or datetime.min,
        ))

    checks.append(execution.score(
        execution_baseline,
        execution_scenarios,
        max_sharpe_degradation=max_sharpe_degradation,
    ))
    checks.append(universe.score(universe_manifest, min_instruments=min_instruments))
    checks.append(papertrade.score(paper_record))

    return ValidationReport(
        strategy_id=strategy_id,
        verdict=combine(c.verdict for c in checks),
        checks=checks,
    )
