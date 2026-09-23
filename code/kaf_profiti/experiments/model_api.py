"""Unified point/probabilistic model interface contracts (CH2.5-P02-T01).

Every pilot model is consumed through one trainer and one evaluator, so model
differences come only from encoding and probabilistic structure — never from
different targets or evaluation paths. The contract:

* Point models expose ``predict_point(batch) -> [B, P*N]`` (same flatten order
  as ``batch.y_flat``), a scalar ``loss(batch)`` and ``parameter_count()``.
* Probabilistic models additionally expose ``gaussian_params(batch)`` (diagonal
  mean/scale), ``batch_nll(batch)`` (denominator ``mask.sum()``),
  ``sample_flat(batch, nsamples)`` (``[B, S, P*N]`` masked by ``mq_flat``) and
  ``interval95_flat(batch)``. Flow-based models declare
  ``gaussian_kind = "flow"`` and may derive intervals from samples instead of a
  closed-form scale.
* No prediction path may read the future/target fields ``Y_q``, ``y_flat``,
  ``M_q``, ``mq_flat`` or ``rul``; the check helpers below verify this
  behaviourally by perturbing those fields.

``check_point_interface`` / ``check_gaussian_interface`` run the full public
contract (shapes, finiteness, mask invariance, gradients, save/restore and
history-only usage) and raise ``AssertionError`` with the violated rule.
"""

import copy
import math
from typing import Iterable, Optional, Tuple

import torch
from torch import Tensor, nn

from kaf_profiti.industrial.batch import IndustrialBatch

#: Batch fields a model must never consume on a prediction path.
FORBIDDEN_BATCH_FIELDS = ("Y_q", "y_flat", "M_q", "mq_flat", "rul")

#: Two-sided 95% Gaussian quantile (P95 interval = mean +/- Z95 * scale).
Z95 = 1.959964


def parameter_count(model: nn.Module) -> int:
    """Trainable parameter count as reported next to every pilot run."""

    return int(sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad))


def masked_mse(y_flat: Tensor, prediction: Tensor, mq_flat: Tensor) -> Tensor:
    """Masked MSE with the unified valid-position denominator."""

    return ((prediction - y_flat).pow(2) * mq_flat).sum() / mq_flat.sum().clamp_min(1.0)


def _perturbed_target_batch(batch: IndustrialBatch, seed: int = 4242) -> IndustrialBatch:
    """Copy of ``batch`` with every forbidden field replaced by random values."""

    generator = torch.Generator().manual_seed(seed)
    random_y = torch.randn(batch.Y_q.shape, generator=generator)
    random_m = (torch.rand(batch.M_q.shape, generator=generator) > 0.5).float()
    return IndustrialBatch(
        **{
            **batch.__dict__,
            "Y_q": random_y,
            "y_flat": random_y.reshape(batch.y_flat.shape),
            "M_q": random_m,
            "mq_flat": random_m.reshape(batch.mq_flat.shape),
            "rul": torch.rand(batch.rul.shape, generator=generator) * 1000.0,
        }
    )


def _masked_target_perturbation(batch: IndustrialBatch, seed: int = 777) -> IndustrialBatch:
    """Copy of ``batch`` whose targets change only where the mask is zero."""

    generator = torch.Generator().manual_seed(seed)
    garbage = torch.randn(batch.y_flat.shape, generator=generator)
    y_flat = torch.where(batch.mq_flat > 0, batch.y_flat, garbage)
    y_q = y_flat.reshape(batch.Y_q.shape)
    return IndustrialBatch(**{**batch.__dict__, "Y_q": y_q, "y_flat": y_flat})


def _call(
    model: nn.Module,
    method_name: str,
    batch: IndustrialBatch,
    generator: Optional[torch.Generator] = None,
    nsamples: Optional[int] = None,
):
    method = getattr(model, method_name)
    kwargs = {}
    if generator is not None:
        kwargs["generator"] = generator
    if nsamples is not None:
        kwargs["nsamples"] = int(nsamples)
    return method(batch, **kwargs) if kwargs else method(batch)


def assert_history_only(
    model: nn.Module,
    batch: IndustrialBatch,
    method_names: Iterable[str] = ("predict_point",),
    atol: float = 1e-5,
) -> None:
    """Fail if any prediction method reacts to the forbidden batch fields."""

    was_training = model.training
    model.eval()

    def _clone(output):
        if isinstance(output, tuple):
            return tuple(element.clone() for element in output)
        return output.clone()

    try:
        with torch.no_grad():
            reference = tuple(
                _clone(_call(model, name, batch, None)) for name in method_names
            )
            tampered = tuple(
                _call(model, name, _perturbed_target_batch(batch), None)
                for name in method_names
            )
        for name, expected, actual in zip(method_names, reference, tampered):
            pairs = zip(expected, actual) if isinstance(expected, tuple) else ((expected, actual),)
            for element_index, (expected_part, actual_part) in enumerate(pairs):
                if not torch.allclose(expected_part, actual_part, atol=atol):
                    raise AssertionError(
                        f"{type(model).__name__}.{name} is not history-only: "
                        "its output changed when Y_q/M_q/rul were perturbed"
                        + (f" (output element {element_index})" if isinstance(expected, tuple) else "")
                    )
    finally:
        model.train(was_training)


