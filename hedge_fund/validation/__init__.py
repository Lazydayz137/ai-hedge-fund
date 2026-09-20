"""Does the number mean anything? — report 02 §5.E as executable checks.

This package scores a strategy against the six-point bar in
`research/02-signal-evidence-review.md` §5.E, and it is built around one rule:

    A check that cannot run returns UNKNOWN. Never PASS.

That rule matters more than any formula in here. The failure this project keeps
hitting is not a wrong statistic, it is a protection that is present but not in
force — a validation gate that exists, is wired in, runs, and certifies
nothing, because the thing it needed was missing and missing read as fine. So
the overall verdict is PASS only when every check is PASS, UNKNOWN anywhere
makes the whole verdict UNKNOWN, and a caller who supplies nothing gets six
UNKNOWNs rather than a clean sweep.

Three other rules follow from it:

  * No number without its provenance. Every CheckResult carries an `evidence`
    dict of what it was computed from — sample size, trial count, window
    bounds, which moment estimator — so a reader can tell a real result from a
    degenerate one without rerunning it.
  * Refuse degenerate inputs loudly. A Deflated Sharpe on twelve observations,
    a holdout of three days, a universe of one instrument: each raises
    DegenerateInput or returns UNKNOWN with a reason string. None of them
    returns a confident float.
  * Deterministic. Same inputs, same verdict, and no wall-clock read anywhere
    inside scoring — every timestamp is an argument.

The modules are independently testable and independently callable:

  outcome      Verdict, CheckResult, the precedence rule
  dsr          Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014)
  registry     the pre-registration store and the persistent trial ledger
  holdout      the sealed forward window and the record that it was opened
  execution    lag and volume-capped-fill robustness, reported as degradation
  universe     survivorship, where the failure mode is silence
  papertrade   intended vs achieved fill over >= 30 live days
  gate         the five checks composed into the verdict of item 6

Pure library. No network, no LLM, no writes outside the store under
`paths.VALIDATION_DIR`. `backtesting/` can call it and so can a CI gate.

Not here, and named so that their absence is not mistaken for coverage. CPCV
and PBO — which the stub this replaced promised — are not implemented; they
partition in-sample history, which is a different question from the forward
window item 2 asks for, and report 06 notes that a deliberately leaky oracle at
Sharpe 35 passes both of them cleanly. Neither is a substitute for the holdout,
and neither would have changed the verdict below. Leakage detection generally
is out of scope: nothing in here can tell that a model was trained on the
window it is being scored over.

It gates nothing today. Wiring it into the engine, the TUI or CI is a separate
decision, and one worth making deliberately: on the current system it returns
UNKNOWN, which is the honest answer and also a blocking one.
"""

from hedge_fund.validation.dsr import (
    DeflatedSharpe,
    ReturnMoments,
    deflated_sharpe_ratio,
    expected_maximum_sharpe,
    moments,
    probabilistic_sharpe_ratio,
)
from hedge_fund.validation.execution import FillCap, Scenario, cap_fill
from hedge_fund.validation.gate import (
    ValidationReport,
    evaluate,
    returns_from_nav,
    score_deflated_sharpe,
    score_preregistration,
)
from hedge_fund.validation.holdout import HoldoutWindow, SealedHoldout
from hedge_fund.validation.outcome import (
    CheckResult,
    DegenerateInput,
    Verdict,
    combine,
)
from hedge_fund.validation.papertrade import PaperFill, PaperTradeRecord
from hedge_fund.validation.registry import (
    AlreadyRegistered,
    NotRegistered,
    Preregistration,
    Trial,
    record_trial,
    register,
    trial_count,
    trial_sharpe_variance,
)
from hedge_fund.validation.universe import Instrument, UniverseManifest

__all__ = [
    "AlreadyRegistered",
    "CheckResult",
    "DeflatedSharpe",
    "DegenerateInput",
    "FillCap",
    "HoldoutWindow",
    "Instrument",
    "NotRegistered",
    "PaperFill",
    "PaperTradeRecord",
    "Preregistration",
    "ReturnMoments",
    "Scenario",
    "SealedHoldout",
    "Trial",
    "UniverseManifest",
    "ValidationReport",
    "Verdict",
    "cap_fill",
    "combine",
    "deflated_sharpe_ratio",
    "evaluate",
    "expected_maximum_sharpe",
    "moments",
    "probabilistic_sharpe_ratio",
    "record_trial",
    "register",
    "returns_from_nav",
    "score_deflated_sharpe",
    "score_preregistration",
    "trial_count",
    "trial_sharpe_variance",
]
