# Matrix Candidate 001 Phase-Abort RCA

Status: the original Candidate 001 failure was a testbench reachability
assumption, not evidence that an asserted abort was ignored. The old regression
failure remains recorded. After moving the abort stimulus to a final-write
pending boundary and aligning workload stimulus, Candidate 001R2 and
Candidate 002R2 both passed the configured simulation gates in isolated
NMAForge snapshots. Each changed the five-workload total by -0.25%, below the
5% target. No PPA or signoff result is available.

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

The written contract is NMAForge `docs/spec/COMPUTE_CLUSTER_SPEC_ZH.md`
REQ-PC-009 and the Matrix P0-B/P0-C abort-drain requirements. They require
stopping new reads, draining already accepted responses, and reporting abort
completion; they do not prescribe cycle counts or internal state encodings.

Therefore Candidate 001's observed failure does not establish an abort
protocol violation: the test never presented an abort. The old regression
result still correctly records that Candidate 001 could not pass that test
revision. The isolated test-contract branch now asserts abort while the final
output line is valid and stalled, with `busy` high; it checks `ERR_ABORT`, no
additional line/scalar writes, and accepted-read drain. No assertion,
scoreboard check, or fault check was removed or weakened.

## Initial Candidate 002 Comparison (Superseded)

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
manifest. The large baseline workload's initial-stream profile recorded 328
write cycles, 490 prefetch-wait cycles, 208 arbiter-stall cycles, and 72
writeback-wait cycles. These historical counters overlap and must not be
summed as exclusive costs. The later aligned baseline profile adds exclusive
attribution within `ST_PREFETCH_WAIT` and `ST_WRITE`; see
[`matrix-cycle-attribution.md`](matrix-cycle-attribution.md). That run is
baseline-only and does not compare the corrected candidates. It still does not
show whether prefetch drain is hidden under MAC, so the next step is a
prefetch-state cross-tab, not an RTL candidate.

## Corrected Replay: Candidate 001R2 And Candidate 002R2

The isolated test-contract branch starts at
`409c3a9fd647d4f8c4c881c9bfdaf5d93b7076ee`; commits
`987c957e32a3be71e7d8b593e8d7a515eecf9b42` and
`52353d5454284e05119764705fb8a6e406a5c8f4` update the abort stimulus and
per-workload backpressure seeding. The revised testbench SHA-256 is
`7b886201d9f95d22aee03f2c8826aa217a819e3ef73d5393ad05cd5e1d1dc85c`.

Baseline and both isolated candidates passed regression and reference-model
stages on seeds `20261021/20261022/20261023`; each seed passed 18 cases and 35
fault checks. The corrected final-write case reports
`MATRIX_CORE_PHASE_ABORT_PASS phase=final_write_pending id=29 prior_writes=3/0`.
Regression, reference-model, latency-gate, and performance Stage Runtime
stages passed for all three snapshots. A final-write abort-ignored negative
control failed with `done/error/code/busy=0/0/0/1`.

The earlier Candidate 002 comparison let random backpressure continue between
workloads, so an RTL cycle change could shift later workload stimulus. The
aligned rerun below re-seeds stalls per workload and supersedes the earlier
cycle comparison for A/B conclusions. Results use seed `20261113`:

| Workload MxNxK | Baseline cycles | Candidate 001R2 | Candidate 002R2 |
| --- | ---: | ---: | ---: |
| 4x4x32 | 78 | 77 | 77 |
| 8x8x32 | 110 | 109 | 109 |
| 16x16x32 | 230 | 229 | 229 |
| 16x32x32 | 403 | 402 | 402 |
| 32x32x64 | 1189 | 1188 | 1188 |
| Aggregate | 2010 | 2005 (-0.25%) | 2005 (-0.25%) |

Weighted useful MAC/cycle changed from 46.105 to 46.220 (+0.25%). Both
candidates passed the four configured simulation stages, but neither met the
5% target. This is not ASIC PPA evidence. Logs and Stage Runtime artifacts are
retained at `/tmp/nmaforge_m3_phaseabort_aligned_stagecampaign`; machine-readable
decisions are `MATRIX-CYCLE-001R2.decision.json` and
`MATRIX-CYCLE-002R2.decision.json` in the NMAForge report branch.

