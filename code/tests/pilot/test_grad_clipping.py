"""CH3-S04 regression: global gradient clipping in the pilot training loop.

History (2026-09-17): the first pilot runner draft omitted gradient clipping,
while every established training entrypoint (``run_experiment.py``,
``train_metropt_kaf_profiti.py``, ``train_cmapss_kaf_profiti.py``) clips at
norm 1.0. Without clipping, the adapted Euler-expansion ODE-RNN diverges on
the MetroPT central condition (grad-norm peaks ~6.6e7, valid MAE 9.30 vs the
persistence floor 0.9159); with clip=1.0 at the frozen lr=1e-3 it reaches
valid MAE 0.747 within 6 epochs.

These tests pin the restored recipe so a future rewrite of the training loop
cannot silently drop it again:
- ``_train_one_epoch`` clips every batch at ``GRAD_CLIP_NORM == 1.0``;
- the clipped update is mathematically the manual clipped update;
- both ``pilot_train_and_evaluate`` and ``pilot_sanity_train`` route their
  epoch loops through ``_train_one_epoch`` (no private inline loops).
"""

import inspect

import torch

from kaf_profiti.experiments.pilot_runner import (
    GRAD_CLIP_NORM,
    _train_one_epoch,
    pilot_sanity_train,
    pilot_train_and_evaluate,
)


class _HugeGradientModel(torch.nn.Module):
    """Linear model with an extreme loss scale to force grad norms >> 1."""

    def __init__(self):
        super().__init__()
        self.linear = torch.nn.Linear(1, 1, bias=False)

    def loss(self, batch):
        return (self.linear(batch) * 1e9).sum()


def _single_batch_loader():
    batch = torch.tensor([[2.0]])
    return [batch]


def test_grad_clip_norm_is_frozen_at_one():
    assert GRAD_CLIP_NORM == 1.0


def test_train_one_epoch_applies_clip_grad_norm():
    calls = []
    original = torch.nn.utils.clip_grad_norm_

    def spy(parameters, max_norm, **kwargs):
        params = list(parameters)
        calls.append((max_norm, params))
        return original(params, max_norm, **kwargs)

    torch.nn.utils.clip_grad_norm_ = spy
    try:
        model = _HugeGradientModel()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
        _train_one_epoch(model, _single_batch_loader(), optimizer, torch.device("cpu"))
    finally:
        torch.nn.utils.clip_grad_norm_ = original

    assert len(calls) == 1, "expected exactly one clip call per batch"
    max_norm, parameters = calls[0]
    assert max_norm == GRAD_CLIP_NORM
    assert parameters == list(model.parameters())


def test_clipped_update_matches_manual_clipped_step():
    # Same init: one trained by _train_one_epoch, one by a manual
    # backward -> clip(1.0) -> step sequence. They must agree exactly.
    torch.manual_seed(2026)
    trained = _HugeGradientModel()
    optimizer = torch.optim.AdamW(trained.parameters(), lr=1e-3, weight_decay=1e-4)
    _train_one_epoch(trained, _single_batch_loader(), optimizer, torch.device("cpu"))

    torch.manual_seed(2026)
    manual = _HugeGradientModel()
    manual_optimizer = torch.optim.AdamW(
        manual.parameters(), lr=1e-3, weight_decay=1e-4
    )
    batch = _single_batch_loader()[0]
    manual_optimizer.zero_grad()
    loss = manual.loss(batch)
    loss.backward()
    grad_norm = torch.nn.utils.clip_grad_norm_(
        manual.parameters(), GRAD_CLIP_NORM
    )
    manual_optimizer.step()

    assert grad_norm.item() > GRAD_CLIP_NORM, "fixture must force clipping"
    assert torch.allclose(
        trained.linear.weight, manual.linear.weight, atol=1e-9
    ), "training step must be the clipped update"


def test_full_and_sanity_trainers_share_the_clipped_epoch_loop():
    for trainer in (pilot_train_and_evaluate, pilot_sanity_train):
        source = inspect.getsource(trainer)
        assert "_train_one_epoch(" in source, (
            f"{trainer.__name__} must route epochs through _train_one_epoch "
            "(the only loop that carries the global gradient clip)"
        )
