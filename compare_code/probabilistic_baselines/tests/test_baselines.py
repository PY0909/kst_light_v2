import pytest
import torch
from torch.utils.data import DataLoader

from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.industrial.batch import IndustrialCollator
from baselines.models import create_baseline_model, list_baseline_models


DATA_ROOT = "/home/work/new_work/dataset"


def _make_inputs(batch_size=3, history_len=24, pred_len=5, num_sensors=7, context_dim=2):
    generator = torch.Generator().manual_seed(123)
    x = torch.randn(batch_size, history_len, num_sensors, generator=generator)
    mask = (torch.rand(batch_size, history_len, num_sensors, generator=generator) > 0.25).float()
    context = torch.randn(batch_size, context_dim, generator=generator)
    t_obs = torch.linspace(0, 1, history_len).repeat(batch_size, 1)
    t_q = torch.linspace(1.01, 1.2, pred_len).repeat(batch_size, 1)
    y = torch.randn(batch_size, pred_len, num_sensors, generator=generator)
    return x * mask, t_obs, mask, t_q, context, y


@pytest.mark.parametrize("model_name", list_baseline_models())
def test_baseline_models_emit_finite_gaussian_outputs(model_name):
    x, t_obs, mask, t_q, context, y = _make_inputs()
    model = create_baseline_model(
        model_name,
        num_sensors=7,
        context_dim=2,
        pred_len=5,
        hidden_dim=16,
        levels=2,
        patch_len=4,
        patch_stride=2,
    )

    mean, scale = model(x, mask, context, t_obs=t_obs, t_q=t_q)
    loss = model.nll(y, mean, scale)
    samples = model.sample(x, mask, context, nsamples=6, t_obs=t_obs, t_q=t_q)
    risk = model.risk_score(mean, scale)

    assert mean.shape == y.shape
    assert scale.shape == y.shape
    assert samples.shape == (3, 6, 5, 7)
    assert risk.shape == (3,)
    assert torch.isfinite(mean).all()
    assert torch.isfinite(scale).all()
    assert torch.isfinite(loss)
    assert torch.isfinite(samples).all()
    assert torch.isfinite(risk).all()


@pytest.mark.parametrize(
    ("dataset", "history_len", "pred_len", "stride"),
    [
        ("metropt3_chrono_502030", 12, 3, 100_000),
        ("cmapss_fd001", 12, 3, 120),
        ("tep", 12, 3, 120),
    ],
)
def test_baseline_models_accept_project_protocol_batches(dataset, history_len, pred_len, stride):
    try:
        bundle = create_protocol_datasets(
            dataset,
            DATA_ROOT,
            seed=2026,
            history_len=history_len,
            pred_len=pred_len,
            stride=stride,
            async_mode="none",
        )
    except FileNotFoundError:
        if dataset == "tep":
            pytest.skip("TEP dataverse files are not available in this workspace")
        raise

    loader = DataLoader(bundle.train, batch_size=2, shuffle=False, collate_fn=IndustrialCollator())
    batch = next(iter(loader))
    for model_name in list_baseline_models():
        model = create_baseline_model(
            model_name,
            num_sensors=bundle.num_sensors,
            context_dim=bundle.context_dim,
            pred_len=pred_len,
            hidden_dim=16,
            levels=2,
            patch_len=4,
            patch_stride=2,
        )
        mean, scale = model(
            batch.X_obs,
            batch.M_obs,
            batch.context,
            t_obs=batch.T_obs,
            t_q=batch.T_q,
        )
        assert mean.shape == batch.Y_q.shape
        assert scale.shape == batch.Y_q.shape
        assert torch.isfinite(mean).all()
        assert torch.isfinite(scale).all()
