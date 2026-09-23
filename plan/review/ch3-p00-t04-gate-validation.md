# CH3-P00 D0-D2 Gate Validation Evidence

> Evidence ID: `ch3-p00-t04-validation-20260904`
> Checked at UTC: `2026-09-04T06:26:03Z`
> Scope: documentation gates D0, D1 and D2 only; no model, data, run artifact or experiment result is asserted here.

## Command And Result

```bash
bash plan/tests/test_validate_ch3_p00.sh
LC_ALL=C.UTF-8 LANG=C.UTF-8 bash plan/scripts/validate_ch3_p00.sh
```

Both commands exited with `0`. The first command confirms that the validator test passes under the previously warning-producing locale. The second command validates the protocol, traceability and output-contract inputs without locale-warning contamination.

## Validation Summary

- `validated=CH3-P00`
- `table_sections=8`
- `figure_sections=5`
- `model_variant_families=7`: six E1 main-comparison models plus the controlled-ablation variant family.
- The validator found no placeholders in the four D0-D2 input documents.
- The validator found no prohibited third-chapter probability/risk metrics in the traceability or output-contract documents.
- The validator found no machine-specific paths or remote links in the four D0-D2 input documents.

## Canonical Input SHA Sets

### D0

```text
sha256=a4f852395340f46f4cf8066f5d2099e7bfef98736b2af19c4efa881084156efa path=plan/experiment-protocol.md
```

### D1

```text
sha256=a4f852395340f46f4cf8066f5d2099e7bfef98736b2af19c4efa881084156efa path=plan/experiment-protocol.md
sha256=aa4d9731196da6a2ec0d174aaf1dc656a0f0640017ba8ed65a4b75fc63793114 path=plan/review/method-experiment-traceability.md
```

### D2

```text
sha256=38f31084c9584b6a2c35690f017ff33b60601d75e4804080d357374b059d6a6a path=figures/data-manifest.md
sha256=a4f852395340f46f4cf8066f5d2099e7bfef98736b2af19c4efa881084156efa path=plan/experiment-protocol.md
sha256=aa4d9731196da6a2ec0d174aaf1dc656a0f0640017ba8ed65a4b75fc63793114 path=plan/review/method-experiment-traceability.md
sha256=d071c73ac3e1625796879632778a56c59c3c71326d0e5dab79d48750755fd7b0 path=tables/table-schema.md
```

## Closure Boundary

The evidence closes only the planning-document gates. Any change to a listed input requires `validate_ch3_p00.sh` to recompute its input SHA set before downstream work proceeds. D3-D5 remain open because no formal run coverage, output bundle or reviewer/freeze evidence exists.
