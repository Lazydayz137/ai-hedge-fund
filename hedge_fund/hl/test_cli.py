"""cli.py tests -- the exit-code contract a scheduler depends on.

A partial pass (some scopes failed) must still archive what it collected
AND signal failure via exit code, so an unattended scheduler notices.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hedge_fund.hl import cli
from hedge_fund.hl.models import MarketSnapshot, ScopeFailure


def _snapshot(*, failures=()) -> MarketSnapshot:
    return MarketSnapshot(observed_at=datetime.now(timezone.utc), failures=list(failures))


def test_clean_pass_exits_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "collect_snapshot", lambda: _snapshot())
    monkeypatch.setattr(cli, "save_snapshot", lambda snap: tmp_path / "hl-x.json")
    cli.main()  # must not raise


def test_partial_pass_still_saves_and_exits_non_zero(monkeypatch, tmp_path):
    saved = []
    monkeypatch.setattr(
        cli, "collect_snapshot",
        lambda: _snapshot(failures=[ScopeFailure(scope="native", error="boom")]),
    )
    monkeypatch.setattr(cli, "save_snapshot", lambda snap: saved.append(snap) or tmp_path / "hl-x.json")

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert len(saved) == 1  # the partial snapshot was archived, not withheld
