---
name: rtl-ppa-optimization
description: Use this skill to establish a measured RTL PPA baseline and evaluate bounded RTL candidate patches through functional, formal or reference-model, synthesis, timing, power, and performance stages. Use it when a user asks to compare RTL implementations or improve area, timing, power, throughput, or numerical behavior. It does not claim signoff without tool reports.
---

# RTL PPA Optimization

Use this skill for an evidence driven RTL optimization loop. Keep the existing
project layout and EDA execution skills. The framework invokes project supplied
stage commands; it does not generate vendor scripts, modify RTL projects, or
claim Synopsys validation by itself.

## Required workflow

1. Identify the exact optimization scope, design top, testbench top, clock and
   reset assumptions, libraries, constraints, and existing regressions. Keep the
   first target at a block or compute tile boundary.
2. Define a behavior contract before changing RTL:
   - `cycle_equivalent` requires a passing formal equivalence stage.
   - `transaction_level` requires an independent reference model and a latency
     gate with an explicit maximum cycle count.
3. Establish and preserve a measured baseline. Record the source Git revision,
   tool versions, constraints, seeds, metrics, and report artifacts. A clock
   frequency assumption or performance estimate is not measured PPA evidence.
4. Bound candidate edits with `allowed_patch_paths`. Save each candidate as a
   patch and evaluate it in an isolated snapshot. Changes must also be present
   in the ordered `rtl_sources` list. Do not overwrite the user's RTL tree or
   prior candidate evidence.
5. Run the configured stages in order. A failed stage stops downstream stages;
   downstream records become `SKIPPED`. Missing tools, licenses, reports,
   artifacts, or required metrics must remain visible as `BLOCKED`, `ERROR`, or
   another non-PASS status.
6. Compare candidate metrics against the baseline and report the evaluator
   decision separately from execution status. `NO_IMPROVEMENT` is not an
   optimization win; `REVIEW_TRADEOFF` needs human review. Any failed, blocked,
   or skipped required candidate stage prevents acceptance, even if an earlier
   stage reported improved metrics.
7. Preserve the candidate patch, source revision, command logs, stage results,
   reports, and comparison JSON together. Never claim Design or Verification
   Signoff from this framework alone.

## Run the evaluator

The plan contract and a planning-only example are in
[`references/plan-schema.md`](references/plan-schema.md) and
[`references/nmaforge-matrix-plan.example.yaml`](references/nmaforge-matrix-plan.example.yaml).

```bash
python3 skills/rtl-ppa-optimization/scripts/rtl_ppa.py validate \
  --project-root /path/to/clean/project \
  --plan /path/to/committed/rtl-ppa-plan.yaml

python3 skills/rtl-ppa-optimization/scripts/rtl_ppa.py plan \
  --project-root /path/to/clean/project \
  --plan /path/to/committed/rtl-ppa-plan.yaml

python3 skills/rtl-ppa-optimization/scripts/rtl_ppa.py baseline \
  --project-root /path/to/clean/project \
  --plan /path/to/committed/rtl-ppa-plan.yaml \
  --runs-root /path/outside/project/rtl-ppa-runs --execute

python3 skills/rtl-ppa-optimization/scripts/rtl_ppa.py evaluate \
  --project-root /path/to/clean/project \
  --plan /path/to/committed/rtl-ppa-plan.yaml \
  --runs-root /path/outside/project/rtl-ppa-runs \
  --baseline /path/outside/project/rtl-ppa-runs/baseline/baseline.json \
  --candidate-id area-share-01 --patch /path/to/candidate.diff --execute
```

`validate` checks configuration only. `plan`, baseline dry runs, and candidate
dry runs report `NOT_RUN`; only an executed campaign with passing required
stages and measured required metrics can report `PASS`. The project worktree
must be clean for execution, and `runs-root` must be outside it. Read-only PDK
and library inputs are copied into the snapshot; assets containing symlinks or
special files are blocked. The plan carries ordered RTL/testbench file lists,
design top, and testbench top to the stage adapter through a source manifest.

Each stage declares an `adapter_id`; a passing stage result must repeat that
ID, report `adapter_supported: true`, and provide nonempty tool versions and
required artifacts. Every metric must include artifact, parser ID, and parser
version provenance that points to a validated stage artifact. The runner hashes
passing artifacts and result JSON.
Candidate comparison requires the same plan hash, source revision and base
source hashes, ordered source/top contract, seed, read-only asset hashes, and
compatible adapter/tool and metric parser versions for shared stages. This
detects incompatible evidence; trusted adapters still need review to confirm
they actually read the declared constraints and libraries.

`max_runtime_sec` bounds one campaign. `max_total_runtime_sec` bounds baseline
plus candidate runtime across a shared runs root. Fractional seconds are kept;
campaigns share a file lock, and an interrupted attempt is charged its reserved
allowance on the next invocation. Candidate attempts that reach campaign
creation consume a candidate slot even if a later stage fails.

## Capability boundary

| Capability | This skill provides | Project adapter still must provide |
|---|---|---|
| Baseline and candidate bookkeeping | Git-pinned snapshot, patch allowlist, budgets, status model, evidence manifest | Tool commands and parsers that emit truthful stage JSON |
| Functional behavior | Ordered required-stage gates | Regression execution and independent checker/reference model |
| Cycle equivalence | Requires a `formal` candidate stage | Formality setup, non-identical Golden/Revised designs, constraints and report parser |
| Transaction-level changes | Requires `reference_model` and `latency_gate` candidate stages | Reference model, scoreboard and latency measurement |
| Area, setup timing, power | Metric comparison and threshold gates | Valid synthesis/STA/power runs and report extraction under the intended libraries and constraints |
| Throughput and numerical accuracy | Metric comparison and threshold gates | Reproducible workloads, counters, reference values and checker implementation |

The framework is not a synthesis, STA, power, formal, or regression adapter.
An adapter that omits required support declaration, tool version, metric, or
nonempty report cannot produce a passing stage. Adapter JSON remains a trust
boundary: fake-adapter CI verifies runner semantics only, not Synopsys behavior.

## Bounded optimization controller

[`scripts/autonomous_optimizer.py`](scripts/autonomous_optimizer.py) contains
small evidence-policy components that consume `rtl_ppa.py` reports; it does not
launch a second scheduler or mutate RTL. `QoRAnalyzer` requires passing stages,
metric provenance, and structured timing/area hotspot evidence. `CandidateGenerator`
binds a proposed change to a source revision, patch hash, hotspot, approved
scope, risks, expected impact, and required validation. `OptimizationController`
requires every declared candidate stage and remaining candidate/runtime budget
before it can return `ACCEPT`. Missing mandatory evidence returns `STOP`.

The NMAForge Matrix readiness record is
[`docs/milestone3/nmaforge-matrix-autonomous-optimization-readiness.md`](../../docs/milestone3/nmaforge-matrix-autonomous-optimization-readiness.md).
Its ASIC PPA baseline remains blocked until approved target libraries and SDC,
technology setup, and a candidate equivalence policy are available.

For read-only assertion/protocol/FSM/waveform triage, profile-grounded
architecture experiments, and budget-aware next-action selection, use
[`references/optimization-readiness.md`](references/optimization-readiness.md)
and `scripts/optimization_readiness.py`. These helpers consume evidence and
never launch a competing runtime or change RTL.
