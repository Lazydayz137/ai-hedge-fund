"""fills_cli.py tests -- argument validation that keeps a bad --delay from
reaching time.sleep() mid-backfill."""

from __future__ import annotations

import argparse

import pytest

from hedge_fund.hl.fills_cli import _non_negative_float


def test_negative_delay_rejected():
    with pytest.raises(argparse.ArgumentTypeError):
        _non_negative_float("-1")


def test_zero_and_positive_delay_accepted():
    assert _non_negative_float("0") == 0.0
    assert _non_negative_float("2.5") == 2.5
