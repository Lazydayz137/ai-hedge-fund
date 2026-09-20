"""Survivorship: the check whose failure mode is silence.

Every other check in this package fails by producing a bad number. This one
fails by producing nothing at all. A universe assembled from instruments that
still exist does not announce itself — it looks exactly like a universe that
was reconstructed as-of each date, and it prints a better Sharpe. Report 02
puts a figure on the difference: 3,904 cryptos over 2014-2021, annualised
survivorship bias of 0.93% value-weighted and 62.19% equal-weighted, with 58%+
of listed tokens classified dead.

So the rule here is the opposite of the rest of the package: an absent manifest
is a FAIL, not an UNKNOWN. The reasoning is not that absence proves bias. It is
that a universe nobody can describe is the exact artifact a survivorship-biased
universe produces, and the two are indistinguishable from outside. An UNKNOWN
would make "I did not write down what I traded" the cheapest way past the
check. Every other route through this module — not enough names, dates that do
not parse — is a genuine inability to measure and returns UNKNOWN.

`hedge_fund/fund/spec.py` is deliberately ticker-free: the universe is a
run-time argument. That is the right shape for a mandate and it is also why
nothing in this repo currently has anything to hand this function.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hedge_fund.validation.outcome import CheckResult, Verdict, unknown

CHECK = "survivorship"

# Two is arithmetic, not judgement: a cross-sectional strategy ranks names
# against each other and one name is not a cross-section. Callers testing a
# breadth strategy should raise it a long way; nobody may lower it.
MIN_INSTRUMENTS = 2


class Instrument(BaseModel):
    """One name in the tested universe, and how it left if it left.

    `terminal_value` is a price, not a return, and it is required of anything
    that stopped trading inside the window. Report 02 §5.A: a delisted name is
    retained to its final trading date and then marked to its terminal value —
    usually near zero — never to NaN. Dropping it is the bias; NaN-ing it is
    the same bias with a nullable column.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    first_date: str
    last_date: str | None = Field(
        default=None, description="YYYY-MM-DD final trading day; None = still "
        "trading at the window's end"
    )
    terminal_value: float | None = Field(
        default=None, description="the mark applied after last_date"
    )
    exit_reason: str | None = Field(
        default=None, description="delisted, rugged, acquired, expired, ..."
    )

    @property
    def died(self) -> bool:
        return self.last_date is not None


class UniverseManifest(BaseModel):
    """What was actually tested, asserted by whoever assembled it.

    `point_in_time` is the load-bearing claim: membership was reconstructed
    as-of each date rather than taken from today's roster. It is a claim the
    manifest cannot verify about itself, which is why this check also requires
    the dead names to be *there* — a point-in-time universe over a real window
    that contains no dead names at all is a claim someone should have to make
    explicitly, and `no_deaths_attested` is where they make it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_start: str
    window_end: str
    point_in_time: bool
    instruments: list[Instrument] = Field(default_factory=list)
    residual_bias_estimate_pct: float | None = Field(
        default=None,
        description="annualised phantom return still assumed to be in the "
        "result after this reconstruction; report 02 §5.A asks for a stated "
        "estimate, and 0.0 is an acceptable answer that 'unstated' is not",
    )
    no_deaths_attested: bool = Field(
        default=False,
        description="set only when the assembler has checked and every name "
        "in the universe really did survive the whole window",
    )
    source: str | None = None

    @model_validator(mode="after")
    def _ordered(self) -> "UniverseManifest":
        for label, value in (
            ("window_start", self.window_start), ("window_end", self.window_end),
        ):
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{label}={value!r} is not YYYY-MM-DD") from exc
        if self.window_end < self.window_start:
            raise ValueError(
                f"window ends {self.window_end} before it starts "
                f"{self.window_start}"
            )
        return self


def score(
    manifest: UniverseManifest | None,
    *,
    min_instruments: int = MIN_INSTRUMENTS,
) -> CheckResult:
    """Report 02 §5.E item 4: survivorship-free universe, deaths marked."""
    if manifest is None:
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                "no universe manifest was supplied. This is a FAIL and not an "
                "UNKNOWN on purpose: a universe that cannot be described is "
                "indistinguishable from a survivorship-selected one, and "
                "silence is this check's failure mode, not its absence"
            ),
        )
    if min_instruments < MIN_INSTRUMENTS:
        raise ValueError(
            f"min_instruments={min_instruments} is below the floor of "
            f"{MIN_INSTRUMENTS}; one name is not a cross-section"
        )

    dead = [i for i in manifest.instruments if i.died]
    alive = [i for i in manifest.instruments if not i.died]
    evidence = {
        "window_start": manifest.window_start,
        "window_end": manifest.window_end,
        "point_in_time": manifest.point_in_time,
        "n_instruments": len(manifest.instruments),
        "n_died": len(dead),
        "n_survived": len(alive),
        "residual_bias_estimate_pct": manifest.residual_bias_estimate_pct,
        "no_deaths_attested": manifest.no_deaths_attested,
        "source": manifest.source,
    }

    if len(manifest.instruments) < min_instruments:
        return unknown(
            CHECK,
            f"the manifest lists {len(manifest.instruments)} instrument(s) "
            f"against a required {min_instruments}; there is no survivorship "
            "question to answer about a universe this small",
            **evidence,
        )

    if not manifest.point_in_time:
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                "the manifest does not claim point-in-time membership, so the "
                "roster is today's roster applied to the past — the bias "
                "itself, re-entering through the universe definition"
            ),
            evidence=evidence,
        )

    unmarked = [i.symbol for i in dead if i.terminal_value is None]
    if unmarked:
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                f"{len(unmarked)} instrument(s) stopped trading inside the "
                f"window with no terminal value ({', '.join(sorted(unmarked)[:8])}"
                f"{', ...' if len(unmarked) > 8 else ''}); marked to NaN is "
                "the same omission as dropped, with a nullable column"
            ),
            evidence=evidence | {"unmarked": sorted(unmarked)},
        )

    if not dead and not manifest.no_deaths_attested:
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                f"every one of the {len(manifest.instruments)} instruments "
                "survived the whole window and nobody attested that this was "
                "checked. That is what a survivorship-selected universe looks "
                "like from here; set no_deaths_attested once it has actually "
                "been verified"
            ),
            evidence=evidence,
        )

    if manifest.residual_bias_estimate_pct is None:
        return CheckResult(
            check=CHECK,
            verdict=Verdict.FAIL,
            reason=(
                "no residual bias estimate. Report 02 §5.A asks for a stated "
                "estimate of what survivorship is still in the number after "
                "reconstruction; 0.0 is an answer, unstated is not"
            ),
            evidence=evidence,
        )

    return CheckResult(
        check=CHECK,
        verdict=Verdict.PASS,
        reason=(
            f"point-in-time universe of {len(manifest.instruments)} "
            f"instruments over {manifest.window_start}..{manifest.window_end}; "
            f"{len(dead)} died and each carries a terminal value; residual "
            f"bias stated at {manifest.residual_bias_estimate_pct:.2f}%/yr"
        ),
        evidence=evidence,
    )
