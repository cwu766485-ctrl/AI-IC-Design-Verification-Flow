# R1–R4 Ordered Development Backlog

R1 is the current implementation scope. R2–R4 are follow-up work and are not implemented by this change.

## R1 — Unified Flow Engine

**State:** Implemented on this feature branch; review and CI are pending.

- One versioned Stage Input/Result boundary and subprocess core serve the existing EDA and PPA entry points.
- Existing CLIs remain compatible; `aicflow` composes supported sequential DAGs, partial-stage execution, checkpoint/resume, and verified cache reuse.
- Run-local attempts are serialized and budgeted; statuses and artifacts are machine-readable and hashed.
- VCS/URG/DC/PrimeTime smoke evidence and mock cold/repeat/incremental results are in [`r1-efficiency-report.md`](../r1-efficiency-report.md).

**Remaining gaps:** EDA input snapshots, one transactional budget ledger shared with PPA, parallel scheduling, a broader parser registry, and product PDK/corner validation.

## R2 — AI Verification Agent

**Dependency:** R1 stable execution contracts and project-owned specifications, reference models, checkers, and approved verification assets.

1. Define versioned Feature, Testpoint, Checker, and CoverageRequirement contracts with stable IDs and links to spec paragraphs and RTL hierarchy.
2. Generate a reviewable Testplan; validate that a checker is independent of the DUT result it is intended to verify.
3. Generate project-scoped TB/sequence/SVA candidates that reuse approved VIP and checker interfaces; require human review before execution.
4. Run bounded VCS regression and URG extraction through R1; store seed, tool version, logs, reports, and artifact hashes per testpoint.
5. Classify failures as design, testbench, assertion, tool, environment, or unknown. Return `ADD_TEST`, `FIX_TB`, `FIX_RTL`, `REQUEST_SPEC`, or `STOP` with evidence.
6. Require rerun evidence for closure. Keep unreachable/dead-code hypotheses separate from proven unreachable behavior; never auto-approve waivers.

**Acceptance:** An existing block and approved reference/checkers produce a reviewed Testplan; a bounded regression identifies a known injected failure and coverage gap; repairs pass the required rerun. Coverage percentage alone cannot grant signoff.

## R3 — AI Design / PPA Agent

**Dependency:** R1 execution plus R2 functional gates, or an independently approved equivalent checker suite for the target block.

1. Establish a reproducible baseline with fixed RTL revision, PDK/library, corner, SDC, tool configuration, workload, and accuracy checker.
2. Record each candidate hypothesis: target path/area hotspot, intended RTL change, expected benefit, and functional/timing/power risks.
3. Generate isolated candidate snapshots within the approved patch allowlist; do not modify the original worktree.
4. Evaluate candidates through shared R1 stages and approved functional, formal/equivalence, synthesis, STA, power, and performance checks.
5. Compare only compatible baseline/candidate inputs and report measured QoR deltas with artifact provenance. Reject failed or incomplete evidence.
6. Keep the best verified candidate and all rejected-candidate evidence.

**Acceptance:** A small owned block has a repeatable baseline and candidate experiment. Functional behavior remains gated; PPA metrics are compared only when measured under matching conditions. No assumed metric or signoff claim is allowed.

## R4 — Agentic Decision and Efficiency

**Dependency:** R1 run histories and at least one useful R2 or R3 decision loop.

1. Derive next-stage decisions from structured failure classes and evidence links.
2. Enforce per-run, per-candidate, iteration, seed, and wall-clock budgets before launching work.
3. Record cache reuse, tool calls/runtime, retries, agent/API calls, and token usage only when the caller provides reliable counters.
4. Benchmark a fixed task set against the prior manual/Codex flow; report correctness, completion, EDA runtime, retries, and token counts separately.
5. Add stop/escalation criteria for repeated failures, unavailable licenses, unsupported adapters, and ambiguous specifications.

**Acceptance:** A reproducible benchmark uses real counters and identical correctness gates, and separates measurements from unavailable telemetry.
