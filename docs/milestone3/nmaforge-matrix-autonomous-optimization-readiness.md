# NMAForge Matrix Optimization Readiness

Status: functional verification reproduced; ASIC PPA baseline blocked; no RTL
candidate was attempted.

## Integration State

- Integration branch: `feature/m2-r1-verification-integration` at
  `6b81d88cedde3fa32acbff18ee5e6f309e40d094`.
- PR #3: https://github.com/cwu766485-ctrl/AI-IC-Design-Verification-Flow/pull/3
- GitHub Actions for this SHA: both `RTL PPA Python tests` runs succeeded:
  https://github.com/cwu766485-ctrl/AI-IC-Design-Verification-Flow/actions/runs/43424976851
  https://github.com/cwu766485-ctrl/AI-IC-Design-Verification-Flow/actions/runs/43424969667
- Local pre-readiness results reproduced: `python3.12 -m pytest -q tests`:
  78 passed; `python3.12 -m pytest -q tests/rtl_ppa`: 21 passed.
- Readiness branch result after adding the controller: full suite 94 passed;
  PPA-focused suite 37 passed. New-branch GitHub Actions status is pending
  until its push completes.
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
(`V-2023.12-SP2`) executables are installed. No approved target-specific
standard-cell library, SRAM timing library or SDC is available in the public
NMAForge worktree or configured environment. `TSMC28_STDCELL_DB` and
`TSMC28_SRAM_DB_TT` are unset. `syn/README.md` states that the library views,
macro adapter, technology constraints and generated reports belong to a
private ASIC overlay. The checked-in synthesis report describes a historical
`ai_accel_top` result, not this standalone matrix-core target, and cannot
provide its area or timing baseline.

The existing example plan still contains `/path/to/approved/stdcells.db`,
`/path/to/approved/matrix.sdc`, and `__CONFIGURE_PROJECT_ADAPTER__`; these are
explicit placeholders, not runnable commands. No target-specific SDC defines
the matrix-core clock, input/output delays, loads, driving cells, uncertainty,
or operating corner. The reported 4 ns top-level clock from the historical
report is not automatically applicable to this block. DC and PrimeTime were
not run. Power was not run because there is no approved mapped netlist/library
pair or workload-annotated activity input for this target. No area, WNS, ASIC
frequency, or power metric is claimed.

The mandatory approved functional/equivalence policy for a candidate is also
not yet attached to this project plan. The existing VCS golden regression is
available; the existing matrix formal properties are FSM guards, not a full
candidate-to-baseline equivalence proof. Until owners supply the allowed
behavioral contract and proof gate, cycle-equivalence is not assumed.

Required inputs to unblock a real baseline:

- owner-approved standard-cell and SRAM timing views for a named PVT corner;
- a reviewed standalone matrix-core SDC with clock and IO assumptions;
- the matching technology setup and synthesis/STA scripts;
- an approved candidate functional/equivalence gate and its acceptance policy;
- workload activity plus a reviewed power methodology, only if power remains
  a mandatory metric.

The next action while these are unavailable is STOP. No candidate count was
consumed and no candidate was evaluated.

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

This implementation deliberately stops before a controlled candidate
evaluation because a valid measured PPA baseline and approved candidate gate do
not exist yet. Once those inputs are supplied, the next reviewable change can
replace the example placeholders with a target-specific adapter and run no
more than three isolated candidates through `rtl_ppa.py`.
