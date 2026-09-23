"""Validated, portable configuration for Chapter 3 experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import yaml


CORE_SEEDS = frozenset({2026, 2027, 2028})
DATASETS = frozenset({"metropt3_chrono_502030", "cmapss_fd004", "tep"})
MISSING_MODES = frozenset({"random", "low_rate", "block_offline", "mixed"})
HEAD_TYPES = frozenset({"linear", "mlp"})
RUN_LEVELS = frozenset({"smoke", "tuning", "pilot", "formal", "profile"})

# CH2.5 pre-experiment track: the pilot level is FD004-only, single-seed, and
# must never be consumed as formal evidence (see plan section 12.1 rule 2).
PILOT_DATASET = "cmapss_fd004"
PILOT_SPLIT_SEED = 2026
PILOT_WINDOWS = {"history_len": 50, "pred_len": 10, "stride": 1}
PILOT_OVERRIDABLE_FIELDS = frozenset({"seed", "mask_seed", "experiment_id"})


@dataclass(frozen=True)
class Ch3ExperimentConfig:
    """Scientific configuration that is independent of machine-specific paths."""

    experiment_id: str
    dataset: str
    model: str
    seed: int
    split_seed: int
    mask_seed: int
    history_len: int
    pred_len: int
    stride: int
    missing_mode: str
    target_missing_rate: float
    epochs: int
    batch_size: int
    hidden_dim: int
    head_type: str
    run_level: str
    max_train_batches: int | None
    max_eval_batches: int | None

    def __post_init__(self) -> None:
        self.validate()

    @property
    def allows_test_loader(self) -> bool:
        """Whether a runner may construct a test loader at this run level."""

        return self.run_level != "tuning"

    @property
    def is_formal_evidence(self) -> bool:
        """Whether this run level may ever feed a formal catalog or thesis table."""

        return self.run_level == "formal"

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        overrides: Mapping[str, Any] | None = None,
    ) -> "Ch3ExperimentConfig":
        return from_yaml(path, overrides)

    def with_overrides(self, overrides: Mapping[str, Any]) -> "Ch3ExperimentConfig":
        """Return a separately validated configuration with named overrides."""

        unknown_keys = set(overrides) - set(self.to_dict())
        if unknown_keys:
            unknown = ", ".join(sorted(unknown_keys))
            raise ValueError(f"Unknown Chapter 3 config override(s): {unknown}")
        if self.run_level == "pilot":
            forbidden = set(overrides) - PILOT_OVERRIDABLE_FIELDS
            if forbidden:
                blocked = ", ".join(sorted(forbidden))
                raise ValueError(
                    "Pilot configs only allow run-identity overrides "
                    f"(seed/mask_seed/experiment_id); refusing: {blocked}"
                )
        return replace(self, **dict(overrides))

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable copy of the scientific configuration."""

        return asdict(self)

    def validate(self) -> None:
        """Reject scientific configurations that violate the locked protocol."""

        _require_nonempty_string("experiment_id", self.experiment_id)
        _require_nonempty_string("model", self.model)
        _require_allowed_string("dataset", self.dataset, DATASETS)
        if not _is_positive_int(self.seed) or self.seed not in CORE_SEEDS:
            raise ValueError(f"seed must be one of {sorted(CORE_SEEDS)}")
        if not _is_positive_int(self.mask_seed) or self.mask_seed != self.seed:
            raise ValueError("mask_seed must equal seed for Chapter 3 runs")
        if not _is_positive_int(self.split_seed):
            raise ValueError("split_seed must be a positive integer")
        for name, value in {
            "history_len": self.history_len,
            "pred_len": self.pred_len,
            "stride": self.stride,
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "hidden_dim": self.hidden_dim,
        }.items():
            if not _is_positive_int(value):
                raise ValueError(f"{name} must be a positive integer")
        _require_allowed_string("missing_mode", self.missing_mode, MISSING_MODES)
        if not _is_rate(self.target_missing_rate):
            raise ValueError("target_missing_rate must be between 0.0 and 1.0")
        _require_allowed_string("head_type", self.head_type, HEAD_TYPES)
        _require_allowed_string("run_level", self.run_level, RUN_LEVELS)
        _validate_batch_limit("max_train_batches", self.max_train_batches)
        _validate_batch_limit("max_eval_batches", self.max_eval_batches)
        if self.run_level == "formal":
            if self.epochs < 2:
                raise ValueError("formal runs require epochs >= 2")
            if self.max_train_batches and self.max_train_batches > 0:
                raise ValueError("formal runs cannot limit training batches")
            if self.max_eval_batches and self.max_eval_batches > 0:
                raise ValueError("formal runs cannot limit evaluation batches")
            if self.split_seed != 2026:
                raise ValueError("formal runs require split_seed=2026")
        if self.run_level == "pilot":
            if self.dataset != PILOT_DATASET:
                raise ValueError(
                    f"pilot runs are restricted to dataset={PILOT_DATASET}"
                )
            if self.split_seed != PILOT_SPLIT_SEED:
                raise ValueError(
                    f"pilot runs require split_seed={PILOT_SPLIT_SEED}"
                )
            for name, expected in PILOT_WINDOWS.items():
                if getattr(self, name) != expected:
                    raise ValueError(
                        f"pilot runs require {name}={expected}"
                    )
            if self.epochs < 2:
                raise ValueError("pilot runs require epochs >= 2")
            if self.max_train_batches and self.max_train_batches > 0:
                raise ValueError("pilot runs cannot limit training batches")
            if self.max_eval_batches and self.max_eval_batches > 0:
                raise ValueError("pilot runs cannot limit evaluation batches")


def from_yaml(
    path: str | Path,
    overrides: Mapping[str, Any] | None = None,
) -> Ch3ExperimentConfig:
    """Load a configuration with ``yaml.safe_load`` and validate all values."""

    config_path = Path(path)
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"Unable to read Chapter 3 config: {config_path}") from error
    if not isinstance(loaded, dict):
        raise ValueError("Chapter 3 YAML must contain a mapping")
    expected_keys = set(Ch3ExperimentConfig.__dataclass_fields__)
    unknown_keys = set(loaded) - expected_keys
    missing_keys = expected_keys - set(loaded)
    if unknown_keys or missing_keys:
        parts = []
        if unknown_keys:
            parts.append(f"unknown keys: {', '.join(sorted(unknown_keys))}")
        if missing_keys:
            parts.append(f"missing keys: {', '.join(sorted(missing_keys))}")
        raise ValueError("Invalid Chapter 3 YAML schema; " + "; ".join(parts))
    config = Ch3ExperimentConfig(**loaded)
    return config.with_overrides(overrides) if overrides else config


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_rate(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0.0 <= float(value) <= 1.0
    )


def _require_nonempty_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_allowed_string(name: str, value: object, allowed: frozenset[str]) -> None:
    _require_nonempty_string(name, value)
    if value not in allowed:
        raise ValueError(f"Unsupported {name}: {value}")


def _validate_batch_limit(name: str, value: object) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be null, 0, or a positive integer")
