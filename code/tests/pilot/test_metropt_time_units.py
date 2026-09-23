"""MetroPT time-unit semantics regression tests (pandas 2.x/3.x invariant).

Found 2026-09-17 while running the CH34 suite in an unpinned environment
(pandas 3.0.5): ``median_interval_seconds`` cast datetimes to int64 and
divided by 1e9, assuming nanosecond resolution. pandas 3.0 changed the
default datetime unit to microseconds, so the median interval silently
shrank 1000x (10 s -> 0.01 s), the gap threshold followed, ``segmentize``
split every row into its own segment, and the window catalog came back
empty (IndexError in ``_window_bounds_entry``). ``raw_data_sha`` had the
same ns assumption inside its digest.

These tests pin the *semantic* contract — seconds come out as seconds and
the SHA hashes nanosecond ints — on any pandas version:

- a 10-second cadence yields ``median_interval_seconds == 10.0``;
- sub-second cadences survive too;
- ``raw_data_sha`` byte-matches a manual digest built from explicit
  nanosecond integers.
"""

import hashlib

import numpy as np
import pandas as pd

from kaf_profiti.industrial.metropt import (
    median_interval_seconds,
    raw_data_sha,
)


def _frame(timestamps, values=(1.0, 2.0, 3.0), column="TP2"):
    n = len(timestamps)
    filled = [values[i % len(values)] for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps),
            "source_row_id": list(range(n)),
            column: filled,
        }
    )


def test_median_interval_is_ten_seconds_for_ten_second_cadence():
    timestamps = pd.date_range("2020-01-01", periods=9, freq="10s")
    assert median_interval_seconds(_frame(timestamps)) == 10.0


def test_median_interval_supports_subsecond_cadence():
    timestamps = pd.date_range("2020-01-01", periods=5, freq="100ms")
    assert median_interval_seconds(_frame(timestamps)) == 0.1


def test_median_interval_ignores_duplicate_timestamps():
    base = pd.date_range("2020-01-01", periods=4, freq="10s")
    frame = _frame(list(base) + [base[-1]])
    assert median_interval_seconds(frame) == 10.0


def test_raw_data_sha_hashes_nanosecond_integers():
    timestamps = pd.date_range("2020-01-01", periods=4, freq="10s")
    frame = _frame(timestamps, values=(0.5, -1.25, 3.0, 2.0))
    column = "TP2"

    expected = hashlib.sha256()
    expected.update(column.encode("utf-8"))
    expected.update(b"\x00")
    expected.update(np.asarray([0, 1, 2, 3], dtype=np.int64).tobytes())
    # explicit nanosecond integers: epoch_seconds * 1e9
    ns = np.asarray(
        [int(ts.timestamp() * 1_000_000_000) for ts in timestamps],
        dtype=np.int64,
    )
    expected.update(ns.tobytes())
    expected.update(np.asarray([0.5, -1.25, 3.0, 2.0], dtype=np.float64).tobytes())

    assert raw_data_sha(frame, [column]) == expected.hexdigest()
