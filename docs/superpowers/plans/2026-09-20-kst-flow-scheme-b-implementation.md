# KST-Flow Scheme B Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Apply test-driven-development for every code task and verification-before-completion before closing each phase.

**Goal:** Implement versioned `kst_light_v2` and `kst_flow_v2` models whose missingness-aware representation, joint probability distribution, and sample-derived risk path satisfy the approved Scheme B design.

**Architecture:** Build causal missingness features and a mask-normalized hierarchical KAF encoder, route its variable representations through exactly one cross-variable block, then attach either a last-value residual point decoder or the existing triangular ProFITi flow. Derive quantiles, intervals, and risk from that flow's samples and fit calibration only on validation data.

**Tech Stack:** Python 3.12, PyTorch 2.5, pytest, YAML experiment matrices, existing pilot runner/manifest framework.

**Design contract:** `docs/plans/2026-09-20-kst-flow-scheme-b-design.md`

---

## Execution rules

- Implement in order P0 through P7. A phase begins only after the previous phase's tests and acceptance checks pass.
- Run all selection and tuning on train/validation. Test evaluation remains the single frozen evaluation already enforced by the runner.
- Keep `kst_light` and `kst_probflow` importable for old checkpoints and artifacts. New behavior uses `kst_light_v2` and `kst_flow_v2` only.
- Do not edit JSON under `result/`. Every experimental run creates a new `run_id` and records seed, dataset, model ID, checkpoint and scientific identity.
- Each task follows red, implementation, green, focused commit. If a red test unexpectedly passes, inspect whether the test exercises the intended contract before writing code.

## P0 — Freeze v2 identity and runtime contracts

### Task P0.1: Add versioned model identities and reject incomplete recipes

**Files:**
- Modify: `code/kaf_profiti/experiments/registry.py`
- Modify: `code/kaf_profiti/experiments/pilot_runner.py`
- Modify: `code/kaf_profiti/experiments/model_api.py`
- Create: `code/tests/pilot/test_scheme_b_identity.py`

**Step 1: Write the failing tests**

Add tests asserting:

```python
def test_v2_models_are_distinct_from_legacy_registry_entries():
    assert get_model_spec("kst_light_v2").name == "kst_light_v2"
    assert get_model_spec("kst_flow_v2").name == "kst_flow_v2"
    assert get_model_spec("kst_light").name == "kst_light"
    assert get_model_spec("kst_probflow").name == "kst_probflow"

def test_v2_recipe_requires_scheme_b_identity_fields():
    with pytest.raises(ValueError, match="recipe_version"):
        validate_scheme_b_recipe({"model_id": "kst_light_v2"})
```

The valid fixture must contain `recipe_version=scheme_b_v1`, encoder/cross-variable/missing-feature versions, flow order for `kst_flow_v2`, and all protocol SHA fields.

**Step 2: Run the red test**

```bash
python -m pytest code/tests/pilot/test_scheme_b_identity.py -q
```

Expected: failure because v2 registry entries and validation do not exist.

**Step 3: Implement the minimum contract**

Add registry entries with `status="enabled"` only after their constructors exist; during P0 use `status="not_implemented"`. Add a pure validator:

```python
SCHEME_B_REQUIRED_FIELDS = frozenset({
    "recipe_version", "encoder_version", "cross_variable_mode",
    "missing_feature_version", "split_sha", "normalization_sha",
    "mask_sha", "target_schema_sha", "evaluator_sha", "code_sha",
})

def validate_scheme_b_recipe(recipe: Mapping[str, object]) -> None:
    if recipe.get("recipe_version") != "scheme_b_v1":
        raise ValueError("recipe_version must be scheme_b_v1")
    missing = sorted(SCHEME_B_REQUIRED_FIELDS - recipe.keys())
    if missing:
        raise ValueError(f"missing Scheme B identity fields: {missing}")
```

`kst_flow_v2` additionally requires `flow_order` and `lambda_point`. Preserve legacy registry builders unchanged.

**Step 4: Run focused and regression tests**

```bash
python -m pytest code/tests/pilot/test_scheme_b_identity.py code/tests/pilot/test_pilot_model_identity.py code/tests/pilot/test_pilot_legacy_fingerprint.py -q
```

Expected: all pass; legacy fingerprint tests remain green.

**Step 5: Commit**

```bash
git add code/kaf_profiti/experiments/registry.py code/kaf_profiti/experiments/pilot_runner.py code/kaf_profiti/experiments/model_api.py code/tests/pilot/test_scheme_b_identity.py
git commit -m "feat: freeze Scheme B model identities"
```

### Task P0.2: Add v2 config templates without changing formal matrices

