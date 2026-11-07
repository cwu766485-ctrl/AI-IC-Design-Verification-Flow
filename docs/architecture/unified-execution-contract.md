# Unified Stage Execution Contract (Proposal)

**Status:** design proposal for review. This document does not add or migrate a
runner. The current `eda-tool-engineering/scripts/eda.py` CLI and
`rtl-ppa-optimization/scripts/rtl_ppa.py` remain in place for this iteration.

## One execution core, two compatibility surfaces

Use one future `aicflow` execution core for deterministic stage setup, process
launch, status classification, evidence collection, checkpointing, and cache
decisions. Keep responsibilities distinct:

- `eda.py` remains the compatible EDA skill CLI. Its existing commands map to
  canonical stages and call the shared runtime. Existing scripts, options, and
  exit codes get compatibility tests before the implementation moves.
- `rtl_ppa.py` remains the PPA campaign interface. It owns baseline/candidate
  lifecycle, patch scope, candidate budgets, metric comparison, and decision
  records. It submits its configured stages to the shared runtime instead of
  maintaining another process launcher or evidence format.
- Project adapters translate a canonical stage request into VCS, URG, DC,
  Formality, or project-specific commands. They report what they did and the
  evidence they produced; the core does not infer unsupported capabilities.

The shared runtime must not make each Skill an independent flow engine. A stage
request is a pure input document plus a selected snapshot; the same request
validator, argv launcher, timeout handling, artifact hasher, result parser,
budget ledger, and checkpoint verifier are used from either CLI.

## Stage input contract

The persisted input is JSON (`stage-input.json`); YAML plans are parsed before
this boundary. Paths in the contract are relative to an immutable source
snapshot, an explicitly mounted read-only asset, or the stage output directory.
The core must reject path escapes and never pass the original editable project
root as the work directory.

```json
{
  "contract_version": "1.0",
  "run_id": "run-2026-11-07-001",
  "stage_id": "vcs_simulate",
  "stage_kind": "simulation",
  "adapter_id": "project.vcs.simulation.v1",
  "project": {
    "name": "block-a",
    "source_revision": "<git-sha>",
    "source_tree_sha256": "<digest>",
    "design_top": "block_top",
    "testbench_top": "tb_block_top",
    "ordered_sources": ["rtl/pkg.sv", "rtl/block_top.sv", "dv/tb.sv"],
    "includes": ["rtl/include"],
    "defines": {"SIMULATION": "1"},
    "constraints": [{"path": "assets/block.sdc", "sha256": "<digest>"}],
    "libraries": [{"path": "assets/slow.db", "sha256": "<digest>"}]
  },
  "argv": ["vcs", "-top", "tb_block_top", "-f", "inputs/sources.f"],
  "environment": {"SEED": "17"},
  "working_directory": ".",
  "input_artifacts": [{"path": "source_manifest.json", "sha256": "<digest>"}],
  "output_directory": "stages/vcs_simulate",
  "expected_artifacts": ["simv", "simulation.log", "simulation-result.json"],
  "dependencies": ["vcs_compile"],
  "seed": 17,
  "timeout_seconds": 1800,
  "budgets": {"run_remaining_seconds": 4200, "candidate_remaining": 2}
}
```

Required input fields are the contract version, run/stage IDs, stage kind,
adapter ID, source revision and effective source manifest, argv, working and
output directories, dependency IDs, timeout, and remaining budgets. EDA
settings such as top names, file order, include paths, defines, SDC, libraries,
operating conditions, and seed are explicit when relevant to that stage. Secrets
and license credentials are references from the execution environment, never
serialized into the request or evidence JSON.

The adapter receives argv as an array, not a shell string. Shell use is permitted
only when an adapter explicitly declares and validates that behavior. Tool
install paths and mounted asset paths are distinct fields so the runtime can
audit what a command reads.

