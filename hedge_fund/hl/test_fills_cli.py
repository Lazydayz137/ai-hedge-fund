"""fills_cli.py tests -- argument validation that keeps a bad --delay from
reaching time.sleep() mid-backfill, and the exit-code contract a scheduler
depends on."""

from __future__ import annotations

import argparse

import pytest

from hedge_fund.hl import fills_cli
from hedge_fund.hl.fills_cli import _non_negative_float
from hedge_fund.hl.models import FillFetchResult


def test_negative_delay_rejected():
    with pytest.raises(argparse.ArgumentTypeError):
        _non_negative_float("-1")


def test_zero_and_positive_delay_accepted():
    assert _non_negative_float("0") == 0.0
    assert _non_negative_float("2.5") == 2.5


def _result(status: str) -> FillFetchResult:
    return FillFetchResult(builder="0xbuilder", date="2026-09-01", status=status)


def test_a_failed_day_exits_non_zero_after_finishing_the_whole_backfill(monkeypatch):
    """A failure anywhere in a --backfill range must not cut the run short
    (every day is still attempted and its result printed) but must still
    signal the scheduler via a non-zero exit, consistent with cli.py."""
    monkeypatch.setattr(fills_cli, "load_builders", lambda: ["0xbuilder"])
    outcomes = iter(["new", "failed", "new"])
    calls = []

    def fake_collect(builder, day):
        calls.append(day)
        return _result(next(outcomes))

    monkeypatch.setattr(fills_cli, "collect_fills", fake_collect)
    monkeypatch.setattr(
        "sys.argv",
        ["hl-collect-fills", "--backfill", "2026-09-01", "2026-09-03", "--delay", "0"],
    )

    with pytest.raises(SystemExit) as exc_info:
        fills_cli.main()

    assert exc_info.value.code == 1
    assert len(calls) == 3  # every day was attempted, not stopped at the first failure


def test_restated_day_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(fills_cli, "load_builders", lambda: ["0xbuilder"])
    monkeypatch.setattr(fills_cli, "collect_fills", lambda builder, day: _result("restated"))
    monkeypatch.setattr(
        "sys.argv",
        ["hl-collect-fills", "--date", "2026-09-01", "--delay", "0"],
    )

    fills_cli.main()  # must not raise


def test_a_clean_run_exits_zero(monkeypatch):
    monkeypatch.setattr(fills_cli, "load_builders", lambda: ["0xbuilder"])
    monkeypatch.setattr(fills_cli, "collect_fills", lambda builder, day: _result("new"))
    monkeypatch.setattr(
        "sys.argv",
        ["hl-collect-fills", "--date", "2026-09-01", "--delay", "0"],
    )

    fills_cli.main()  # must not raise
