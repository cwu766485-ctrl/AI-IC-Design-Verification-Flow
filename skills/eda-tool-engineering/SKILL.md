---
name: eda-tool-engineering
description: Reproducible project-level Synopsys VCS/URG simulation, regression, coverage, Design Compiler synthesis, and PrimeTime STA. Use when a project contains eda.yaml or when Codex must inspect, plan, or run these flows.
---

# Synopsys EDA engineering

Use the project's `<project-root>/eda.yaml` as the source of project facts.
This skill adds validated adapters to the existing flow; it does not replace
the repository's three-Skill structure or claim design/verification signoff.
Paths resolve from the project root, while absolute installed library paths
are allowed when explicitly configured. RTL and nested filelist order is kept.

## Configuration and environment

The field contract is documented in
[project-eda-contract.md](references/project-eda-contract.md), and a fuller
sample is in [examples/eda.yaml](examples/eda.yaml). It covers design top,
testbench top/sources, ordered filelists, globs, includes, defines, PDK/library
inputs, SDC, regression seeds, coverage, debug, synthesis activity, and local
or explicitly authorized SSH execution.

Run the read-only capability probe first:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/eda-tool-engineering/scripts/check_environment.py" \
  --project-root "$PWD" --output runs/environment.json
```

It reports tool installation, version probe, license evidence, project
configuration/assets, and smoke-test evidence as separate fields. Presence in
`PATH` or license-server environment variables alone does not establish a
license checkout. `--probe-licenses` checks only feature names explicitly
listed in `eda.yaml`; it never prints license server values. To test an
authorized remote host, pass its SSH config alias with `--ssh-host`.

## Commands

Run from the project root. `eda.py` is the canonical CLI; root `aicflow` is a
compatibility wrapper into the same CLI.

```bash
EDA_SCRIPT="${CODEX_HOME:-$HOME/.codex}/skills/eda-tool-engineering/scripts/eda.py"
python3 "$EDA_SCRIPT" doctor
python3 "$EDA_SCRIPT" plan --flow regression
python3 "$EDA_SCRIPT" run --flow regression --dry-run
python3 "$EDA_SCRIPT" run --flow regression --execute
python3 "$EDA_SCRIPT" run --flow synth --execute
python3 "$EDA_SCRIPT" run --flow sta --execute
python3 "$EDA_SCRIPT" resume --run-id <run-id> --execute
python3 "$EDA_SCRIPT" report --run-id <run-id>
```

The repository-root `./aicflow` wrapper exposes the same execution runtime
for composed stage graphs. Current sequential graphs include VCS compile to
simulation/regression and URG, DC synthesis to PrimeTime STA, and a combined
verification plus synthesis run:

```bash
./aicflow plan --flow rtl_to_regression
./aicflow run --flow rtl_to_regression --execute
./aicflow run --flow rtl_to_synth_sta --execute
./aicflow run --flow rtl_to_sim_synth --from vcs_compile --to dc_synthesis --execute
./aicflow resume --run-id <run-id> --execute
./aicflow report --run-id <run-id> --log-tail 50
```

`--from`/`--to` select a topological interval and preserve required
dependencies. The generic scheduler is sequential. It uses the shared
versioned Stage Input/Result boundary and verified content cache described in
[`unified-execution-contract.md`](../../docs/architecture/unified-execution-contract.md).
The EDA runner uses the current project worktree; it does not create a source
snapshot. `rtl_ppa.py` uses the shared process boundary while retaining
candidate snapshot, patch, metric, and campaign-budget policy.

Dry run and planning only generate commands and return `NOT_RUN`; execution
requires `--execute`. A run writes to a unique `runs/<run-id>/` with Tcl,
filelists, logs, run manifest, unified metrics JSON, and hashes/inventories of
inputs and artifacts. Failed dependencies block downstream stages. Resume
reuses a passing stage only when its recorded outputs still match their hashes.

## Implemented adapters and boundaries

| Adapter | Implemented behavior |
|---|---|
| `sim` | VCS compile and simulation are separate dependent stages. The configured testbench top is used for simulation. A test passes only with `TEST PASSED` or a UVM summary with zero errors and fatals. |
| `regression` | VCS compile once; run each configured test/seed in a separate stage and coverage database; classify every result; merge coverage with URG. |
| `coverage` | URG reads configured existing VDB directories. Required dashboard and parseable module-definition code coverage are enforced. Functional summaries are reported separately and required when requested. |
| `debug` option | VCS KDB/debug access is enabled at compile. KDB/wave artifacts and a Verdi launch script are inventoried. The Verdi GUI itself is not run by this adapter. |
| `synth` | DC analyzes/elaborates the design top, links configured libraries, reads SDC, maps, and emits netlist, check, QoR, area, timing, constraint, and power reports. Missing required report/QoR metrics blocks the run. Optional SAIF activity is tracked. |
| `sta` | PrimeTime analyzes the explicitly named netlist against configured libraries and SDC, with QoR/timing/constraint reports and required parseable WNS/TNS. |

Formality remains planning-only and refuses identical Golden/Revised sources.
SpyGlass lint is not represented as CDC. VC Formal, Formality execution, APR,
power signoff, StarRC, TestMAX insertion/ATPG, and other legacy flows are
unsupported or planning/templates until separately validated adapters exist.
See [flow capabilities](../../docs/eda-adapter-capabilities.md) and the
[host tool matrix](../../docs/tool-capability-matrix.md).

The example at `examples/r1_dag_smoke/` uses explicitly mocked executables.
It demonstrates graph execution, cache reuse, and input invalidation, not RTL
simulation correctness or Synopsys tool behavior. Python-only CI results must
not be presented as licensed-tool validation.

`PASS` means the configured stage completed and its implemented required
evidence checks passed; it is not a design or signoff claim. Default DC power
activity is an estimate. Missing or unitless total power remains `null` and is
marked partial in the metrics JSON. The local smoke used a generic installed
example library, not a product PDK.

Do not modify Synopsys installations, licenses, PDKs, libraries, external RTL,
or existing evidence. Review generated scripts and reports before relying on
results.
