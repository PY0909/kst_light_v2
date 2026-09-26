"""V2-CH3-CODE-T01: unified six-protocol data entry contract.

Pins the unified per-window sample fields (Y_q, context, T_obs, T_q, M_obs,
unit_id, window_id, risk_label), seed passthrough (split_seed/mask_seed), the
persisted C-MAPSS split manifests, the new ``tep_faulty`` protocol (stratified
fault-class split, official faulty-testing test split, explicit failure when
faulty sources are missing), and the stability of the existing identity chain
(mask_seed recording must not move any split_sha256).
"""

import json
import os
from pathlib import Path

import pytest

from kaf_profiti.experiments.datasets import create_protocol_datasets

DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", Path(__file__).resolve().parents[2] / "dataset"))

UNIFIED_FIELDS = (
    "Y_q", "context", "T_obs", "T_q", "M_obs", "unit_id", "window_id", "risk_label",
)

SIX_PROTOCOLS = {
    "metropt3_chrono_502030_v2": (168, 24, 60),
    "cmapss_fd001": (50, 10, 1),
    "cmapss_fd002": (50, 10, 1),
    "cmapss_fd003": (50, 10, 1),
    "cmapss_fd004": (50, 10, 1),
    "tep_faulty": (96, 24, 12),
}

#: Identity anchors captured before V2-CH3-CODE-T01; recording mask_seed in the
#: outer split_info must never move these digests.
PINNED_SPLIT_SHA256 = {
    "metropt3_chrono_502030_v2": "eb7b957c983972c6bdc01ce03018bea2119b4afabf914699694dcf5cae6658cb",
    "cmapss_fd004": "61c7db91a38f1f350a79ea3632e2456cf247aeffcb5b3c8f24f98746d8345880",
}


def _build(dataset, **overrides):
    history_len, pred_len, stride = SIX_PROTOCOLS[dataset]
    kwargs = dict(
        dataset=dataset,
        data_root=DATA_ROOT,
        seed=2026,
        split_seed=2026,
        history_len=history_len,
        pred_len=pred_len,
        stride=stride,
    )
    kwargs.update(overrides)
    return create_protocol_datasets(**kwargs)


def _data_present(dataset: str) -> bool:
    if dataset.startswith("cmapss"):
        subset = dataset.replace("cmapss_", "").upper()
        return (DATA_ROOT / "CMAPSSData" / f"train_{subset}.txt").is_file()
    if dataset == "tep_faulty":
        return (DATA_ROOT / "dataverse_files" / "TEP_Faulty_Training.RData").is_file()
    return (DATA_ROOT / "metropt+3+dataset" / "MetroPT3(AirCompressor).csv").is_file()


def _assert_unified_sample(sample) -> None:
    for field_name in UNIFIED_FIELDS:
        assert hasattr(sample, field_name), f"sample missing unified field {field_name}"
    assert sample.window_id, "window_id must be a non-empty identifier"
    assert float(sample.risk_label) in (0.0, 1.0)


@pytest.mark.parametrize("dataset", sorted(SIX_PROTOCOLS))
def test_unified_sample_fields_and_seed_passthrough(dataset):
    if not _data_present(dataset):
        pytest.skip(f"{dataset} raw data not present")
    info = _build(dataset)
    # MetroPT splits chronologically (no random split); every other protocol
    # carries the registered split seed verbatim.
    assert info.split_info["split_seed"] in (2026, "not_applicable_chronological")
    assert info.split_info["mask_seed"] == 2026
    _assert_unified_sample(info.train[0])
    _assert_unified_sample(info.valid[0])
    _assert_unified_sample(info.test[0])


@pytest.mark.parametrize("dataset,expected", sorted(PINNED_SPLIT_SHA256.items()))
def test_identity_chain_unchanged_by_seed_recording(dataset, expected):
    if not _data_present(dataset):
        pytest.skip(f"{dataset} raw data not present")
    info = _build(dataset)
    assert info.split_info["split_sha256"] == expected


@pytest.mark.skipif(not _data_present("cmapss_fd001"), reason="FD001 raw data not present")
def test_cmapss_split_manifest_persisted(tmp_path: Path):
    info = _build("cmapss_fd001", manifest_dir=tmp_path)
    manifest_path = tmp_path / "cmapss_fd001" / "cmapss_split_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for filename in ("train_FD001.txt", "test_FD001.txt", "RUL_FD001.txt"):
        entry = manifest["files"][filename]
        digest = entry["sha256"]
        assert len(digest) == 64
        assert entry["bytes"] == (DATA_ROOT / "CMAPSSData" / filename).stat().st_size

    assert manifest["split_seed"] == 2026
    assert manifest["train_engine_ids"] == info.split_info["train_engine_ids"]
    assert manifest["valid_engine_ids"] == info.split_info["valid_engine_ids"]
    assert manifest["split_sha256"] == info.split_info["split_sha256"]
    assert manifest["window"] == {"history_len": 50, "pred_len": 10, "stride": 1}
    assert manifest["split_rule"] == info.split_info["split_rule"]


