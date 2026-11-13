# R1 Execution and Efficiency Report

Validation date: 2026-11-07. This report separates fake-adapter measurements
from the licensed Synopsys smoke. Neither is a design or signoff claim.

## Python and mocked DAG validation

The Python-only suite completed with **65 passed**. It covers the runtime
contract and JSON Schemas, invalid DAGs, selection/dependency behavior,
failure propagation, cache invalidation and tamper detection, concurrent resume serialization, mocked SSH routing, existing CLI adapters, and the PPA evaluator.

The demo at
[`r1_dag_smoke`](../skills/eda-tool-engineering/examples/r1_dag_smoke/run_demo.sh)
uses fake `vcs`, `dc_shell`, and `pt_shell` executables. It validates scheduler,
status, cache, and invalidation behavior only. The measured run records were:

| Case | Manifest status | Stages | Tool invocations | Cache hits | Workflow time |
|---|---:|---:|---:|---:|---:|
| Cold composite run | PASS | 4 | 3 | 0 | 0.307 s |
| Unchanged repeat | PASS | 4 | 0 | 4 | 0.161 s |
| Config changed, compile→DC slice | NOT_RUN | 2 | 2 | 0 | 0.218 s |

In the partial run both selected stages (`vcs_compile`, `dc_synthesis`) were
PASS; the overall status remains `NOT_RUN` because the rest of the composite
flow was not selected. `agent_invocations` and `token_usage` are `null` because
the caller does not expose those counters. These fake-tool timings do not
support a real EDA speedup or token-savings claim.

## Licensed Synopsys smoke

The final R1 runtime ran an isolated copy of an owned counter RTL/TB fixture.
The copy received local Git revision
`76930b5c1951455479a2f0efe86450ce66f05ae6`. Runs were written to a temporary
workspace under `/tmp/aicflow-r1-final-real.jt9trB/`; those logs/reports were
not added to the repository.

| Run | Status | Tool invocations | Workflow time | Tool versions | Stage evidence |
|---|---:|---:|---:|---|---|
| `r1-vcs-urg-final` | PASS | 4 | 5.517 s | VCS `V-2023.12-SP1`; URG `V-2023.12-SP1` | Compile PASS; seeds 11 and 23 simulation/result PASS; URG and coverage summary PASS; Verdi debug artifacts inventoried |
| `r1-dc-pt-final` | PASS | 2 | 112.446 s | DC `V-2023.12-SP1`; PrimeTime `V-2023.12-SP2` | DC synthesis PASS; PrimeTime STA PASS |

The URG report parser read 80.15% code coverage and 100% functional coverage
for one covergroup in this fixture. This is fixture output, not a coverage
closure claim for a product design. The Verdi GUI was not launched; its stage
only inventoried debug artifacts and wrote a launch script.

DC reported cell area 50.0, WNS 3.99, and TNS 0.0 in the generated fixture
reports; PrimeTime reported WNS 8.5 and TNS 0.0. The example `lsi_10k.db`
library is not a product PDK or a signoff library. DC power parsing was
`PARTIAL`: dynamic power was present, but the library's leakage unit was
unitless, so total power remained `null`. No power pass or signoff is claimed.

The first runtime attempt exposed a VCS-generated `csrc` symlink during
incidental top-level artifact inventory. The runtime now records that helper
tree in `omitted_artifacts`; declared stage outputs remain content-verified,
and the final fresh-copy rerun passed. This omission is visible in the run
manifest and does not relax any required-report check.

## Efficiency interpretation and limits

The unchanged mock repeat avoided all three external fake-tool invocations
through four verified stage cache hits. The config edit invalidated the two
selected stage keys, and those tools ran again. This demonstrates expected
cache semantics, not a general speedup: only one small example run was
measured, and fixture setup/OS cache effects are not controlled.

The general EDA run budget and PPA campaign ledger are still separate. The R1
runtime serializes same-run execution and carries EDA time across resume, but
does not yet reconcile EDA and PPA cumulative budgets transactionally. Codex
token and agent-call telemetry is unavailable here and is intentionally
reported as `null`.