**Files:**
- Create: `configs/scheme_b/metropt3_kst_light_v2.yaml`
- Create: `configs/scheme_b/metropt3_kst_flow_v2.yaml`
- Modify: `code/tests/pilot/test_scheme_b_identity.py`

**Step 1: Extend the failing test**

Load both YAML files and assert exact IDs, `scheme_b_v1`, `cross_variable_mode: fla`, shared encoder fields, and the flow-only fields. Assert no existing pilot matrix entry has changed its model ID.

**Step 2: Run red**

```bash
python -m pytest code/tests/pilot/test_scheme_b_identity.py -q
```

Expected: file-not-found failures.

**Step 3: Create explicit configs**

Use shared starting values `hidden_dim=64`, `te_dim=10`, `kernel_count=4`, `n_layers=2`, `n_heads=2`, `preconv_dim=16`, `patch_lens=[12,24,48]`, `freshness_tau=24.0`, and `cross_variable_mode=fla`. The flow config uses `lambda_point=0.1`, `flow_order=horizon_major_sensor_minor`, `nsamples=100`.

**Step 4: Run green**

```bash
python -m pytest code/tests/pilot/test_scheme_b_identity.py -q
git diff --check
```

**Step 5: Commit**

```bash
git add configs/scheme_b code/tests/pilot/test_scheme_b_identity.py
git commit -m "config: add Scheme B recipe templates"
```

### Task P0.3: Add a config-driven Scheme B runner

**Files:**
- Create: `code/run_scheme_b_matrix.py`
- Modify: `code/kaf_profiti/experiments/pilot_runner.py`
- Create: `code/tests/pilot/test_scheme_b_runner.py`

**Step 1: Write failing CLI tests**

Invoke the CLI against a temporary two-entry matrix and assert `--mode dry-run` prints two unique scientific keys without writing artifacts. Assert unknown fields, duplicate keys, missing v2 identity and an unsupported mode fail before dataset loading.

**Step 2: Run red**

```bash
python -m pytest code/tests/pilot/test_scheme_b_runner.py -q
```

Expected: import or file-not-found failure because the entrypoint does not exist.

**Step 3: Implement the narrow entrypoint**

Expose `--config`, `--mode {dry-run,smoke,validation,full}`, `--data-root`, `--result-root`, `--device` and `--num-workers`. Reuse `load_matrix`, `PilotRunner`, runtime path resolution, manifest verification and existing test-evaluation guards. The runner must not translate a v2 config into legacy IDs.

**Step 4: Run green and show the real help text**

```bash
python -m pytest code/tests/pilot/test_scheme_b_runner.py code/tests/pilot/test_pilot_runner.py -q
python code/run_scheme_b_matrix.py --help
```

Expected: tests pass and help lists all four modes.

**Step 5: Commit**

```bash
git add code/run_scheme_b_matrix.py code/kaf_profiti/experiments/pilot_runner.py code/tests/pilot/test_scheme_b_runner.py
git commit -m "feat: add Scheme B matrix runner"
```

**P0 gate:** v2 IDs cannot resume or aggregate legacy artifacts; config-driven dry-run works without dataset access; existing formal matrices are byte-for-byte unchanged.

## P1 — Build causal missingness features

### Task P1.1: Implement `MissingnessFeatures`

**Files:**
- Create: `code/kaf_profiti/models/missingness_features.py`
- Create: `code/tests/ch3/test_missingness_features.py`

**Step 1: Write failing unit tests**

Cover these exact cases:

```python
def test_delta_t_resets_only_on_observation(): ...
def test_block_length_counts_consecutive_missing_steps(): ...
def test_never_observed_sensor_sets_has_history_zero(): ...
def test_future_mask_change_cannot_change_history_features(): ...
def test_features_are_finite_for_empty_history(): ...
```

Use a hand-calculated two-sensor timeline and compare exact tensors for `delta_t`, `block_length`, `has_history`, and `freshness`.

**Step 2: Run red**

```bash
python -m pytest code/tests/ch3/test_missingness_features.py -q
```

**Step 3: Implement a causal module**

Define a dataclass output and a module with this interface:

```python
@dataclass(frozen=True)
class MissingnessFeatureBatch:
    delta_t: Tensor
    freshness: Tensor
    block_length: Tensor
    has_history: Tensor

class MissingnessFeatures(nn.Module):
    def __init__(self, freshness_tau: float, max_delta: float): ...
    def forward(self, times: Tensor, mask: Tensor) -> MissingnessFeatureBatch: ...
```

Use a forward scan over `L`; never inspect target tensors or indices beyond the current history step. Clamp `delta_t` before exponentiation.

**Step 4: Run green and local regressions**

```bash
python -m pytest code/tests/ch3/test_missingness_features.py code/tests/test_model_components.py -q
```

**Step 5: Commit**

