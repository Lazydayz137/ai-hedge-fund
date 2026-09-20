"""The precedence rule is the package's central claim; it gets its own tests."""

from __future__ import annotations

import pytest

from hedge_fund.validation.outcome import CheckResult, Verdict, combine, unknown


def test_all_pass_is_pass():
    assert combine([Verdict.PASS, Verdict.PASS]) is Verdict.PASS


def test_one_fail_sinks_a_sweep_of_passes():
    assert combine([Verdict.PASS, Verdict.FAIL, Verdict.PASS]) is Verdict.FAIL


def test_unknown_outranks_fail():
    # The surprising half of the rule: a suite that could not measure did not
    # measure, and FAIL would claim a verdict nobody is entitled to.
    assert combine([Verdict.FAIL, Verdict.UNKNOWN]) is Verdict.UNKNOWN
    assert combine([Verdict.UNKNOWN, Verdict.FAIL]) is Verdict.UNKNOWN


def test_a_single_unknown_among_passes_sinks_everything():
    assert combine([Verdict.PASS] * 5 + [Verdict.UNKNOWN]) is Verdict.UNKNOWN


def test_no_checks_is_unknown_not_pass():
    """Zero checks passing is not a clean sweep."""
    assert combine([]) is Verdict.UNKNOWN


def test_check_result_requires_a_reason():
    with pytest.raises(ValueError):
        CheckResult(check="x", verdict=Verdict.PASS, reason="")


def test_check_result_is_frozen():
    """A verdict that can be edited after the fact is not a receipt."""
    result = unknown("x", "because")
    with pytest.raises(ValueError):
        result.verdict = Verdict.PASS


def test_unknown_helper_carries_evidence():
    result = unknown("x", "because", n=3)
    assert result.verdict is Verdict.UNKNOWN
    assert result.evidence == {"n": 3}
