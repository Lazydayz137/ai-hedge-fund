"""What one observation of one Hyperliquid perp is.

Field names follow the venue's JSON one for one, snake_cased — ``markPx``
becomes ``mark_px`` and nothing is renamed to something more readable.
A row written today has to still mean what it meant when someone reads it in
2029, and a name that matches the wire is the only name that can be checked
against the wire.

Prices and rates arrive as decimal strings and are parsed to float once, here.
``None`` in this module always means the venue sent null; it never means
"we could not get it". A field the collector could not read costs the whole
row — see ``collector.observe``.
"""

from __future__ import annotations

from pydantic import BaseModel


class PerpObservation(BaseModel):
    """One perp's market state at one instant, as the venue reported it."""

    # "xyz:NVDA" for a builder market, "BTC" for a native one. The prefix
    # before the colon is the DEX's short name; native instruments have no
    # prefix and no colon.
    instrument: str

    # The DEX this instrument lives on: "" for Hyperliquid's own crypto book,
    # the builder's short name for a HIP-3 market. Empty is the venue's own
    # spelling for native, not a missing value.
    dex: str

    # UTC, from our clock at the moment this DEX's response came back. The
    # venue's metaAndAssetCtxs response carries no timestamp of its own, so
    # this is the observer's time, not the exchange's — which is why it is
    # recorded per observation rather than once per pass.
    observed_at: str

    # Funding for the next hour, as a rate on notional. Hyperliquid funds
    # hourly, not every eight hours; the number is small for that reason and
    # annualizing it means x8760, not x1095.
    funding: float

    # Base units, not notional. Multiply by mark_px for dollars.
    open_interest: float

    mark_px: float
    oracle_px: float

    # Null when the book has no two-sided quote — a delisted or never-traded
    # market. An empty book is an observation, not an error.
    mid_px: float | None = None

    # The venue's own (mark - oracle) premium input to funding, null on a
    # market with no book to compute it from. Recorded alongside our basis
    # because the two can disagree: this one is time-averaged, ours is a
    # point reading.
    premium: float | None = None

    # The impact bid/ask — the prices a fixed notional would fill at. Two
    # entries when present. This is the only depth signal in the snapshot;
    # without it an empty book and a paper-thin one look identical.
    impact_pxs: list[float] | None = None

    prev_day_px: float | None = None
    day_ntl_vlm: float | None = None
    day_base_vlm: float | None = None

    # Venue metadata that a basis trade needs to size and to know what it is
    # looking at. is_delisted is the flag that separates a market that has
    # gone quiet from one that was switched off.
    max_leverage: int | None = None
    sz_decimals: int | None = None
    margin_mode: str | None = None
    only_isolated: bool | None = None
    is_delisted: bool = False

    # Per-instrument settings the builder can change under a live position.
    # margin_table_id names the leverage ladder this instrument is on;
    # deployer_fee_scale multiplies the builder's cut of the fee. Both are
    # recorded because a row that cannot say what regime it was taken under
    # cannot be reinterpreted once the regime moves.
    margin_table_id: int | None = None
    deployer_fee_scale: float | None = None
    growth_mode: str | None = None
    # The venue's own answer to "when did the fee last move", verbatim: a
    # naive local-format timestamp, no zone, unlike observed_at. Left as the
    # string it arrives as rather than coerced into a UTC instant it does not
    # claim to be.
    last_fee_scale_change_time: str | None = None

    @property
    def basis_bps(self) -> float:
        """(mark - oracle) / oracle, in basis points.

        THE TRAP: for a HIP-3 equity market this only means what "basis"
        normally means while the underlying cash market is open. Outside
        session hours — overnight, weekends, holidays — the oracle for these
        markets is an EMA of the perp's *own* price rather than an external
        reference, so mark and oracle are two readings of the same thing and
        their difference is reflexive. It will look mean-reverting because it
        is definitionally mean-reverting, and a backtest that does not gate on
        session hours will find an edge that cannot be traded.

        Nothing in the snapshot marks the regime — the venue exposes no oracle
        source or staleness field on this endpoint — so observed_at is what a
        later reader has to reconstruct it from. That is why it is UTC and why
        it is stored per observation.
        """
        return (self.mark_px - self.oracle_px) / self.oracle_px * 10_000


class DexConfig(BaseModel):
    """One builder-deployed DEX's settings at the time of a pass.

    Recorded per pass rather than copied onto all ~500 observation rows, and
    stamped by the snapshot's started_at.

    This exists because a HIP-3 market's terms are set by its builder and can
    move: the addresses allowed to post its oracle, the multiplier and
    interest rate that turn a premium into the funding actually charged, the
    open-interest caps that bound a position. A funding rate recorded without
    the multiplier that produced it is a number nobody can reinterpret later,
    and if a builder changes either, every earlier observation silently means
    something else. Nothing else is writing this down.

    Only builder DEXs appear here. Hyperliquid's own book has no entry in
    perpDexs at all — the endpoint returns a literal null in its place — so
    a native observation has no config row, rather than an empty one that
    would read like a builder that set nothing.

    Every field is straight from perpDexs; the venue's assoc-lists are turned
    into dicts keyed by the full namespaced instrument name ("xyz:NVDA"), so
    they join to PerpObservation.instrument directly.
    """

    name: str
    full_name: str | None = None
    deployer: str | None = None

    # The address posting this DEX's oracle — and null on most of them,
    # including the largest. sub_deployers is what actually answers "who
    # could post the oracle that week": its setOracle entry names the
    # authorized addresses, and it is populated where oracle_updater is not.
    # Oracle manipulation is the demonstrated attack on this market class, so
    # both are kept, and neither is inferred from the other.
    oracle_updater: str | None = None
    sub_deployers: dict[str, list[str]] = {}

    fee_recipient: str | None = None

    # Funding inputs, per instrument. The venue computes funding from the
    # premium, the interest rate and the multiplier; recording the rate alone
    # would be recording an output whose inputs are gone.
    asset_to_funding_multiplier: dict[str, float] = {}
    asset_to_funding_interest_rate: dict[str, float] = {}
    asset_to_funding_clamp: dict[str, float] = {}

    # Notional open-interest ceiling per instrument — the size bound on any
    # position taken against it.
    asset_to_streaming_oi_cap: dict[str, float] = {}


class ObservationError(BaseModel):
    """Something the pass could not see, and what it cost.

    Written into the snapshot rather than logged and dropped: a gap in the
    archive has to be distinguishable from a market that simply was not
    listed that day, and the only way to tell later is for the failure to
    have been written down at the time.
    """

    # The DEX name, or "dex:INSTRUMENT" when one instrument in an otherwise
    # readable response was the problem.
    scope: str
    reason: str


class MarketSnapshot(BaseModel):
    """One collection pass: every perp it could read, and every one it could not.

    A pass with errors is still written. Deleting a partial snapshot would
    lose the observations it did get, and pretending it was complete would
    be worse; the errors list is the record of which is which.
    """

    # UTC, when the pass started. Individual observations carry their own,
    # later, timestamps — a pass takes a few seconds to walk every DEX.
    started_at: str
    source_url: str
    observations: list[PerpObservation] = []
    # One entry per builder-deployed DEX; none for the native book, which the
    # venue exposes no config for. A DEX whose config would not parse has no
    # entry here and an error instead — never a stale one carried forward.
    dexes: list[DexConfig] = []
    errors: list[ObservationError] = []