```bash
git add code/kaf_profiti/models/missingness_features.py code/tests/ch3/test_missingness_features.py
git commit -m "feat: add causal missingness features"
```

### Task P1.2: Connect features to the batch/model API

**Files:**
- Modify: `code/kaf_profiti/industrial/batch.py`
- Modify: `code/kaf_profiti/experiments/model_api.py`
- Modify: `code/tests/pilot/test_model_api.py`
- Modify: `code/tests/ch3/test_missingness_features.py`

**Step 1: Write failing API tests**

Assert the v2 adapter accepts `[B,L]` and `[B,L,N]` timestamps, emits the same feature shape, keeps tensors on the input device, and does not alter legacy model calls.

**Step 2: Run red**

```bash
python -m pytest code/tests/pilot/test_model_api.py code/tests/ch3/test_missingness_features.py -q
```

**Step 3: Add the v2-only adapter path**

Derive features inside the v2 model boundary from existing batch fields. Do not persist derived tensors into datasets and do not add paths to result artifacts. Include feature-version and scalar parameters in model config serialization.

**Step 4: Run green**

```bash
python -m pytest code/tests/pilot/test_model_api.py code/tests/ch3/test_missingness_features.py -q
```

**Step 5: Commit**

```bash
git add code/kaf_profiti/industrial/batch.py code/kaf_profiti/experiments/model_api.py code/tests/pilot/test_model_api.py code/tests/ch3/test_missingness_features.py
git commit -m "feat: expose Scheme B missingness inputs"
```

**P1 gate:** hand-calculated features pass, empty histories stay finite, future information cannot affect historical features, and legacy model API tests pass.

## P2 — Implement the hierarchical missingness-aware KAF encoder

### Task P2.1: Add mask-normalized pre-convolution

**Files:**
- Modify: `code/kaf_profiti/models/kafnet_encoder.py`
- Create: `code/tests/ch3/test_hierarchical_kaf_encoder.py`

**Step 1: Write failing invariance tests**

```python
def test_masked_fill_value_does_not_change_encoder_output(): ...
def test_all_missing_patch_is_finite_and_marked_invalid(): ...
def test_observed_value_change_does_change_encoder_output(): ...
```

Construct two inputs that differ only where `M_obs == 0`. Compare outputs with `torch.testing.assert_close`.

**Step 2: Run red**

```bash
python -m pytest code/tests/ch3/test_hierarchical_kaf_encoder.py -q
```

Expected: fill-value invariance fails against the current `pre_conv`.

**Step 3: Implement `MaskNormalizedConv1d`**

```python
class MaskNormalizedConv1d(nn.Module):
    def forward(self, values: Tensor, mask: Tensor) -> tuple[Tensor, Tensor]:
        numerator = self.value_conv(values * mask)
        support = F.conv1d(mask, self.support_kernel, padding=self.padding)
        valid = support > 0
        output = torch.where(valid, numerator / support.clamp_min(self.eps), 0.0)
        return output, valid.to(values.dtype)
```

Pass the resulting validity mask into KAF pooling. Do not change legacy `KAFNetEncoder`; introduce the path through the v2 encoder class so old checkpoints remain loadable.

**Step 4: Run green**

```bash
python -m pytest code/tests/ch3/test_hierarchical_kaf_encoder.py code/tests/test_model_components.py -q
```

**Step 5: Commit**

```bash
git add code/kaf_profiti/models/kafnet_encoder.py code/tests/ch3/test_hierarchical_kaf_encoder.py
git commit -m "feat: add mask-normalized KAF convolution"
```

### Task P2.2: Add patch identity and hierarchical aggregation

**Files:**
- Modify: `code/kaf_profiti/models/kafnet_encoder.py`
- Modify: `code/tests/ch3/test_hierarchical_kaf_encoder.py`

**Step 1: Add failing structure tests**

Test that swapping equal-content patches at different positions changes their pre-pool tokens; changing `patch_len` changes scale embeddings; increasing last-observation age changes recency embeddings; invalid patches receive zero aggregation weight; output shape is `[B,N,D]`.

**Step 2: Run red**

```bash
python -m pytest code/tests/ch3/test_hierarchical_kaf_encoder.py -q
```

**Step 3: Implement the v2 encoder**

Add `HierarchicalMissingnessKAFEncoder`. Group patch tokens by scale, apply masked softmax within each scale, then gate the scale summaries with the global token:

```python
scale_summary = masked_softmax_pool(tokens, valid, self.patch_score)
gate = torch.sigmoid(self.scale_gate(torch.cat([global_z, scale_summary], dim=-1)))
z = gate * scale_summary + (1.0 - gate) * global_z
```

Expose token diagnostics only when `return_diagnostics=True` to avoid retaining large tensors during training.