def _check_round_trip(model: nn.Module, batch: IndustrialBatch, method_name: str) -> None:
    """State must fully determine predictions: perturb, reload, replay."""

    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            reference = _call(model, method_name, batch, None).clone()
            saved = copy.deepcopy(model.state_dict())
            for parameter in model.parameters():
                parameter.data.add_(torch.randn_like(parameter.data) * 0.05)
            model.load_state_dict(saved)
            replay = _call(model, method_name, batch, None)
        assert torch.allclose(reference, replay, atol=1e-6), (
            f"state_dict round-trip changed {method_name} output"
        )
    finally:
        model.train(was_training)


def _check_gradients(model: nn.Module, loss: Tensor) -> None:
    model.zero_grad(set_to_none=True)
    try:
        loss.backward()
    except RuntimeError as error:
        raise AssertionError(
            f"loss is not connected to any trainable parameter: {error}"
        ) from error
    alive = any(
        parameter.grad is not None and bool(parameter.grad.abs().sum() > 0)
        for parameter in model.parameters()
        if parameter.requires_grad
    )
    assert alive, "loss.backward() produced no gradient in any trainable parameter"


def check_point_interface(model: nn.Module, batch: IndustrialBatch) -> None:
    """Run the public point-model contract against one batch."""

    model.eval()
    prediction = model.predict_point(batch)
    assert prediction.shape == batch.y_flat.shape, (
        f"predict_point shape {tuple(prediction.shape)} != y_flat shape "
        f"{tuple(batch.y_flat.shape)}"
    )
    assert bool(torch.isfinite(prediction).all()), "predict_point produced non-finite values"

    loss = model.loss(batch)
    assert loss.dim() == 0, "loss must be a scalar"
    assert bool(torch.isfinite(loss)), "loss is not finite"

    # ``loss`` legitimately consumes the targets; only prediction paths must
    # be history-only.
    assert_history_only(model, batch, ("predict_point",))
    _check_gradients(model, loss)
    _check_round_trip(model, batch, "predict_point")


def _check_mask_invariant_nll(model: nn.Module, batch: IndustrialBatch) -> None:
    model.eval()
    with torch.no_grad():
        reference = _call(model, "batch_nll", batch, None)
        replay = _call(model, "batch_nll", _masked_target_perturbation(batch), None)
    assert torch.allclose(reference, replay, atol=1e-6), (
        "batch_nll changed when only masked-out targets were perturbed; "
        "the NLL denominator/mask handling ignores the valid mask"
    )


def check_gaussian_interface(
    model: nn.Module,
    batch: IndustrialBatch,
    nsamples: int = 256,
) -> None:
    """Run the public probabilistic-model contract against one batch."""

    model.eval()
    prediction = model.predict_point(batch)
    assert prediction.shape == batch.y_flat.shape, (
        f"predict_point shape {tuple(prediction.shape)} != y_flat shape "
        f"{tuple(batch.y_flat.shape)}"
    )
    assert bool(torch.isfinite(prediction).all()), "predict_point produced non-finite values"

    nll = model.batch_nll(batch)
    assert nll.dim() == 0, "batch_nll must be a scalar"
    assert bool(torch.isfinite(nll)), "batch_nll is not finite"
    _check_mask_invariant_nll(model, batch)

    generator = torch.Generator().manual_seed(2026)
    samples = _call(model, "sample_flat", batch, generator=generator, nsamples=nsamples)
    expected_shape = (batch.y_flat.shape[0], int(nsamples)) + batch.y_flat.shape[1:]
    assert samples.shape == expected_shape, (
        f"sample_flat shape {tuple(samples.shape)} != {expected_shape}"
    )
    assert bool(torch.isfinite(samples).all()), "sample_flat produced non-finite values"
    valid = batch.mq_flat > 0
    assert int(valid.sum()) == 0 or bool((samples != 0.0).any()), (
        "sample_flat is all-zero; sampling is broken"
    )
    std = samples.std(dim=1)
    tolerance = 8.0 * std / math.sqrt(float(nsamples)) + 1e-4
    deviation = (samples.mean(dim=1) - prediction).abs()
    assert bool((deviation[valid] <= tolerance[valid]).all()), (
        "sample mean is inconsistent with predict_point beyond sampling noise"
    )

    lower, upper = model.interval95_flat(batch)
    assert lower.shape == batch.y_flat.shape and upper.shape == batch.y_flat.shape
    assert bool(torch.isfinite(lower).all()) and bool(torch.isfinite(upper).all())
    assert bool((upper[valid] >= lower[valid]).all()), "95% interval is inverted"

    if getattr(model, "gaussian_kind", "diagonal") == "diagonal":
        mean, scale = model.gaussian_params(batch)
        assert mean.shape == batch.Y_q.shape and scale.shape == batch.Y_q.shape
        assert bool((scale >= getattr(model, "min_scale", 0.0) - 1e-6).all()), (
            "diagonal scale fell below the declared minimum scale"
        )
        expected_lower = (mean - Z95 * scale).reshape(batch.y_flat.shape)
        assert torch.allclose(lower, expected_lower, atol=1e-5), (
            "interval95_flat does not equal mean - Z95*scale for a diagonal Gaussian"
        )

    # ``batch_nll``/``loss`` consume targets by design (mask invariance is
    # checked separately), and ``sample_flat`` is masked by ``mq_flat`` by
    # contract, so only the unmasked prediction paths must be history-only.
    if getattr(model, "gaussian_kind", "diagonal") == "diagonal":
        assert_history_only(model, batch, ("predict_point", "gaussian_params"))
    else:
        assert_history_only(model, batch, ("predict_point",))
    _check_gradients(model, model.batch_nll(batch))
    _check_round_trip(model, batch, "predict_point")


