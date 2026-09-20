"""Load .env for v2 tests so FINANCIAL_DATASETS_API_KEY is available."""

import pytest
from dotenv import load_dotenv

from hedge_fund import paths

load_dotenv()


@pytest.fixture(autouse=True)
def _isolate_nansen_dir(tmp_path, monkeypatch):
    """Point the Nansen snapshot archive at a scratch dir for every test.

    Snapshots are written with open(..., "x") and are meant to be
    permanent. Without this, a test that collects a round would drop files
    into the user's own archive, where they would be indistinguishable
    from real observations and could never be safely deleted in bulk.
    """
    monkeypatch.setattr(paths, "NANSEN_DIR", tmp_path / "nansen-snapshots")
