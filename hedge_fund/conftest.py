"""Load .env for v2 tests so FINANCIAL_DATASETS_API_KEY is available."""

import pytest
from dotenv import load_dotenv

from hedge_fund import paths

load_dotenv()


@pytest.fixture(autouse=True)
def _isolate_archive_dir(tmp_path, monkeypatch):
    """Point the archive dir at a scratch dir for every test.

    Without this, any test that saves a Hyperliquid snapshot would write
    into the user's own ~/.hedge-fund/archive.
    """
    monkeypatch.setattr(paths, "ARCHIVE_DIR", tmp_path / "archive")
