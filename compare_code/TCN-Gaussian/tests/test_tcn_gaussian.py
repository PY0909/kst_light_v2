import torch
from torch.utils.data import DataLoader

from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.industrial.batch import IndustrialCollator
from tcn_gaussian.model import TCNGaussian


DATA_ROOT = "/home/work/new_work/dataset"


def _make_batch(batch_size=3, history_len=12, pred_len=4, num_sensors=5, context_dim=2):
    generator = torch.Generator().manual_seed(123)
    x = torch.randn(batch_size, history_len, num_sensors, generator=generator)
    mask = (torch.rand(batch_size, history_len, num_sensors, generator=generator) > 0.25).float()
    context = torch.randn(batch_size, context_dim, generator=generator)
    y = torch.randn(batch_size, pred_len, num_sensors, generator=generator)
    return x * mask, mask, context, y


def test_tcn_gaussian_outputs_finite_distribution_and_samples():
    x, mask, context, y = _make_batch()
    model = TCNGaussian(
        num_sensors=5,
        context_dim=2,
        pred_len=4,
        hidden_dim=16,
        levels=2,
    )

    mean, scale = model(x, mask, context)
    loss = model.nll(y, mean, scale)
    samples = model.sample(x, mask, context, nsamples=7)

    assert mean.shape == y.shape
    assert scale.shape == y.shape
    assert samples.shape == (3, 7, 4, 5)
    assert torch.isfinite(mean).all()
    assert torch.isfinite(scale).all()
    assert torch.isfinite(loss)
    assert torch.isfinite(samples).all()


def test_tcn_gaussian_accepts_metropt_cmapss_and_tep_batches():
    protocols = [
        ("metropt3_chrono_502030", 12, 3, 100_000),
        ("cmapss_fd001", 12, 3, 120),
    ]
    for dataset, history_len, pred_len, stride in protocols:
        bundle = create_protocol_datasets(
            dataset,
            DATA_ROOT,
            seed=2026,
            history_len=history_len,
            pred_len=pred_len,
            stride=stride,
            async_mode="none",
        )
        loader = DataLoader(
            bundle.train,
            batch_size=2,
            shuffle=False,
            collate_fn=IndustrialCollator(),
        )
        batch = next(iter(loader))
        model = TCNGaussian(
            num_sensors=bundle.num_sensors,
            context_dim=bundle.context_dim,
            pred_len=pred_len,
            hidden_dim=16,
            levels=2,
        )

        mean, scale = model(batch.X_obs, batch.M_obs, batch.context)
        loss = model.nll(batch.Y_q, mean, scale, batch.M_q)

        assert mean.shape == batch.Y_q.shape
        assert scale.shape == batch.Y_q.shape
        assert torch.isfinite(loss)


def test_tcn_gaussian_supports_tep_dimensions_when_dataverse_files_are_absent():
    x, mask, context, y = _make_batch(
        batch_size=2,
        history_len=12,
        pred_len=3,
        num_sensors=52,
        context_dim=11,
    )
    model = TCNGaussian(
        num_sensors=52,
        context_dim=11,
        pred_len=3,
        hidden_dim=16,
        levels=2,
    )

    mean, scale = model(x, mask, context)
    loss = model.nll(y, mean, scale)

    assert mean.shape == y.shape
    assert scale.shape == y.shape
    assert torch.isfinite(loss)


def test_tcn_gaussian_accepts_real_tep_batch_when_available():
    data_root = __import__("pathlib").Path(DATA_ROOT)
    if not (data_root / "dataverse_files").exists():
        import pytest

        pytest.skip("TEP dataverse_files are not available in this workspace")

    bundle = create_protocol_datasets(
        "tep",
        DATA_ROOT,
        seed=2026,
        history_len=12,
        pred_len=3,
        stride=250,
        async_mode="none",
    )
    batch = next(
        iter(
            DataLoader(
                bundle.train,
                batch_size=2,
                shuffle=False,
                collate_fn=IndustrialCollator(),
            )
        )
    )
    model = TCNGaussian(
        num_sensors=bundle.num_sensors,
        context_dim=bundle.context_dim,
        pred_len=3,
        hidden_dim=16,
        levels=2,
    )

    mean, scale = model(batch.X_obs, batch.M_obs, batch.context)
    loss = model.nll(batch.Y_q, mean, scale, batch.M_q)

    assert mean.shape == batch.Y_q.shape
    assert scale.shape == batch.Y_q.shape
    assert torch.isfinite(loss)
