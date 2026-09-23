#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "${script_dir}/../.." && pwd)
validator="${repo_root}/plan/scripts/validate_ch3_p00.sh"

test -x "${validator}"
output=$(LC_ALL=C.UTF-8 LANG=C.UTF-8 "${validator}" 2>&1)
rg -qx 'validated=CH3-P00' <<<"${output}"
rg -qx 'input_sha_set_begin' <<<"${output}"
rg -qx 'input_sha_set_end' <<<"${output}"
rg -q '^sha256=[0-9a-f]{64} path=plan/experiment-protocol.md$' <<<"${output}"
if rg -q 'warning:' <<<"${output}"; then
  printf 'validator emitted locale warning\n' >&2
  exit 1
fi
printf 'test_validate_ch3_p00=pass\n'
