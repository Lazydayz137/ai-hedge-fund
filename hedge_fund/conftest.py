"""Load .env for v2 tests so FINANCIAL_DATASETS_API_KEY is available."""

from pathlib import Path

import pytest
from dotenv import load_dotenv

from hedge_fund import paths

load_dotenv()

# One fixture per archive rather than one that redirects them all: each is
# owned by the module that writes to it, and a module that never writes
# should not be able to silently depend on someone else's redirect.


@pytest.fixture(autouse=True)
def _no_test_may_touch_the_real_user_dir(tmp_path, monkeypatch):
    """Fail any test that writes into ~/.hedge-fund, and say which one.

    The redirects below are the intended protection; this is the backstop
    for when one of them silently stops applying. That is not theoretical:
    a `monkeypatch.undo()` in a test reverts the autouse fixtures too,
    because pytest hands them all the same function-scoped instance — and
    it did, quietly, one snapshot per run into a real archive.

    These archives are append-only and can never be refetched, so a stray
    test file in one is indistinguishable from a real observation
    afterwards. Better to fail the suite than to let it write.
    """
    before = _user_dir_contents()
    yield
    added = _user_dir_contents() - before
    if added:
        raise AssertionError(
            "this test wrote into the real user directory: "
            + ", ".join(sorted(str(p) for p in added))
        )


def _user_dir_contents() -> set:
    """Every file under the real ~/.hedge-fund, or nothing if it has none."""
    root = Path.home() / ".hedge-fund"
    return set(root.rglob("*")) if root.exists() else set()


@pytest.fixture(autouse=True)
def _isolate_archive_dir(tmp_path, monkeypatch):
    """Point the archive dir at a scratch dir for every test.

    Without this, any test that saves a Hyperliquid snapshot would write
    into the user's own ~/.hedge-fund/archive.
    """
    monkeypatch.setattr(paths, "ARCHIVE_DIR", tmp_path / "archive")


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