**Step 4: Run green**

```bash
python -m pytest code/tests/ch3/test_hierarchical_kaf_encoder.py code/tests/test_model_components.py -q
```

**Step 5: Commit**

```bash
git add code/kaf_profiti/models/kafnet_encoder.py code/tests/ch3/test_hierarchical_kaf_encoder.py
git commit -m "feat: add hierarchical patch identity aggregation"
```

**P2 gate:** masked fill invariance, empty-patch finiteness, patch identity, recency sensitivity and legacy component regressions all pass.

## P3 — Add exclusive cross-variable blocks and `kst_light_v2`

### Task P3.1: Extract an exclusive cross-variable interface

**Files:**
- Create: `code/kaf_profiti/models/cross_variable.py`
- Create: `code/tests/ch3/test_cross_variable_ablation.py`

**Step 1: Write failing tests**

Cover `identity`, `fla`, and `missing_graph`. Assert construction rejects lists or combined modes; graph adjacency rows sum to one; unavailable sensors receive zero incoming source weight; stale-source weight decreases when only its age increases; gradients are finite.

**Step 2: Run red**

```bash
python -m pytest code/tests/ch3/test_cross_variable_ablation.py -q
```

**Step 3: Implement the interface**

```python
def build_cross_variable_block(mode: str, config: CrossVariableConfig) -> nn.Module:
    builders = {"identity": IdentityCrossVariable, "fla": FLACrossVariable,
                "missing_graph": MissingnessAwareGraph}
    if mode not in builders:
        raise ValueError(f"unsupported cross_variable_mode: {mode}")
    return builders[mode](config)
```

Reuse `FreqBlock` through composition. Implement graph age bias exactly as frozen in the design and return detached adjacency only in diagnostics.

**Step 4: Run green**

```bash
python -m pytest code/tests/ch3/test_cross_variable_ablation.py -q
```

**Step 5: Commit**

```bash
git add code/kaf_profiti/models/cross_variable.py code/tests/ch3/test_cross_variable_ablation.py
git commit -m "feat: add exclusive cross-variable blocks"
```

### Task P3.2: Implement the residual point model

**Files:**
- Create: `code/kaf_profiti/models/kst_light.py`
- Modify: `code/kaf_profiti/models/__init__.py`
- Modify: `code/kaf_profiti/experiments/registry.py`
- Modify: `code/kaf_profiti/experiments/pilot_runner.py`
- Create: `code/tests/ch3/test_kst_light_v2.py`

**Step 1: Write failing model tests**

Assert output `[B,H,N]`, exact zero-delta reconstruction of `x_last`, train-only center fallback for never-observed variables, masked Huber denominator, finite backward gradients, config serialization, and registry construction.

**Step 2: Run red**

```bash
python -m pytest code/tests/ch3/test_kst_light_v2.py -q
```

**Step 3: Implement `KSTLightV2`**

Use `HierarchicalMissingnessKAFEncoder`, one `CrossVariableBlock`, future horizon/sensor embeddings and a residual MLP. Compute last observations with a reverse masked index, without Python indexing per batch item. Initialize the final delta projection to zero so the initial prediction equals the anchor.

**Step 4: Enable only the completed registry entry and run green**

```bash
python -m pytest code/tests/ch3/test_kst_light_v2.py code/tests/ch3/test_cross_variable_ablation.py code/tests/pilot/test_model_api.py code/tests/pilot/test_scheme_b_identity.py -q
```

**Step 5: Commit**

```bash
git add code/kaf_profiti/models/kst_light.py code/kaf_profiti/models/__init__.py code/kaf_profiti/experiments/registry.py code/kaf_profiti/experiments/pilot_runner.py code/tests/ch3/test_kst_light_v2.py
git commit -m "feat: implement KST Light v2"
```

### Task P3.3: Add optimizer and validation selection controls

**Files:**
- Modify: `code/run_experiment.py`
- Modify: `code/kaf_profiti/experiments/pilot_runner.py`
- Create: `code/tests/ch3/test_scheme_b_training.py`

**Step 1: Write failing tests**

Assert optimizer, learning rate, weight decay, scheduler, patience and gradient clip are serialized; best checkpoint is selected only by validation; test evaluator is called once after selection; invalid negative values fail early.

**Step 2: Run red**

```bash
python -m pytest code/tests/ch3/test_scheme_b_training.py -q
```

**Step 3: Add v2 training controls**

Keep legacy defaults untouched. For v2, configure AdamW, optional cosine scheduler, early stopping and clip norm from recipe. Store full epoch history and the selected validation metric.

**Step 4: Run green**

```bash
python -m pytest code/tests/ch3/test_scheme_b_training.py code/tests/pilot/test_grad_clipping.py code/tests/pilot/test_pilot_runner.py -q
```

