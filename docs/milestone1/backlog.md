# Milestone 1 Integration Backlog

This backlog tracks the remaining Milestone 1 integration after R1. The R1
branch now shares stage execution, JSON contracts, sequential DAG scheduling,
checkpoint/cache validation, and run-budget locking between the existing EDA
and PPA entry points. VCS/URG/DC/PrimeTime adapters passed an owned counter
fixture smoke using Synopsys' `lsi_10k.db` example library. Target-project PDK
validation, broader parser support, and future agent stages remain pending.

## M1-01 — Freeze the shared stage contract

**Status:** Stage Input/Result v1 JSON Schemas, strict runtime validators, and
EDA/PPA compatibility mapping are implemented. A single schema for the full
legacy run manifest and exhaustive golden-output compatibility fixtures remain
future work.

**Goal:** Turn `docs/architecture/unified-execution-contract.md` into the
versioned input/result/manifest schemas used by both current entry points.

**Work:** Add JSON Schema files; map existing `eda.py` and `rtl_ppa.py` fields
to canonical stage inputs; document exit-code compatibility; define status and
error-class mapping; inventory existing parsers and artifacts.

**Acceptance:** Runtime and JSON Schema tests cover valid and invalid inputs
and results; existing CLI behavior is covered by regression tests; no second
runner is introduced. Further legacy-output snapshots are still useful.

## M1-02 — Separate VCS compile and simulation stages

**Status:** Implemented as separate VCS compile, simulation, and result stages;
the shared contracts and append-only attempt journal are now used. Fake tests
and the local licensed smoke both passed.

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

**Status:** Inline regression and standalone URG extraction are implemented
and tested. The local licensed smoke parsed code and covergroup coverage.
Uncovered-item normalization and the versioned parser registry remain pending.

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

**Status:** DC synthesis and explicit-netlist PrimeTime stages passed fake
tests and the local licensed smoke using Synopsys' installed example library.
Target PDK/library validation, corner modeling, and signoff criteria remain
pending.

**Goal:** Produce a reproducible mapped synthesis result with explicit
constraints and libraries.

**Work:** Read ordered RTL, top, link/target libraries, operating conditions,
SDC, and approved DC options from the project contract. Separate RTL compile
success from mapped synthesis. Capture tool version, command/script hashes,
area/timing reports, and exact inputs. Reject unresolved references and missing
or empty reports.

**Acceptance:** Fake DC executable tests cover argv, source/library/SDC
provenance, exit propagation and missing reports. Local Synopsys smoke passed
with the installed example library; project PDK/library validation remains
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

**Status:** Generic sequential DAG validation, topological execution,
dependency-aware `--from`/`--to`, composite flows, and shared Stage Runtime
submission from `rtl_ppa.py` are implemented. Parallel scheduling is deferred.

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

**Status:** Resume verifies stage contract and artifact hashes; cache keys
include source/config/assets/tool/adapter/dependency inputs; failures remain in
an append-only journal. Same-run execution is serialized under a run lock, and
interrupted attempts reserve their configured timeout. EDA and PPA still have
separate cumulative budget ledgers.

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

**Status:** Python-only CI runs JSON Schema validation, fake VCS/URG/DC/PT
adapter tests, DAG/cache/budget tests, mocked SSH routing, and the PPA
evaluator. Local result: 65 pytest tests passed; the GitHub check is reported
in the PR.

**Work:** Preserve report fixtures and keep CI independent of licensed EDA;
report mock tests as mock tests.

**Acceptance:** CI checks plan schemas, filelists, command construction,
artifacts, statuses, parser results, checkpoint invalidation, and old CLI
wrappers. No licensed tools or private collateral are required. Depends on
M1-01 through M1-06 as the corresponding code lands.

## M1-09 — Local licensed Synopsys smoke test

**Status:** R1 runtime smoke passed VCS compile, two seeded simulations, URG
code/functional coverage extraction, DC synthesis, and PrimeTime STA on an
isolated copy of an owned counter fixture. The DC/STA portion used Synopsys'
installed `lsi_10k.db` example library. This does not satisfy project PDK
validation or constitute signoff.

**Goal:** Validate one clean, owned RTL fixture with the actual installed tools.

**Work:** On an authorized EDA host, record host/tool versions and license
availability; run VCS compile, one deterministic simulation, URG extraction,
and DC synthesis against approved libraries and SDC. Archive the exact
commands, logs, report hashes, and manifests. Keep this separate from CI.

**Acceptance:** Current branch manifests capture the temporary fixture's
source revision, tool versions, commands, artifact hashes, and statuses. The
smoke used the installed example library; running against an approved product
PDK remains pending. No signoff claim is made. Depends on licensed Synopsys
tool availability.

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