@pytest.mark.skipif(not _data_present("cmapss_fd001"), reason="FD001 raw data not present")
def test_cmapss_risk_label_rule_and_window_id():
    info = _build("cmapss_fd001")
    for sample in [info.train[0], info.train[len(info.train) // 2], info.valid[0]]:
        assert float(sample.risk_label) == float(sample.rul <= 30.0)
        assert sample.window_id.startswith("engine")


@pytest.mark.skipif(not _data_present("tep_faulty"), reason="TEP faulty RData not present")
def test_tep_faulty_protocol_stratified_split_and_identity():
    info = _build("tep_faulty")
    si = info.split_info
    assert si["dataset"] == "tep_faulty"
    assert si["split_rule"] == "fault_class_stratified_run_80_20_official_faulty_test"
    assert si["sources"]["train_valid"] == "TEP_Faulty_Training.RData"
    assert si["sources"]["test"] == "TEP_Faulty_Testing.RData"
    assert si["split_sha256"]
    assert si["normalization"]["sha256"]
    assert si["normalization"]["source_split"] == "train"

    train_by_fault = si["train_run_ids_by_fault"]
    valid_by_fault = si["valid_run_ids_by_fault"]
    assert sorted(train_by_fault) == list(range(1, 21))
    assert sorted(valid_by_fault) == list(range(1, 21))
    for fault in range(1, 21):
        assert set(train_by_fault[fault]).isdisjoint(valid_by_fault[fault])
        # official stratified 80/20 over 500 runs per fault class
        assert len(train_by_fault[fault]) == 400
        assert len(valid_by_fault[fault]) == 100


@pytest.mark.skipif(not _data_present("tep_faulty"), reason="TEP faulty RData not present")
def test_tep_faulty_sources_manifest_persisted(tmp_path: Path):
    info = _build("tep_faulty", manifest_dir=tmp_path)
    sources_path = tmp_path / "tep_faulty" / "tep_faulty_sources.json"
    assert sources_path.is_file()
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    for filename in ("TEP_Faulty_Training.RData", "TEP_Faulty_Testing.RData"):
        entry = sources["files"][filename]
        assert len(entry["sha256"]) == 64
    assert sources["fault_classes"] == list(range(1, 21))
    assert sources["fault_interval"]["training"] == [1, 500]
    assert sources["fault_interval"]["testing"] == [161, 960]
    assert sources["split_seed"] == 2026


@pytest.mark.skipif(not _data_present("tep_faulty"), reason="TEP faulty RData not present")
def test_tep_faulty_split_deterministic_and_run_isolated():
    # free each protocol before rebuilding: the cached raw frames stay, the
    # per-split frame copies must not stack up on a 24GB host
    first = _build("tep_faulty")
    first_sha = first.split_info["split_sha256"]
    first_windows = (first.train.windows, first.test.windows)
    first_units_train = first.train._units
    first_history, first_stride = first.train.history_len, first.train.stride
    first_pred = first.train.pred_len
    del first

    again = _build("tep_faulty")
    assert again.split_info["split_sha256"] == first_sha
    del again

    other = _build("tep_faulty", split_seed=2027)
    assert other.split_info["split_sha256"] != first_sha
    del other

    # windows never cross a simulation run: per-unit window count follows the
    # run length formula at the protocol stride
    windows_train, windows_test = first_windows
    counts: dict = {}
    for unit_id, _start in windows_train:
        counts.setdefault(unit_id, 0)
        counts[unit_id] += 1
    run_len = len(next(iter(first_units_train.values())))
    expected = (run_len - first_history - first_pred) // first_stride + 1
    assert set(counts.values()) == {expected}


def test_tep_faulty_missing_sources_fail_explicitly(tmp_path: Path):
    (tmp_path / "dataverse_files").mkdir(parents=True)
    # only fault-free files present: the faulty protocol must refuse, never
    # silently fall back to fault-free data
    with pytest.raises(FileNotFoundError, match="TEP_Faulty_Training.RData"):
        create_protocol_datasets(
            dataset="tep_faulty",
            data_root=tmp_path,
            seed=2026,
            split_seed=2026,
            history_len=96,
            pred_len=24,
            stride=12,
        )


@pytest.mark.skipif(not _data_present("tep_faulty"), reason="TEP faulty RData not present")
def test_tep_faulty_risk_labels_follow_split_specific_fault_start():
    info = _build("tep_faulty")
    si = info.split_info
    assert si["label_rule"].startswith("risk = faultNumber > 0")
    # training runs carry the fault from sample 1; testing runs from 161
    assert si["fault_start_sample"]["train"] == 1
    assert si["fault_start_sample"]["test"] == 161
    train_labels = {float(info.train[i].risk_label) for i in range(0, len(info.train), 97)}
    test_labels = {float(info.test[i].risk_label) for i in range(0, len(info.test), 997)}
    assert train_labels <= {0.0, 1.0} and test_labels <= {0.0, 1.0}
    assert 1.0 in test_labels, "faulty testing windows must contain positives"
