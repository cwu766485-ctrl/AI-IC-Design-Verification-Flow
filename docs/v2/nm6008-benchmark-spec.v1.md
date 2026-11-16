# NM6008 Benchmark Specification v1

**Status:** proposed protocol. No benchmark run is claimed. The first task is to establish an authorized, reproducible Synopsys baseline.

## Cohorts and modes

| Cohort | Configuration | Question |
|---|---|---|
| B0 | Native Codex interaction with Synopsys shell; fixed instructions and project inputs. | Baseline operator performance. |
| B1 | Codex with reviewed, optimized Synopsys Skills; same shell and fixed tasks. | Incremental value of tool guidance. |
| B2 | Codex + Skills + fixed, validated EDA DAG; agent does not choose graph repairs. | Value of deterministic orchestration. |
| B3 | Full intelligent AI-IC Agent using evidence-backed diagnosis/action selection on the same shared Stage Runtime. | Incremental value of agent decisions over a fixed DAG. |

Run `functional_only` and `full_dft` as separate cohorts. Full RTL-to-GDS results use a fresh Synopsys-native physical baseline. Historical Innovus results may be reported as historical context, never as the B0/B1/B2/B3 Synopsys PPA baseline.

## Frozen conditions and repeats

Freeze exact RTL snapshot/hash, ordered filelists, testplan/testbench, seeds, tool versions/patches, scripts, PDK/library release and hashes, RC corners, SDC/MMMC, floorplan/IO, DFT configuration, operating conditions, machine/runner, and license feature set. Each condition is repeated at least three times where the tool flow is deterministic enough to compare; random seeds and physical nondeterminism are recorded. Failed or incomplete runs remain in the denominator and are not silently discarded. Compare modes only when all hard-gate input hashes match.

## Metrics

| Dimension | Required measurements | Evidence |
|---|---|---|
| Functional correctness | Compile/elaboration, directed/random tests, assertions/checkers, pass/fail tests and seeds; equivalence result where applicable. | VCS logs, test summary, checker reports, source/testplan hashes. |
| DFT | Scan insertion/DFT DRC; fault model and denominator; detected/possibly detected/undetected/untestable faults; ATPG coverage, pattern count and test time; pattern simulation if required. | TestMAX reports, scan netlist/chain manifest and ATPG patterns, all hashed. |
| Timing | Setup/hold WNS and TNS by mode/corner, violating endpoint/path counts, clock uncertainty and extracted parasitic identity. | PrimeTime reports with parser provenance, SDC/MMMC and extraction hashes. |
| Physical validity | Floorplan/place/CTS/route completion; DRC/LVS results; antenna/fill if required; GDS streamout manifest and post-streamout checks. | ICC2/ICV or approved Synopsys report artifacts and hashes. GDS existence alone is insufficient. |
| QoR | Cell area by hierarchy/type, utilization, routed wirelength/congestion, clock metrics, power with documented activity and analysis assumptions. | DC/ICC2/PT/PrimePower and extraction reports. Missing power stays unavailable. |
| Efficiency | End-to-end and per-stage wall/runtime, tool launches, cache hits, retries, checkpoint restores, license wait, token input/output when available, human interventions. | Run manifest, Stage Results, host telemetry; null when not observable. |
| Intelligence | Earliest-cause classification accuracy, root-cause localization, repair acceptance, downstream regression impact, recovery success, budget adherence. | Blind case ground truth sealed from agent, decision records, stage evidence. |

## Scoring and hard gates

Do not collapse unlike dimensions into an arbitrary single score. Publish a vector and per-run distributions. A run is **eligible for QoR comparison** only if functional correctness passes, all required DFT gates pass for the full-DFT cohort, timing constraints pass, required physical checks pass, and artifacts/provenance are complete. Ineligible runs still count in completion rate and cost metrics but cannot win on area, frequency or power.

Report Pareto dominance across verified area, timing, power, runtime, tool invocations, token use and human interventions. Include medians/ranges across repeats and every failed case. Compare B3 against B2 for decision-intelligence benefit; B1 vs B0 for Skill value; B2 vs B1 for DAG value. Keep task prompts and budgets fixed across cohorts. Blind-debug cases withhold fault/root-cause labels and include multiple failure classes; any seeded faults must be created in disposable benchmark snapshots, not original project sources.

## Baseline admission gate

No benchmark cohort begins until project identity, test oracle, licensed required tools, approved technology profile, flow scripts, mode/corner constraints, artifact manifest, DFT scope, physical check requirements, and source snapshot are reviewed and frozen. Until then, all NM6008 benchmark metrics are `NOT_RUN` or `BLOCKED`; there is no baseline QoR value to report.