For the aligned baseline `32x32x64` run (1189 cycles), mutually exclusive FSM
state counts are prefetch wait 500 (42.05%), write 320 (26.91%), MAC 256
(21.53%), prepare-MAC 64 (5.38%), A/B requests and waits 44 (3.70%), and next
plus done 5 (0.42%). Event counters overlap those state totals: arbiter stall
210, writeback wait 64, response wait 11. Follow-up profiling should separate
prefetch response delay from arbiter denial and productive write cycles from
writeback stalls before another RTL change. No third candidate was attempted
after the two measured candidates showed the same 0.25% change.

## Corrected Campaign Instrumentation

| Measure | Observed result |
| --- | --- |
| Unique RTL candidates | 2: Candidate 001R2 and Candidate 002R2 |
| Corrected simulation gate rate | 2/2 candidates passed all four Stage Runtime stages; baseline also passed |
| 5% cycle objective | 0/2; both candidates changed the aligned total from 2010 to 2005 cycles (-0.25%) |
| Weighted useful MAC/cycle | 46.105 baseline; 46.220 for both candidates (+0.25%) |
| Functional regression | 3 seeds per snapshot, 18 cases and 35 fault checks per seed; no corrected-candidate failures; the abort-ignored negative control was detected |
| Stage Runtime elapsed | 34.527 s across baseline and both candidates; candidate runs were 12.045 s and 11.162 s |
| VCS tool runs | 12 compile invocations and 24 Stage Runtime simulation runs; 3 additional archived simulation reports cover the first-divergence and negative-control runs |
| Cache hits | Not separately recorded; all configured stages have execution-attempt records |
| Area and WNS | Not measured; ASIC PPA remains STOP |
| Agent calls, token use, human intervention count | Not instrumented; no efficiency comparison is claimed |

## Initial Campaign Instrumentation (Historical)

| Measure | Observed result |
| --- | --- |
| Isolated RTL candidates evaluated | 2: Candidate 001 and Candidate 002 |
| Required-gate pass rate | 1/2 (50%); Candidate 001 failed regression, Candidate 002 passed all configured stages |
| 5% objective success rate | 0/2; Candidate 002's aggregate reduction was 0.44% |
| Functional regression evidence | Candidate 001: one phase-abort regression failure; Candidate 002: 3 seeds, 18 cases and 35 fault checks per seed passed |
| Recorded Stage Runtime | 21.691 s total: 5.448 s for Candidate 001 and 16.243 s for Candidate 002 |
| VCS compile invocations | 5: one for Candidate 001 and four for Candidate 002's regression, reference, latency and performance stages |
| VCS simulation runs | 9: one Candidate 001 run; Candidate 002 regression/reference each ran three seeds, plus one latency and one performance run |
| Stage cache hits | 0 |
| Cell-area and WNS changes | Not measured; ASIC synthesis and STA were blocked |
| Agent calls, token usage, human intervention count | Not captured by the campaign |

The measured invocation counts are taken from each retained command log
(`vcs -licwait` compile lines and VCS runtime banners). They describe these two
campaigns only and do not support a workflow-efficiency comparison. The
controller comparator marked Candidate 002 `ACCEPT` based on direction of the
two simulation metrics; the separate 5% campaign objective was not met.

## Decision

- Candidate 001's original `REJECT` remains attached to its old failing
  regression run; Candidate 001R2 passes the corrected simulation gates.
- Candidate 002R2 passed the corrected simulation gates and remains a
  reviewable simulation candidate; it does not meet the 5% objective.
- The original failure was a testbench reachability defect, not a demonstrated
  DUT abort violation. A retained negative control confirms the corrected
  final-write abort checker detects ignored abort behavior.
- No verification signoff or PPA improvement is claimed.
- Original assertions, scoreboards, and fault checks remain intact.
