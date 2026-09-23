# Missingness-Aware Sensor-Token Mixer

## Scope

This change directly replaces the FLA cross-variable block in Scheme-B point
models. It does not add a recurrent or direct prediction branch and keeps the
existing `cross_variable(z, freshness, available) -> [B,N,H]` contract.

## Data flow

The block applies pre-normalized sensor-token Q/K/V attention. Source tokens
with no history are masked, source freshness contributes a log-age penalty, and
an optional learnable sensor-pair relation bias captures stable cross-sensor
structure. A bottleneck gate conditions the residual message on the original
token, message, freshness, and availability. If a sample has no valid source,
the block returns the input identity exactly, avoiding undefined softmax rows.

## Candidate variants

- `m1_missing_sensor_mixer_l1`: one mixer layer, relation bias enabled.
- `m2_missing_sensor_mixer_l2`: two mixer layers, relation bias enabled.
- `m3_missing_sensor_mixer_relation`: two layers with a larger relation scale.
- `m4_missing_sensor_mixer_age`: two layers with a stronger freshness decay.

All variants use the same mask-safe hierarchical KAF encoder, query adapter,
residual decoder, and last-value anchor. Selection is by validation MAE only;
test evaluation happens once after the structure is frozen.
