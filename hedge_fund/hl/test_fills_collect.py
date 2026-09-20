"""collect_fills tests -- fixtures only, no network. fetch_raw is monkeypatched
so every outcome (new/unchanged/restated/failed) is exercised deterministically.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import lz4.frame

from hedge_fund.hl.fills_client import FillDownloadError
from hedge_fund.hl.fills_collect import collect_fills

DAY = date(2026, 9, 18)
BUILDER = "0xb838e4d1c8bcf71fa8e63299d5aa3258c83d6adb"
FIXTURE = (Path(__file__).parent / "fixtures" / "builder_fill_sample.csv.lz4").read_bytes()

TARGET = "hedge_fund.hl.fills_collect.fetch_raw"


def test_success_archives_and_reports_new(monkeypatch):
    monkeypatch.setattr(TARGET, lambda addr, day, **kw: (200, FIXTURE))
    result = collect_fills(BUILDER, DAY)
    assert result.status == "new"
    assert result.path is not None
    assert Path(result.path).exists()


def test_refetch_same_content_reports_unchanged(monkeypatch):
    monkeypatch.setattr(TARGET, lambda addr, day, **kw: (200, FIXTURE))
    collect_fills(BUILDER, DAY)
    result = collect_fills(BUILDER, DAY)
    assert result.status == "unchanged"
    assert result.path is None


def test_restated_content_reports_restated(monkeypatch):
    monkeypatch.setattr(TARGET, lambda addr, day, **kw: (200, FIXTURE))
    collect_fills(BUILDER, DAY)

    restated = lz4.frame.compress(
        b"time,user,coin,side,px,sz,crossed,special_trade_type,tif,is_trigger,"
        b"counterparty,closed_pnl,twap_id,builder_fee\n"
    )
    monkeypatch.setattr(TARGET, lambda addr, day, **kw: (200, restated))
    result = collect_fills(BUILDER, DAY)
    assert result.status == "restated"
    assert result.path is not None
    assert result.detail


def test_403_reports_failed_and_writes_nothing(monkeypatch):
    monkeypatch.setattr(TARGET, lambda addr, day, **kw: (403, b"denied"))
    result = collect_fills(BUILDER, DAY)
    assert result.status == "failed"
    assert result.path is None
    assert "403" in result.detail


def test_network_error_reports_failed(monkeypatch):
    def _raise(addr, day, **kw):
        raise FillDownloadError("boom")

    monkeypatch.setattr(TARGET, _raise)
    result = collect_fills(BUILDER, DAY)
    assert result.status == "failed"
    assert result.path is None
    assert "boom" in result.detail
