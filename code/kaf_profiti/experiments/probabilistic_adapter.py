"""V2-CH4-CODE-T01: unified probabilistic adapter over the ch4 matrix models.

Every chapter-4 model enters evaluation through one surface:

* ``point_mean(batch)`` — deterministic point forecast; for flows this is the
  model's own fixed caliber (seeded sample mean or flow base mean), never an
  independently trained head
* ``sample(batch, nsamples)`` — ``[B, S, P*N]`` samples, masked-zero, finite
* ``quantiles(batch, levels)`` — ``[L, B, P*N]`` quantiles, monotone
  non-decreasing in the level (Gaussian z-scale for diagonal heads, seeded
  sample quantiles for flows)
* ``nll(batch)`` — the model's own distribution NLL

Point-only models never enter silently: they require an explicitly attached
Gaussian head (``adapted_gaussian``), whose scale is a real trainable
parameter and whose head type lands in the run manifest.
"""

import math
from dataclasses import dataclass
from typing import Tuple

import torch

from kaf_profiti.experiments.model_api import UnifiedGaussianModel

#: Default central-interval levels recorded in every probabilistic manifest.
DEFAULT_QUANTILE_LEVELS = (0.025, 0.975)

#: Seeded generator for adapters that must derive flow quantiles themselves.
ADAPTER_QUANTILE_SEED = 20260913


class GaussianHeadPointAdapter(UnifiedGaussianModel):
    """Explicit diagonal-Gaussian head over a point-only model.

    The wrapped model supplies the mean (``predict_point``); the scale is a
    trainable per-position parameter created lazily on the first batch (so
    the adapter needs no shape knowledge at construction time).
    """

    def __init__(self, point_model, num_flat: int = None):
        super().__init__()
        self.point_model = point_model
        self.log_scale = None
        if num_flat is not None:
            # eager construction: the parameter exists before any optimizer is
            # built, so trainers that create the optimizer before the first
            # forward still train the scale
            self.log_scale = torch.nn.Parameter(torch.zeros(int(num_flat)))

    def _ensure_scale(self, batch) -> None:
        if self.log_scale is None:
            # lazy fallback: NOTE an optimizer built before the first forward
            # will not see this parameter — prefer passing num_flat
            num_flat = int(batch.y_flat.shape[-1])
            self.log_scale = torch.nn.Parameter(torch.zeros(num_flat))

    def gaussian_params(self, batch):
        self._ensure_scale(batch)
        mean = self.point_model.predict_point(batch).reshape(batch.y_flat.shape)
        mean = mean.reshape(-1, *batch.Y_q.shape[1:])
        scale = torch.nn.functional.softplus(self.log_scale) + self.min_scale
        scale = scale.reshape(1, *batch.Y_q.shape[1:]).expand_as(batch.Y_q)
        return mean, scale


