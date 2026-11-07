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
   patch and evaluate it in an isolated snapshot. Do not overwrite the user's
   RTL tree or prior candidate evidence.
5. Run the configured stages in order. A failed stage stops downstream stages;
   downstream records become `SKIPPED`. Missing tools, licenses, reports,
   artifacts, or required metrics must remain visible as `BLOCKED`, `ERROR`, or
   another non-PASS status.
6. Compare candidate metrics against the baseline and report the evaluator
   decision separately from execution status. `NO_IMPROVEMENT` is not an
   optimization win; `REVIEW_TRADEOFF` needs human review.
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
An adapter that emits `PASS` without its required report and metrics cannot
produce a passing campaign.