**Step 5: Commit**

```bash
git add code/run_experiment.py code/kaf_profiti/experiments/pilot_runner.py code/tests/ch3/test_scheme_b_training.py
git commit -m "feat: add Scheme B validation training controls"
```

**P3 gate:** each run contains exactly one cross-variable mode; residual anchors handle stale and absent histories; validation-only checkpoint selection is enforced; legacy paths remain green.

## P4 — Tune and validate the Chapter 3 representation

### Task P4.1: Run bounded validation-only optimizer screening

**Files:**
- Create: `configs/scheme_b/metropt3_kst_light_v2_tuning.yaml`
- Modify: `plan/progress.md`
- Output: `result/scheme_b/metropt3/tuning/runs/`

**Step 1: Freeze the grid**

Use seed 2026, mixed 0.30, FLA, and the Cartesian grid:

```yaml
lr: [0.0001, 0.0002, 0.0005, 0.001]
weight_decay: [0.00001, 0.0001]
```

All other architecture values remain fixed. Ranking key is validation macro MAE, then validation micro MAE, then lower parameter count.

**Step 2: Validate without training**

```bash
python -u code/run_scheme_b_matrix.py --config configs/scheme_b/metropt3_kst_light_v2_tuning.yaml --mode dry-run
```

Expected: eight unique scientific keys, zero test evaluation requests.

**Step 3: Run on AutoDL**

```bash
cd /root/autodl-tmp/new_work
mkdir -p logs
nohup python -u code/run_scheme_b_matrix.py --config configs/scheme_b/metropt3_kst_light_v2_tuning.yaml --mode validation > logs/scheme_b_p4_tuning.log 2>&1 &
```

**Step 4: Verify artifacts**

Use the repository validator to require eight completed runs, finite history, one best validation checkpoint per run, `test_evaluation_count=0`, and shared protocol SHA values. Record the chosen optimizer in `plan/progress.md` with all eight validation scores.

**Step 5: Commit only config and progress**

```bash
git add configs/scheme_b/metropt3_kst_light_v2_tuning.yaml plan/progress.md
git commit -m "exp: freeze Scheme B optimizer selection"
```

### Task P4.2: Run the Chapter 3 ablation gate

**Files:**
- Create: `configs/scheme_b/metropt3_kst_light_v2_ablation.yaml`
- Modify: `code/build_tables.py`
- Create: `code/tests/ch3/test_scheme_b_tables.py`
- Modify: `plan/progress.md`

**Step 1: Write the table test and matrix**

The matrix contains the seven design variants, seed 2026, mixed 0.30, and the optimizer frozen in P4.1. The test rejects duplicate keys, test-based ranking, missing `recipe_version`, and mixed legacy/v2 aggregation.

**Step 2: Run red then implement table grouping**

```bash
python -m pytest code/tests/ch3/test_scheme_b_tables.py -q
```

Group by `recipe_version`, variant and condition; render validation selection separately from frozen test reporting.

**Step 3: Run green and dry-run**

```bash
python -m pytest code/tests/ch3/test_scheme_b_tables.py -q
python -u code/run_scheme_b_matrix.py --config configs/scheme_b/metropt3_kst_light_v2_ablation.yaml --mode dry-run
```

Expected: seven unique keys and no legacy artifact reuse.

**Step 4: Execute and apply the gate**

Run the seven experiments. Continue only if the complete `v2_fla` is finite, improves over legacy KST-Light on validation, and does not regress block-offline in the subsequent condition check. Record failed variants as results rather than editing their metrics.

**Step 5: Commit**

```bash
git add configs/scheme_b/metropt3_kst_light_v2_ablation.yaml code/build_tables.py code/tests/ch3/test_scheme_b_tables.py plan/progress.md
git commit -m "exp: evaluate Scheme B representation ablations"
```

### Task P4.3: Run frozen three-seed Chapter 3 experiments

**Files:**
- Create: `configs/scheme_b/metropt3_kst_light_v2_formal.yaml`
- Modify: `plan/progress.md`
- Output: `result/scheme_b/metropt3/formal/runs/`

**Step 1: Freeze matrix**

Use seeds 2026/2027/2028 and conditions random 0/30/70, low-rate 30, block-offline 30 and mixed 30. Compare the selected complete v2 path, identity interaction, accepted graph candidate if it passed, and preregistered point baselines.

**Step 2: Dry-run and cross-machine preflight**

```bash
python -u code/run_scheme_b_matrix.py --config configs/scheme_b/metropt3_kst_light_v2_formal.yaml --mode dry-run
python -u code/check_pilot_environment.py --profile metropt3 --require-clean
```

**Step 3: Execute, download, validate**

