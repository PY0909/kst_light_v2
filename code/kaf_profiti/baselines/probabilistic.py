"""Chapter-4 probabilistic baselines on the unified distribution API (CH2.5-P02-T03).

The factory assembles the seven models of the Chapter-4 probabilistic matrix:
five diagonal Gaussian baselines (TCN-Gaussian, PatchTST-Gaussian, GRU-D
Gaussian, ODE-RNN Gaussian, GraFITi Gaussian), the ProFITi conditional-flow
baseline and the project's KST ProbFlow. TCN-Gaussian stays a standalone
reference (its unified math is duplicated and behaviorally verified), while
the other compare-code baselines subclass the unified base directly. Paths to
the comparison code are resolved repo-relative; nothing here hardcodes a
machine path.
"""

import sys
from pathlib import Path
from typing import Callable

import torch

from kaf_profiti.baselines.grafiti import GraFITiGaussian
from kaf_profiti.baselines.grud import GRUDGaussian
from kaf_profiti.experiments.model_api import UnifiedFlowModel
from kaf_profiti.models.kst_probflow import KSTProbFlow, KSTProbFlowConfig

_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMPARE_DIRS = (
    _REPO_ROOT / "compare_code" / "TCN-Gaussian",
    _REPO_ROOT / "compare_code" / "probabilistic_baselines",
)
for _compare_dir in _COMPARE_DIRS:
    _dir = str(_compare_dir)
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

from baselines.models import ODERNNGaussian, PatchTSTGaussian, ProFITiGaussian  # noqa: E402
from tcn_gaussian.model import TCNGaussian  # noqa: E402


class UnifiedKSTProbFlow(UnifiedFlowModel):
    """KST ProbFlow adapter: one flow provides NLL, samples and the point path."""

    IMPLEMENTATION = "own"
    SOURCE_IDENTITY = (
        "Project model KST ProbFlow: MultiScaleKAFEncoder asynchronous "
        "regularized-history encoder + dynamic sensor graph + "
        "QueryConditionAdapter with a Student-t low-rank copula flow head "
        "(joint NLL with seeded sampling); NLL and samples come from the same "
        "trained head"
    )
    REQUIRES_TIME_INPUT = True
    ADAPTER = (
        "native sparse input: the encoder consumes the shared observation "
        "mask and real T_obs/T_q event times; no imputation, and no target or "
        "future field enters the prediction paths"
    )

    def __init__(self, model: KSTProbFlow):
        super().__init__()
        self.model = model

    def flow_hidden(self, batch) -> torch.Tensor:
        return self.model.distribution(batch)

    def _flow_nll_rows(self, y_flat, hidden, mq_flat) -> torch.Tensor:
        return self.model.flow_head.nll(y_flat, hidden, mq_flat)

    def _flow_sample(self, hidden, mq_flat, nsamples, generator=None) -> torch.Tensor:
        return self.model.flow_head.sample(
            hidden, mq_flat, nsamples=nsamples, generator=generator
        )


def _build_kst_probflow(
    num_sensors: int,
    context_dim: int,
    pred_len: int,
    hidden_dim: int,
    **kwargs,
) -> UnifiedKSTProbFlow:
    config = KSTProbFlowConfig(
        num_sensors=num_sensors,
        context_dim=context_dim,
        hidden_dim=hidden_dim,
        te_dim=int(kwargs.pop("te_dim", 5)),
        kernel_count=int(kwargs.pop("kernel_count", 2)),
        n_layers=int(kwargs.pop("n_layers", 1)),
        n_heads=int(kwargs.pop("n_heads", 2)),
        preconv_dim=int(kwargs.pop("preconv_dim", 4)),
        patch_lens=tuple(kwargs.pop("patch_lens", (2, 4))),
        graph_layers=int(kwargs.pop("graph_layers", 1)),
        copula_rank=int(kwargs.pop("copula_rank", 8)),
        sample_clip=float(kwargs.pop("sample_clip", 20.0)),
        device=str(kwargs.pop("device", "cpu")),
    )
    return UnifiedKSTProbFlow(KSTProbFlow(config))


_PROB_FACTORIES = {
    "tcn_gaussian": lambda n, c, p, h, kw: TCNGaussian(
        num_sensors=n, context_dim=c, pred_len=p, hidden_dim=h, **kw
    ),
    "patchtst_gaussian": lambda n, c, p, h, kw: PatchTSTGaussian(
        num_sensors=n, context_dim=c, pred_len=p, hidden_dim=h, **kw
    ),
    "gru_d_gaussian": lambda n, c, p, h, kw: GRUDGaussian(
        num_sensors=n, context_dim=c, pred_len=p, hidden_dim=h, **kw
    ),
    "ode_rnn_gaussian": lambda n, c, p, h, kw: ODERNNGaussian(
        num_sensors=n, context_dim=c, pred_len=p, hidden_dim=h, **kw
    ),
    "grafiti_gaussian": lambda n, c, p, h, kw: GraFITiGaussian(
        num_sensors=n, context_dim=c, pred_len=p, hidden_dim=h, **kw
    ),
    "profiti": lambda n, c, p, h, kw: ProFITiGaussian(
        num_sensors=n, context_dim=c, pred_len=p, hidden_dim=h, **kw
    ),
    "kst_probflow": lambda n, c, p, h, kw: _build_kst_probflow(n, c, p, h, **kw),
}


def create_probabilistic_baseline(
    name: str,
    num_sensors: int,
    context_dim: int,
    pred_len: int,
    hidden_dim: int = 64,
    **kwargs,
):
    """Instantiate a registered probabilistic model by its matrix ``model_id``."""

    try:
        factory: Callable = _PROB_FACTORIES[name]
    except KeyError as exc:
        raise KeyError(f"Unknown probabilistic model: {name}") from exc
    return factory(num_sensors, context_dim, pred_len, hidden_dim, kwargs)
