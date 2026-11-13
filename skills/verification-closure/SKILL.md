---
name: verification-closure
description: Build traceable verification plans, UVM increments, bounded regressions, and evidence based coverage closure from RTL project specifications.
---

# Verification Closure

Use this skill when a chip project needs a Spec-to-test plan, UVM testbench work, regression analysis, or a bounded functional/code coverage closure loop.

Keep the plan beside the project’s verification sources. Map each feature to a stable testpoint, an independent checker, and named coverage goals. Separate protocol VIP checks from DUT business behavior: protocol compliance does not prove DMA data movement, compute results, reset recovery, or completion semantics.

Inspect and reuse existing agents, VIP, sequences, monitors, scoreboards, assertions, filelists, and regression targets before generating code. A generated test must fit the project’s real UVM package and sequencer hierarchy. Generate a reviewable patch by default; apply changes only when the user asked for integration.

Run only the project’s canonical regression entry point. Every run needs a unique output directory, seed, timeout, captured log, process exit code, and explicit pass markers. Analyze functional coverage, assertion attempts/failures, and DUT code coverage separately. Do not infer closure from an overall percentage. Classify each gap as missing stimulus, missing checker, unreachable with reviewed rationale, model issue, or run failure; leave uncertain cases open for human/Codex triage.

Use `scripts/verification_closure.py` to validate and render a curated YAML plan, generate an optional UVM test increment, execute one bounded regression campaign, and analyze machine-readable evidence. YAML can be parsed by PyYAML or Ruby. The plan schema and a DMA example are in [references/plan-schema.md](references/plan-schema.md) and [references/dma-plan-example.yaml](references/dma-plan-example.yaml).

The closure loop is bounded: one command runs at most 20 seeds, each process has a timeout, and the configured campaign budget limits follow-up runs and new tests. The script never invents stimulus or edits RTL. After reviewing a gap, make one targeted test/checker change, rerun the affected regression, and stop at the budget or when the declared closure gate is met. Preserve exact commands, source hashes, tool version, logs, coverage data, and dispositions in the evidence report.