Run each seed independently with a distinct log. Require all expected keys, shared protocol/mask SHA values, finite metrics, exact seed counts and no test-based retry.

**Step 4: Aggregate**

```bash
python code/build_tables.py --results-dir result/scheme_b/metropt3/formal
```

Report mean±std and `n=3`; keep condition-level values and run IDs.

**Step 5: Commit config and progress**

```bash
git add configs/scheme_b/metropt3_kst_light_v2_formal.yaml plan/progress.md
git commit -m "exp: record Scheme B Chapter 3 formal runs"
```

**P4 gate:** v2 architecture choice and optimizer are frozen from validation; formal results have three verified seeds; graph replaces FLA only if every design criterion passes.

## P5 — Implement `kst_flow_v2` with one coherent distribution

### Task P5.1: Add distribution identity tests around `ProFITiFlowHead`

**Files:**
- Modify: `code/kaf_profiti/models/profiti_flow_head.py`
- Create: `code/tests/pilot/test_kst_flow_distribution.py`

**Step 1: Write failing contract tests**

Assert triangular forward/inverse reconstruction, finite log determinant, masked NLL denominator, fixed-generator sample reproducibility, nonzero gradients for every joint-flow parameter, and sample/quantile/interval shape consistency.

**Step 2: Run red**

```bash
python -m pytest code/tests/pilot/test_kst_flow_distribution.py -q
```

**Step 3: Add only missing public methods**

Adapt the existing head rather than rewriting its transform. Standardize methods:

```python
nll(y_flat, hidden, mask) -> Tensor
sample(hidden, mask, nsamples, generator) -> Tensor
summarize(samples, levels=(0.025, 0.5, 0.975)) -> DistributionSummary
```

All summaries operate on the supplied samples. No parallel quantile network is allowed.

**Step 4: Run green**

```bash
python -m pytest code/tests/pilot/test_kst_flow_distribution.py code/tests/pilot/test_probabilistic_baseline_fidelity.py -q
```

**Step 5: Commit**

```bash
git add code/kaf_profiti/models/profiti_flow_head.py code/tests/pilot/test_kst_flow_distribution.py
git commit -m "test: enforce ProFITi distribution identity"
```

### Task P5.2: Implement `KSTFlowV2`

**Files:**
- Create: `code/kaf_profiti/models/kst_flow.py`
- Modify: `code/kaf_profiti/models/__init__.py`
- Modify: `code/kaf_profiti/experiments/registry.py`
- Modify: `code/kaf_profiti/experiments/pilot_runner.py`
- Modify: `code/tests/pilot/test_kst_flow_distribution.py`

**Step 1: Write failing integration tests**

Construct a tiny model and assert `loss = joint_nll + lambda_point * masked_huber`, horizon-major/sensor-minor flattening round-trips, samples restore `[B,S,H,N]`, no `QuantileHead` or `RiskHead` exists in named modules, and Stage 1 encoder loading records exact matched keys.

**Step 2: Run red**

```bash
python -m pytest code/tests/pilot/test_kst_flow_distribution.py -q
```

**Step 3: Implement and register**

Compose `KSTLightV2` representation modules, `QueryConditionAdapter`, residual point projection and `ProFITiFlowHead`. Add one public query-order utility used by loss, sampling and artifact serialization. Enable `kst_flow_v2` only after all tests pass.

**Step 4: Run green and regressions**

```bash
python -m pytest code/tests/pilot/test_kst_flow_distribution.py code/tests/pilot/test_model_api.py code/tests/test_model_components.py -q
```

**Step 5: Commit**

```bash
git add code/kaf_profiti/models/kst_flow.py code/kaf_profiti/models/__init__.py code/kaf_profiti/experiments/registry.py code/kaf_profiti/experiments/pilot_runner.py code/tests/pilot/test_kst_flow_distribution.py
git commit -m "feat: implement coherent KST Flow v2"
```

### Task P5.3: Insert the distribution gate before CH4-S06

**Files:**
- Modify: `configs/pilot/metropt3/probabilistic_matrix.yaml`
- Modify: `plan/implementation-plan.md`
- Modify: `code/tests/pilot/test_metropt_matrices.py`

**Step 1: Write a failing matrix test**

Require the new formal Scheme B probability entry to use `kst_flow_v2`, `recipe_version=scheme_b_v1`, `nsamples=100`, `lambda_point` in the frozen set, and distribution identity metadata. Preserve the old `kst_probflow` entry as legacy pilot evidence or move it to an explicitly named legacy matrix without altering its artifact key.

**Step 2: Run red**

```bash
python -m pytest code/tests/pilot/test_metropt_matrices.py -q
```

**Step 3: Update the matrix and master plan**

