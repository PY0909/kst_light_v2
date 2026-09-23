"""V2-P00-T05: pilot_root/dataset misrouting guard.

The historical default ``pilot_root="pilot/fd004"`` silently routed MetroPT-3
artifacts into the FD004 result tree. The guard makes the mismatch impossible
and the fast-fail must happen before any dataset access.
"""

import pytest

from kaf_profiti.experiments.pilot_runner import (
    RealProtocolProvider,
    ensure_pilot_root_matches,
)

METROPT3 = "metropt3_chrono_502030_v2"
FD004 = "cmapss_fd004"


def test_guard_accepts_matching_pilot_roots():
    assert ensure_pilot_root_matches("pilot/metropt3", METROPT3) == "pilot/metropt3"
    assert ensure_pilot_root_matches("pilot/fd004", FD004) == "pilot/fd004"


def test_guard_rejects_fd004_default_for_metropt3():
    with pytest.raises(ValueError, match=r"expected 'pilot/metropt3'"):
        ensure_pilot_root_matches("pilot/fd004", METROPT3)


def test_guard_rejects_malformed_root():
    with pytest.raises(ValueError, match=r"expected 'pilot/metropt3'"):
        ensure_pilot_root_matches("metropt3", METROPT3)
    with pytest.raises(ValueError, match=r"expected 'pilot/metropt3'"):
        ensure_pilot_root_matches("pilot/fd004/extra", METROPT3)


def test_guard_rejects_unknown_dataset():
    with pytest.raises(ValueError, match="no pilot profile mapping"):
        ensure_pilot_root_matches("pilot/metropt3", "unknown_dataset_v9")


def test_real_provider_rejects_default_root_for_metropt3_before_data_access(tmp_path):
    """Constructing the MetroPT provider with the implicit default must fail fast."""
    with pytest.raises(ValueError, match=r"expected 'pilot/metropt3'"):
        RealProtocolProvider(
            data_root=tmp_path / "missing-data",
            result_root=tmp_path / "out",
            dataset=METROPT3,
            history_len=168,
            pred_len=24,
            stride=60,
            mechanism="mixed",
            requested_rate=0.30,
            mask_seed=2026,
            split_seed=2026,
        )
