# Unified Stage Execution Contract — R1

**Status:** implemented for sequential execution in the R1 branch. This document describes current behavior and limits; it is not a signoff claim.

## Shared runtime and compatibility surfaces

`aicflow`/`flow_engine.py` composes and schedules the EDA stage graph. The existing `eda.py` CLI remains available: composite-flow, partial-stage, resume, and report requests are forwarded to that engine. Existing single-flow adapter setup remains in `eda.py`, and execution is handled through `eda_runtime.execute_plan`.

`rtl_ppa.py` remains the PPA campaign interface. It owns candidate snapshots, patch allowlists, candidate selection, metric gates, and campaign budgets. It creates the same Stage Input/Result documents and calls `stage_runtime.run_process` for EDA commands. Its candidate policy checks stay outside the shared runtime. PPA campaigns do not yet use the general EDA DAG cache.

[`stage_runtime.py`](../../skills/eda-tool-engineering/scripts/stage_runtime.py) contains strict Python validators, argv-based subprocess execution, timeout and license/tool classification, content hashing, DAG validation, atomic JSON writes, and cache locking. Versioned schemas: [`Stage Input v1`](../schemas/stage-input.v1.schema.json) and [`Stage Result v1`](../schemas/stage-result.v1.schema.json).

## Stage Input v1

The runtime writes `stage_contracts/<stage-id>.input.v1.json` for each node. Required fields: `contract_version`, `run_id`, `stage_id`, `stage_kind`, `adapter_id`, `project`, `argv`, `environment`, `working_directory`, `output_directory`, `expected_artifacts`, `dependencies`, `timeout_seconds`, and `budgets.run_remaining_seconds`. `input_artifacts` and `seed` are optional. Unknown top-level and project fields are rejected.

`project` includes source revision, content-derived source tree hash, ordered RTL sources, design/testbench tops when known, filelists, include paths, defines, and hashed SDC/library assets. Paths are resolved local paths. EDA flows execute against the current project worktree; the shared EDA runtime does not create immutable snapshots. PPA separately creates candidate snapshots and rejects commands referencing the original project path.

Commands are argv arrays, not shell strings. Credentials remain in the process environment and are not serialized; the validator rejects environment keys that look like license, token, password, secret, or credential fields. The EDA adapter currently leaves the explicit environment map empty and inherits its process environment; selected tool environment variables are hashed into cache keys.

## Stage Result v1 and status model

The runtime writes `stage_contracts/<stage-id>.result.v1.json` with status, error class, adapter identity/support, exit code, timestamps, source revision, tool versions when known, metrics/provenance, artifact hashes, and a message.

Statuses: `PASS`, `FAIL`, `ERROR`, `BLOCKED`, `NOT_RUN`, `SKIPPED`. `PASS` requires a supported adapter, exit code zero, and at least one hashed artifact. Tool stages also block when the version is unavailable or required reports are missing. Internal bookkeeping stages may have no tool version. A dry run is `NOT_RUN`; unsupported adapters, missing tools/licenses/reports, and exhausted budgets are `BLOCKED`; nonzero tool exits are `FAIL` unless classified as an environment/license block. Dependents of non-PASS nodes become `SKIPPED` with `DEPENDENCY_FAILED`. These statuses never mean signoff.

Common error classes include `TOOL_UNAVAILABLE`, `LICENSE_UNAVAILABLE`, `ADAPTER_UNSUPPORTED`, `COMMAND_FAILED`, `TIMEOUT`, `DESIGN_CHECK_FAILED`, `REPORT_MISSING`, `REPORT_INCOMPLETE`, `VERSION_UNAVAILABLE`, `DEPENDENCY_FAILED`, `BUDGET_EXHAUSTED`, and `STAGE_CONTRACT_INVALID`.

## Current DAGs and CLI

Stage IDs and dependencies are validated for uniqueness, missing/duplicate edges, and cycles. The scheduler uses deterministic topological order and sequential execution; independent branches are not parallelized.

| Flow | Stage relationship |
|---|---|
| `rtl_to_sim` | `vcs_compile` → simulation → result classification |
| `rtl_to_regression` | compile → each test/seed simulation and result → URG → coverage summary |
| `rtl_to_synth_sta` | `dc_synthesis` → `pt_sta` |
| `rtl_to_sim_synth` | verification and synthesis branches share one run manifest/cache |

Single-flow names (`sim`, `regression`, `coverage`, `synth`, `sta`) remain available. Run from a project with a valid `eda.yaml`:

