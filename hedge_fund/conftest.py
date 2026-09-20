"""Load .env for v2 tests so FINANCIAL_DATASETS_API_KEY is available."""

import builtins
import io
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from hedge_fund import paths

load_dotenv()

# One fixture per archive rather than one that redirects them all: each is
# owned by the module that writes to it, and a module that never writes
# should not be able to silently depend on someone else's redirect.


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


@pytest.fixture(autouse=True)
def _isolate_validation_dir(tmp_path, monkeypatch):
    """Point the validation store at a scratch dir for every test.

    Pre-registrations are published with a link that refuses to overwrite, so
    a test registering into the real store would burn that strategy id for the
    user permanently. The trial ledger is worse in the other direction: a test
    that appended trials would raise a real strategy's trial count, and the
    Deflated Sharpe threshold rises with it — the suite would quietly make the
    user's own results look worse and nothing would say so.
    """
    monkeypatch.setattr(paths, "VALIDATION_DIR", tmp_path / "validation")


@pytest.fixture(autouse=True)
def _no_writes_to_the_real_user_dir(monkeypatch):
    """Backstop: fail any test that CREATES something under ~/.hedge-fund.

    The fixtures above redirect the paths this package knows about today. This
    one catches what they cannot: a module that builds its own path, or a
    directory added to paths.py whose isolation fixture nobody wrote. That
    second case is the one worth guarding — it fails as a missing fixture here
    rather than as a user noticing their archive has test data in it.

    Scoped deliberately. Reads pass through, because a developer with a real
    .env should not fail the suite for having one. It guards the five calls
    that actually create files in this repo — open(), io.open(), os.open(),
    os.link(), os.mkdir() — and compares with abspath rather than resolve() so
    it costs no syscalls. A symlink out of a redirected tmp dir and back in
    would slip past it; this is a net for accidents, not an adversary.
    """
    real = str(Path.home() / ".hedge-fund")

    def forbidden(path: object) -> str | None:
        try:
            target = os.path.abspath(os.fspath(path))
        except TypeError:
            return None  # a file descriptor, already open, already guarded
        return target if target == real or target.startswith(real + os.sep) else None

    def guard(name, original, *, writes):
        def wrapper(file, *args, **kwargs):
            if writes(args, kwargs):
                target = forbidden(file)
                if target is not None:
                    raise AssertionError(
                        f"{name} tried to create {target} under the real "
                        f"{real}. Add an isolation fixture for whichever "
                        "paths.py entry that came from — do not delete this "
                        "check."
                    )
            return original(file, *args, **kwargs)
        return wrapper

    def mode_writes(args, kwargs):
        mode = kwargs.get("mode", args[0] if args else "r")
        return isinstance(mode, str) and any(f in mode for f in "wax+")

    def flags_write(args, kwargs):
        flags = kwargs.get("flags", args[0] if args else 0)
        return bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))

    monkeypatch.setattr(builtins, "open", guard("open", builtins.open, writes=mode_writes))
    monkeypatch.setattr(io, "open", guard("io.open", io.open, writes=mode_writes))
    monkeypatch.setattr(os, "open", guard("os.open", os.open, writes=flags_write))
    monkeypatch.setattr(os, "mkdir", guard("os.mkdir", os.mkdir, writes=lambda a, k: True))
    # os.link's new name is its SECOND argument, so it cannot share the
    # wrapper above — and it is the call the snapshot and validation stores
    # publish through, which makes it the one that most needs covering.
    real_link = os.link

    def guarded_link(src, dst, **kwargs):
        target = forbidden(dst)
        if target is not None:
            raise AssertionError(
                f"os.link tried to create {target} under the real {real}. "
                "Add an isolation fixture for whichever paths.py entry that "
                "came from — do not delete this check."
            )
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", guarded_link)
