"""CycleRecord schema-compatibility tests.

A receipt is the only record of a fund's book. It is read back by builds that
postdate it, so these pin the property that matters more than any field:
an old receipt still loads.
"""

import json

import pytest
from pydantic import ValidationError

from hedge_fund.fund.spec import AuditFundSpec, FundSpec
from hedge_fund.pipeline.models import CycleRecord

_SPEC = {
    "name": "test",
    "strategies": [{"name": "value", "models": [{"name": "buffett"}]}],
    "risk": {"max_position_pct": 0.25, "max_gross_exposure": 1.0},
}


def _record(**overrides) -> dict:
    """A minimal but complete CycleRecord payload, as JSON-shaped dicts."""
    payload = {
        "fund": "test",
        "as_of": "2024-06-03",
        "spec": dict(_SPEC),
        "universe": ["AAPL"],
        "marks": {"AAPL": 200.0},
        "skipped": [],
        "strategies": [],
        "target_weights": {"AAPL": 0.5},
        "clamps": [],
        "final_weights": {"AAPL": 0.25},
        "equity_before": 100_000.0,
        "cash_before": 100_000.0,
        "orders": [],
        "fills": [],
        "positions": {"AAPL": 125},
        "cash": 75_000.0,
        "nav": 100_000.0,
    }
    payload.update(overrides)
    return payload


def test_legacy_universe_key_in_embedded_spec_still_loads():
    """The regression this file exists for: mandates once carried a `universe`
    key, `load_spec` pops it, and receipts written back then still embed it.
    Under the strict mandate model that receipt is unreadable and the fund
    silently restarts at mandate capital with no book."""
    legacy = _record(spec={**_SPEC, "universe": ["AAPL", "MSFT"]})

    record = CycleRecord.model_validate_json(json.dumps(legacy))

    assert record.spec.name == "test"
    assert record.cash == 75_000.0
    # The dropped key is preserved, not discarded: the audit copy must still
    # say what the old mandate said.
    assert record.spec.model_extra["universe"] == ["AAPL", "MSFT"]


def test_strict_spec_would_reject_what_the_audit_copy_accepts():
    """Pins WHY the audit copy exists — FundSpec itself must stay strict, so a
    YAML typo keeps failing loud at load time."""
    with pytest.raises(ValidationError):
        FundSpec(**{**_SPEC, "universe": ["AAPL"]})

    assert AuditFundSpec(**{**_SPEC, "universe": ["AAPL"]}).name == "test"


def test_unknown_field_added_to_a_future_mandate_still_loads():
    """Forward direction too: a receipt written by a LATER build, carrying a
    mandate field this build has never heard of, is still readable."""
    forward = _record(spec={**_SPEC, "sleeve_cap_pct": 0.4})

    record = CycleRecord.model_validate_json(json.dumps(forward))

    assert record.spec.model_extra["sleeve_cap_pct"] == 0.4


def test_schema_version_defaults_to_one_on_receipts_that_predate_it():
    """Receipts written before the field existed are version 1 — that is what
    they are, so the default must not be a sentinel or a raise."""
    assert CycleRecord.model_validate_json(json.dumps(_record())).schema_version == 1
    assert json.loads(
        CycleRecord.model_validate(_record()).model_dump_json()
    )["schema_version"] == 1


def test_audit_copy_round_trips_through_json():
    """Serialize -> parse -> serialize is stable, extras included; a resume must
    not quietly rewrite the mandate it is resuming."""
    original = CycleRecord.model_validate(
        _record(spec={**_SPEC, "universe": ["AAPL"]})
    )
    again = CycleRecord.model_validate_json(original.model_dump_json())
    assert again == original
    assert again.model_dump_json() == original.model_dump_json()
