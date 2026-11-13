# Milestone 3: RTL/PPA Optimization Framework

This change adds `skills/rtl-ppa-optimization` and an adapter-driven evaluator
for measured baselines and bounded RTL candidate patches. It does not replace
the existing skills or create a new EDA tool adapter. Project commands supply
the actual regression, formal/reference, synthesis, STA, power, performance and
accuracy measurements.

## Accurate capability matrix

| Capability | Framework state | NMAForge Matrix evidence state |
|---|---|---|
| Source revision and candidate patch records | Implemented; isolated Git snapshot, compiled-source patch allowlist, plan/source/asset/seed/tool compatibility, fractional per-campaign and cumulative budgets | Not run against NMAForge |
| Stage artifact and metric evidence | Implemented checks for supported adapter identity, nonempty SHA-256 artifacts, and metric-to-artifact/parser provenance | No real adapter evidence captured |
| Regression gate | Implemented as a required ordered stage | Existing regression documentation and reference model were found; no adapter is wired to this evaluator |
| Formal equivalence | Candidate `formal` stage is mandatory for cycle-equivalent plans | No formal campaign evidence captured for this milestone |
| Synthesis cell area | Metric gate and report-artifact requirement | No measured area report captured |
| Setup WNS | Metric gate and report-artifact requirement | No measured STA report captured |
| Power | Metric gate and report-artifact requirement | No measured power report captured |
| INT8 throughput | Metric gate | An existing benchmark references 250 MHz, but identifies it as an assumed reference frequency rather than a measured clock |
| BF16/FP16 accuracy | Metric gates | A project checker/reference model is documented; candidate accuracy metrics were not captured |
| Coverage closure or UVM generation | Out of scope | Not claimed |

## NMAForge target and baseline readiness

The proposed first optimization target is the NMAForge Matrix Compute Tile, not
the full NPU. The inspected design top is `ai_tensor_matrix_core` with testbench
top `tb_ai_tensor_matrix_core_random`. The RTL scope is:

- `rtl/compute/matrix/ai_tensor_matrix_core.v`
- `rtl/compute/matrix/ai_tensor_matrix_array.sv`
- `rtl/compute/matrix/ai_tensor_matrix_datapath.v`

The inspected NMAForge revision was
`c290eba7697138a4fcf2cbbac9262264849f0aeb`. Existing simulation and reference
model material provide useful functional starting points, but no reproducible
area, setup WNS, or power baseline was found. The 250 MHz performance reference
must not be presented as measured STA or PPA evidence.

Baseline execution is currently **BLOCKED**. The inspected external NMAForge
worktree contained untracked `novas.conf` and `novas.rc`; this evaluator requires
a clean source worktree and intentionally does not ignore or modify those
files. Its configured private library and SDC inputs also need to be supplied
to a project adapter as copied read-only assets. The example plan is explicitly
planning-only and contains placeholder commands and asset paths.

No licensed EDA command, candidate RTL patch, or external project write was
performed for this milestone. This repo change therefore delivers the skill
and evaluation framework, not a measured optimization result or signoff claim.

## Evaluation behavior

The runner in `skills/rtl-ppa-optimization/scripts/rtl_ppa.py` supports:

- `validate`: structural plan validation only.
- `plan`: source/top-level scope and ordered stages preview, status `NOT_RUN`.
- `baseline`: clean Git snapshot plus configured baseline stages.
- `evaluate`: apply a scoped patch to a new snapshot, run candidate stages, and
  compare only metrics emitted by their configured source stages.

The run manifest supplies the explicit RTL and testbench file order, module
tops, behavior contract, asset mount points, and effective source hashes to
project adapters.

Each execution requires an explicit `--execute`. Campaigns write outside the
project worktree. Candidate source edits are confined to `allowed_patch_paths`;
stage outputs are confined to each run directory. Required reports and
metrics cannot be replaced with zero or inferred from a successful shell exit.

PR-01 hardening requires a named and supported adapter in every passing stage
result, hashes every nonempty required artifact, and checks baseline/candidate
compatibility across the plan, source revision and base RTL hashes, file/top
contract, seed, copied read-only asset hashes, and shared-stage adapter/tool
versions. Patch changes must belong to the ordered RTL file list as well as the
allowlist. A candidate stage failure produces a blocked comparison and cannot
be accepted based on metrics from an earlier stage. Per-campaign and cumulative
runtime budgets are separate, retain fractional seconds, and share a locked
ledger. Python-only tests are in `tests/rtl_ppa`; they use fake adapters and do
not validate Synopsys commands.

## Migration and compatibility

The existing `organize-chip-project`, `write-agents-md`, and
`eda-tool-engineering` skills remain the execution and project-layout sources
of truth. The new skill is additive. Existing `eda.py` entry points and
project-specific flows do not need to migrate to this evaluator. To adopt it,
add a committed project plan and adapter commands that return the documented
stage JSON and artifacts, then capture a baseline before submitting candidate
patches.

## Remaining limitations

- Tool adapters and report parsers are project supplied; none are bundled for
  Synopsys or for NMAForge.
- The framework relies on trusted adapter commands to honor the supplied
  snapshot and output directory. It does not sandbox EDA processes at the OS
  level.
- Adapter identity, support, and tool versions are adapter-reported fields.
  The evaluator checks consistency and evidence presence but cannot prove the
  named tool or operation was actually used.
- External constraints and libraries must be declared as `read_only_assets` so
  the runner copies and hashes them. The runner cannot discover undeclared
  files an adapter might open through an external path.
- Candidate runs require the same committed plan as the baseline. A changed
  PDK or SDC requires a new baseline.
- PDK/library assets are copied into a private run snapshot, which can require
  substantial disk space. Symlink-containing asset trees are rejected.
- No physical PPA smoke run, formal proof, or licensed-tool check was possible
  or attempted in this repository-only milestone.