### Stage input JSON Schema (v1)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:aicflow:stage-input:1.0",
  "type": "object",
  "additionalProperties": false,
  "required": ["contract_version", "run_id", "stage_id", "stage_kind", "adapter_id", "project", "argv", "working_directory", "output_directory", "expected_artifacts", "dependencies", "timeout_seconds", "budgets"],
  "properties": {
    "contract_version": {"const": "1.0"},
    "run_id": {"type": "string", "minLength": 1},
    "stage_id": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"},
    "stage_kind": {"type": "string", "minLength": 1},
    "adapter_id": {"type": "string", "minLength": 1},
    "project": {
      "type": "object",
      "required": ["name", "source_revision", "source_tree_sha256", "ordered_sources"],
      "properties": {
        "name": {"type": "string"},
        "source_revision": {"type": "string"},
        "source_tree_sha256": {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"},
        "design_top": {"type": "string"},
        "testbench_top": {"type": "string"},
        "ordered_sources": {"type": "array", "items": {"type": "string"}},
        "includes": {"type": "array", "items": {"type": "string"}},
        "defines": {"type": "object", "additionalProperties": {"type": "string"}},
        "constraints": {"$ref": "#/$defs/hashed_inputs"},
        "libraries": {"$ref": "#/$defs/hashed_inputs"}
      },
      "additionalProperties": true
    },
    "argv": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
    "environment": {"type": "object", "additionalProperties": {"type": "string"}},
    "working_directory": {"type": "string", "minLength": 1},
    "input_artifacts": {"$ref": "#/$defs/hashed_inputs"},
    "output_directory": {"type": "string", "minLength": 1},
    "expected_artifacts": {"type": "array", "items": {"type": "string"}},
    "dependencies": {"type": "array", "uniqueItems": true, "items": {"type": "string"}},
    "seed": {"type": ["integer", "null"]},
    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
    "budgets": {"type": "object", "required": ["run_remaining_seconds"], "properties": {"run_remaining_seconds": {"type": "number", "minimum": 0}, "candidate_remaining": {"type": "integer", "minimum": 0}}, "additionalProperties": false}
  },
  "$defs": {
    "hashed_input": {"type": "object", "required": ["path", "sha256"], "properties": {"path": {"type": "string"}, "sha256": {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"}}, "additionalProperties": false},
    "hashed_inputs": {"type": "array", "items": {"$ref": "#/$defs/hashed_input"}}
  }
}
```

## Stage result and status schema

Every launched stage writes `stage-result.json`; the runner also writes its
authoritative `runner-record.json`. The adapter result describes tool-level
outcome. The runner record adds process exit, timestamps, final classification,
and verified artifact hashes.

```json
{
  "contract_version": "1.0",
  "run_id": "run-2026-11-07-001",
  "stage_id": "vcs_simulate",
  "status": "PASS",
  "error_class": null,
  "adapter_id": "project.vcs.simulation.v1",
  "adapter_supported": true,
  "exit_code": 0,
  "started_at": "2026-11-07T08:00:00Z",
  "finished_at": "2026-11-07T08:00:08Z",
  "source_revision": "<git-sha>",
  "tool_versions": {"vcs": "V-2026.06"},
  "metrics": {},
  "metric_provenance": {},
  "artifacts": [{
    "path": "simulation.log",
    "kind": "file",
    "size_bytes": 2841,
    "sha256": "<digest>",
    "producer_stage": "vcs_simulate",
    "role": "required_report"
  }],
  "message": null
}
```

Status enum: `PASS`, `FAIL`, `ERROR`, `BLOCKED`, `NOT_RUN`, `SKIPPED`.
`PASS` means the adapter declared support, process exit succeeded, required
markers and reports were present, and the runner validated every required
artifact. It does not mean design or verification signoff. An unsupported
adapter must return `BLOCKED`; a dry run is `NOT_RUN`; downstream work whose
dependency did not pass is `SKIPPED`.

Recommended `error_class` values are `CONFIG_INVALID`, `SOURCE_MISSING`,
`TOOL_UNAVAILABLE`, `LICENSE_UNAVAILABLE`, `ADAPTER_UNSUPPORTED`,
`COMMAND_FAILED`, `TIMEOUT`, `REPORT_MISSING`, `ARTIFACT_INVALID`,
`METRIC_MISSING`, `DEPENDENCY_FAILED`, `BUDGET_EXHAUSTED`,
`CHECKPOINT_INVALID`, and `INTERNAL_ERROR`. Preserve the raw exit code and
message; never turn a missing report, timeout, unsupported adapter, or nonzero
exit into `PASS`.

### Stage result JSON Schema (v1)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:aicflow:stage-result:1.0",
  "type": "object",
  "additionalProperties": false,
  "required": ["contract_version", "run_id", "stage_id", "status", "error_class", "adapter_id", "adapter_supported", "exit_code", "started_at", "finished_at", "source_revision", "tool_versions", "metrics", "metric_provenance", "artifacts", "message"],
  "properties": {
    "contract_version": {"const": "1.0"},
    "run_id": {"type": "string"},
    "stage_id": {"type": "string"},
    "status": {"enum": ["PASS", "FAIL", "ERROR", "BLOCKED", "NOT_RUN", "SKIPPED"]},
    "error_class": {"type": ["string", "null"]},
    "adapter_id": {"type": "string", "minLength": 1},
    "adapter_supported": {"type": "boolean"},
    "exit_code": {"type": ["integer", "null"]},
    "started_at": {"type": "string", "format": "date-time"},
    "finished_at": {"type": "string", "format": "date-time"},
    "source_revision": {"type": "string"},
    "tool_versions": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1}},
    "metrics": {"type": "object", "additionalProperties": {"type": ["number", "object"]}},
    "metric_provenance": {"type": "object", "additionalProperties": {"type": "object", "required": ["artifact", "parser_id", "parser_version"], "properties": {"artifact": {"type": "string"}, "parser_id": {"type": "string", "minLength": 1}, "parser_version": {"type": "string", "minLength": 1}}, "additionalProperties": false}},
    "artifacts": {"type": "array", "items": {"$ref": "#/$defs/artifact"}},
    "message": {"type": ["string", "null"]}
  },
  "allOf": [{"if": {"properties": {"status": {"const": "PASS"}}, "required": ["status"]}, "then": {"properties": {"adapter_supported": {"const": true}, "exit_code": {"const": 0}, "tool_versions": {"minProperties": 1}, "artifacts": {"minItems": 1}}, "required": ["tool_versions", "artifacts"]}}],
  "$defs": {
    "artifact": {"type": "object", "required": ["path", "kind", "size_bytes", "sha256", "producer_stage", "role"], "properties": {"path": {"type": "string"}, "kind": {"enum": ["file", "directory"]}, "size_bytes": {"type": "integer", "minimum": 1}, "sha256": {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"}, "producer_stage": {"type": "string"}, "role": {"type": "string"}, "file_count": {"type": "integer", "minimum": 1}}, "additionalProperties": false}
  }
}
```

## Artifact manifest and provenance

Each run has one immutable `manifest.json`. It records the contract version,
run ID, UTC start/end, plan SHA-256, Git commit, clean-tree state, source file
list/order and per-file hashes, design/testbench tops, constraints and library
asset hashes, stage dependency graph, adapter IDs, tool versions, seeds,
budgets, statuses, and a complete index of stage artifacts.

Artifacts use project-relative or run-relative paths, never absolute paths as
identity. A file entry contains `path`, `kind`, `size_bytes`, `sha256`,
`producer_stage`, and `role`. Directory artifacts contain a deterministic tree
hash and a sorted child manifest. Symlinks, empty required reports, paths
outside the stage output directory, and duplicate artifact identities are
rejected. Metrics name their source stage, source artifact, unit, and parser
version; parsed metrics retain report line or structured path where available.

## Stage dependencies and execution

Represent the flow as a DAG. Each node has an ID, adapter, explicit inputs,
outputs, and dependency IDs. Validate that IDs are unique, dependencies exist,
and the graph is acyclic before launch. A stage runs only after every required
dependency is `PASS`; otherwise record `SKIPPED` with the blocking dependency.
Independent nodes may later run concurrently, but the first implementation is
sequential for reproducibility and simple budget accounting.

The selected start/end stage is a graph slice: calculate the ancestors required
for the selected end stage, then execute only the slice from the requested
start. Reject a start stage that omits a required ancestor unless a verified
checkpoint supplies that dependency.

## Checkpoint and resume

Checkpoint after every passing stage. A checkpoint contains the immutable
stage-input SHA-256, result JSON SHA-256, artifact manifest, dependency
checkpoint IDs, source revision, adapter ID, and tool versions. Resume verifies
all hashes and dependencies before reuse. A missing, edited, or incompatible
checkpoint becomes `BLOCKED` and reruns only when the user explicitly requests
resume with rerun enabled. Failed or partial stage output is never a checkpoint.

The run manifest is append-only by stage attempt. Resume creates a new attempt
record instead of replacing the earlier failure. This preserves provenance and
lets a user distinguish a resumed run from a clean run.

## Cache key and invalidation

Cache only stage outputs with a passing result and complete artifact manifest.
The key is a canonical hash of:

- contract and adapter schema versions;
- stage ID/kind, argv, declared environment inputs, and working directory;
- source revision plus exact input file hashes and source ordering;
- top names, defines, include paths, SDC, libraries, operating conditions,
  seed, and all stage configuration;
- adapter ID/version, executable/tool versions, and parent checkpoint hashes.

Any input change invalidates the stage and its descendants. Do not key on a
mutable tool alias such as `latest`; require an adapter-provided version string
or binary fingerprint. License state, a command exit alone, incomplete reports,
and failed runs are never cache hits. Cache hits remain explicit `PASS` records
with `cache_hit: true` and the original artifact provenance.

## Run and candidate budgets

The shared runtime enforces per-stage timeout, per-run wall-clock limit, total
run wall-clock limit, and optional concurrency/resource limits. The PPA campaign
layer additionally enforces candidate count, per-candidate runtime, and
cumulative search runtime. Account fractional monotonic elapsed time and persist
reservations before launching work, so failed and interrupted campaigns cannot
evade the budget. Serialize updates to a shared ledger; reject a ledger with a
different plan hash or invalid counters. Budget exhaustion emits
`BLOCKED/BUDGET_EXHAUSTED` and prevents downstream stages and optimization
acceptance.

## Compatibility and rollout

Keep current CLI flags and exit conventions as contract tests. Implement the
runtime in incremental layers inside the existing `aicflow` package, then make
`eda.py` delegate stage execution and adapt `rtl_ppa.py` to call the same public
runtime function. Do not move PPA comparison, candidate patch policy, or metric
gates into the generic runner. Do not add a second scheduler or subprocess
launcher to either Skill. Real Synopsys smoke tests remain separate from
Python-only fake-adapter CI.
