import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import torch
from torch.utils.data import Dataset

from kaf_profiti.industrial.missing import (
    MissingMechanismSimulator,
    canonical_mechanism,
    timeline_block_offline_mask,
    timeline_low_rate_mask,
    timeline_mixed_mask,
    timeline_random_mask,
)

TIMELINE_MASK_SCHEMA_VERSION = 3
_TIMELINE_MECHANISMS = {"none", "random", "low_rate", "block_offline", "mixed"}
_TIMELINE_SPLITS = {"train", "valid", "test"}
DEFAULT_RATE_TOLERANCE = 0.01
_CALIBRATION_MAX_ITERATIONS = 14


@dataclass(frozen=True)
class TimelineMaskConfig:
    """Identity of one shared timeline-first mask bundle.

    All fields participate in the artifact identity: schema version, dataset,
    split, mechanism, requested rate, mask seed, and the SHA of the source
    data split. Two models compared on the same protocol must reference a
    bundle with an identical config and content digest.
    """

    dataset: str
    split: str
    mechanism: str
    requested_rate: float
    mask_seed: int
    source_split_sha256: str
    schema_version: int = TIMELINE_MASK_SCHEMA_VERSION

    def __post_init__(self):
        if self.split not in _TIMELINE_SPLITS:
            raise ValueError(f"split must be one of {sorted(_TIMELINE_SPLITS)}")
        object.__setattr__(self, "mechanism", canonical_mechanism(self.mechanism))
        if self.mechanism not in _TIMELINE_MECHANISMS:
            raise ValueError(f"mechanism must be one of {sorted(_TIMELINE_MECHANISMS)}")
        if not 0.0 <= self.requested_rate <= 1.0:
            raise ValueError("requested_rate must be within [0, 1]")
        if len(self.source_split_sha256) != 64:
            raise ValueError("source_split_sha256 must be a 64-hex digest")
        if self.schema_version != TIMELINE_MASK_SCHEMA_VERSION:
            raise ValueError("unsupported timeline mask schema version")


@dataclass(frozen=True)
class TimelineMaskBundle:
    """Loaded/generated timeline masks plus their shared artifact reference.

    ``masks`` maps engine id to a ``[timeline_length, num_sensors]`` uint8
    array generated once per engine; windows slice into it by ``(unit, start)``
    so overlapping windows always share the observation state of the same
    engine/cycle rows. ``realized_rate`` is the final split-level missing rate
    achieved after deterministic calibration and the per-channel
    at-least-one-observation safety constraint.
    """

    config: TimelineMaskConfig
    masks: Dict[int, np.ndarray]
    path: Path
    content_sha256: str
    realized_rate: float
    calibration: Dict[str, object]


def _derive_engine_mask_seed(config: TimelineMaskConfig, engine_id: int) -> int:
    """Derive a per-engine RNG seed from the full mask identity.

    The seed depends only on the identity fields and the engine id, never on
    iteration order, so engines and splits never chain random streams.
    """
    payload = (
        f"{config.schema_version}|{config.dataset}|{config.split}|"
        f"{config.mechanism}|{config.mask_seed}|{engine_id}"
    )
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8], 16)


