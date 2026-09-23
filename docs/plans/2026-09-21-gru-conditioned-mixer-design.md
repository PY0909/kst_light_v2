# GRU-Conditioned Mixer for Scheme-B Point Pilot

## Scope

This change adds four isolated MetroPT-3 point-pilot variants on top of the
existing A1 recipe. The existing mask-safe hierarchical KAF encoder and query
decoder remain unchanged. The FLA cross-variable block is replaced by a
missingness-aware GRU-conditioned mixer for G1-G4.

## Data flow

The mixer keeps the existing `(z, freshness, available)` cross-variable
contract and accepts the history tensors as optional auxiliary inputs. It
builds a history-only sequence from either forward-filled values plus the
original mask (G1/G2/G4), or `X * mask` plus the mask (G3), with static context
broadcast over time. A single-layer unidirectional GRU returns a global state
`g`; a linear projection broadcasts it to sensor tokens. A bottleneck MLP
computes a sigmoid gate from each token, the broadcast message, freshness and
availability, and returns `z + gate * message`. Fully missing histories use
zero fill and finite GRU inputs.

G4 additionally exposes a GRU-to-sensor direct residual head. KST-Light adds
that sensor residual only at the final point prediction, so it is counted in
the model parameters without replacing the existing decoder interface.

## Variant identity

- `g1_gru_mixer_h16`: hidden 16, forward fill, no direct residual
- `g2_gru_mixer_h32`: hidden 32, forward fill, no direct residual
- `g3_gru_mixer_no_ffill`: hidden selected from the better G1/G2 validation candidate, no forward fill
- `g4_gru_mixer_direct_residual`: same selected hidden size as G3, forward fill and direct residual ablation

Each variant uses its own matrix and result key. Recipe identity records mixer
mode, hidden size, bottleneck ratio, forward-fill flag, and direct-residual
flag, so it cannot resume or overwrite A1/F1-F3 artifacts.

## Validation and experiment policy

Tests cover output shape, freshness/availability sensitivity, finite all-missing
inputs, hidden-size configuration, parameter counting, and variant identity.
G1-G4 run with seed 2026, mixed 30% missingness, 50 epochs, batch size 128,
four data workers, CUDA when available, validation-best checkpoint selection,
and one test evaluation only after structure selection. Results are reported as
single-seed pilot evidence, not formal multi-seed conclusions.
