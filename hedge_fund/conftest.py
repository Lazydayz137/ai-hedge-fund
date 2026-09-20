"""Load .env for v2 tests so FINANCIAL_DATASETS_API_KEY is available."""

import pytest
from dotenv import load_dotenv

from hedge_fund import paths

load_dotenv()


@pytest.fixture(autouse=True)
def _isolate_user_dir(tmp_path, monkeypatch):
    """Point the fund directory at a scratch dir for every test.

    A run now saves a receipt and the next run resumes from the newest one.
    Without this, any test that runs a cycle would write into the user's own
    fund history, and the test after it would resume from that — making the
    suite both destructive and order-dependent.
    """
    monkeypatch.setattr(paths, "MANDATES_DIR", tmp_path / "mandates")
