"""lite_pipeline_v1 training-pipeline contract and training manifest.

V2-LITE-T01 fixes one reproducible training pipeline for all formal runs:

* ``num_workers=4`` with ``persistent_workers`` (true whenever workers > 0)
* ``pin_memory=true``
* ``non_blocking=true`` host-to-device copies in the train loop
* fp32 training at C0 (``amp_dtype=None`` records the explicit choice)

Every run writes a training manifest carrying ``epoch_seconds``,
``train_seconds``, ``peak_gpu_memory_mb``, ``num_workers``, ``amp_dtype`` and
``parameter_count`` plus the run identity, so pipeline behavior is part of the
artifact identity rather than folklore.
"""

import json
import resource
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import torch

LITE_PIPELINE_VERSION = "lite_pipeline_v1"

#: Evidence status assigned at training time; ``formal_validated`` is only ever
#: assigned downstream by validators, never here.
_RUN_LEVEL_EVIDENCE = {
    "smoke": "smoke_passed",
    "formal": "full_completed",
}


@dataclass(frozen=True)
class LitePipeline:
    """The pinned loader/transfer configuration (device-independent flags)."""

    version: str = LITE_PIPELINE_VERSION
    num_workers: int = 4
    pin_memory: bool = True
    persistent_workers: bool = True
    non_blocking: bool = True
    amp_dtype: Optional[str] = None

    @classmethod
    def resolve(cls, device, num_workers: int = 4) -> "LitePipeline":
        """Resolve the pipeline for a device.

        The flag contract is device-independent; torch rejects
        ``persistent_workers=True`` with ``num_workers=0``, so that one flag
        follows the worker count.
        """

        workers = max(int(num_workers), 0)
        return cls(
            num_workers=workers,
            pin_memory=True,
            persistent_workers=workers > 0,
            non_blocking=True,
            amp_dtype=None,
        )

    def dataloader_kwargs(self) -> Dict[str, object]:
        return {
            "num_workers": self.num_workers,
            "pin_memory": self.pin_memory,
            "persistent_workers": self.persistent_workers,
        }


def peak_gpu_memory_mb(device) -> Optional[float]:
    """CUDA allocator peak in MB; None when no CUDA device is in use."""

    if torch.cuda.is_available() and str(device).startswith("cuda"):
        return round(torch.cuda.max_memory_allocated() / (1024**2), 1)
    return None


def peak_host_memory_mb() -> float:
    """Process peak RSS in MB (macOS reports bytes, Linux kilobytes)."""

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(peak / (1024**2), 1)
    return round(peak / 1024, 1)


def build_training_manifest(
    *,
    pipeline: LitePipeline,
    epoch_seconds: List[float],
    train_seconds: float,
    peak_gpu_memory_mb: Optional[float],
    parameter_count: int,
    identity: Dict[str, object],
    peak_host_memory_mb: Optional[float] = None,
    run_level: str,
    test_evaluation_count: int,
) -> Dict[str, object]:
    """Assemble the training manifest for one run."""

    if run_level not in _RUN_LEVEL_EVIDENCE:
        raise ValueError(f"unknown run_level {run_level!r}")
    manifest: Dict[str, object] = {
        "schema": "training-manifest-v1",
        "recipe_version": pipeline.version,
        "run_level": run_level,
        "evidence_status": _RUN_LEVEL_EVIDENCE[run_level],
        "test_evaluation_count": int(test_evaluation_count),
        "epoch_seconds": [float(s) for s in epoch_seconds],
        "train_seconds": float(train_seconds),
        "peak_gpu_memory_mb": peak_gpu_memory_mb,
        "peak_host_memory_mb": peak_host_memory_mb,
        "num_workers": pipeline.num_workers,
        "pin_memory": pipeline.pin_memory,
        "persistent_workers": pipeline.persistent_workers,
        "non_blocking": pipeline.non_blocking,
        "amp_dtype": pipeline.amp_dtype,
        "parameter_count": int(parameter_count),
        "identity": dict(identity),
    }
    if run_level == "smoke":
        manifest["eligibility"] = "tuning_only"
    return manifest


def write_training_manifest(path, manifest: Dict[str, object]) -> None:
    """Atomically write a training manifest JSON."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
