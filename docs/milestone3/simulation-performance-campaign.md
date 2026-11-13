# Matrix Simulation Performance Campaign 001

Status: baseline reproduced; first candidate REJECTED by a required fault/abort
regression; no candidate performance result is available.

## Baseline

- NMAForge revision: `409c3a9fd647d4f8c4c881c9bfdaf5d93b7076ee`
- VCS: `V-2023.12-SP1_Full64`
- Configuration: 16x16 physical array, outstanding depth 4, next-K prefetch on,
  A-tile cache on, one-cycle behavioral bank response
- Regression command:

  ```sh
  make -C dv/block/compute/matrix/sim core-random-regress \
    SEEDS='20261021 20261022 20261023' \
    CORE_OUT_DIR=/tmp/nmaforge_m3_iteration_baseline_regression
  ```

- Benchmark command:

  ```sh
  make -C dv/block/compute/matrix/sim matrix-pipeline-benchmark \
    SEED=20261113 PIPELINE_ARRAY_SIZE=16 \
    PIPELINE_BENCH_OUT=/tmp/nmaforge_m3_iteration_baseline_benchmark
  ```

All three regression seeds passed 18 cases and 35 fault checks, including
late-tile faults, prefetch handoff, phase abort and reset recovery. The
reference model is checked by the existing testbench. The fixed workload
benchmark measured 2,029 aggregate cycles and 45.674 weighted useful MAC/cycle:

| Workload MxNxK | Cycles | Useful MAC/cycle |
| --- | ---: | ---: |
| 4x4x32 | 76 | 6.737 |
| 8x8x32 | 116 | 17.655 |
| 16x16x32 | 233 | 35.159 |
| 16x32x32 | 417 | 39.290 |
| 32x32x64 | 1187 | 55.211 |

The large workload recorded 328 write-state cycles, 490 prefetch-wait cycles,
208 arbiter-stall cycles, and 72 writeback-wait cycles. These are overlapping
event/state counters and must not be summed as disjoint overhead. The benchmark
reports workload cycles and useful MAC/cycle only. Its 250 MHz normalized GOPS
field is not treated as measured ASIC frequency or throughput.

RTL SHA-256 at the baseline revision:

| Source | SHA-256 |
| --- | --- |
| `rtl/compute/matrix/ai_tensor_matrix_datapath.v` | `c7fc6ab36d39df0f4890dec11c3c39265a0b8efec79ce4806560d96a2fe5aac9` |
| `rtl/compute/matrix/ai_tensor_matrix_array.sv` | `83d8e6b170fe3645207ecfd2a82d7290f36a8d8114e4d940bbeb8f94f790594d` |
| `rtl/compute/matrix/ai_tensor_matrix_core.v` | `dedc44406ab9f30b270bde12dbfeb3ab88184bb29af446fa1f119321e5d73aad` |
| `dv/block/compute/matrix/tb/tb_ai_tensor_matrix_core_random.sv` | `cc45beb5dfad30bb5db60081378f63ecd00f2e484a0faac7b89f1aaf4fc61dcf` |

Log artifacts remain under `/tmp/nmaforge_m3_iteration_baseline_regression`
and `/tmp/nmaforge_m3_iteration_baseline_benchmark`. Their hashes are recorded
below. The original NMAForge worktree was not changed; the run used a detached
temporary worktree.

The same baseline was then executed by the shared Stage Runtime using the
explicit `simulation_performance` plan. All four required stages passed in
23.046 s: regression (6.955 s), reference model (7.165 s), latency gate
(4.538 s), performance (3.882 s). Runtime metrics were 2,029 cycles and
45.674 weighted useful MAC/cycle. Stage evidence is in
`/tmp/nmaforge_m3_stage_runtime_campaign/baseline`.

Stage Runtime campaign evidence is under
`/tmp/nmaforge_m3_stage_runtime_campaign_final`; the plan hash is
`986815351385309591e739fdac18dff70e318cae69d8ab3d55c4203591cedea7`.
SHA-256 for the final Stage Runtime command logs:

| Stage | SHA-256 |
| --- | --- |
| regression | `90f6d0b575e16db66a98f09fc1b429993deef1401247ee40371667947d46f3a1` |
| reference_model | `edf9d52ffe524d2ef39a9a2416203979c6daf4f4326428db32faa33c44dcc612` |
| latency_gate | `78a49b438eb87374d436ed148fe661b367b7eb291a3661264047293d4d5d221a` |
| performance | `89c88c63634ff271c182efe8689e7e694eb253a1c5599a6378e5702ea98d8195` |

## Candidate 001

- Feature: `MATRIX-CYCLE-001`
- Hypothesis: remove the terminal `ST_DONE` bubble to save one cycle per
  completed command.
- Scope: `rtl/compute/matrix/ai_tensor_matrix_core.v` only.
- Intended impact: at most one cycle per workload; below the 5% campaign goal.
- Functional risk: asserting `done` early may bypass phase-abort behavior.
- Validation: the same three-seed `core-random-regress` command as baseline.
- Result: `REJECT`. Seed `20261021` failed because the phase-abort test waiting
  for `ST_PREFETCH_WAIT` instead observed `done` asserted and the core in IDLE.
  The required functional gate failed, so the candidate benchmark was skipped.
- Decision: preserve failure evidence; do not pursue this change.

Candidate worktree: `/tmp/NMAForge-m3-candidate-409c3a9`. Candidate regression
logs: `/tmp/nmaforge_m3_stage_runtime_campaign_final/MATRIX-CYCLE-001`. Stage Runtime
returned candidate execution `FAIL` and marked dependent stages `SKIPPED`; its
comparison is `BLOCKED` because performance was not evaluated. The decision
controller classifies the observed required regression failure as `REJECT`.
The reviewable patch and machine-readable decision are
[`MATRIX-CYCLE-001.diff`](candidates/MATRIX-CYCLE-001.diff) and
[`MATRIX-CYCLE-001.decision.json`](candidates/MATRIX-CYCLE-001.decision.json).
This is a simulation-only experiment; it contains no synthesis, STA, area,
frequency, or power result.

## Controller Scope

The evaluator recognizes an explicit `simulation_performance` mode and
validates that its plan uses transaction-level behavior, regression/reference/
latency/performance evidence, and only workload-cycle and MAC/cycle metrics.
The ASIC PPA mode remains the default and is not automatically downgraded.
The baseline and rejected candidate both ran through Stage Runtime. Controller
tests cover metric-only candidate generation and deterministic decisions for
failed required gates with downstream stages skipped. More candidate strategies
and a passing performance-improvement case remain untested. Agent-call/token
telemetry and a comparable manual-workflow baseline are unavailable, so no
efficiency comparison is claimed.
