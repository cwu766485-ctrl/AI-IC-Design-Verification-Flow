#!/usr/bin/env bash
set -euo pipefail

example_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$example_dir/../../../.." && pwd)"
cd "$example_dir"
export PATH="$example_dir/tools:$PATH"
unset VCS_HOME DC_HOME PRIME_HOME
run_tag="r1-mock-$(date +%Y%m%d-%H%M%S)-$$"

"$repo_root/aicflow" plan --flow rtl_to_sim_synth
"$repo_root/aicflow" run --flow rtl_to_sim_synth --execute --run-id "$run_tag-cold"
"$repo_root/aicflow" run --flow rtl_to_sim_synth --execute --run-id "$run_tag-repeat"

backup="$(mktemp)"
cp eda.yaml "$backup"
restore_config() { cp "$backup" eda.yaml; rm -f "$backup"; }
trap restore_config EXIT
printf '\n# Cache invalidation exercise; restored when the demo exits.\n' >> eda.yaml
"$repo_root/aicflow" run --flow rtl_to_sim_synth --from vcs_compile --to dc_synthesis \
  --execute --run-id "$run_tag-incremental"
printf 'Demo run IDs: %s-cold %s-repeat %s-incremental\n' "$run_tag" "$run_tag" "$run_tag"
