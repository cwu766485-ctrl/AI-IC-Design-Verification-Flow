# RTL PPA Plan Contract

The evaluator consumes a YAML mapping. It needs PyYAML or Ruby's standard YAML
library. Plans are project-specific; commands must be argument arrays, never
shell command strings.

## Required fields

```yaml
schema_version: 1
project: accelerator-block
optimization_mode: asic_ppa # or simulation_performance
design_top: accelerator_core
testbench_top: tb_accelerator_core
rtl_scope:
  - rtl/block/*.sv
rtl_sources:             # explicit compile order
  - rtl/block/pkg.sv
  - rtl/block/accelerator_core.sv
testbench_sources:       # explicit simulation order
  - dv/block/tb_accelerator_core.sv
allowed_patch_paths:
  - rtl/block/*.sv
behavior_contract: cycle_equivalent
required_stages:
  baseline: [regression, synthesis, sta]
  candidate: [regression, synthesis, sta]
stages: []       # ordered stage definitions; see below
metrics: {}      # see metric rules below
budget:
  max_candidates: 4
  max_runtime_sec: 7200
  max_total_runtime_sec: 28800
read_only_assets: []
```

`design_top` and `testbench_top` are explicit HDL module identifiers consumed
by project adapters. `rtl_sources` and `testbench_sources` are ordered relative
file lists; the evaluator verifies that the declared top modules occur in the
respective lists and records them in a source manifest for adapters.
`rtl_scope` must match at least one project-relative source file and include
every `rtl_sources` entry. It is used for source hashes and audit context.
`allowed_patch_paths` must limit candidate
changes to the intended RTL. Candidate changes must also be limited to files in
the explicit ordered `rtl_sources` list, so a broad allowed pattern cannot
introduce RTL absent from the compile order. All stage IDs listed under `required_stages` must
exist and be enabled for that mode.
Required stages and required metric source stages must declare at least one
`expected_artifacts` path so missing reports cannot be silently ignored.

`optimization_mode` defaults to `asic_ppa`. The separate
`simulation_performance` mode requires a `transaction_level` behavior contract,
`regression`, `reference_model`, `latency_gate`, and `performance` stages for
both baseline and candidate, and exactly the `workload_cycles` and
`macs_per_cycle` metrics from the performance stage. It rejects formal,
synthesis, STA, and power stages. This mode uses the same snapshot, stage,
cache, budget, artifact, and comparison runtime, but its results make no ASIC
area, timing, frequency, or power claim. Selecting this mode is explicit; an
ASIC PPA plan is never rewritten or downgraded automatically.

`behavior_contract` is either `cycle_equivalent` or `transaction_level`. A
cycle-equivalent candidate additionally requires a candidate stage named
`formal`. A transaction-level candidate additionally requires candidate stages
named `reference_model` and `latency_gate`, plus `max_latency_cycles` as a
positive integer. The project must define the actual proof/checker semantics;
the evaluator only requires and records those gates.

## Ordered stages

```yaml
stages:
  - id: regression
    adapter_id: project.regression.v1
    modes: [baseline, candidate]
    cwd: .
    argv: [python3, tools/rtl_ppa/run_stage.py, regression, "{source_root}", "{run_dir}"]
    timeout_sec: 1800
    result_json: "{run_dir}/stage-result.json"
    expected_artifacts: ["{run_dir}/regression-summary.json"]
    pass_patterns: ["REGRESSION PASS"]
    fail_patterns: ["REGRESSION FAIL"]
```

Stages run in list order and stop at the first non-`PASS` result. Paths are
resolved inside the source snapshot or that stage's run directory. Supported
placeholders are `{project_root}`, `{source_root}`, `{candidate_root}`,
`{run_dir}`, `{manifest}`, and `{seed}`. In stage commands, `project_root` intentionally
resolves to the isolated snapshot; the original project path is not passed to
the process. The stage command is responsible for producing its own evidence.

Each command must write the configured JSON result file and include a matching
`adapter_id`, `adapter_supported: true`, and nonempty `tool_versions` provenance
in addition to the stage status, metrics and artifacts. The adapter identity
must match the plan. The runner cannot prove that trusted adapter code reports
truthful versions or implements the named operation; adapter review and a
licensed-tool smoke test remain separate requirements.

