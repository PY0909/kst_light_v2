import pytest

torch = pytest.importorskip("torch")

from kaf_profiti.industrial.risk import risk_from_samples


def test_sample_risk_returns_sensor_horizon_and_device_views():
    samples = torch.tensor(
        [
            [
                [[0.0, 0.0], [2.0, 0.0]],
                [[0.0, 3.0], [0.0, 0.0]],
                [[0.0, 0.0], [0.0, 0.0]],
            ]
        ]
    )
    result = risk_from_samples(
        samples,
        lower=torch.tensor([-1.0, -1.0]),
        upper=torch.tensor([1.0, 1.0]),
        aggregation="any_sensor",
    )
    assert torch.allclose(result["sensor_horizon_risk"], torch.tensor([[[0.0, 1 / 3], [1 / 3, 0.0]]]))
    assert torch.allclose(result["sensor_risk"], torch.tensor([[1 / 3, 1 / 3]]))
    assert torch.allclose(result["horizon_risk"], torch.tensor([[1 / 3, 1 / 3]]))
    assert torch.allclose(result["device_risk"], torch.tensor([2 / 3]))
    assert result["aggregation"] == "any_sensor"


def test_sample_risk_respects_query_mask_and_explicit_aggregation():
    samples = torch.tensor(
        [[[[2.0, 0.0]], [[2.0, 2.0]], [[0.0, 2.0]]]], dtype=torch.float32
    )
    common = dict(lower=torch.tensor([-1.0, -1.0]), upper=torch.tensor([1.0, 1.0]))
    masked = risk_from_samples(
        samples,
        mask=torch.tensor([[[1.0, 0.0]]]),
        aggregation="horizon_max",
        **common,
    )
    assert torch.allclose(masked["sensor_horizon_risk"], torch.tensor([[[2 / 3, 0.0]]]))
    assert torch.allclose(masked["device_risk"], torch.tensor([2 / 3]))
    with pytest.raises(ValueError, match="aggregation"):
        risk_from_samples(samples, aggregation="unknown", **common)


def test_sample_risk_is_monotone_when_more_samples_cross_limits():
    base = torch.zeros(1, 4, 1, 1)
    more = base.clone()
    more[:, 2:, 0, 0] = 2.0
    common = dict(lower=torch.tensor([-1.0]), upper=torch.tensor([1.0]))
    before = risk_from_samples(base, **common)["device_risk"]
    after = risk_from_samples(more, **common)["device_risk"]
    assert bool((after >= before).all())
