"""CH2.5-P01-T05: global metric accumulation tests.

Metrics must be computed from globally accumulated sums (absolute-error sum,
squared-error sum, log-score sum, coverage count, width sum, and one unified
valid count), so the same predictions evaluate identically under any batch
size. RMSE comes from the global squared-error sum; averaging per-batch RMSE
is a defect. Point-only outputs must report probabilistic metrics as
null / not_applicable.
"""

import math
import sys
from pathlib import Path

import pytest
import torch

from kaf_profiti.experiments.accumulators import GlobalMetricAccumulator
from kaf_profiti.industrial.batch import IndustrialBatch

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _extra in (
    _REPO_ROOT / "compare_code" / "TCN-Gaussian",
    _REPO_ROOT / "compare_code" / "probabilistic_baselines",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))


# --------------------------------------------------------------------------
# Unit tests: global sums, batch-size invariance, point-only guards.
# --------------------------------------------------------------------------


def _case_tensors():
    y = torch.tensor([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0], [9.0, 10.0]])
    mean = torch.tensor(
        [[1.5, 1.0], [4.0, 4.0], [5.0, 7.5], [6.5, 8.0], [9.0, 10.5]]
    )
    mask = torch.tensor([[1.0, 1.0], [1.0, 0.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0]])
    return y, mean, mask


def test_accumulator_matches_global_computation_and_is_batch_invariant():
    y, mean, mask = _case_tensors()
    valid = mask > 0
    diff = (mean - y) * valid
    expected_mae = float(diff.abs().sum() / valid.sum())
    expected_rmse = float(torch.sqrt(diff.pow(2).sum() / valid.sum()))

    def accumulate(sizes):
        acc = GlobalMetricAccumulator()
        offset = 0
        for size in sizes:
            acc.update_point(
                y[offset : offset + size], mean[offset : offset + size], mask[offset : offset + size]
            )
            n_positions = int(valid[offset : offset + size].sum())
            acc.update_nll(float(n_positions) * 0.5, float(n_positions))
            acc.update_crps(float(n_positions) * 0.25, float(n_positions))
            acc.update_interval_means("main", 0.9, 3.0, float(n_positions))
            offset += size
        return acc.result()

    whole = accumulate([5])
    split = accumulate([2, 3])
    odd = accumulate([1, 1, 1, 1, 1])

    for key, expected in (
        ("mae", expected_mae),
        ("rmse", expected_rmse),
        ("nll", 0.5),
        ("crps", 0.25),
        ("picp", 0.9),
        ("mpiw", 3.0),
    ):
        assert whole[key] == pytest.approx(expected, rel=1e-6), key
        assert split[key] == pytest.approx(whole[key], rel=1e-9), key
        assert odd[key] == pytest.approx(whole[key], rel=1e-9), key
    assert whole["valid_count"] == 9


def test_rmse_comes_from_global_squared_sum_not_batch_means():
    acc_a = GlobalMetricAccumulator()
    acc_a.update_point(
        torch.zeros(10), torch.ones(10), torch.ones(10)
    )  # squared sum 10 over 10 positions
    acc_a.update_point(
        torch.zeros(10), torch.full((10,), 3.0), torch.ones(10)
    )  # squared sum 90 over 10 positions

    result = acc_a.result()
    assert result["rmse"] == pytest.approx(math.sqrt(100.0 / 20.0))
    assert result["rmse"] != pytest.approx((1.0 + 3.0) / 2.0)


def test_point_only_output_forces_probabilistic_metrics_null():
    acc = GlobalMetricAccumulator()
    acc.update_point(torch.ones(4), torch.ones(4), torch.ones(4))

    result = acc.point_only_result()
    assert result["mae"] == pytest.approx(0.0)
    assert result["nll"] is None
    assert result["crps"] is None
    assert result["picp"] is None
    assert result["mpiw"] is None
    assert result["probabilistic_metrics"] == "not_applicable"

    acc.update_nll(1.0, 4.0)
    with pytest.raises(ValueError, match="point-only"):
        acc.point_only_result()


def test_invalid_positions_are_excluded_and_empty_is_rejected():
    acc = GlobalMetricAccumulator()
    y = torch.tensor([[1.0, float("nan")], [float("inf"), 4.0]])
    mean = torch.tensor([[1.0, 5.0], [5.0, 6.0]])
    mask = torch.tensor([[1.0, 1.0], [1.0, 0.0]])
    acc.update_point(y, mean, mask)
    result = acc.result()
    assert result["valid_count"] == 1
    assert result["mae"] == pytest.approx(0.0)

    empty = GlobalMetricAccumulator()
    empty.update_point(torch.full((2, 2), float("nan")), torch.zeros(2, 2), torch.ones(2, 2))
    with pytest.raises(ValueError, match="valid"):
        empty.result()


# --------------------------------------------------------------------------
# Shared synthetic protocol: per-row seeded data so values are identical
# under any batch split.
# --------------------------------------------------------------------------

_HISTORY, _PRED, _SENSORS = 8, 3, 4


def _make_row(row_index: int, seed: int):
    generator = torch.Generator().manual_seed(seed * 1000 + row_index)
    x_obs = torch.randn(_HISTORY, _SENSORS, generator=generator)
    y_q = torch.randn(_PRED, _SENSORS, generator=generator)
    m_q = (torch.rand(_PRED, _SENSORS, generator=generator) > 0.25).float()
    m_q[:, 0] = 1.0
    context = torch.randn(3, generator=generator)
    return x_obs, y_q, m_q, context


