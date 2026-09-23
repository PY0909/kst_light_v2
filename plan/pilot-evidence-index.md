# CH3-S04 Pilot Evidence Index

> Scope: the single-seed CH3-S04 center-condition pilot and preceding CH34-S03 sanity gate. Runtime files under `result/` remain machine-local evidence and are not edited by hand.

## Evidence levels

- `pilot`: complete 50-epoch run with `test_evaluation_count=1`, prediction artifact, metrics, history, checkpoint, manifest, and SHA validation. Seven runs support point-estimate validation/test, per-channel, and timing observations only.
- `sanity_train`: validation-only short run with `test_evaluation_count=0`, no prediction/checkpoint, and a separate standardized masked-query persistence contract. It is not a formal result and must not enter model ranking.
- `data_gate`: history-only persistence reference. Its raw/all-query and standardized `std_micro` values are not interchangeable with the sanity loader contract.
- All claims are `seed=2026` single-seed observations. No significance, confidence interval, or general model-superiority claim is permitted.

## Formal pilot catalog

The seven source keys are the seven `point_mixed_030` entries under `result/pilot/metropt3/runs/`:

| Evidence ID | Scientific key | Level | Required artifact chain | Allowed claim |
|---|---|---|---|---|
| S04-01 | `...|point|ff_gru|linear|point_mixed_030|2026` | pilot | manifest → history/metrics/predictions/checkpoint | point-estimate validation/test and timing |
| S04-02 | `...|point|gru_d|linear|point_mixed_030|2026` | pilot | manifest → history/metrics/predictions/checkpoint | point-estimate validation/test and timing |
| S04-03 | `...|point|li_tcn|linear|point_mixed_030|2026` | pilot | manifest → history/metrics/predictions/checkpoint | point-estimate validation/test and timing |
| S04-04 | `...|point|masked_tcn|linear|point_mixed_030|2026` | pilot | manifest → history/metrics/predictions/checkpoint | point-estimate validation/test and timing |
| S04-05 | `...|point|ode_rnn|linear|point_mixed_030|2026` | pilot | manifest → history/metrics/predictions/checkpoint | point-estimate validation/test and timing |
| S04-06 | `...|point|kst_light|linear|point_mixed_030|2026` | pilot | manifest → history/metrics/predictions/checkpoint | point-estimate validation/test and timing |
| S04-07 | `...|point|kst_light|mlp|point_mixed_030|2026` | pilot | manifest → history/metrics/predictions/checkpoint | point-estimate validation/test and timing |

The `...` prefix is a display abbreviation only. Exact keys and complete hashes are in each runtime manifest; a report claiming a numeric row must cite its Evidence ID and corresponding runtime manifest/artifact SHA set. Do not treat directory names or filesystem mtime as evidence identity.

## Sanity and diagnostic catalog

| Evidence ID | Runtime source | Level | Contract | Allowed claim |
|---|---|---|---|---|
| S03-SAN-LI | `result/pilot/metropt3/sanity/<li_tcn-key>/` | sanity_train | standardized masked-query LOCF persistence micro, validation-only, no test | finite/updated/validation-improved and gate status after aligned rerun |
| S03-SAN-ODE | `result/pilot/metropt3/sanity/<ode_rnn-key>/` | sanity_train | same as above | same; never formal ranking |
| S01-GATE | `result/pilot/metropt3/diagnostics/data_gate.json` | data_gate | raw and standardized all-query floors | formal all-query reference only |

Historical sanity manifests generated before the aligned baseline implementation are superseded for `beat_naive`; the replacement manifests were generated on commit `2b47c07`. Their loader-contract persistence baseline is 0.4572 (standardized masked-query LOCF micro); they must remain separate from the data-gate all-query floor and formal pilot ranking.

## Code version equivalence (CH3-S04 vs CH3-S05)

The seven CH3-S04 `point_mixed_030` runs were generated under commit `c535097` (`code_fingerprint=f44952ed50f6801b092b9a9e6f29d5c34b5519da6a55d24373c7ce2ac41571d1`). CH3-S05 runs are generated under commit `2b47c07` (`code_fingerprint=fdd06602a6f90de74da0c963d8d948d6040a8281f375d0949f1dad02eca6eb8d`). `_verified_specs` requires an exact code-fingerprint match, so the seven older manifests are not auto-resumed by the newer checkout; CH3-S05 therefore schedules its new runs with an explicit `--condition-id` list that excludes `point_mixed_030`, and never re-runs or overwrites the seven CH3-S04 runs.

The `c535097 → 2b47c07` code delta is limited to pilot sanity and manifest provenance and does not change formal training/evaluation behavior:

- `_persistence_score` / `_persistence_forecast` — used only by `run_sanity_train` (validation-only gate), never by `execute`.
- `_git_provenance` and `generated_at_utc` — added manifest metadata fields only.
- `_naive_floor_reference` note text — documentation wording only.

The runner uses a scoped audited-fingerprint allowlist for resume/gating: `f44952ed…` is accepted only for completed `point_mixed_030` pilot runs, and `fdd06602…` only for completed baseline pilot runs. Identity, protocol, artifact SHA, checkpoint SHA, and test-count checks remain mandatory; arbitrary or tampered fingerprints are rejected. New T02 runs use the current fingerprint.

## Analysis mask semantics and stability boundary

For point runs, `predictions.json["mask"]` is the query/evaluation-validity mask (`M_q`/`mq_flat`), not the history/input missingness mask. It is all ones in this protocol because query targets are valid. Observed-vs-missing history analysis must reconstruct `M_obs` from the protocol mask bundle referenced by `manifest.protocol_sha.mask_sha.{train,valid,test}`. The T01 audit and T03 output contract must keep these masks separate.

The ODE-RNN `point_mixed_030` run is finite but has validation spikes/late degradation and heavy-tail/extreme-prediction pathology. It remains a diagnostic baseline; T02 is not blocked, but T03 must expose the instability fields and boundary described in `plan/ch3-s05-t01-baseline-evidence.md`.
## Provenance contract

A complete pilot evidence chain is:

`claim/table -> aggregate command -> scientific key/seed -> prediction/metrics -> checkpoint -> resolved config -> manifest -> protocol/shared-artifact/code hash -> preflight identity`.

New manifests record full commit SHA, clean/dirty state, and UTC generation time. The existing formal run artifacts retain their original code/protocol/artifact hashes; this index does not rewrite or re-sign them. `result/` is ignored runtime evidence, so a future formal report must attach exact manifest/artifact SHA sets and validator command output (or an evidence-bundle SHA) rather than relying on this catalog's abbreviated display keys.

The CH3-S04 pilot `go` is outside D3-D5 formal stage-gate closure: `plan/stage-gates.md` remains authoritative for those gates.