class UnifiedPointModel(nn.Module):
    """Base class for point pilot models with the shared loss and counts.

    Subclasses implement :meth:`predict_point` over history-only fields; the
    masked MSE and parameter count come from the unified contract.
    """

    def predict_point(self, batch: IndustrialBatch) -> Tensor:
        raise NotImplementedError

    def loss(self, batch: IndustrialBatch) -> Tensor:
        return masked_mse(batch.y_flat, self.predict_point(batch), batch.mq_flat)

    def parameter_count(self) -> int:
        return parameter_count(self)


class UnifiedGaussianModel(nn.Module):
    """Base class for probabilistic pilot models.

    Diagonal subclasses implement :meth:`gaussian_params` returning
    ``(mean, scale)`` of shape ``[B, P, N]`` with ``scale >= min_scale``.
    Flow-based subclasses set ``gaussian_kind = "flow"`` and override
    ``batch_nll``/``sample_flat``/``interval95_flat``/``predict_point`` from a
    single shared distribution.
    """

    gaussian_kind = "diagonal"
    min_scale = 0.05
    lambda_point = 0.1

    def gaussian_params(self, batch: IndustrialBatch) -> Tuple[Tensor, Tensor]:
        raise NotImplementedError

    def predict_point(self, batch: IndustrialBatch) -> Tensor:
        mean, _ = self.gaussian_params(batch)
        return mean.reshape(batch.y_flat.shape)

    def batch_nll(self, batch: IndustrialBatch) -> Tensor:
        mean, scale = self.gaussian_params(batch)
        log_prob = (
            -0.5 * ((batch.Y_q - mean) / scale).pow(2)
            - torch.log(scale)
            - 0.5 * math.log(2.0 * math.pi)
        )
        return -((log_prob * batch.M_q).sum() / batch.M_q.sum().clamp_min(1.0))

    def batch_nll_rows(self, batch: IndustrialBatch) -> Tensor:
        """Per-row NLL sums over valid positions (``[B]``).

        Rows are raw sums (not per-position averages) so
        ``rows.sum() == batch_nll * mq_flat.sum()``; evaluators accumulate
        ``rows.sum()`` against the global valid-position count.
        """

        mean, scale = self.gaussian_params(batch)
        log_prob = (
            -0.5 * ((batch.Y_q - mean) / scale).pow(2)
            - torch.log(scale)
            - 0.5 * math.log(2.0 * math.pi)
        )
        return -((log_prob * batch.M_q).sum(dim=(1, 2)))

    def sample_flat(
        self,
        batch: IndustrialBatch,
        nsamples: int = 100,
        generator: Optional[torch.Generator] = None,
    ) -> Tensor:
        mean, scale = self.gaussian_params(batch)
        flat_mean = mean.reshape(batch.y_flat.shape)
        flat_scale = scale.reshape(batch.y_flat.shape)
        eps = torch.randn(
            flat_mean.shape[0], int(nsamples), flat_mean.shape[1],
            device=flat_mean.device, dtype=flat_mean.dtype, generator=generator,
        )
        samples = flat_mean.unsqueeze(1) + flat_scale.unsqueeze(1) * eps
        mask = batch.mq_flat.unsqueeze(1) > 0
        return torch.where(mask, samples, torch.zeros_like(samples))

    def interval95_flat(self, batch: IndustrialBatch) -> Tuple[Tensor, Tensor]:
        mean, scale = self.gaussian_params(batch)
        flat_mean = mean.reshape(batch.y_flat.shape)
        flat_scale = scale.reshape(batch.y_flat.shape)
        return flat_mean - Z95 * flat_scale, flat_mean + Z95 * flat_scale

    def loss(self, batch: IndustrialBatch) -> Tensor:
        return self.batch_nll(batch) + self.lambda_point * masked_mse(
            batch.y_flat, self.predict_point(batch), batch.mq_flat
        )

    def parameter_count(self) -> int:
        return parameter_count(self)


