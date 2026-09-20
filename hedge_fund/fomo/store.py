"""The archive: one file per pass, and a cursor so the next pass resumes.

Same discipline as the Hyperliquid and Nansen archives, for the same reason —
a sponsored transaction is a historical observation, and a chain's history is
pruned by most endpoints, so a pass missed today may not be re-walkable later.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from hedge_fund import paths
from hedge_fund.fomo.models import CollectionResult, Cursor


class CorruptCursor(ValueError):
    """The cursor exists but cannot be read.

    Raised rather than swallowed: a resume that silently restarts from the
    newest signature would leave a hole in the middle of the archive and
    report success, which is the one outcome this package exists to prevent.
    """


def _archive_dir() -> Path:
    # Through the module on every call, never bound at import: the suite
    # monkeypatches paths.ARCHIVE_DIR, and a test must not be able to write
    # into a real archive just because this module cached the path once.
    return paths.ARCHIVE_DIR / "fomo"


def save_pass(result: CollectionResult) -> Path:
    """Write one pass where nothing can overwrite it, and say where.

    Serialized in full to a temporary file, fsynced, then published with
    os.link — which refuses to overwrite, where rename and replace would
    silently succeed. A pass interrupted mid-write leaves no file behind
    rather than a truncated one under a real name.
    """
    directory = _archive_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = result.observed_at.strftime("%Y%m%dT%H%M%SZ")

    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as writer:
            writer.write(result.model_dump_json(indent=2))
            writer.flush()
            os.fsync(writer.fileno())

        path = directory / f"fomo-{stamp}.json"
        suffix = 1
        while True:
            try:
                os.link(temporary, path)
                _sync_directory(directory)
                return path
            except FileExistsError:
                suffix += 1
                path = directory / f"fomo-{stamp}-{suffix}.json"
    finally:
        with suppress(OSError):
            os.unlink(temporary)


def _sync_directory(directory: Path) -> None:
    """Make a newly linked name durable, where the platform allows it.

    Guarded: opening a directory read-only is POSIX, and Windows raises.
    Skipping the sync there loses the guarantee, which is honest; raising
    would lose the pass, which is worse.
    """
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _cursor_path() -> Path:
    return _archive_dir() / "cursor.json"


def read_cursor() -> Cursor | None:
    """Where the last completed pass stopped, or None if there was none."""
    path = _cursor_path()
    if not path.exists():
        return None
    try:
        return Cursor.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CorruptCursor(f"{path} could not be read: {exc}") from exc


def write_cursor(cursor: Cursor) -> Path:
    """Move the cursor forward. The one file here that IS overwritten.

    Deliberately unlike the passes beside it: the cursor is not an
    observation, it is a bookmark, and keeping every bookmark a pass ever
    set would be noise that nothing reads. Written through a temporary file
    and os.replace so a crash mid-write cannot leave it half-parsed — losing
    the bookmark costs a re-walk, but a corrupt one raises on the next read
    rather than being mistaken for "never collected".
    """
    directory = _archive_dir()
    directory.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as writer:
            writer.write(cursor.model_dump_json(indent=2))
            writer.flush()
            os.fsync(writer.fileno())
        path = _cursor_path()
        os.replace(temporary, path)
        _sync_directory(directory)
        return path
    except BaseException:
        with suppress(OSError):
            os.unlink(temporary)
        raise


def read_as_of(when: datetime) -> CollectionResult | None:
    """The newest pass observed at or before *when*, or None if there is none.

    Ordered by each pass's own observed_at, never file mtime: a copy, an
    rsync or a backup restore rewrites mtime and would silently reorder the
    archive. Never falls forward to a later pass — that would hand a
    simulated date transactions from its own future.
    """
    directory = _archive_dir()
    if not directory.exists():
        return None

    best: tuple[datetime, Path] | None = None
    for path in directory.glob("fomo-*.json"):
        try:
            stamped = json.loads(path.read_text(encoding="utf-8"))["observed_at"]
            observed = datetime.fromisoformat(stamped)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if observed <= when and (best is None or observed > best[0]):
            best = (observed, path)

    if best is None:
        return None
    return CollectionResult.model_validate_json(best[1].read_text(encoding="utf-8"))
