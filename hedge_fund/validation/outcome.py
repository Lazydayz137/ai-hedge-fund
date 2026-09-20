"""Verdicts, and the rule that keeps a missing measurement from reading as a pass.

The failure mode this package exists to prevent is not a wrong number. It is a
protection that is *present but not in force*: a check that could not run,
reported as if it had run and been satisfied. So there are three verdicts, not
two, and the third one is load-bearing.

Precedence, when the checks disagree: UNKNOWN beats FAIL beats PASS.

That ordering surprises people, so the reason is worth stating. A FAIL is a
measurement: the strategy was scored and did not clear the bar. An UNKNOWN is
the absence of one. If any check could not run, the suite did not measure the
strategy, and reporting FAIL would claim a verdict nobody is entitled to — the
same overclaim as reporting PASS, pointed the other way. Neither UNKNOWN nor
FAIL permits risking money, and every individual CheckResult is kept in the
report, so nothing is hidden by the precedence: the FAIL is still right there,
named, next to the reason the suite as a whole could not conclude.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field


class Verdict(str, Enum):
    """What a check, or a whole suite, concluded."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


# Higher wins when combining. Not alphabetical, not declaration order: this is
# the precedence rule from the module docstring, written once so no caller can
# re-derive it slightly differently.
_PRECEDENCE = {Verdict.PASS: 0, Verdict.FAIL: 1, Verdict.UNKNOWN: 2}


class DegenerateInput(ValueError):
    """Input that cannot support the number the caller asked for.

    Raised by the arithmetic (a Sharpe on twelve observations, a holdout of
    three days) rather than returned, because a function whose whole output is
    one float has nowhere honest to put "I declined". The checks that wrap that
    arithmetic catch it and turn it into an UNKNOWN carrying the reason string,
    which is how the refusal survives all the way to the report.
    """


class CheckResult(BaseModel):
    """One check's conclusion, with what it concluded from.

    `evidence` is not decoration and is not optional in spirit: a Sharpe with
    no sample size, a trial count with no ledger behind it, a holdout verdict
    with no window bounds are all numbers a reader cannot tell apart from a
    degenerate one. Every check here populates it, and a reader who wants to
    know whether a PASS is real reads this dict, not the verdict.

    `reason` is always a sentence, on every verdict including PASS. "Why did
    this pass" is as much an audit question as "why did this fail".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    check: str = Field(description="stable id, e.g. 'deflated_sharpe'")
    verdict: Verdict
    reason: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


def combine(verdicts: Iterable[Verdict]) -> Verdict:
    """Fold check verdicts into the suite's verdict.

    Empty input is UNKNOWN, not PASS. A suite that ran no checks has measured
    nothing, and "all zero of my checks passed" is the purest form of the
    failure this package is about.
    """
    worst = Verdict.UNKNOWN
    seen = False
    for verdict in verdicts:
        if not seen:
            worst = verdict
            seen = True
        elif _PRECEDENCE[verdict] > _PRECEDENCE[worst]:
            worst = verdict
    return worst if seen else Verdict.UNKNOWN


def unknown(check: str, reason: str, **evidence: Any) -> CheckResult:
    """An UNKNOWN with its reason — the shape every check reaches for most."""
    return CheckResult(
        check=check, verdict=Verdict.UNKNOWN, reason=reason, evidence=evidence
    )
