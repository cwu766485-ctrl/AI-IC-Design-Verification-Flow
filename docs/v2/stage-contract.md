# V2 Stage Contract and Runtime Mapping

**Contract version:** stage-input 1.0 / stage-result 1.0; graph plan 1.0.
**Runtime:** existing `aicflow` Stage Runtime only.

## Canonical execution path

Every planned graph node is materialized as the existing [Stage Input v1](../schemas/stage-input.v1.schema.json) document and executed by the existing Stage Runtime. The node result is the existing [Stage Result v1](../schemas/stage-result.v1.schema.json) document. `eda.py` and `rtl_ppa.py` remain compatibility entry points; neither receives a competing orchestration engine. The V2 graph JSON is a versioned planning document, not a runner or a second runtime.

The current runtime executes sequentially. Independent graph branches express logical independence and may be scheduled sequentially by the current runtime; this specification does not claim parallel execution. Only adapters actually present and validated may be selected. Planned Synopsys adapters remain unsupported until implementation and validation.

## Stage input mapping

Each stage input must carry:

- Immutable run ID and stable stage ID/kind; adapter ID and declared support.
- Project identity, source revision, SHA-256 of the full source tree, ordered source paths, filelists, includes and defines; include design top and testbench top where applicable and require each stage's needed top at preflight.
- Hashed SDC/MMMC and logical/physical library references. Restricted assets remain in authorized storage; only approved references, metadata and hashes enter logs/manifests.
- Argument vector, sanitized environment, working/output directories, expected artifacts, dependencies, timeout, seed (when relevant), and remaining run budget.
- Hash-addressed upstream artifacts in `input_artifacts`; downstream stages must consume the produced hash, not a mutable “latest” path.

The current Stage Input v1 contract does not have explicit fields for physical technology profile IDs, remote-host identity, DFT mode, tool feature checkout, or cumulative campaign budget. Until a compatible versioned schema is approved, record these in the immutable run/graph manifest and pass hashed project inputs via existing `project.constraints`, `project.libraries`, and `input_artifacts`. Never add ad-hoc Stage Input properties because the current schema rejects unknown fields.

## Result and artifact manifest

Stage Result v1 is the per-stage status record. The V2 run manifest must reference every result and record graph version, mode (`functional_only` or `full_dft`), selected interval, source/technology/configuration hashes, host/remote identity, tool install/version fingerprints, feature-license probe outcome, timestamps, budgets and recovery lineage. The existing runtime already records source revision/tree state, stage contracts/results, tool versions when available, artifacts, elapsed time, and cache/checkpoint events; host/remote identity and explicit feature-license evidence are not yet complete fields and remain implementation work.

Every output is an artifact manifest entry containing relative run-local path, kind, size, SHA-256, producer stage and role. Required outputs are declared before execution. A parser may emit a metric only with report artifact, parser ID/version, unit, and source location/section in the run manifest; absent or incomplete reports yield `BLOCKED`/`ERROR`, never zero or `PASS`. Store commands as argv arrays with sensitive environment values excluded.

The required status vocabulary remains `PASS`, `FAIL`, `ERROR`, `BLOCKED`, `NOT_RUN`, and `SKIPPED`. Interpret `FAIL` as a completed tool/design check that failed; `ERROR` as tool/runtime execution error; `BLOCKED` as prerequisite, license, unsupported adapter, missing configuration/artifact, or budget gate; `NOT_RUN` as planned/dry-run; and `SKIPPED` as explicitly mode-excluded or dependency-excluded. A downstream release gate cannot pass with any required stage missing or non-PASS.

## Dependency, checkpoint, and recovery rules

Dependencies are explicit in the graph. At plan construction, filter mode-conditional edges/nodes, then serialize prerequisite stage IDs into Stage Input v1 `dependencies`. A selected `--from/--to` interval is valid only if all required ancestors are available as verified artifacts or are included in the selected plan. No stage may silently substitute a different netlist, SDC, library, corner, scan manifest or source revision.

Use the current runtime's atomic run checkpoint and content-addressed stage cache only after validating inputs. A checkpoint records completed stage IDs, result document hashes, artifact hashes, cache provenance, cumulative elapsed time and remaining budgets. Reuse is allowed only when the exact stage contract, tool/executable fingerprint, version, relevant environment, source/config/technology hashes, dependency output hashes and expected artifact hashes match. Tool version, RTL, filelist/order, defines, SDC/MMMC, libraries, DFT config, physical constraints, parser version, run mode, stage command or dependency artifact changes invalidate the affected stage and all graph descendants. License availability changes may unblock a stage, but do not turn prior BLOCKED into PASS. Never reuse failed, blocked, dry-run, incomplete, or tampered outputs. Physical tool-database restore semantics are specified as requirements here; they are not implemented or validated by the current generic runtime.

Recovery is stage-specific and evidence-led: retry transient infrastructure/license failures only within a bounded retry policy; rerun a failed stage after a reviewed input/constraint correction; restore only a verified checkpoint; invalidate all affected descendants; otherwise stop and report the earliest causal stage. Recovery must not rewrite prior attempts. The current generic runtime resumes an existing sequential DAG and verifies cache/checkpoint hashes; physical stage-specific checkpoint restore semantics still need adapter design and licensed validation.

## Budgets and cost accounting

Maintain separate limits for per-stage timeout, cumulative run EDA seconds, campaign/candidate search budget, retry count, wall-clock budget, candidate count, and (when available) agent/token usage. Each launch reserves from both stage timeout and remaining run budget; completed elapsed time is charged across resume. Candidate work is also charged to the parent campaign ledger. Cache hits do not count as EDA runtime but are recorded as cache reuse. A resume cannot replenish a consumed campaign budget. If token usage cannot be read from the Codex host, record `null`/unavailable, not a fabricated estimate. The current PPA campaign and general EDA run budgets are not yet one transactional ledger.

## Compatibility

Preserve `aicflow`, `eda.py`, and `rtl_ppa.py` CLI entry points. New graph plans call the shared runtime contracts, and legacy flows retain their current behavior. Any schema evolution must be additive/versioned, include migration notes and compatibility tests, and preserve strict rejection of unknown fields.
