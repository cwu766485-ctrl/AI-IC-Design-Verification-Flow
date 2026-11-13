# Milestone 1 Integration Backlog

This backlog tracks the remaining Milestone 1 integration after the initial
adapter slice. The current branch implements VCS compile/simulation, URG
extraction, DC synthesis, and explicit-netlist PrimeTime STA adapters, plus
Python-only regression tests. The local Synopsys smoke used an installed
example library; target-project validation remains pending. The items below
cover the canonical runner contract and evidence requirements that are still
not shared by `eda.py` and `rtl_ppa.py`.

## M1-01 — Freeze the shared stage contract

**Status:** Architecture and JSON Schema proposal exists; runtime validation
and compatibility mapping remain pending.

**Goal:** Turn `docs/architecture/unified-execution-contract.md` into the
versioned input/result/manifest schemas used by both current entry points.

**Work:** Add JSON Schema files; map existing `eda.py` and `rtl_ppa.py` fields
to canonical stage inputs; document exit-code compatibility; define status and
error-class mapping; inventory existing parsers and artifacts.

**Acceptance:** Schema validation tests cover valid, missing, and extra fields;
golden CLI fixtures show old `eda.py` invocation output and exit behavior;
no second runner is introduced. Depends on review of the contract proposal.

## M1-02 — Separate VCS compile and simulation stages

**Status:** Implemented as separate VCS stages with fake and local smoke
coverage. Canonical cross-runner schemas and append-only attempt records remain
pending.

**Goal:** Make compile and simulation independently reproducible and resumable.

**Work:** Compile the ordered RTL and testbench filelists with explicit
`testbench_top`, include directories, defines, seed policy, and tool options.
Persist executable/build artifacts and versioned compile result. Simulation
consumes only a passing compile checkpoint, executes the selected test, and
records simulator exit code, test name, seed, log, and result.

**Acceptance:** Fake VCS executable tests prove argv ordering, selected testbench
top, compile/sim separation, nonzero exit propagation, missing binary/license
classification, and that simulation cannot run after failed compile. Depends
on M1-01.

## M1-03 — URG coverage extraction from an existing simulation

**Status:** Inline and standalone URG extraction are implemented and tested.
Canonical VDB content hashing and a normalized uncovered-item parser remain
pending.

**Goal:** Parse coverage from a known VCS regression without rerunning
simulation unnecessarily.

**Work:** Define supported coverage database inputs and URG command options;
extract line/toggle/functional coverage only when requested; record URG version,
coverage configuration, input database hash, summary report and uncovered-item
artifact. Missing DB/report is a failure or blocked result, never zero coverage.

**Acceptance:** Fixture DB/report parser tests plus fake URG exit/missing-report
tests; evidence proves which simulation database was read. Depends on M1-01 and
M1-02 compile/simulation evidence format.

## M1-04 — Design Compiler synthesis adapter

**Status:** A project-level DC synthesis adapter is implemented, with fake
adapter tests and a smoke run using Synopsys' installed example library. Target
PDK/library validation and operating-corner configuration remain pending.

**Goal:** Produce a reproducible mapped synthesis result with explicit
constraints and libraries.

**Work:** Read ordered RTL, top, link/target libraries, operating conditions,
SDC, and approved DC options from the project contract. Separate RTL compile
success from mapped synthesis. Capture tool version, command/script hashes,
area/timing reports, and exact inputs. Reject unresolved references and missing
or empty reports.

**Acceptance:** Fake DC executable tests cover argv, source/library/SDC
provenance, exit propagation and missing reports. Local Synopsys smoke remains
pending. Depends on M1-01.

## M1-05 — Shared report parser registry

**Status:** Current DC/STA QoR and legacy DFT parsers are strict about required
metrics but are not yet in a versioned parser registry.

**Goal:** Use versioned parsers with source locations and units for reports
consumed by VCS/URG/DC and later STA/DFT stages.

**Work:** Extract existing parsers behind a common parser interface; normalize
metric names, units, parser version, report hash and source line/section;
distinguish missing, malformed, unsupported, and numeric-zero values.

