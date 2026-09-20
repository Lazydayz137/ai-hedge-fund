"""The pre-registration store: what was declared, and how many times it was tried.

Two records, and the second is the one that bites. A pre-registration says what
the strategy claimed *before* anybody ran it — hypothesis, universe, features,
horizon, abandon threshold — and is written with a link that refuses to
overwrite, so a mandate cannot be edited after the fact to match what the data
turned out to say. A trial is one evaluation of that strategy, appended
whenever the engine scores it; the count of trials is the N the Deflated Sharpe
deflates by, and it persists precisely so that abandoning a variant does not
un-try it.

Style is `hedge_fund/nansen/store.py`, deliberately and for the same reasons:
publish under a name that cannot be overwritten, order by the record's own
stamp and never by mtime, and raise on a record that does not parse rather than
skipping it. The divergence from `ledger.py`, which skips unreadable receipts,
is intentional — there the cost of a skip is one lost resume, here it is a
trial count that silently reads lower than the truth, which inflates every
Deflated Sharpe computed against it.

Nothing here reads the wall clock. Every timestamp is an argument, because a
verdict that depends on when it was computed is not a verdict you can re-derive
from a receipt.
"""

from __future__ import annotations

import os
import re
import tempfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from hedge_fund import paths

# Bumped when the shape of what gets written changes, so a reader can tell a
# record written by an older validator from one it can trust verbatim.
REGISTRY_VERSION = "1"

# Strategy ids become directory names. Anchored, no dots-only, no separators:
# an id is a key in a store, not a path, and "../../mandates" is not an id.
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class BadStrategyId(ValueError):
    """A strategy id that cannot safely be a directory name."""


class AlreadyRegistered(FileExistsError):
    """A pre-registration exists for this strategy id.

    Raised rather than overwritten: the whole value of the record is that it
    predates the result. A caller who genuinely has a new hypothesis has a new
    strategy — give it a new id and let the old declaration stand beside it.
    """


class NotRegistered(LookupError):
    """No pre-registration for this strategy id."""


class CorruptRecord(ValueError):
    """A file in the validation store did not parse."""


class Preregistration(BaseModel):
    """What the strategy claimed before it was tested.

    `declared_at` is supplied by the caller rather than stamped here. That
    looks like an invitation to lie, and it is — but the honest version of this
    record is not enforced by a clock the same process controls anyway. What
    the store can enforce is that the declaration cannot be *revised* once
    written, and that is what the exclusive-creation publish does.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str
    declared_at: datetime
    hypothesis: str = Field(min_length=1)
    universe: list[str] = Field(min_length=1)
    features: list[str] = Field(default_factory=list)
    horizon_days: int = Field(gt=0)
    success_threshold: str = Field(
        min_length=1,
        description="the number that would make this worth trading, and the "
        "one that would make it worth abandoning, written before the run",
    )
    spec_fingerprint: str | None = Field(
        default=None,
        description="hash of the mandate this declaration was made against, so "
        "a later spec edit is visible rather than inferred",
    )
    registry_version: str = REGISTRY_VERSION


class Trial(BaseModel):
    """One evaluation of one strategy.

    `sharpe` is per-observation and un-annualized, matching `dsr.moments`: the
    variance of these values across trials is what deflates the selected one,
    and mixing frequencies in that variance would quietly change the threshold.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str
    evaluated_at: datetime
    label: str = Field(min_length=1, description="which variant this was")
    sharpe: float
    frequency: str
    n_observations: int = Field(gt=0)
    config_fingerprint: str | None = None
    abandoned: bool = Field(
        default=False,
        description="a variant that was tried and dropped still counts; "
        "dropping it is the selection the deflation is correcting for",
    )
    registry_version: str = REGISTRY_VERSION


class Reveal(BaseModel):
    """One unsealing of a holdout window. Written by `holdout.py`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str
    revealed_at: datetime
    window_start: str
    window_end: str
    reason: str = Field(min_length=1)
    registry_version: str = REGISTRY_VERSION


def strategy_dir(strategy_id: str) -> Path:
    """Where one strategy's validation records live."""
    if not _ID.match(strategy_id):
        raise BadStrategyId(
            f"{strategy_id!r} is not a usable strategy id: letters, digits, "
            "dot, dash and underscore only, starting with a letter or digit"
        )
    # Looked up through the module, not bound at import: tests redirect it, and
    # nothing should be able to write into a real strategy's trial ledger by
    # accident.
    return paths.VALIDATION_DIR / strategy_id


