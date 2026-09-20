"""Load .env for v2 tests so FINANCIAL_DATASETS_API_KEY is available."""

import pytest
from dotenv import load_dotenv

from hedge_fund import paths

load_dotenv()


@pytest.fixture(autouse=True)
def _isolate_snapshots_dir(tmp_path, monkeypatch):
    """Point the market-snapshot archive at a scratch dir for every test.

    The archive is append-only and never refetchable, so a test that wrote
    into the user's own would be adding rows to a permanent record that
    nothing can clean up afterwards.
    """
    monkeypatch.setattr(paths, "SNAPSHOTS_DIR", tmp_path / "market-snapshots")
