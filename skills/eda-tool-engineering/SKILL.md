---
name: eda-tool-engineering
description: Reproducible project-level Synopsys VCS/URG simulation and coverage, Design Compiler synthesis, and PrimeTime STA flows. Use when a project contains eda.yaml or when Codex must inspect, plan, generate, or run these flows.
---

# Synopsys EDA engineering

This skill reads project facts from `<project-root>/eda.yaml`, constructs
deterministic commands, and writes logs and machine-readable results below
`runs/`. It does not claim design or verification signoff.

## Project contract

Use the project-root `eda.yaml`. The field contract and examples are in
[references/project-eda-contract.md](references/project-eda-contract.md).
Paths resolve relative to the project root, except absolute paths for installed
libraries or project assets explicitly configured by the user. Preserve RTL
source and filelist order.

Core fields are `name`, `top`, `rtl`, `filelists`, `include_dirs`, and `defines`.
The executable flows additionally use:

- VCS simulation: `flows.sim.tb`, optional `flows.sim.top`, `seed`, `test_name`,
  `plusargs`, and `coverage`.
- Standalone URG: `flows.coverage.vdb` as one nonempty VDB directory or a list
  of VDB directories.
- DC synthesis: `pdk.root`, `pdk.target_library`, optional
  `pdk.link_libraries`, and `constraints` or `flows.synth.sdc`.
- PrimeTime STA: the same library/constraint fields and an explicit existing
  `flows.sta.netlist`.

## Commands

Run from the project root:

```bash
python3 "$HOME/.codex/skills/eda-tool-engineering/scripts/eda.py" doctor
python3 "$HOME/.codex/skills/eda-tool-engineering/scripts/eda.py" plan --flow sim
python3 "$HOME/.codex/skills/eda-tool-engineering/scripts/eda.py" run --flow sim --dry-run
python3 "$HOME/.codex/skills/eda-tool-engineering/scripts/eda.py" run --flow sim --execute
python3 "$HOME/.codex/skills/eda-tool-engineering/scripts/eda.py" run --flow synth --execute
python3 "$HOME/.codex/skills/eda-tool-engineering/scripts/eda.py" run --flow sta --execute
```

`plan` and dry runs produce `NOT_RUN`, never PASS. Only `run --execute` launches
a tool. Every execution writes `runs/<run-id>/manifest.json`, command scripts,
logs, source and configuration hashes, stage statuses, tool versions, and
artifact records. VCS compile, simulation, result checking, and optional URG
extraction are independent stages with explicit dependencies.

The root `aicflow` command plans and checkpoints the current simulation and
synthesis pipelines. It delegates each executed stage to `eda.py`. The
proposed shared contract for the separate PPA campaign interface is documented
in [the unified execution contract](../../docs/architecture/unified-execution-contract.md).

## Capability boundary

| Flow | Current implementation |
|---|---|
| `sim` | Executable VCS compile → simulation → result checks. Testbench top is selected independently from design top. Simulation must have an explicit pass marker or a zero-error/zero-fatal UVM summary. |
| `coverage` | Executable URG report extraction from configured existing VDB input. Missing/empty database or missing dashboard blocks the run. |
| `sim` with coverage | Enables compile-time and runtime VCS coverage instrumentation, then extracts the run VDB with URG. |
| `synth` | Executable DC SystemVerilog analysis/elaboration, link, SDC application, mapping, netlist and report generation. Missing artifacts or required area/WNS/TNS block PASS. |
| `sta` | Executable PrimeTime analysis of the explicitly configured gate-level netlist, libraries, and SDC. Required reports and parseable WNS/TNS are checked. |
| `formality` | Planning only. A generated script requires separately configured Golden and Revised source lists and refuses identical paths or file contents. |
| `cdc` | Planning only. A SpyGlass lint script is not treated as CDC validation. |
| Other legacy flows | Their planning interfaces and script generation remain available. Execution is `BLOCKED` until an adapter and evidence contract are validated. MBIST/LBIST/APR/Power/StarRC include templates. |

See [the complete adapter matrix](../../docs/eda-adapter-capabilities.md).

`doctor` checks tool availability and config shape; it does not prove that a
license can be checked out. License, unsupported tool, missing input, failed
command, timeout, and missing required evidence are represented as
`BLOCKED`, `FAIL`, or `ERROR`, never silently mapped to PASS.

## Evidence and limits

`PASS` means only that the configured stage and its required artifacts passed
the implemented checks. It is not a signoff claim. The local smoke records in
[`docs/milestone1.md`](../../docs/milestone1.md) used an owned temporary RTL
fixture and an installed Synopsys example library for DC/STA; they do not
validate a target PDK or production design.

Do not modify installed Synopsys tools, licenses, PDKs, libraries, source RTL,
or existing verification evidence. Keep generated runs under `runs/` and
review scripts and reports before relying on results.
