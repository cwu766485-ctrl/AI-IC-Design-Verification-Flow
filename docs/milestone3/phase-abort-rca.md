# Matrix Candidate 001 Phase-Abort RCA

Status: Candidate 001 remains `REJECT`. Its reported failure is a testbench
reachability assumption, not evidence that an asserted abort was ignored. A
separate, narrower Candidate 002 patch passed the configured simulation gates
in an isolated NMAForge snapshot. Its workload improvement is small and mixed;
it does not meet the campaign's 5% target and is not a PPA or signoff result.

## Scope and preservation

- Base NMAForge revision: `409c3a9fd647d4f8c4c881c9bfdaf5d93b7076ee`.
- Candidate 001 changes only the final `ST_NEXT` branch in
  `rtl/compute/matrix/ai_tensor_matrix_core.v`: it replaces the transition to
  `ST_DONE` with `busy=0`, `done=1`, and a transition to `IDLE`.
- The Candidate 001 and baseline reproductions used separate temporary
  snapshots. Trace instrumentation was added only to those temporary
  testbench copies. No assertion, scoreboard check, or fault check was removed
  or weakened. The original NMAForge worktree was not modified.
- Seed: `20261021`; VCS: `V-2023.12-SP1_Full64`.

## First divergence

Cycle numbers below are operation-local `cycle_count`; absolute simulation
timestamps differ because earlier cases consumed different time. At cycle 21,
both implementations have completed four line writes and are in state 10
(`ST_NEXT`). At the next sample, before the testbench can assert abort, they
diverge:

| Snapshot | Cycle | State | `busy` | `done` | `error` | `abort` | Outstanding reads | Line writes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 21 | 10 (`ST_NEXT`) | 1 | 0 | 0 | 0 | 0 | 4 |
| Baseline | 22 | 11 (`ST_DONE`) | 1 | 0 | 0 | 0 | 0 | 4 |
| Candidate 001 | 21 | 10 (`ST_NEXT`) | 1 | 0 | 0 | 0 | 0 | 4 |
| Candidate 001 | 22 | 0 (`IDLE`) | 0 | 1 | 0 | 0 | 0 | 4 |

The baseline log then records
`MATRIX_CORE_PHASE_ABORT_PASS state=11 id=29 prior_writes=4/0`. Candidate 001
instead fails with `Matrix phase-abort target state=11 not reached current=0
done=1`. The task waits for `state_r == target_state` or `done`, and only after
that wait does it assert `abort`. Thus, in the failing Candidate 001 trace,
`abort` is still low and was never sampled by the DUT. This is the first
behavioral divergence and the direct cause of the regression failure.

Evidence logs:

- Baseline: `/tmp/nmaforge_m3_rca_baseline_20261021/run_seed_20261021.log`
- Candidate 001: `/tmp/nmaforge_m3_rca_candidate001_20261021/run_seed_20261021.log`

## Contract assessment

The testbench checks abort behavior after reaching several internal phases,
including state 11 (`ST_DONE`). It assumes that this implementation detail is
reachable before successful completion. The inspected Matrix contract
requires abort/error handling to stop new requests and drain already accepted
responses; the design's top-level abort handler applies while `busy` is high.
The inspected contract does not require a fixed completion latency or require
the internal `ST_DONE` encoding to be externally reachable.

Therefore Candidate 001's observed failure does not establish an abort
protocol violation: the test never presented an abort. The strict regression
still correctly rejects Candidate 001 because the implementation-level phase
test can no longer execute its intended abort check. Resolving that test
contract would require a test that asserts abort at an externally meaningful
condition (for example, before completion while `busy`) and checks the same
error, drain, and no-write-after-abort properties. Such a test change is not
included in this RCA, and no existing check was weakened.

## Narrow alternative: Candidate 002

Candidate 002 preserves the `ST_DONE` handling and abort path. Only after the
final output line does it detect that row tile, column tile, and instance are
all final, then transition directly to `ST_DONE`; non-final work still passes
through `ST_NEXT`. The review patch is
[`MATRIX-CYCLE-002.diff`](candidates/MATRIX-CYCLE-002.diff).

Patch SHA-256: `63b95da01b6de1e89ae85913bbb5ac07ccc2dc151765bd47899c87ea00843d3a`.
The candidate RTL SHA-256 is
`d23209307c62ad7b37f447c85f1ba48c341756b3befadaefb9d36723524b72ee`.
The candidate ran in isolated worktree `/tmp/NMAForge-m3-candidate002-409c3a9`;
the baseline revision and testbench source hashes matched the campaign
manifest. No change was applied to the original NMAForge worktree.

Shared Stage Runtime result: regression, reference model, latency gate, and
performance stages all passed. Regression used seeds `20261021`, `20261022`,
and `20261023`; each seed passed 18 cases and 35 fault checks, including
`MATRIX_CORE_PHASE_ABORT_PASS state=11 id=29`. The benchmark used seed
`20261113` and measured five workloads.

| Workload MxNxK | Baseline cycles | Candidate 002 cycles | Change |
| --- | ---: | ---: | ---: |
| 4x4x32 | 76 | 75 | -1 |
| 8x8x32 | 116 | 116 | 0 |
| 16x16x32 | 233 | 233 | 0 |
| 16x32x32 | 417 | 403 | -14 |
| 32x32x64 | 1187 | 1193 | +6 |
| Aggregate | 2029 | 2020 | -9 (-0.44%) |

Weighted useful throughput changed from 45.674 to 45.877 MAC/cycle (+0.45%).
The aggregate direction is favorable, while one large workload regressed and
the aggregate change is below the stated 5% optimization objective. The Stage
Runtime comparator's `ACCEPT` records metric direction and passed gates; it
does not establish a robust optimization or ASIC PPA improvement. No area,
frequency, timing, or power measurement was performed.

Full Stage Runtime evidence is retained at
`/tmp/nmaforge_m3_rca_candidate002_campaign/MATRIX-CYCLE-002`, including
`comparison.json`, `source_revision.json`, per-stage JSON/logs, and source
manifest. The large baseline workload's profile recorded 328 write cycles,
490 prefetch-wait cycles, 208 arbiter-stall cycles, and 72 writeback-wait
cycles. These counters overlap and must not be summed as exclusive costs.
This suggests further profiling should focus on prefetch/arbiter interaction
and writeback acceptance, then isolate compute, prefetch, and writeback stalls
with non-overlapping cycle attribution before proposing another RTL change.

## Decision

- Candidate 001: `REJECT` remains in force; its required regression fails.
- Candidate 002: isolated simulation experiment passed all configured gates;
  retain as a reviewable candidate, with no claim of meeting the 5% objective.
- No verification signoff or PPA improvement is claimed.
- Original assertions, scoreboards, and fault checks remain intact.