```json
{
  "status": "PASS",
  "adapter_id": "project.synthesis.v1",
  "adapter_supported": true,
  "tool_versions": {"synthesis": "Tool 2026.06"},
  "metrics": {"cell_area": 1234.5},
  "metric_provenance": {
    "cell_area": {"artifact": "synthesis-report.rpt", "parser_id": "dc-area", "parser_version": "1.2"}
  },
  "artifacts": ["synthesis-report.rpt"]
}
```

Only a zero command exit code, passing log patterns, a result JSON with status
`PASS`, a matching supported adapter declaration, and nonempty expected
artifacts allow the stage to pass. Passing stages record SHA-256 and size
provenance for their result JSON and artifacts. A nonzero exit is
`FAIL`, a missing executable/license/report/artifact is `BLOCKED`, malformed
stage JSON is `ERROR`, and an unstarted downstream stage is `SKIPPED`. Stage
artifacts and result JSON must stay inside the stage run directory. Every
reported metric must be finite and have `metric_provenance` naming one of the
validated artifacts plus a nonempty parser ID and version; otherwise the stage
is blocked or erroneous and its metric cannot be compared.

## Metric rules

Every compared metric names its authoritative stage. The stage JSON must report
that metric as a finite number. Required metrics default to true:

```yaml
metrics:
  cell_area:
    source_stage: synthesis
    direction: lower
    unit: um^2
    required: true
    max_regression_pct: 0
  setup_wns:
    source_stage: sta
    direction: higher
    unit: ns
    required: true
    min_value: 0
```

`direction` is `lower` or `higher`. `min_value`, `max_value`, and
`max_regression_pct` are optional absolute or relative gates. Missing required
values block comparison; they are never replaced with zero. Configure limits
from the design specification and approved signoff methodology. An area or
frequency estimate must not be labelled as a measured implementation result.

## Read-only assets and isolation

Assets are copied into the Git snapshot rather than symlinked to their source.
This keeps EDA tools away from the original library/PDK files:

```yaml
read_only_assets:
  - source: /licensed/pdk/stdcells/slow.db
    target: external/pdk/slow.db
```

The copied asset is marked read-only. Sources containing symlinks or special
files are rejected so copying cannot escape the specified tree. Asset storage
can be large; include only what the configured stages need. Run output must be
outside `project_root`. The project worktree must be clean; the snapshot is
created from `HEAD`, not from uncommitted state.

## Status and decision

The evaluator emits `PASS`, `FAIL`, `ERROR`, `BLOCKED`, `NOT_RUN`, or `SKIPPED`.
`validate` returning `PASS` means only that the plan is structurally valid.
Dry runs are `NOT_RUN`. An executed candidate can have execution status `PASS`
while its optimization decision is `NO_IMPROVEMENT` or
`REVIEW_TRADEOFF`; the decision is recorded separately in `comparison.json`.
No status means design signoff.

## Evidence layout

Each campaign is stored under its run ID with:

```text
source/                 # immutable Git snapshot plus copied assets
source_manifest.json    # tops, ordered file lists and effective source hashes
source_revision.json    # source, patch and plan hashes
rtl_patch.diff          # candidate only
stages/<id>/            # command log, adapter JSON, artifacts and runner record
metrics.json            # metrics extracted from configured source stages
baseline.json           # baseline campaign summary
evidence.json            # campaign status and stage records
comparison.json         # candidate only, metric deltas and decision
budget.json              # shared candidate count and fractional elapsed-time ledger
```

`max_runtime_sec` applies to one baseline or candidate campaign. The separate
`max_total_runtime_sec` applies cumulatively to baseline plus candidate time in
the shared runs directory. Elapsed seconds retain fractional values. Campaigns
in one runs directory are serialized with a lock; a process interrupted during
a campaign is charged its reserved per-campaign allowance on the next run so
an interrupted attempt cannot evade the cumulative budget. Stage timeouts are
bounded by the tighter remaining campaign and cumulative allowance.

The ledger is local bookkeeping, not a tamper-proof accounting service. Keep a
runs directory single-user and preserve it with the resulting evidence. The
runner does not edit the original RTL tree. Stage adapter commands are trusted
project code and must be written to operate on the supplied snapshot and run
directory only.

Candidate comparison is blocked if the plan/source/top contract, seed, copied
asset hashes, shared-stage adapter/tool versions, or metric parser provenance
differ from the baseline. Declare external SDC and library files in
`read_only_assets`; the runner cannot detect inputs an adapter reads without
declaring them.