Add a CH4-S06 precondition that P5 distribution tests and a no-test smoke run pass before formal probability runs. State that old `kst_probflow` output cannot satisfy this gate.

**Step 4: Run green and dry-run**

```bash
python -m pytest code/tests/pilot/test_metropt_matrices.py code/tests/pilot/test_pilot_matrix.py -q
python -u code/run_pilot_matrix.py --profile metropt3 --matrix probabilistic --mode dry-run
```

**Step 5: Commit**

```bash
git add configs/pilot/metropt3/probabilistic_matrix.yaml plan/implementation-plan.md code/tests/pilot/test_metropt_matrices.py
git commit -m "plan: gate Chapter 4 on coherent KST Flow v2"
```

**P5 gate:** density, samples, quantiles and intervals use one flow; joint parameters receive gradients; formal CH4 matrix identifies v2 explicitly.

## P6 — Derive risk from samples and calibrate on validation

### Task P6.1: Add sensor and device risk extraction

**Files:**
- Modify: `code/kaf_profiti/industrial/risk.py`
- Create: `code/tests/pilot/test_sample_risk_calibration.py`

**Step 1: Write failing risk tests**

Use small deterministic sample tensors to hand-calculate lower/upper exceedance probabilities, any-sensor device risk, horizon maximum risk, mask behavior and monotonicity when more samples cross a limit.

**Step 2: Run red**

```bash
python -m pytest code/tests/pilot/test_sample_risk_calibration.py -q
```

**Step 3: Implement sample-only risk APIs**

Extend `risk_from_samples()` to return a typed result with sensor/horizon and device views. Require an explicit aggregation enum and record thresholds plus aggregation in serialized metadata.

**Step 4: Run green**

```bash
python -m pytest code/tests/pilot/test_sample_risk_calibration.py code/tests/test_experiment_framework.py -q
```

**Step 5: Commit**

```bash
git add code/kaf_profiti/industrial/risk.py code/tests/pilot/test_sample_risk_calibration.py
git commit -m "feat: derive calibrated risk inputs from joint samples"
```

### Task P6.2: Enforce validation-only calibration

**Files:**
- Modify: `code/evaluate_risk_calibration.py`
- Modify: `code/kaf_profiti/experiments/pilot_runner.py`
- Modify: `code/tests/pilot/test_sample_risk_calibration.py`

**Step 1: Write failing leakage tests**

Spy on fitter inputs and assert only validation IDs/labels are passed; test IDs are transformed once after calibrator and threshold freeze; Platt and isotonic selection uses validation Brier/ECE; one-class splits emit null metrics according to protocol.

**Step 2: Run red**

```bash
python -m pytest code/tests/pilot/test_sample_risk_calibration.py -q
```

**Step 3: Refactor calibration into fit/transform stages**

```python
calibrator = fit_calibrator(valid_prob, valid_label, method)
threshold = select_threshold(valid_label, calibrator.transform(valid_prob))
test_prob_cal = calibrator.transform(test_prob)
```

Persist validation fit metadata, calibrator parameters and threshold. Never serialize test labels into the calibration artifact.

**Step 4: Run green**

```bash
python -m pytest code/tests/pilot/test_sample_risk_calibration.py code/tests/pilot/test_pilot_runner.py -q
```

**Step 5: Commit**

```bash
git add code/evaluate_risk_calibration.py code/kaf_profiti/experiments/pilot_runner.py code/tests/pilot/test_sample_risk_calibration.py
git commit -m "feat: enforce validation-only sample risk calibration"
```

**P6 gate:** risk is a deterministic function of joint samples and frozen limits; calibration fit and threshold selection never receive test labels; class-degenerate metrics follow null policy.

## P7 — Formal probability runs, aggregation and documentation alignment

### Task P7.1: Run preflight, smoke and bounded probability tuning

**Files:**
- Create: `configs/scheme_b/metropt3_kst_flow_v2_tuning.yaml`
- Modify: `plan/progress.md`

**Step 1: Freeze the only flow sweep**

Use Stage 1 selected checkpoint, seed 2026, mixed 0.30, fixed flow architecture, `lambda_point=[0.05,0.1,0.2]`. Rank by validation joint NLL, then Energy Score, CRPS and MAE. Test remains unopened.

**Step 2: Preflight and smoke**

```bash
python -m pytest code/tests/pilot/test_kst_flow_distribution.py code/tests/pilot/test_sample_risk_calibration.py -q
python -u code/check_pilot_environment.py --profile metropt3 --require-clean
python -u code/run_scheme_b_matrix.py --config configs/scheme_b/metropt3_kst_flow_v2_tuning.yaml --mode dry-run
```

Run one-batch forward/backward and sampling smoke on RTX 3090. Require finite loss, finite gradients, peak memory below 24GB and `test_evaluation_count=0`.