def register(prereg: Preregistration) -> Path:
    """Write *prereg* where nothing can overwrite it, and say where."""
    directory = strategy_dir(prereg.strategy_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "preregistration.json"
    try:
        return _publish(directory, path, prereg.model_dump_json(indent=2))
    except FileExistsError as exc:
        raise AlreadyRegistered(
            f"{prereg.strategy_id} is already pre-registered at {path}; a "
            "declaration that can be rewritten after the result is not a "
            "declaration"
        ) from exc


def registration(strategy_id: str) -> Preregistration:
    """The strategy's declaration, or NotRegistered."""
    path = strategy_dir(strategy_id) / "preregistration.json"
    if not path.is_file():
        raise NotRegistered(f"{strategy_id} has no pre-registration at {path}")
    return _parse(path, Preregistration)


def is_registered(strategy_id: str) -> bool:
    """Whether a declaration exists, without parsing it."""
    return (strategy_dir(strategy_id) / "preregistration.json").is_file()


def record_trial(trial: Trial) -> Path:
    """Append *trial* to the strategy's ledger. Every evaluation calls this."""
    directory = strategy_dir(trial.strategy_id) / "trials"
    directory.mkdir(parents=True, exist_ok=True)
    return _publish(
        directory,
        directory / f"{_stamp(trial.evaluated_at)}.json",
        trial.model_dump_json(indent=2),
        unique=True,
    )


def trials(strategy_id: str) -> list[Trial]:
    """Every logged trial, oldest first by its own `evaluated_at`.

    Ordered by the record's stamp rather than by mtime: a copy, an rsync or a
    backup restore rewrites mtimes, and the trial ledger has to survive being
    moved between machines with its order intact.
    """
    directory = strategy_dir(strategy_id) / "trials"
    if not directory.is_dir():
        return []
    found = [_parse(path, Trial) for path in sorted(directory.glob("*.json"))]
    return sorted(found, key=lambda t: t.evaluated_at)


def trial_count(strategy_id: str) -> int:
    """How many times this strategy has been evaluated."""
    return len(trials(strategy_id))


def trial_sharpe_variance(strategy_id: str) -> float | None:
    """Variance of the logged trial Sharpes, or None below two trials.

    None rather than 0.0. The Deflated Sharpe's threshold is proportional to
    the square root of this, so handing back zero for "not enough trials to
    say" would deflate by nothing and read as a clean pass.
    """
    sharpes = [t.sharpe for t in trials(strategy_id)]
    if len(sharpes) < 2:
        return None
    return float(np.var(np.asarray(sharpes, dtype=float), ddof=1))


def record_reveal(reveal: Reveal) -> Path:
    """Write that a holdout was unsealed. Called by `holdout.reveal`."""
    directory = strategy_dir(reveal.strategy_id) / "reveals"
    directory.mkdir(parents=True, exist_ok=True)
    return _publish(
        directory,
        directory / f"{_stamp(reveal.revealed_at)}.json",
        reveal.model_dump_json(indent=2),
        unique=True,
    )


def reveals(strategy_id: str) -> list[Reveal]:
    """Every recorded unsealing, oldest first by its own `revealed_at`."""
    directory = strategy_dir(strategy_id) / "reveals"
    if not directory.is_dir():
        return []
    found = [_parse(path, Reveal) for path in sorted(directory.glob("*.json"))]
    return sorted(found, key=lambda r: r.revealed_at)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _stamp(when: datetime) -> str:
    """A sortable UTC filename stamp. Naive input is read as UTC."""
    aware = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%S%fZ")


def _parse(path: Path, model: type[BaseModel]) -> Any:
    """Read one record, or raise. Never skip."""
    try:
        return model.model_validate_json(path.read_text())
    except (OSError, ValueError) as exc:
        raise CorruptRecord(
            f"{path} did not parse as {model.__name__}: {exc}. Look at it and "
            "move it aside deliberately — skipping it would lower this "
            "strategy's trial count, which raises every Deflated Sharpe "
            "computed against it."
        ) from exc


def _publish(directory: Path, path: Path, payload: str, *, unique: bool = False) -> Path:
    """Write *payload* to *path* so that nothing can overwrite it.

    Serialized in full to a temporary file first, then linked into place.
    Creating the final path up front leaves a half-written file at that name if
    anything interrupts the write, and every reader here raises on a record
    that does not parse — so one truncated trial would take the whole ledger
    down rather than costing its own write.

    `unique` suffixes on collision instead of raising, for the append-only
    ledgers where two writers inside the same microsecond must both keep their
    record. The pre-registration passes it as False: there, a collision is the
    thing being prevented.
    """
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as writer:
            writer.write(payload)
            # On disk before it is linked, not merely in the page cache: a host
            # that lost power here would otherwise drop a trial the caller was
            # already told had been recorded.
            writer.flush()
            os.fsync(writer.fileno())

        target = path
        suffix = 1
        while True:
            try:
                # os.link, not rename or replace: both overwrite silently on
                # POSIX, and not overwriting is this store's only promise.
                os.link(temporary, target)
                _sync_directory(directory)
                return target
            except FileExistsError:
                if not unique:
                    raise
                suffix += 1
                target = path.with_name(f"{path.stem}-{suffix}{path.suffix}")
    finally:
        # The temporary is never the record, published or not: on success a
        # second link to the same bytes, on failure a fragment.
        with suppress(OSError):
            os.unlink(temporary)


def _sync_directory(directory: Path) -> None:
    """Make a newly linked name durable, where the platform allows it.

    Guarded rather than assumed: opening a directory read-only is a POSIX
    thing and raises on Windows. Skipping the sync there costs the durability
    guarantee, which is honest; raising would cost the record itself.
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
