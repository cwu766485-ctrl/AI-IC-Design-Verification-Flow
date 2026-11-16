# Agent Decision Contract v1

**Status:** specification only. The current repository provides deterministic stage execution and reports; it does not implement this complete autonomous decision loop.

## Decision record

Each proposed action is a versioned JSON record stored as run evidence with:

- `decision_id`, timestamp, run/graph ID, current source revision, mode and failed stage.
- Observed status/error class and evidence references: artifact paths and hashes, tool version, parser identity/version, log/report sections and upstream contract hashes.
- Failure classification: `DESIGN`, `TESTBENCH`, `ASSERTION`, `TOOL`, `ENVIRONMENT`, `CONSTRAINT`, `PHYSICAL`, `DFT`, `UNKNOWN`.
- Root-cause hypotheses with confidence and supporting/contradicting evidence; uncertainty must be explicit.
- Candidate actions (`RETRY`, `FIX_CONFIG`, `FIX_TB`, `FIX_RTL`, `CHANGE_CONSTRAINT`, `CHANGE_DFT`, `RESTORE_CHECKPOINT`, `REQUEST_INPUT`, `STOP`) with expected benefit, risk, affected graph descendants, estimated runtime/license needs, and authorization requirement.
- Selected action, reason, budget reservation, approval/authorization state, Stage Input contract hash, resulting Stage Result hash and post-action gate outcome.

An action without traceable evidence, a valid stage contract, budget, and required authorization cannot be executed.

## Bounded loop

1. **Diagnose:** identify the earliest non-PASS causal stage. Distinguish design/testbench/checker failures from command, license, configuration, parser, and infrastructure failures. Do not call a later skipped stage the root cause.
2. **Collect evidence:** retrieve only relevant logs/reports/artifacts; verify hashes; use parsers that identify report sections and units. Protect restricted design data and credentials. Do not send project collateral to external AI without explicit data authorization and sanitization.
3. **Generate options:** provide a small set of materially different fixes, including stop/request-owner-input. Estimate confidence, changed inputs, invalidated descendants, license/runtime/token costs, and functional/DFT/physical risks.
4. **Select:** choose one bounded action that fits policy and budgets. Human approval is mandatory for RTL edits, SDC/PDK/library/DFT changes, waivers, signoff exceptions, external data transfer, or destructive recovery. No automatic coverage waiver or signoff override.
5. **Execute:** use existing `aicflow`/Stage Runtime and its Stage Input v1 contract. Do not invoke a parallel shell orchestration path or write into the source snapshot. Snapshot/candidate mechanics are a prerequisite for any RTL mutation.
6. **Verify:** validate result schema/status, report completeness, artifact hashes, and all affected downstream gates. A successful command is not a passing design check. If the action fails, preserve evidence and stop or request input; no unbounded retry.
7. **Continue/rollback/stop:** continue only on required PASS gates; rollback only to a verified checkpoint with matching provenance; stop on unknown root cause, exhausted budget, missing authorization, unavailable license, unsupported stage, or repeated failure.

## Decision and retry limits

Every campaign declares maximum decision iterations, candidate count, retries per stage, cumulative EDA time, wall time, and optionally token budget before execution. Limits are cumulative across resume. Retry only classified transient errors, with bounded backoff; never retry a deterministic design failure without an input change. Every retry creates a new attempt record. A candidate with any functional, DFT, timing, or physical hard-gate failure is rejected, regardless of QoR.

## Safety and acceptance

The agent cannot edit technology collateral or original project inputs; candidate RTL edits must be isolated, reviewed, diffed, and reversible. Constraints and libraries are immutable within a comparison cohort. Signoff claims require named, parsed evidence from the relevant tool stages and reviewed project thresholds. “GDS exists” and “tool exited zero” are not signoff evidence.
