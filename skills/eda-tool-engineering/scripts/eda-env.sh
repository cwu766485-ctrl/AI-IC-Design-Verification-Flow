#!/usr/bin/env bash
# Source after setting the product homes installed on this host.
set -euo pipefail
eda_paths=()
for eda_home_var in SCL_HOME VCS_HOME VERDI_HOME DC_HOME ICC_HOME ICC2_HOME PRIME_HOME FM_HOME LC_HOME SPYGLASS_HOME RTLA_HOME STARRC_HOME VC_FORMAL_HOME TESTMAX_HOME; do
  eda_home="${!eda_home_var:-}"
  if [[ -n "$eda_home" && -d "$eda_home/bin" ]]; then
    eda_paths+=("$eda_home/bin")
  fi
done
if ((${#eda_paths[@]})); then
  eda_joined=$(IFS=:; echo "${eda_paths[*]}")
  export PATH="$eda_joined:$PATH"
fi
unset eda_home_var eda_home eda_paths eda_joined