**Step 3: Run three tuning jobs**

Execute independently and validate three completed scientific keys. Freeze one `lambda_point` from validation.

**Step 4: Record evidence**

Append all validation metrics, selected value, checkpoint SHA and memory use to `plan/progress.md`.

**Step 5: Commit**

```bash
git add configs/scheme_b/metropt3_kst_flow_v2_tuning.yaml plan/progress.md
git commit -m "exp: freeze KST Flow v2 loss weight"
```

### Task P7.2: Run formal multi-seed probability and risk experiments

**Files:**
- Create: `configs/scheme_b/metropt3_kst_flow_v2_formal.yaml`
- Modify: `plan/progress.md`
- Output: `result/scheme_b/metropt3/probability/runs/`

**Step 1: Freeze the formal matrix**

Use seeds 2026/2027/2028, selected Stage 1 architecture, selected `lambda_point`, `nsamples=100`, preregistered probability baselines, limits, risk aggregation and calibration candidate set.

**Step 2: Dry-run and identity audit**

```bash
python -u code/run_scheme_b_matrix.py --config configs/scheme_b/metropt3_kst_flow_v2_formal.yaml --mode dry-run
```

Require unique keys, baseline-first ordering, one distribution identity, identical split/mask/normalization/evaluator SHA values and no legacy KST artifact reuse.

**Step 3: Execute and validate**

Run each seed independently. For every run require finite NLL/CRPS/Energy Score/PICP/MPIW, `nsamples=100`, one frozen test evaluation, checkpoint and prediction SHA matches, and complete validation-only calibration metadata.

**Step 4: Aggregate**

```bash
python code/build_tables.py --results-dir result/scheme_b/metropt3/probability
```

Generate mean±std tables for probability and risk, include `n=3`, run IDs, missing denominators and null metrics.

**Step 5: Commit config and progress**

```bash
git add configs/scheme_b/metropt3_kst_flow_v2_formal.yaml plan/progress.md
git commit -m "exp: record KST Flow v2 formal probability runs"
```

### Task P7.3: Align thesis plans and project documentation

**Files:**
- Modify: `README.md`
- Modify: `统一对比实验方案.md`
- Modify: `3.2_结构框架.md`
- Modify: `plan/implementation-plan.md`
- Modify: `plan/progress.md`

**Step 1: Audit terms and evidence**

Search for `kst_probflow`, `LowRankCopulaFlowHead`, independent quantile/risk claims and single-seed superiority language. Classify each occurrence as legacy history, implementation description or thesis claim.

**Step 2: Update only claims supported by verified artifacts**

Describe `kst_light_v2` as Chapter 3 and `kst_flow_v2` as Chapter 4. Mark old pilot artifacts as legacy. Insert formal run IDs, seeds, denominators and checkpoint provenance only after P7.2 passes.

**Step 3: Verify cross-document consistency**

```bash
rg -n "kst_probflow|kst_light_v2|kst_flow_v2|LowRankCopulaFlowHead|QuantileHead|RiskHead" README.md 统一对比实验方案.md 3.2_结构框架.md plan/implementation-plan.md plan/progress.md
git diff --check
```

Check chapter titles, model IDs, risk calibration scope and experiment counts against the configs and manifests.

**Step 4: Run the full code suite**

```bash
python -m pytest code/tests/ -q
```

Expected: all tests pass. Record exact count and environment in `plan/progress.md`.

**Step 5: Commit**

```bash
git add README.md 统一对比实验方案.md 3.2_结构框架.md plan/implementation-plan.md plan/progress.md
git commit -m "docs: align thesis with verified Scheme B evidence"
```

**P7 gate:** all formal keys and three seeds verify; probability and risk tables are reproducible from artifacts; documentation distinguishes legacy, implemented and experimentally verified claims.

## Final verification checklist

Run from repository root:

```bash
python -m pytest code/tests/ch3/ -q
python -m pytest code/tests/pilot/ -q
python -m pytest code/tests/ -q
python -u code/run_scheme_b_matrix.py --config configs/scheme_b/metropt3_kst_light_v2_formal.yaml --mode dry-run
python -u code/run_scheme_b_matrix.py --config configs/scheme_b/metropt3_kst_flow_v2_formal.yaml --mode dry-run
git diff --check
```

Confirm from generated manifests:

1. `model_id` and `recipe_version` separate v2 from legacy.
2. Every formal configuration has exactly three seeds.
3. Split, normalization, mask, target schema and evaluator hashes match across compared models.
4. Point, probability and risk artifacts identify their source checkpoint.
5. Test selection count is zero and frozen test evaluation count is one.
6. No non-finite metric or missing artifact is silently excluded from aggregation.