def _make_batches(sizes, seed: int = 11):
    rows = [_make_row(index, seed) for index in range(sum(sizes))]
    batches = []
    offset = 0
    for size in sizes:
        chunk = rows[offset : offset + size]
        offset += size
        x_obs = torch.stack([row[0] for row in chunk])
        y_q = torch.stack([row[1] for row in chunk])
        m_q = torch.stack([row[2] for row in chunk])
        context = torch.stack([row[3] for row in chunk])
        batches.append(
            IndustrialBatch(
                X_obs=x_obs,
                T_obs=torch.arange(_HISTORY, dtype=torch.float32).repeat(size, 1),
                M_obs=torch.ones(size, _HISTORY, _SENSORS),
                T_q=torch.arange(_HISTORY, _HISTORY + _PRED, dtype=torch.float32).repeat(size, 1),
                Y_q=y_q,
                M_q=m_q,
                context=context,
                y_flat=y_q.reshape(size, -1),
                mq_flat=m_q.reshape(size, -1),
                query_channel_ids=torch.arange(_SENSORS).repeat(_PRED),
                rul=torch.rand(size, generator=torch.Generator().manual_seed(seed)) * 100.0,
                unit_id=torch.arange(size),
            )
        )
    return batches


class _ListLoader:
    def __init__(self, batches):
        self.batches = list(batches)

    def __iter__(self):
        return iter(self.batches)

    def __len__(self):
        return len(self.batches)


_PREDICTION_KEYS = ("mae", "rmse", "nll", "crps", "picp", "mpiw")


def _assert_metric_invariance(metrics_a, metrics_b):
    for key in _PREDICTION_KEYS:
        assert metrics_a[key] == pytest.approx(metrics_b[key], rel=1e-6, abs=1e-8), key


def test_tcn_evaluator_metrics_are_batch_size_invariant():
    from train_tcn_gaussian import TCNGaussianConfig, TCNGaussian, _evaluate
    from tcn_gaussian.model import TCNGaussian as _Model

    model = _Model(
        num_sensors=_SENSORS, context_dim=3, pred_len=_PRED, hidden_dim=8, levels=2
    )
    config = TCNGaussianConfig(dataset="cmapss_fd004", max_eval_batches=0, nsamples=8)

    whole = _evaluate(model, _ListLoader(_make_batches([6])), torch.device("cpu"), config)
    split = _evaluate(model, _ListLoader(_make_batches([2, 4])), torch.device("cpu"), config)
    _assert_metric_invariance(whole, split)


def test_probabilistic_baseline_evaluator_metrics_are_batch_size_invariant():
    from baselines.models import PatchTSTGaussian
    from train_baseline import BaselineConfig, _evaluate

    model = PatchTSTGaussian(
        num_sensors=_SENSORS, context_dim=3, pred_len=_PRED, hidden_dim=8, patch_len=4, patch_stride=2
    )
    config = BaselineConfig(
        dataset="cmapss_fd004", model="patchtst_gaussian", max_eval_batches=0, nsamples=8
    )

    whole = _evaluate(model, _ListLoader(_make_batches([6])), torch.device("cpu"), config)
    split = _evaluate(model, _ListLoader(_make_batches([1, 2, 3])), torch.device("cpu"), config)
    _assert_metric_invariance(whole, split)


def test_run_experiment_evaluator_metrics_are_batch_size_invariant():
    import run_experiment as run_experiment_module
    from run_experiment import ExperimentConfig

    model = _DeterministicGaussianStub()

    def evaluate(sizes):
        config = ExperimentConfig(
            dataset="cmapss_fd004",
            history_len=_HISTORY,
            pred_len=_PRED,
            max_eval_batches=0,
            nsamples=8,
        )
        metrics, _, _, _ = run_experiment_module._evaluate(
            model,
            _ListLoader(_make_batches(sizes)),
            torch.device("cpu"),
            config,
            _SENSORS,
            collect_outputs=False,
        )
        return metrics

    whole = evaluate([6])
    split = evaluate([3, 3])
    _assert_metric_invariance(whole, split)
    for key in ("sample_picp", "sample_mpiw"):
        assert whole[key] == pytest.approx(split[key], rel=1e-6), key


class _StubFlowHead:
    """Deterministic Gaussian head whose outputs depend only on row content."""

    scale = 1.2
    sample_clip = 30.0
    attention_diag_floor = 0.05

    def nll(self, y_flat, hidden, mask):
        mean = hidden + 0.1
        log_prob = (
            -0.5 * ((y_flat - mean) / self.scale).pow(2)
            - math.log(self.scale)
            - 0.5 * math.log(2.0 * math.pi)
        )
        return -(log_prob * mask).sum(dim=-1) / mask.sum(dim=-1).clamp_min(1.0)

    def sample(self, hidden, mask, nsamples=8):
        levels = torch.linspace(-1.8, 1.8, int(nsamples)).view(1, int(nsamples), 1)
        center = (hidden + 0.1).unsqueeze(1)
        return center + levels * self.scale

    def crps(self, y_flat, samples, mask):
        term1 = (samples - y_flat.unsqueeze(1)).abs().mean(dim=1)
        pairwise = (samples.unsqueeze(2) - samples.unsqueeze(1)).abs().mean(dim=(1, 2))
        crps = (term1 - 0.5 * pairwise) * mask
        return crps.sum() / mask.sum().clamp_min(1.0)


class _DeterministicGaussianStub(torch.nn.Module):
    """Stub model matching the kst_probflow evaluation interface."""

    def __init__(self):
        super().__init__()
        self.flow_head = _StubFlowHead()

    def distribution(self, batch):
        # [B, P*N]: deterministic per-row encoding of the observed history.
        sensor_mean = batch.X_obs.mean(dim=1)  # [B, N]
        return sensor_mean.repeat(1, _PRED)

    def forward(self, batch):
        return self.distribution(batch)