def _timeline_content_sha256(masks: Dict[int, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for engine_id in sorted(masks):
        array = np.ascontiguousarray(masks[engine_id], dtype=np.uint8)
        digest.update(f"{engine_id}:{array.shape[0]}x{array.shape[1]}:".encode("utf-8"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _generate_timeline_masks(
    config: TimelineMaskConfig,
    engine_timeline_lengths: Dict[int, int],
    num_sensors: int,
    tolerance: float = DEFAULT_RATE_TOLERANCE,
):
    """Generate calibrated per-engine timeline masks.

    Returns ``(masks, calibration)`` where ``masks`` maps engine id to a uint8
    ``[timeline_len, num_sensors]`` array and ``calibration`` records the
    deterministic knob search: mechanism, knob name/value, iterations, and the
    realized / pre-safety rates. ``requested_rate`` is matched as the final
    split-level realized missing rate within ``tolerance``; the per-channel
    at-least-one-observation safety constraint is applied before the rate is
    measured, and its deviation is recorded.
    """
    rate = float(config.requested_rate)
    total_cells = sum(int(length) * num_sensors for length in engine_timeline_lengths.values())
    if total_cells <= 0:
        raise ValueError("engine timelines contain no cells")

    def gen_once(knob_value: float):
        masks: Dict[int, np.ndarray] = {}
        pre_safety_missing = 0
        missing = 0
        for engine_id in sorted(engine_timeline_lengths):
            timeline_len = int(engine_timeline_lengths[engine_id])
            if timeline_len <= 0:
                raise ValueError(f"engine {engine_id} has a non-positive timeline length")
            generator = torch.Generator().manual_seed(_derive_engine_mask_seed(config, engine_id))
            if config.mechanism == "none":
                mask = torch.ones(timeline_len, num_sensors)
            elif config.mechanism == "random":
                mask = timeline_random_mask(timeline_len, num_sensors, knob_value, generator)
            elif config.mechanism == "low_rate":
                mask = timeline_low_rate_mask(timeline_len, num_sensors, knob_value, generator)
            elif config.mechanism == "block_offline":
                mask = timeline_block_offline_mask(
                    timeline_len, num_sensors, knob_value, generator, max_block_fraction=0.8
                )
            else:  # mixed
                mask = timeline_mixed_mask(timeline_len, num_sensors, knob_value, generator)
            pre_safety_missing += int((mask == 0).sum())
            mask = MissingMechanismSimulator._ensure_observed(mask, generator)
            missing += int((mask == 0).sum())
            masks[engine_id] = mask.to(torch.uint8).cpu().numpy()
        return masks, pre_safety_missing / total_cells, missing / total_cells

    if config.mechanism == "none":
        if rate > 0.0:
            raise ValueError("mechanism 'none' cannot realize a positive requested rate")
        masks, pre_safety_rate, realized = gen_once(1.0)
        calibration = {
            "mechanism": "none",
            "knob": None,
            "value": None,
            "iterations": 0,
            "tolerance": tolerance,
            "requested_rate": rate,
            "realized_rate": realized,
        }
        return masks, calibration, pre_safety_rate

    knob_specs = {
        "random": ("keep_prob", max(1e-4, 1.0 - rate), -1.0, 1e-4, 1.0),
        "low_rate": ("keep_prob", max(1e-4, 1.0 - rate), -1.0, 1e-4, 1.0),
        "block_offline": (
            "block_prob",
            min(1.0, rate / 0.4),
            1.0,
            0.0,
            1.0,
        ),
        "mixed": ("keep_prob", min(1.0, max(1e-4, (1.0 - rate) / 0.72)), -1.0, 1e-4, 1.0),
    }
    knob_name, value, slope, low, high = knob_specs[config.mechanism]

    masks = None
    realized = None
    pre_safety_rate = None
    iterations = 0
    for iterations in range(1, _CALIBRATION_MAX_ITERATIONS + 1):
        masks, pre_safety_rate, realized = gen_once(value)
        if abs(realized - rate) <= tolerance:
            calibration = {
                "mechanism": config.mechanism,
                "knob": knob_name,
                "value": float(value),
                "iterations": iterations,
                "tolerance": tolerance,
                "requested_rate": rate,
                "realized_rate": realized,
            }
            return masks, calibration, pre_safety_rate
        if realized > rate:
            if slope < 0:
                low = value
            else:
                high = value
        else:
            if slope < 0:
                high = value
            else:
                low = value
        value = 0.5 * (low + high)
    raise ValueError(
        f"timeline mask calibration for {config.mechanism}@{rate} failed to reach "
        f"+/-{tolerance} within {_CALIBRATION_MAX_ITERATIONS} iterations "
        f"(last realized rate {realized})"
    )


def _bundle_metadata(
    config: TimelineMaskConfig,
    masks: Dict[int, np.ndarray],
    num_sensors: int,
    content_sha256: str,
    calibration: Dict[str, object],
    pre_safety_realized_rate: float,
) -> str:
    realized_rate = float(calibration["realized_rate"])
    return json.dumps(
        {
            "schema_version": config.schema_version,
            "dataset": config.dataset,
            "split": config.split,
            "mechanism": config.mechanism,
            "requested_rate": float(config.requested_rate),
            "mask_seed": int(config.mask_seed),
            "source_split_sha256": config.source_split_sha256,
            "num_sensors": int(num_sensors),
            "engine_lengths": {
                str(engine): int(mask.shape[0]) for engine, mask in sorted(masks.items())
            },
            "content_sha256": content_sha256,
            "realized_rate": realized_rate,
            "pre_safety_realized_rate": float(pre_safety_realized_rate),
            "safety_adjustment": float(pre_safety_realized_rate - realized_rate),
            "calibration": calibration,
        },
        sort_keys=True,
    )


def _validate_timeline_bundle(
    path: Path,
    config: TimelineMaskConfig,
    engine_timeline_lengths: Dict[int, int],
    num_sensors: int,
) -> TimelineMaskBundle:
    with np.load(path) as loaded:
        if "meta" not in loaded.files:
            raise ValueError(f"{path} is not a timeline mask bundle (missing meta)")
        meta = json.loads(str(loaded["meta"].item()))
        mismatches = []
        for field, expected in (
            ("schema_version", config.schema_version),
            ("dataset", config.dataset),
            ("split", config.split),
            ("mechanism", config.mechanism),
            ("requested_rate", float(config.requested_rate)),
            ("mask_seed", int(config.mask_seed)),
            ("source_split_sha256", config.source_split_sha256),
            ("num_sensors", int(num_sensors)),
        ):
            if meta.get(field) != expected:
                mismatches.append(f"{field}: artifact={meta.get(field)!r} requested={expected!r}")
        if mismatches:
            raise ValueError(f"mask bundle identity mismatch in {path}: " + "; ".join(mismatches))

        expected_engines = {int(engine) for engine in engine_timeline_lengths}
        stored_engines = {int(engine) for engine in meta["engine_lengths"]}
        if stored_engines != expected_engines:
            raise ValueError(
                f"mask bundle engine set/shape mismatch in {path}: "
                f"artifact engines differ from requested engines"
            )
        masks: Dict[int, np.ndarray] = {}
        for engine_key, stored_len in meta["engine_lengths"].items():
            engine = int(engine_key)
            expected_len = int(engine_timeline_lengths[engine])
            if int(stored_len) != expected_len:
                raise ValueError(
                    f"mask bundle shape mismatch for engine {engine} in {path}: "
                    f"artifact length {stored_len} != expected {expected_len}"
                )
            array = loaded[f"engine_{engine}"]
            if array.ndim != 2 or array.shape != (expected_len, num_sensors):
                raise ValueError(
                    f"mask bundle shape mismatch for engine {engine} in {path}: {array.shape}"
                )
            masks[engine] = np.ascontiguousarray(array, dtype=np.uint8)

    content_sha256 = _timeline_content_sha256(masks)
    if content_sha256 != meta["content_sha256"]:
        raise ValueError(
            f"mask bundle content digest mismatch in {path}: "
            f"artifact={meta['content_sha256']} recomputed={content_sha256}"
        )
    total_cells = sum(mask.size for mask in masks.values())
    missing_cells = sum(int((mask == 0).sum()) for mask in masks.values())
    realized_rate = missing_cells / total_cells
    if abs(realized_rate - float(meta["realized_rate"])) > 1e-9:
        raise ValueError(
            f"mask bundle realized-rate mismatch in {path}: "
            f"meta={meta['realized_rate']} recomputed={realized_rate}"
        )
    return TimelineMaskBundle(
        config=config,
        masks=masks,
        path=Path(path),
        content_sha256=content_sha256,
        realized_rate=float(meta["realized_rate"]),
        calibration=dict(meta["calibration"]),
    )


def generate_or_load_timeline_masks(
    path,
    config: TimelineMaskConfig,
    engine_timeline_lengths: Dict[int, int],
    num_sensors: int,
    tolerance: float = DEFAULT_RATE_TOLERANCE,
) -> TimelineMaskBundle:
    """Load or create the shared timeline-first mask bundle at ``path``.

    Existing bundles are strictly validated against ``config``, the expected
    engine timeline lengths, array shapes, the stored content digest, and the
    stored realized rate; any mismatch raises instead of silently reusing or
    regenerating. Newly generated bundles are deterministically calibrated so
    the split-level realized missing rate matches ``config.requested_rate``
    within ``tolerance`` (unreachable tolerances raise instead of saving a
    mislabeled bundle) and are written atomically so all models sharing the
    protocol directory reference the same relative artifact path and SHA.

    Generation consumes only the mask identity and timeline lengths; it never
    reads RUL, targets, fault labels, or any evaluation result.
    """
    path = Path(path)
    if not engine_timeline_lengths:
        raise ValueError("engine_timeline_lengths must not be empty")
    if num_sensors <= 0:
        raise ValueError("num_sensors must be positive")
    if not 0.0 < tolerance <= 0.5:
        raise ValueError("tolerance must be within (0, 0.5]")
    if path.exists():
        return _validate_timeline_bundle(path, config, engine_timeline_lengths, num_sensors)

    masks, calibration, pre_safety_rate = _generate_timeline_masks(
        config, engine_timeline_lengths, num_sensors, tolerance
    )
    if set(masks) != {int(engine) for engine in engine_timeline_lengths}:
        raise ValueError("generated engine set does not match requested engines")
    content_sha256 = _timeline_content_sha256(masks)
    meta = _bundle_metadata(
        config, masks, num_sensors, content_sha256, calibration, pre_safety_rate
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {f"engine_{engine}": mask for engine, mask in masks.items()}
    tmp_path = path.with_name(path.name + ".tmp.npz")
    np.savez_compressed(tmp_path, **arrays, meta=np.array(meta))
    tmp_path.replace(path)
    return TimelineMaskBundle(
        config=config,
        masks=masks,
        path=path,
        content_sha256=content_sha256,
        realized_rate=float(calibration["realized_rate"]),
        calibration=calibration,
    )


class TimelineMaskedWindowDataset(Dataset):
    """Apply a timeline mask bundle to a window dataset via canonical indices.

    The mask for window ``index`` is the bundle slice
    ``masks[unit][start : start + history_len]`` where ``(unit, start)`` is the
    dataset's canonical window record, so every overlapping window reads the
    observation state of the same engine timeline rows. Artificial missingness
    applies only to this history input span: ``M_obs``/``X_obs`` are replaced,
    while the base dataset's ``Y_q`` and ``M_q`` stay untouched. Consequently,
    all missingness conditions are trained and scored on the same future target
    positions; a condition changes what the model observes, never which query
    targets are counted in its loss or metrics.
    """

    def __init__(self, dataset: Dataset, bundle: TimelineMaskBundle):
        self.dataset = dataset
        self.bundle = bundle
        self.history_len = int(dataset.history_len)
        for unit, group in dataset._units.items():
            engine = int(unit)
            if engine not in bundle.masks:
                raise ValueError(f"mask bundle is missing engine {engine}")
            if bundle.masks[engine].shape[0] < len(group):
                raise ValueError(
                    f"mask timeline for engine {engine} is shorter than the data timeline"
                )

    def __len__(self) -> int:
        return len(self.dataset)

    def __getitem__(self, index: int):
        sample = self.dataset[index]
        unit, start = self.dataset.windows[index]
        timeline = self.bundle.masks[int(unit)]
        obs_mask = torch.tensor(
            timeline[start : start + self.history_len], dtype=torch.float32
        )
        return replace(
            sample,
            M_obs=obs_mask,
            X_obs=sample.X_obs * obs_mask,
        )


def generate_masks_array(
    num_windows: int,
    history_len: int,
    num_sensors: int,
    missing_rate: float,
    seed: int,
    mode: str = "mixed",
) -> np.ndarray:
    if not 0 <= missing_rate <= 1:
        raise ValueError("missing_rate must be in [0, 1]")
    if missing_rate == 0 or mode == "none":
        return np.ones((num_windows, history_len, num_sensors), dtype=np.uint8)
    simulator = MissingMechanismSimulator(
        mode=mode,
        random_keep_prob=max(0.0, min(1.0, 1.0 - missing_rate)),
    )
    masks = np.empty((num_windows, history_len, num_sensors), dtype=np.uint8)
    for idx in range(num_windows):
        mask = simulator((history_len, num_sensors), seed + idx * 7919)
        masks[idx] = mask.to(torch.uint8).numpy()
    return masks


def generate_or_load_masks(
    path,
    num_windows: int,
    history_len: int,
    num_sensors: int,
    missing_rate: float,
    seed: int,
    mode: str = "mixed",
) -> np.ndarray:
    path = Path(path)
    if path.exists():
        loaded = np.load(path)
        return loaded["mask"].astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    masks = generate_masks_array(num_windows, history_len, num_sensors, missing_rate, seed, mode)
    np.savez_compressed(
        path,
        mask=masks,
        missing_rate=float(missing_rate),
        seed=int(seed),
        mode=str(mode),
    )
    return masks


def generate_or_load_split_masks(
    path,
    split_shapes: Dict[str, Tuple[int, int, int]],
    missing_rate: float,
    seed: int,
    mode: str = "mixed",
) -> Dict[str, np.ndarray]:
    path = Path(path)
    if path.exists():
        loaded = np.load(path)
        return {split: loaded[split].astype(np.uint8) for split in split_shapes}
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {}
    for offset, (split, shape) in enumerate(split_shapes.items()):
        arrays[split] = generate_masks_array(
            shape[0],
            shape[1],
            shape[2],
            missing_rate,
            seed + offset * 100_003,
            mode,
        )
    np.savez_compressed(
        path,
        **arrays,
        missing_rate=float(missing_rate),
        seed=int(seed),
        mode=str(mode),
    )
    return arrays


class MaskedWindowDataset(Dataset):
    def __init__(self, dataset: Dataset, masks: np.ndarray):
        if len(dataset) != len(masks):
            raise ValueError(f"dataset length {len(dataset)} != mask length {len(masks)}")
        self.dataset = dataset
        self.masks = masks.astype(np.uint8)

    def __len__(self) -> int:
        return len(self.dataset)

    def __getitem__(self, index: int):
        sample = self.dataset[index]
        mask = torch.tensor(self.masks[index], dtype=torch.float32)
        return replace(sample, M_obs=mask, X_obs=sample.X_obs * mask)
