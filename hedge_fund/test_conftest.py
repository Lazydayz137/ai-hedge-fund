"""The isolation fixtures, tested — a backstop nobody checks is not one.

Every assertion here deliberately targets a path under the real ~/.hedge-fund
that the guard must refuse. None of them can create it: if the guard is working
the call raises before touching the filesystem, and if it is not working this
file is the thing that says so.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hedge_fund import paths

_REAL = Path.home() / ".hedge-fund"
_TARGET = _REAL / "zz-conftest-guard-probe" / "probe.json"


def test_every_paths_directory_is_redirected(tmp_path):
    """A new entry in paths.py without an isolation fixture fails here."""
    redirected = {
        "MANDATES_DIR": paths.MANDATES_DIR,
        "NANSEN_DIR": paths.NANSEN_DIR,
        "ARCHIVE_DIR": paths.ARCHIVE_DIR,
        "VALIDATION_DIR": paths.VALIDATION_DIR,
    }
    for name, directory in redirected.items():
        assert not directory.is_relative_to(_REAL), name


def test_builtin_open_for_writing_is_refused():
    with pytest.raises(AssertionError, match="under the real"):
        open(_TARGET, "w")


def test_exclusive_creation_is_refused():
    with pytest.raises(AssertionError, match="under the real"):
        open(_TARGET, "x")


def test_path_write_text_is_refused():
    with pytest.raises(AssertionError, match="under the real"):
        _TARGET.write_text("{}")


def test_os_open_with_creat_is_refused():
    with pytest.raises(AssertionError, match="under the real"):
        os.open(_TARGET, os.O_WRONLY | os.O_CREAT)


def test_mkdir_is_refused():
    with pytest.raises(AssertionError, match="under the real"):
        (_REAL / "zz-conftest-guard-probe").mkdir()


def test_os_link_into_the_real_dir_is_refused(tmp_path):
    source = tmp_path / "source"
    source.write_text("{}")
    with pytest.raises(AssertionError, match="under the real"):
        os.link(source, _TARGET)


def test_reads_are_left_alone(tmp_path):
    """A developer with a real .env must not fail the suite for having one."""
    readable = tmp_path / "ok.txt"
    readable.write_text("fine")
    assert readable.read_text() == "fine"
    with pytest.raises(FileNotFoundError):
        open(_TARGET)


def test_the_probe_never_actually_appeared():
    assert not _TARGET.exists()
    assert not _TARGET.parent.exists()
