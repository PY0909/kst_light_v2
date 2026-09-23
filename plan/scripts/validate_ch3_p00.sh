#!/usr/bin/env bash
set -euo pipefail

export LC_ALL=C
export LANG=C

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "${script_dir}/../.." && pwd)
cd "${repo_root}"

protocol=plan/experiment-protocol.md
traceability=plan/review/method-experiment-traceability.md
table_schema=tables/table-schema.md
figure_manifest=figures/data-manifest.md
plan_file=plan/implementation-plan.md
inputs=("${protocol}" "${traceability}" "${table_schema}" "${figure_manifest}")

fail() {
  printf 'validation_error=%s\n' "$1" >&2
  exit 1
}

require_match() {
  local pattern=$1
  local file=$2
  rg -q -- "${pattern}" "${file}" || fail "missing pattern in ${file}: ${pattern}"
}

for file in "${inputs[@]}" "${plan_file}"; do
  [[ -f "${file}" ]] || fail "missing file: ${file}"
done

for marker in 'Task CH3-P00-T01 完成' 'Task CH3-P00-T02 完成' 'Task CH3-P00-T03 完成'; do
  rg -q -- "- \[x\].*${marker}" "${plan_file}" || fail "incomplete prerequisite: ${marker}"
done

for dataset in 'MetroPT-3' 'C-MAPSS FD004' 'TEP'; do
  require_match "${dataset}" "${protocol}"
done

for model in 'li_tcn' 'ff_gru' 'masked_tcn' 'gru_d' 'ode_rnn' 'kst_light'; do
  require_match "${model}" "${protocol}"
done
require_match 'E5-A 消融' "${protocol}"

for seed in '2026' '2027' '2028'; do
  require_match "${seed}" "${protocol}"
done
require_match '0%/10%/30%/50%/70%' "${protocol}"
for mechanism in 'random' 'low_rate' 'block_offline' 'mixed'; do
  require_match "${mechanism}" "${protocol}"
done

require_match '| Contribution | Method module | Experiment | Table/Figure | Allowed claim | Evidence status |' "${traceability}"
for contribution in '真实时间' 'mask' 'delta_t' '通道身份' '工况' '多尺度' '跨传感器交互'; do
  require_match "${contribution}" "${traceability}"
done

table_sections=$(rg -n '^## [0-9]+\. Ch3-T[1-8] ' "${table_schema}" | wc -l | tr -d ' ')
[[ "${table_sections}" == '8' ]] || fail "table section count is ${table_sections}, expected 8"
for field in '主键' '指标列' '聚合' 'artifact 来源' '允许结论'; do
  require_match "${field}" "${table_schema}"
done

figure_sections=$(rg -n '^## [0-9]+\. Ch3-F[1-5] ' "${figure_manifest}" | wc -l | tr -d ' ')
[[ "${figure_sections}" == '5' ]] || fail "figure section count is ${figure_sections}, expected 5"
for field in 'source CSV' '必需列' '图形与坐标' '允许结论' '证据门槛' 'SVG' '300 dpi PNG'; do
  require_match "${field}" "${figure_manifest}"
done

if rg -n 'T[B]D|T[O]DO|待[定]|稍后实[现]|视情[况]' "${inputs[@]}"; then
  fail 'placeholder found in D0-D2 inputs'
fi

if rg -n -P '(?<!Ch3-)\b(?:NLL|CRPS|Energy Score|PICP|MPIW|AUROC|AUPRC|F1|ECE)\b|风险概率|风险阈值|校准' "${traceability}" "${table_schema}" "${figure_manifest}"; then
  fail 'forbidden chapter-three evidence metric found'
fi

if rg -n '/Users/|/root/|https?://|ssh[[:space:]]|([0-9]{1,3}\.){3}[0-9]{1,3}' "${inputs[@]}"; then
  fail 'machine-specific path or remote link found'
fi

printf 'validated=CH3-P00\n'
printf 'table_sections=%s figure_sections=%s\n' "${table_sections}" "${figure_sections}"
printf 'model_variant_families=7 (six main-comparison models plus controlled-ablation variant family)\n'
printf 'input_sha_set_begin\n'
for file in "${inputs[@]}"; do
  digest=$(shasum -a 256 "${file}" | awk '{print $1}')
  printf 'sha256=%s path=%s\n' "${digest}" "${file}"
done | sort -k2
printf 'input_sha_set_end\n'