@dataclass(frozen=True)
class ProbabilisticAdapter:
    """The chapter-4 evaluation surface for one registered model."""

    model: object
    head_type: str
    gaussian_kind: str
    selection_metric: str = "valid_crps"
    quantile_levels: Tuple[float, ...] = DEFAULT_QUANTILE_LEVELS

    # -- unified surface ---------------------------------------------------

    def point_mean(self, batch) -> torch.Tensor:
        """[B, P*N]; flows use the model's own deterministic caliber."""

        return self.model.predict_point(batch)

    def sample(self, batch, nsamples: int) -> torch.Tensor:
        """[B, S, P*N], masked-zero per ``mq_flat``."""

        return self.model.sample_flat(batch, nsamples=nsamples)

    def nll(self, batch) -> float:
        return float(self.model.batch_nll(batch).detach())

    def distribution(self, batch) -> dict:
        """Distribution representation for the manifest/evaluator layer.

        Diagonal heads expose closed-form (mean, scale); flows are
        sample-based — the representation names the kind and the seeded
        sample path (``sample``) as the distribution, never a surrogate.
        """

        if self.gaussian_kind == "diagonal":
            mean, scale = self.model.gaussian_params(batch)
            return {
                "kind": "diagonal_gaussian",
                "mean": mean.detach(),
                "scale": scale.detach(),
            }
        return {
            "kind": "flow_samples",
            "sample_accessor": "sample",
            "nsamples_hint": int(getattr(self.model, "interval_nsamples", 128)),
        }

    def quantiles(self, batch, levels) -> torch.Tensor:
        """[L, B, P*N] quantiles, monotone non-decreasing in level."""

        levels = tuple(float(level) for level in levels)
        if self.gaussian_kind == "diagonal":
            mean, scale = self.model.gaussian_params(batch)
            mean_flat = mean.reshape(batch.y_flat.shape)
            scale_flat = scale.reshape(batch.y_flat.shape)
            stack = []
            for level in levels:
                z = torch.special.ndtri(
                    torch.tensor(level, dtype=mean_flat.dtype, device=mean_flat.device)
                )
                stack.append(mean_flat + z * scale_flat)
            return torch.stack(stack, dim=0)
        # flow: seeded sample quantiles — the same distribution sample_flat
        # and batch_nll come from, never a separate fit
        nsamples = int(getattr(self.model, "interval_nsamples", 128))
        device = batch.X_obs.device
        generator = torch.Generator(device=device)
        generator.manual_seed(int(getattr(self.model, "point_seed", ADAPTER_QUANTILE_SEED)))
        samples = self.model.sample_flat(batch, nsamples=nsamples, generator=generator)
        return torch.stack(
            [torch.quantile(samples, level, dim=1) for level in levels], dim=0
        )

    # -- manifest identity ---------------------------------------------------

    def manifest_identity(self) -> dict:
        identity = {
            "model_class": type(self.model).__name__,
            "head_type": self.head_type,
            "gaussian_kind": self.gaussian_kind,
            "selection_metric": self.selection_metric,
            "quantile_levels": list(self.quantile_levels),
        }
        for field in ("point_nsamples", "point_seed", "interval_nsamples"):
            value = getattr(self.model, field, None)
            if value is not None:
                identity[field] = value
        return identity


def adapt_probabilistic(
    model, explicit_gaussian_head: bool = False, num_flat: int = None
) -> ProbabilisticAdapter:
    """Adapt a registered model to the chapter-4 probabilistic surface.

    Flow models are detected by ``gaussian_kind == "flow"`` (duck-typed, so
    both ``UnifiedFlowModel`` subclasses and the standalone ``KSTFlowV2``
    qualify). Point-only models raise unless an explicit Gaussian head is
    requested — a silent Gaussian fallback is exactly what the plan forbids.
    """

    if not callable(getattr(model, "predict_point", None)):
        raise ValueError(
            "adapt_probabilistic: model does not provide the probabilistic "
            "surface (sample_flat/batch_nll/predict_point)"
        )
    kind = str(getattr(model, "gaussian_kind", "diagonal"))
    if kind == "flow":
        if not callable(getattr(model, "sample_flat", None)) or not callable(
            getattr(model, "batch_nll", None)
        ):
            raise ValueError(
                "adapt_probabilistic: flow model lacks sample_flat/batch_nll"
            )
        return ProbabilisticAdapter(model=model, head_type="flow", gaussian_kind="flow")
    if callable(getattr(model, "gaussian_params", None)):
        return ProbabilisticAdapter(
            model=model, head_type="gaussian_diag", gaussian_kind="diagonal"
        )
    if explicit_gaussian_head:
        wrapped = GaussianHeadPointAdapter(model, num_flat=num_flat)
        return ProbabilisticAdapter(
            model=wrapped, head_type="adapted_gaussian", gaussian_kind="diagonal"
        )
    raise ValueError(
        "adapt_probabilistic: point-only model — the ch4 matrix requires a "
        "probabilistic head; attach an explicit Gaussian head "
        "(explicit_gaussian_head=True) before entering the matrix"
    )


__all__ = [
    "ADAPTER_QUANTILE_SEED",
    "DEFAULT_QUANTILE_LEVELS",
    "GaussianHeadPointAdapter",
    "ProbabilisticAdapter",
    "adapt_probabilistic",
]