class UnifiedFlowModel(UnifiedGaussianModel):
    """Flow-based probabilistic models whose NLL and samples share one flow.

    Subclasses provide the flow conditioning ``flow_hidden(batch)`` (history
    only) plus per-row flow NLL and flow sampling. The unified methods then
    obey the same contract as the diagonal base: ``batch_nll`` keeps the
    valid-position denominator (per-row NLLs are re-weighted by each row's
    valid count), ``sample_flat`` is masked by ``mq_flat``, and
    ``predict_point`` is a deterministic seeded sample mean — never read from
    a different distribution than the one ``batch_nll`` trains. The point
    prediction uses an all-ones mask so it stays history-only; masking to zero
    happens only in ``sample_flat`` where the query mask belongs.
    """

    gaussian_kind = "flow"
    point_nsamples = 64
    point_seed = 20260913
    interval_nsamples = 256

    def flow_hidden(self, batch: IndustrialBatch) -> Tensor:
        raise NotImplementedError

    def _flow_nll_rows(self, y_flat: Tensor, hidden: Tensor, mq_flat: Tensor) -> Tensor:
        """Per-row flow NLL (any per-row normalization is fine; re-weighted)."""
        raise NotImplementedError

    def _flow_sample(
        self,
        hidden: Tensor,
        mq_flat: Tensor,
        nsamples: int,
        generator: Optional[torch.Generator] = None,
    ) -> Tensor:
        raise NotImplementedError

    def _seeded_generator(self, device) -> torch.Generator:
        generator = torch.Generator(device=device)
        generator.manual_seed(self.point_seed)
        return generator

    def predict_point(self, batch: IndustrialBatch) -> Tensor:
        hidden = self.flow_hidden(batch)
        ones = torch.ones(hidden.shape[0], hidden.shape[1], device=hidden.device)
        samples = self._flow_sample(
            hidden, ones, self.point_nsamples, self._seeded_generator(hidden.device)
        )
        return samples.mean(dim=1)

    def batch_nll(self, batch: IndustrialBatch) -> Tensor:
        hidden = self.flow_hidden(batch)
        rows = self._flow_nll_rows(batch.y_flat, hidden, batch.mq_flat)
        row_counts = batch.mq_flat.sum(dim=-1).clamp_min(1.0)
        return (rows * row_counts).sum() / batch.mq_flat.sum().clamp_min(1.0)

    def batch_nll_rows(self, batch: IndustrialBatch) -> Tensor:
        """Per-row NLL sums; the flow's per-row means are re-expanded."""

        hidden = self.flow_hidden(batch)
        rows = self._flow_nll_rows(batch.y_flat, hidden, batch.mq_flat)
        row_counts = batch.mq_flat.sum(dim=-1).clamp_min(1.0)
        return rows * row_counts

    def sample_flat(
        self,
        batch: IndustrialBatch,
        nsamples: int = 100,
        generator: Optional[torch.Generator] = None,
    ) -> Tensor:
        hidden = self.flow_hidden(batch)
        samples = self._flow_sample(hidden, batch.mq_flat, int(nsamples), generator)
        mask = batch.mq_flat.unsqueeze(1) > 0
        return torch.where(mask, samples, torch.zeros_like(samples))

    def interval95_flat(self, batch: IndustrialBatch) -> Tuple[Tensor, Tensor]:
        hidden = self.flow_hidden(batch)
        samples = self._flow_sample(
            hidden,
            torch.ones(hidden.shape[0], hidden.shape[1], device=hidden.device),
            self.interval_nsamples,
            self._seeded_generator(hidden.device),
        )
        lower = torch.quantile(samples, 0.025, dim=1)
        upper = torch.quantile(samples, 0.975, dim=1)
        return lower, upper

    def loss(self, batch: IndustrialBatch) -> Tensor:
        return self.batch_nll(batch) + self.lambda_point * masked_mse(
            batch.y_flat, self.predict_point(batch), batch.mq_flat
        )

    def parameter_count(self) -> int:
        return parameter_count(self)
