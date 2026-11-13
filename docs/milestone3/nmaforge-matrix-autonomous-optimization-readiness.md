# NMAForge Matrix Optimization Readiness

Status: simulation baseline reproduced. The initial Candidate 001 rejection
is preserved for the old testbench revision; corrected Candidate 001R2 and
Candidate 002R2 passed all configured simulation stages with aligned
per-workload stimulus and a 0.25% cycle reduction. The 5% goal remains unmet.
ASIC PPA is STOP; no signoff claim.

## Integration State

- Integration branch: `feature/m2-r1-verification-integration` at
  `6b81d88cedde3fa32acbff18ee5e6f309e40d094`.
- PR #3: https://github.com/cwu766485-ctrl/AI-IC-Design-Verification-Flow/pull/3
- M3 readiness PR #4: https://github.com/cwu766485-ctrl/AI-IC-Design-Verification-Flow/pull/4
- GitHub Actions for this SHA: both `RTL PPA Python tests` runs succeeded:
  https://github.com/cwu766485-ctrl/AI-IC-Design-Verification-Flow/actions/runs/43424976851
  https://github.com/cwu766485-ctrl/AI-IC-Design-Verification-Flow/actions/runs/43424969667
- Local pre-readiness results reproduced: `python3.12 -m pytest -q tests`:
  78 passed; `python3.12 -m pytest -q tests/rtl_ppa`: 21 passed.
