"""Load .env for v2 tests so FINANCIAL_DATASETS_API_KEY is available."""

import pytest
from dotenv import load_dotenv

from hedge_fund import paths

load_dotenv()

# One fixture per archive rather than one that redirects them all: each is
# owned by the module that writes to it, and a module that never writes
# should not be able to silently depend on someone else's redirect.


@pytest.fixture(autouse=True)
def _isolate_user_dir(tmp_path, monkeypatch):
    """Point the fund directory at a scratch dir for every test.

    A run now saves a receipt and the next run resumes from the newest one.
    Without this, any test that runs a cycle would write into the user's own
    fund history, and the test after it would resume from that — making the
    suite both destructive and order-dependent.
    """
    monkeypatch.setattr(paths, "MANDATES_DIR", tmp_path / "mandates")


@pytest.fixture(autouse=True)
def _isolate_nansen_dir(tmp_path, monkeypatch):
    """Point the Nansen snapshot archive at a scratch dir for every test.

    Snapshots are written with open(..., "x") and are meant to be
    permanent. Without this, a test that collects a round would drop files
    into the user's own archive, where they would be indistinguishable
    from real observations and could never be safely deleted in bulk.
    """
    monkeypatch.setattr(paths, "NANSEN_DIR", tmp_path / "nansen-snapshots")


@pytest.fixture(autouse=True)
def _isolate_snapshots_dir(tmp_path, monkeypatch):
    """Point the market-snapshot archive at a scratch dir for every test.

    The archive is append-only and never refetchable, so a test that wrote
    into the user's own would be adding rows to a permanent record that
    nothing can clean up afterwards.
    """
    monkeypatch.setattr(paths, "SNAPSHOTS_DIR", tmp_path / "market-snapshots")