```bash
./aicflow doctor
./aicflow plan --flow rtl_to_regression
./aicflow run --flow rtl_to_regression --execute
./aicflow run --flow rtl_to_sim_synth --from vcs_compile --to dc_synthesis --execute
./aicflow resume --run-id <run-id> --execute
./aicflow report --run-id <run-id> --log-tail 50
```

`--from`/`--to` select a topological interval. Required ancestors are included and must pass or be restored from a verified checkpoint/cache. `plan` and runs without `--execute` do not launch tools. Existing `eda.py` entry points forward the new options for supported composite flows.

An `eda.yaml` with `runner.kind: ssh` sends composite `run` and `resume` execution through the existing SSH runner after its matching-clean-checkout preflight. The selected flow slice and run budget are forwarded; remote evidence is copied back and annotated. `EDA_REMOTE_EXECUTION=1` prevents recursive re-dispatch on the remote host. SSH routing has fake-command tests but was not exercised against a real remote host.

Each run writes `runs/<run-id>/manifest.json`, `checkpoint.json`, `stage_contracts/`, scripts/logs/reports, and `attempts.jsonl`. `report --log-tail [N]` includes at most 200 lines per log and 1000 characters per line; complete logs remain in their artifacts.

## Checkpoint, cache, invalidation, and budget

The scheduler atomically writes a checkpoint and validated input/result JSON after every stage. Only PASS stages with recorded artifacts are cached. The cache at `runs/.cache/stages/` is protected by a POSIX file lock. A per-run lock serializes concurrent resume/execution requests and refreshes the checkpoint while holding the lock, preventing duplicate launches and budget races. Before reuse, all files/tree hashes are verified. A cache hit restores every recorded run-local output, including logs consumed by downstream classifiers. Artifacts outside the source run tree and symlinks are not cacheable.

Cache keys include stage/adapter identity and version, normalized argv, timeout, seed/test/options, source/config/RTL/filelist/include/constraint/library content hashes, selected tool environment hashes and executable fingerprint/version, and upstream artifact hashes. A changed input or output hash forces a rerun. Failed, blocked, dry-run, and artifact-less results never become cache hits. Cache hits and same-run checkpoint reuse are reported separately.

Resume verifies the prior Stage Input/Result JSON hashes and output hashes. Invalid or failed nodes rerun only on explicit `resume --execute`; prior attempts remain in append-only `attempts.jsonl`. Completed elapsed time is charged cumulatively across resume; an interrupted attempt without a finish record is charged its reserved timeout. Resume can retain or lower an existing budget. Cache reuse does not consume EDA time budget.

## Provenance and efficiency

Run manifests record Git revision/working-tree state, project inputs, stage order, commands, tool versions, statuses, artifacts, and parsed QoR. Artifact records contain path, kind, size, hash, producer, and role. Metric provenance is included when the parser provides report details; complete line/section/unit provenance is not yet available for every parser.

Efficiency records total workflow time, EDA stage time, stage count, tool invocations, cache hits, and checkpoint reuse. `agent_invocations` and `token_usage` are `null` because the runtime has no Codex telemetry. PPA per-candidate and cumulative search budgets remain in the PPA ledger and are passed as remaining stage budget to the common process runner; they are not yet one transactional ledger with general EDA run budgets.

## Tests, demo, and known limitations

Python tests cover runtime contract validation, graph validation and selection, cache reuse/invalidation/tampering, downstream status, dry run, unsupported adapters, budget exhaustion, existing VCS/URG/DC/PT CLI behavior, and the PPA evaluator. The example at `skills/eda-tool-engineering/examples/r1_dag_smoke/` uses explicitly mocked tools: it checks orchestration/cache behavior, not RTL behavior or Synopsys.

The generic EDA runtime is sequential and runs against the existing project worktree on the selected local/remote host; it does not snapshot EDA inputs. Incidental top-level tool helper trees containing symlinks are listed in `omitted_artifacts`; declared stage evidence is still hashed and required outputs gate status. EDA has no shared transactional budget ledger with PPA. Formal, CDC signoff, APR, extracted power, and parasitic signoff remain unsupported or planning-only unless separately validated. Mock tests do not establish real Synopsys validation. The licensed smoke result is recorded in [`r1-efficiency-report.md`](../r1-efficiency-report.md); it is an owned-fixture smoke, not project PDK validation or design signoff.