**Acceptance:** Golden fixture tests for supported report formats and negative
fixtures for truncated/ambiguous reports; parser results include provenance and
cannot turn missing data into PASS. Depends on M1-01; can run alongside M1-02
through M1-04.

## M1-06 — Flow plan and execution slice

**Status:** `aicflow` provides a sequential simulation/synthesis pipeline with
checkpointing. Generic DAG validation, selected start/end stages, and
submission to one runtime from `rtl_ppa.py` remain pending.

**Goal:** Execute a validated dependency DAG from a selected start stage to a
selected end stage.

**Work:** Add stage dependency validation, topological ordering, start/end
ancestor slicing, deterministic sequential scheduling, dependency failure
propagation, per-stage timeout, and canonical stage/run manifests. Keep existing
`eda.py` CLI commands as wrappers; make `rtl_ppa.py` submit stages through the
same runtime API.

**Acceptance:** Fake adapter DAG tests cover cycles, absent dependencies,
partial selection, failed ancestors, status mapping, and compatibility CLI
entry points. Depends on M1-01 and at least M1-02 and M1-04 stage adapters.

## M1-07 — Checkpoint, resume, and cache invalidation

**Status:** Basic resume and fingerprinted cache behavior exist. Append-only
attempt history, fully shared budget locking, and complete tool/adapter
fingerprints remain pending.

**Goal:** Reuse verified stage outputs without silently accepting stale
artifacts.

**Work:** Persist passing checkpoint fingerprints and artifact manifests;
resume only on exact source/config/adapter/tool/dependency match; retain failed
attempt history; invalidate descendants when any input changes. Implement
conservative cache hit reporting and shared budget locking.

**Acceptance:** Fake tests show identical inputs resume, while source order,
source hash, top, seed, SDC, library, tool version, adapter version, or parent
artifact changes force rerun. Interrupted runs remain charged. Depends on M1-06.

## M1-08 — Python-only CI and compatibility regression suite

**Goal:** Make the contract, adapters, parsers, and legacy wrappers testable
without licensed EDA tools.

**Status:** Fake executable fixtures cover VCS compile/sim, URG, DC, and STA;
Python-only GitHub Actions runs them with the RTL PPA tests.

**Work:** Preserve report fixtures and keep CI independent of licensed EDA;
report mock tests as mock tests.

**Acceptance:** CI checks plan schemas, filelists, command construction,
artifacts, statuses, parser results, checkpoint invalidation, and old CLI
wrappers. No licensed tools or private collateral are required. Depends on
M1-01 through M1-06 as the corresponding code lands.

## M1-09 — Local licensed Synopsys smoke test

**Status:** A local owned-fixture smoke passed VCS, URG, DC, and PrimeTime. The
DC/STA portion used Synopsys' installed `lsi_10k.db` example library. This does
not satisfy project PDK validation; the project-specific smoke remains pending.

**Goal:** Validate one clean, owned RTL fixture with the actual installed tools.

**Work:** On an authorized EDA host, record host/tool versions and license
availability; run VCS compile, one deterministic simulation, URG extraction,
and DC synthesis against approved libraries and SDC. Archive the exact
commands, logs, report hashes, and manifests. Keep this separate from CI.

**Acceptance:** A reviewer can reproduce the smoke run from the recorded source
revision and read-only input hashes. Missing license, unsupported tool version,
or unavailable approved library/SDC is reported as blocked. No signoff claim is
made from a smoke test. Depends on M1-02 through M1-08 and local access to
licensed Synopsys tools and approved inputs.

## Suggested merge order

1. M1-01 contract and compatibility fixtures.
2. M1-02 VCS compile/simulation separation.
3. M1-04 DC synthesis and M1-05 report parser registry.
4. M1-03 URG coverage extraction.
5. M1-06 shared planning/execution slice.
6. M1-07 checkpoint/resume/cache invalidation.
7. M1-08 expand fake-adapter CI for every landed stage.
8. M1-09 authorized local Synopsys smoke run.

The dependency graph controls what can start; this ordering puts the first
functional execution path (VCS compile → simulation) and the first reproducible
PPA path (DC synthesis) ahead of optional coverage analysis and resume
optimization.