- Readiness branch local result: `python3.12 -m pytest -q tests` passed 99;
  `python3.12 -m pytest -q tests/rtl_ppa` passed 42. GitHub Actions for the
  current branch commit `c356124b8b037c8e245fabf4ea53fe2d8bd40faa` passed in
  [run 43445415952](https://github.com/cwu766485-ctrl/AI-IC-Design-Verification-Flow/actions/runs/43445415952)
  and [run 43445406484](https://github.com/cwu766485-ctrl/AI-IC-Design-Verification-Flow/actions/runs/43445406484).
- `python3.12 aicflow --help` succeeds. The wrapper inserts its sibling EDA
  script directory into `sys.path`, then imports the canonical `eda` module.
  This confirms the runtime import works. The reported Pylance warning is
  consistent with static analysis not following this dynamic path insertion;
  no runtime failure was reproduced, and Pyright was not installed here for a
  second static check.

## Project Identity And Verification

NMAForge was inspected at commit `409c3a9fd647d4f8c4c881c9bfdaf5d93b7076ee`,
branch `feat/shape-adaptive-gemv-v2`. Its original worktree had two unrelated
untracked files (`novas.conf`, `novas.rc`); they were preserved. No RTL or
tracked NMAForge file was modified.

The isolated Matrix abort-test and evidence branch is available for review in
[NMAForge PR #10](https://github.com/cwu766485-ctrl/NMAForge/pull/10), targeting
`feat/shape-adaptive-gemv-v2`. GitHub reports no Actions checks for that branch;
the required VCS regression was run locally and its logs are archived with
SHA-256 values in the PR branch.

The target is `ai_tensor_matrix_core`. The existing VCS compile order is:

1. `rtl/compute/matrix/ai_tensor_matrix_datapath.v`
2. `rtl/compute/matrix/ai_tensor_matrix_array.sv`
3. `rtl/compute/matrix/ai_tensor_matrix_core.v`
4. `dv/block/compute/matrix/tb/tb_ai_tensor_matrix_core_random.sv`

SHA-256 at the inspected revision:

| Source | SHA-256 |
| --- | --- |
| `rtl/compute/matrix/ai_tensor_matrix_datapath.v` | `c7fc6ab36d39df0f4890dec11c3c39265a0b8efec79ce4806560d96a2fe5aac9` |
| `rtl/compute/matrix/ai_tensor_matrix_array.sv` | `83d8e6b170fe3645207ecfd2a82d7290f36a8d8114e4d940bbeb8f94f790594d` |
| `rtl/compute/matrix/ai_tensor_matrix_core.v` | `dedc44406ab9f30b270bde12dbfeb3ab88184bb29af446fa1f119321e5d73aad` |
| `dv/block/compute/matrix/tb/tb_ai_tensor_matrix_core_random.sv` | `cc45beb5dfad30bb5db60081378f63ecd00f2e484a0faac7b89f1aaf4fc61dcf` |

The testbench computes expected integer results and checks every output word,
layout, completion count, prefetch/cache counters, fault response, write
suppression and reset recovery. The reference is part of this testbench; this
run did not establish an independent formal equivalence proof.

Functional command:

```sh
make -C dv/block/compute/matrix/sim core-random-regress \
  SEEDS='20261021 20261022 20261023' \
  CORE_OUT_DIR=/tmp/nmaforge_aiicflow_409c3a9_matrix_core
```

VCS V-2023.12-SP1 passed all three seeds. Each seed reported 18 cases, 35 fault
checks, a late-tile fault, reset recovery, prefetch handoff, and phase abort and
reset checks. Compile and run logs remain under that `/tmp` directory. The
three seed log hashes are `0803504378e947e205529d0f702c92dec3132c21f8f57626c6e95b4f4e6d9b4f`,
`f628cae194e4ac90875b60890adeb4b91b8a7952d6700d42efbfcee22215180c`, and
`74d19cec417341c687f659c85f89bb083353380b493c428ada234eba4fd46aee`.

Cycle benchmark command:

```sh
make -C dv/block/compute/matrix/sim matrix-pipeline-benchmark \
  SEED=20261113 PIPELINE_ARRAY_SIZE=16 \
  PIPELINE_BENCH_OUT=/tmp/nmaforge_aiicflow_409c3a9_matrix_benchmark
```

The table below preserves the initial stimulus-stream measurements. The
per-workload-aligned comparison in `simulation-performance-campaign.md`
supersedes these values for candidate evaluation.

The measured RTL simulation cycles and useful MAC/cycle were:

| M×N×K | Cycles | MAC/cycle |
| --- | ---: | ---: |
| 4×4×32 | 76 | 6.737 |
| 8×8×32 | 116 | 17.655 |
| 16×16×32 | 233 | 35.159 |
| 16×32×32 | 417 | 39.290 |
| 32×32×64 | 1187 | 55.211 |

These are workload-cycle observations using a one-cycle behavioral bank
response and fixed deterministic backpressure. The testbench also prints a
250 MHz normalized GOPS value, but that clock assumption is not used here as
measured throughput or timing evidence. The benchmark run log SHA-256 is
`7b1a5fb6d0f13a470d6448cf2b486fdc1290fa1dd4d4ed5c5fec500a69cf4a7e`.

## ASIC PPA Blockers

VCS (`V-2023.12-SP1`), Design Compiler (`V-2023.12-SP1`) and PrimeTime
(`V-2023.12-SP2`) executables are installed. A private TSMC 28 nm RVT
standard-cell timing library, physical LEF, SRAM views, and RC extraction tables
are present on the local host outside this repository. The local setup script
exposes a slow-corner standard-cell view by default. These assets are not copied
to this repository; approval for using a specific library/corner in this
project has not been established. `TSMC28_STDCELL_DB` and `TSMC28_SRAM_DB_TT`
remain unset in the current shell, so project-specific adapter configuration
is still required. `syn/README.md` states that library views, macro adapters,
technology constraints and generated reports belong to a private ASIC overlay.
The checked-in synthesis report describes a historical `ai_accel_top` result,
not this standalone matrix-core target, and cannot provide its area or timing
baseline.

The existing example plan still contains `/path/to/approved/stdcells.db`,
`/path/to/approved/matrix.sdc`, and `__CONFIGURE_PROJECT_ADAPTER__`; these are
explicit placeholders, not runnable commands. No target-specific SDC defines
the matrix-core clock, input/output delays, loads, driving cells, uncertainty,
or approved operating corner. The reported 4 ns top-level clock from the
historical report is not automatically applicable to this block. DC and
PrimeTime were not run. Power was not run because there is no approved mapped
netlist/library pair or workload-annotated activity input for this target. No
area, WNS, ASIC frequency, or power metric is claimed.

The mandatory approved functional/equivalence policy for a candidate is also
not yet attached to this project plan. The existing VCS golden regression is
available; the existing matrix formal properties are FSM guards, not a full
candidate-to-baseline equivalence proof. Until owners supply the allowed
behavioral contract and proof gate, cycle-equivalence is not assumed.

Required inputs to unblock a real baseline:

- owner approval of the locally available standard-cell timing view and, if
  instantiated, SRAM timing views for a named PVT corner;
- a reviewed standalone matrix-core SDC with clock and IO assumptions;
- the matching technology setup and synthesis/STA scripts;
- an approved candidate functional/equivalence gate and its acceptance policy;
- workload activity plus a reviewed power methodology, only if power remains
  a mandatory metric.

For the ASIC PPA campaign, the required action while these inputs are
unavailable remains STOP; no ASIC candidate count is consumed and no ASIC
candidate has been evaluated.

## Simulation-Performance Iteration

The simulation-only contract is now explicit in the RTL PPA plan validator.
It accepts only transaction-level behavior with regression, reference-model,
latency-gate and performance stages, and workload-cycle/MAC-per-cycle metrics.
It rejects ASIC synthesis, STA, power and formal stages. This shares the plan
and validation contract with the existing evaluator; ASIC requests remain
strict and are never downgraded automatically.

At NMAForge revision `409c3a9fd647d4f8c4c881c9bfdaf5d93b7076ee`, the original
three-seed regression and five-workload benchmark were reproduced in a detached
worktree. The original Candidate 001 `REJECT` remains historical for that
testbench revision. Corrected Candidate 001R2 and Candidate 002R2 passed all
four configured Stage Runtime stages after the abort test moved to the
final-write-pending boundary. Their aligned aggregate changed from 2010 to 2005
cycles (-0.25%), below the 5% target. Results, source hashes, decisions, and
limits are in [`simulation-performance-campaign.md`](simulation-performance-campaign.md).

## Optimization Components

`skills/rtl-ppa-optimization/scripts/autonomous_optimizer.py` provides a small
decision layer around the existing evaluator and Stage Runtime:

- `QoRAnalyzer` exposes a baseline only when the campaign and required stages
  pass, required metrics have parser/artifact provenance, and structured
  critical-path and area-hotspot evidence exists.
- `CandidateGenerator` records source revision, hypothesis, hotspot, intended
  RTL change, expected metric impact, functional/timing risks, patch SHA-256,
  approved scope and required validation stages. It rejects unknown hotspots
  and out-of-scope patch paths; it does not silently edit RTL.
- `OptimizationController` returns `ACCEPT`, `REJECT`, `RETRY`,
  `CHANGE_STRATEGY`, or `STOP` with evidence, proposed change, required
  validation commands, expected impact and remaining budget. Missing evidence
  or blocked mandatory gates produce `STOP`.
- `summarize_benchmarks` reports candidate rate, metric deltas, regressions,
  elapsed EDA runtime, cache hits, tool starts and human interventions. Agent
  calls and token use remain `null` unless an external telemetry source is
  supplied; no efficiency comparison is claimed.

The simulation-performance mode has evaluated Candidate 001R2 and Candidate
002R2 through the shared Stage Runtime using a reproducible behavioral
baseline. The 0.25% cycle change does not meet the campaign target and does not
unblock ASIC optimization. Without an approved library/corner, reviewed SDC,
formal/equivalence policy, and target-specific synthesis/STA setup, the ASIC
controller must still return `STOP`. Once those inputs are supplied, no more
than three isolated ASIC candidates can be evaluated through `rtl_ppa.py`.
