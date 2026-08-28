"""Turning an uploaded column of timestamps into a series a model can be fitted to.

Every tier-5 operation — decomposition, unit-root tests, ACF, ARIMA, Granger —
assumes observations arrive at a constant interval. Uploaded data almost never
does: two rows share a timestamp, a week is missing, the frequency is implied
rather than declared. Running STL or an ADF test over such a series does not
fail; it returns a confident number about a grid that was never there.

This module is the one place that gap is closed, and the invariant it holds is
that the closing is *reported*. It sorts, collapses duplicate timestamps by a
named aggregation, infers or accepts a frequency, resamples onto the regular
grid, and interpolates the periods with no observation — then hands back a
count of every one of those interventions, notes naming them, and an
:class:`~app.services.analysis_stats.Assumption` that fails whenever a value
was invented rather than measured. An interpolated point is a modelling
choice, and a statistic computed over it must say so.

Where the series is too far from regular to be salvaged — more than
:data:`MAX_GAP_FRACTION` of the grid empty — it refuses and names ``resample``,
which is the operation that would make the question answerable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.services.analysis_result import ExecutionError
from app.services.analysis_stats import Assumption

# The frequencies a tier-5 operation will work at. Deliberately the same set as
# the validator's RESAMPLE_FREQS — imported by neither module, because
# analysis_spec imports the tier modules and the reverse would be a cycle, so a
# test pins the two together instead.
SERIES_FREQS: tuple[str, ...] = ("D", "W", "ME", "QE", "YE")

# How duplicate timestamps and sub-period observations are collapsed when the
# spec does not say. The mean is the only choice that leaves the level of the
# series unchanged when a period happens to carry two readings instead of one.
DEFAULT_AGG = "mean"

# Nominal length of one period, used to pick a frequency from observed spacing.
_FREQ_DAYS: dict[str, float] = {
    "D": 1.0,
    "W": 7.0,
    "ME": 30.44,
    "QE": 91.31,
    "YE": 365.25,
}

# The seasonal cycle a frequency implies when the spec does not name one. Yearly
# data is absent on purpose: there is no cycle shorter than a year in it, so a
# seasonal period has to be stated rather than assumed.
SEASONAL_PERIODS: dict[str, int] = {"D": 7, "W": 52, "ME": 12, "QE": 4}

# Guards on the request path. A 2-million-row upload resampled to a daily grid
# spanning centuries would put an STL or ARIMA fit into minutes; both caps
# refuse instead, naming the operation that shrinks the problem.
MAX_INPUT_ROWS = 1_000_000
MAX_SERIES_PERIODS = 20_000

# Below this many periods nothing here means anything: an ADF test needs lags,
# an ACF needs a tail, a decomposition needs cycles.
MIN_SERIES_PERIODS = 12

# Past this share of the grid being empty, the series is a scatter of
# observations rather than a time series, and interpolating it would invent
# most of the data the statistic is then computed from.
MAX_GAP_FRACTION = 0.2

# How a period with no observation is filled. Time-weighted linear
# interpolation respects the spacing of the surrounding observations, unlike a
# forward fill, which fabricates a flat stretch and biases every variance and
# autocorrelation downward.
INTERPOLATION_METHOD = "time"
INTERPOLATION_DESCRIPTION = "time-weighted linear interpolation"


@dataclass(frozen=True)
class PreparedSeries:
    """One or more value columns on a regular grid, plus what it took to get there."""

    frame: pd.DataFrame
    freq: str
    freq_evidence: str
    agg: str
    n_input: int
    n_used: int
    n_excluded: int
    n_duplicate_timestamps: int
    n_periods: int
    n_empty_periods: int
    n_interpolated: int
    columns: tuple[str, ...] = field(default=())

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.frame.index  # type: ignore[return-value]

    def series(self, column: str) -> np.ndarray:
        return self.frame[column].to_numpy(dtype=float)

    def notes(self) -> list[str]:
        """Plain-language statements of every intervention, for the narrator."""
        lines = [
            f"Series placed on a regular {self.freq} grid of {self.n_periods} period(s) "
            f"from {self.index[0].date()} to {self.index[-1].date()} ({self.freq_evidence})."
        ]
        if self.n_excluded:
            lines.append(f"Excluded {self.n_excluded} row(s) missing a date or a value.")
        if self.n_duplicate_timestamps:
            lines.append(
                f"Collapsed {self.n_duplicate_timestamps} duplicate timestamp(s) by {self.agg}."
            )
        if self.n_used > self.n_periods and not self.n_duplicate_timestamps:
            lines.append(
                f"Aggregated {self.n_used} observation(s) into {self.n_periods} "
                f"{self.freq} period(s) by {self.agg}."
            )
        if self.n_interpolated:
            lines.append(
                f"{self.n_interpolated} of {self.n_periods} period(s) had no observation "
                f"and were filled by {INTERPOLATION_DESCRIPTION}; those points are "
                f"estimates, not measurements."
            )
        return lines

    def assumption(self) -> Assumption:
        """Whether the series was already regular, or had to be made so."""
        name = "Regular spacing"
        if self.n_interpolated == 0:
            return Assumption(
                name,
                True,
                f"all {self.n_periods} {self.freq} period(s) carry at least one observation"
                + (
                    f" (after collapsing {self.n_duplicate_timestamps} duplicate timestamp(s))"
                    if self.n_duplicate_timestamps
                    else ""
                ),
                float(self.n_periods),
            )
        share = self.n_interpolated / self.n_periods
        return Assumption(
            name,
            False,
            f"{self.n_interpolated} of {self.n_periods} period(s) ({share:.1%}) had no "
            f"observation and were filled by {INTERPOLATION_DESCRIPTION}; every statistic "
            f"below is computed partly over values that were estimated rather than measured",
            float(self.n_interpolated),
        )

    def stats(self) -> dict[str, Any]:
        """The ``series`` block every tier-5 result carries."""
        return {
            "frequency": self.freq,
            "frequency_evidence": self.freq_evidence,
            "periods": self.n_periods,
            "observations": self.n_used,
            "duplicate_rule": self.agg,
            "duplicate_timestamps_collapsed": self.n_duplicate_timestamps,
            "periods_with_no_observation": self.n_empty_periods,
            "periods_interpolated": self.n_interpolated,
            "start": self.index[0].isoformat(),
            "end": self.index[-1].isoformat(),
        }


def infer_frequency(index: pd.DatetimeIndex) -> tuple[str, str]:
    """Pick one of :data:`SERIES_FREQS` for *index*, and say what decided it.

    Two sources of evidence, in order. pandas can name an offset alias outright
    when the stamps already fall on a regular grid, which is the strongest
    signal available. Otherwise the median gap between consecutive stamps is
    matched to the nearest nominal period length on a log scale — geometric
    rather than arithmetic midpoints, so 14 days reads as weekly rather than
    being pulled toward monthly by the wider spacing above it.
    """
    unique = pd.DatetimeIndex(index.unique()).sort_values()
    if len(unique) < 2:
        raise ExecutionError("a time series needs at least two distinct timestamps")

    alias = pd.infer_freq(unique) if len(unique) >= 3 else None
    mapped = _map_alias(alias)
    if mapped is not None:
        return mapped, f"pandas read the offset {alias!r} directly from the timestamps"

    gaps = np.diff(unique.to_numpy()).astype("timedelta64[s]").astype(float) / 86_400.0
    median_days = float(np.median(gaps))
    freq = _nearest_freq(median_days)
    return freq, f"median spacing of {median_days:.4g} day(s) is closest to {freq}"


def _map_alias(alias: str | None) -> str | None:
    """Fold a pandas offset alias into the frequencies this tier supports."""
    if not alias:
        return None
    head = alias.split("-", 1)[0].upper()
    if head in SERIES_FREQS:
        return head
    for prefix, freq in (("W", "W"), ("M", "ME"), ("Q", "QE"), ("Y", "YE"), ("A", "YE")):
        if head.startswith(prefix):
            return freq
    if head in ("D", "B", "C"):
        return "D"
    return None  # sub-daily or exotic: let the spacing rule decide


def _nearest_freq(median_days: float) -> str:
    """Closest nominal period to an observed spacing, on a log scale."""
    if median_days <= 0 or not math.isfinite(median_days):
        return "D"
    ordered = sorted(_FREQ_DAYS.items(), key=lambda item: item[1])
    for (freq, days), (_, next_days) in zip(ordered, ordered[1:], strict=False):
        if median_days < math.sqrt(days * next_days):
            return freq
    return ordered[-1][0]


def _resolve_freq(params: dict[str, Any], index: pd.DatetimeIndex) -> tuple[str, str]:
    requested = params.get("freq")
    if requested is None:
        return infer_frequency(index)
    if requested not in SERIES_FREQS:
        raise ExecutionError(f"unknown frequency {requested!r} (allowed: {list(SERIES_FREQS)})")
    return str(requested), f"requested in the analysis spec ({requested})"


def _clean_input(
    df: pd.DataFrame, date: str, values: Sequence[str], op: str
) -> tuple[pd.DataFrame, int]:
    """Drop rows missing the date or any value, and sort by time."""
    for column in (date, *values):
        if column not in df.columns:
            raise ExecutionError(f"{op}: column {column!r} is not in the dataset")
    if len(df) > MAX_INPUT_ROWS:
        raise ExecutionError(
            f"{op}: {len(df)} rows exceeds the {MAX_INPUT_ROWS}-row limit for a time-series "
            f"fit. Use resample to roll the data up first, or filter to a narrower date range."
        )

    frame = pd.DataFrame({date: pd.to_datetime(df[date], errors="coerce")})
    for column in values:
        frame[column] = pd.to_numeric(df[column], errors="coerce")
    frame = frame.dropna().sort_values(date)
    return frame, len(df) - len(frame)


def prepare_series(
    df: pd.DataFrame,
    params: dict[str, Any],
    *,
    op: str,
    values: Sequence[str] | None = None,
    minimum_periods: int = MIN_SERIES_PERIODS,
) -> PreparedSeries:
    """Put *values* on a regular grid indexed by the ``date`` parameter.

    Refuses rather than degrades: an input too large to fit in the request
    path, a grid that is mostly empty, or a series too short to support any of
    these methods all raise :class:`ExecutionError` naming what would work
    instead.
    """
    date = params["date"]
    columns = tuple(values) if values is not None else (params["value"],)
    agg = str(params.get("agg", DEFAULT_AGG))

    frame, excluded = _clean_input(df, date, columns, op)
    if len(frame) < 2:
        raise ExecutionError(f"{op}: only {len(frame)} row(s) have both a usable date and a value")

    index = pd.DatetimeIndex(frame[date])
    freq, evidence = _resolve_freq(params, index)
    duplicates = int(len(index) - index.nunique())

    indexed = frame.set_index(date)[list(columns)]
    grid = indexed.resample(freq).agg(agg)
    occupancy = indexed.resample(freq).size()
    _guard_grid(grid, occupancy, freq, op, minimum_periods)

    missing = int(grid.isna().to_numpy().any(axis=1).sum())
    filled = grid.interpolate(method=INTERPOLATION_METHOD).ffill().bfill()

    return PreparedSeries(
        frame=filled.astype(float),
        freq=freq,
        freq_evidence=evidence,
        agg=agg,
        n_input=len(df),
        n_used=len(frame),
        n_excluded=excluded,
        n_duplicate_timestamps=duplicates,
        n_periods=len(grid),
        n_empty_periods=int((occupancy == 0).sum()),
        n_interpolated=missing,
        columns=columns,
    )


def _guard_grid(
    grid: pd.DataFrame,
    occupancy: pd.Series,
    freq: str,
    op: str,
    minimum_periods: int,
) -> None:
    """Refuse a grid that is too long, too short, or mostly empty."""
    periods = len(grid)
    if periods > MAX_SERIES_PERIODS:
        raise ExecutionError(
            f"{op}: a {freq} grid over this date range is {periods} periods, above the "
            f"{MAX_SERIES_PERIODS}-period limit. Use resample at a coarser frequency first."
        )
    if periods < minimum_periods:
        raise ExecutionError(
            f"{op}: only {periods} {freq} period(s) of data; needs at least {minimum_periods}"
        )

    empty = int((occupancy == 0).sum())
    share = empty / periods
    if share > MAX_GAP_FRACTION:
        raise ExecutionError(
            f"{op}: {empty} of {periods} {freq} period(s) ({share:.0%}) contain no "
            f"observation, above the {MAX_GAP_FRACTION:.0%} limit. Filling that much of the "
            f"series would invent most of the data. Use resample at a coarser frequency, "
            f"where each period would carry real observations."
        )


def seasonal_period_for(params: dict[str, Any], freq: str, op: str) -> int:
    """The seasonal cycle length, declared or implied by the frequency."""
    declared = params.get("seasonal_period")
    if declared is not None:
        period = int(declared)
        if period < 2:
            raise ExecutionError(f"{op}: seasonal_period must be at least 2, got {period}")
        return period
    implied = SEASONAL_PERIODS.get(freq)
    if implied is None:
        raise ExecutionError(
            f"{op}: {freq} data has no cycle shorter than one observation, so "
            f"seasonal_period must be given explicitly"
        )
    return implied
