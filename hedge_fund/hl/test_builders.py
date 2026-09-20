"""builders.py -- loads the config data file, not hardcoded addresses."""

from __future__ import annotations

from hedge_fund.hl.builders import load_builders


def test_default_config_has_two_lowercased_addresses():
    builders = load_builders()
    assert builders == [
        "0xb838e4d1c8bcf71fa8e63299d5aa3258c83d6adb",
        "0x2a2b6b093a9813fbd8cddae800c3d17d46460d17",
    ]


def test_custom_config_path(tmp_path):
    config = tmp_path / "custom.json"
    config.write_text('[{"address": "0xABCDEF", "label": "x"}]', encoding="utf-8")
    assert load_builders(config) == ["0xabcdef"]
