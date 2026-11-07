# M0 audit and Synopsys tool capability matrix

This records the repository and host audit for the M0/M1 increment. Tool
status is evidence-based and separates executable installation, license
checkout, project configuration, and execution testing. A tool in `PATH` is
not treated as licensed. A generated script is not treated as an executed
flow.

## Repository audit and changes

| Area | Audit finding | Current behavior / disposition |
|---|---|---|
| `README.md` and three maintained skills | The repository has `organize-chip-project`, `eda-tool-engineering`, and `write-agents-md`; the first and third are independent reusable skills. | Preserved. README/EDA skill now identify the executable adapter boundary and do not claim signoff. |
| `eda.py` public CLI | Existing dispatch included planning/template flows beside executable operations; initialization and unsupported tool presence could be mistaken for readiness. | Kept `doctor`, `plan`, `run`, `resume`, `report`, and `validate`; supported flows produce status/evidence, unsupported execution is `BLOCKED`. |
| `eda-env.sh` | It adds configured tool `bin` directories to `PATH`; it does not test versions, feature checkout, project assets, or smoke results. It previously omitted `FC_HOME`. | Remains a path helper and now includes `FC_HOME`. The separate read-only `check_environment.py` records those dimensions without printing license values. |
| `eda.yaml` | Examples described sources, tops, filelists, libraries, and constraints, but not an executable regression/runner contract. The repository root has no project `eda.yaml`. | Updated example and reference. Each real design still needs its own reviewed root config, library, and SDC. |
| VCS/URG | VCS compile/simulation and URG appeared as a combined path; regression and covergroup summaries were not fully represented. | Split compile and per-test simulation/result stages; per-seed VDBs are merged with compile design DB for URG. Code and functional coverage are parsed separately. |
| DC/STA | DC/STA scripts existed, but power reporting and evidence expectations were incomplete. | DC emits check/QoR/area/timing/constraint/power reports; STA consumes a pinned netlist. Missing required reports/QoR metrics block. Power provenance/units/errors are explicit; unavailable total stays null. |
| Other adapter/parser tests | Existing test coverage did not cover environment probing, SSH runner boundaries, or all false-success report cases. | Added pytest fixtures for config/flow behavior, environment status separation, mocked SSH, URG report semantics, and failures. Commercial tools are not mocked as real validation. |

`eda-env.sh` does not install tools, alter tool binaries, source proprietary
setup scripts, or perform license checkout. `check_environment.py` is also
read-only except for the requested JSON output path.

## Status definitions

- **Installed:** executable found at a configured home or on `PATH`. Version
  is separate and may remain unconfirmed if the version probe times out or
  returns no parseable version.
- **Licensed:** `YES` only after an explicitly configured feature probe or a
  passing execution stage using that tool. Otherwise `UNKNOWN`; a set license
  server variable is not proof of checkout. No license server values are
  written to reports.
- **Configured:** `YES` requires tool home/license environment indicators, a
  valid project `eda.yaml`, a configured project flow for that tool, resolved
  RTL/TB inputs, and DC/STA assets where relevant. `PARTIAL` means the host
  paths exist but the project's specific flow or required assets are absent.
- **Tested:** `PASS` only for a passing recorded execution of that tool;
  recorded failures stay `FAIL`, `ERROR`, or `BLOCKED`; absent evidence is
  `NOT_RUN`. Dry-run, script generation, KDB inventory, and mocked subprocess
  tests do not count as a tool test.

The current repository root has no `eda.yaml`, target PDK/library configuration,
or project SDC. The real smoke used a disposable counter design under `/tmp`
and the read-only Synopsys demo `lsi_10k.db`; this is not the target product
PDK. Linux local execution passed. SSH is supported only for an explicitly
authorized alias and a matching clean remote checkout; no SSH host was
configured or tested in this environment.

## Host tool status at validation time

`Configured=PARTIAL` below reflects the host's tool home and license-server
environment plus the absence of a project-root `eda.yaml`. Tool-specific
license checkout remains `UNKNOWN` unless a smoke execution passed. Only
version strings observed from a tool are shown.

| Tool | Installed | License | Configured | Tested | Observed version / evidence |
|---|---:|---:|---:|---:|---|
| VCS | YES | YES | PARTIAL | PASS | `V-2023.12-SP1`; real compile and 2-seed regression |
| URG | YES | YES | PARTIAL | PASS | `V-2023.12-SP1`; real code + covergroup report |
| Verdi | YES | UNKNOWN | PARTIAL | NOT_RUN | KDB/debug artifacts generated; GUI/license not invoked |
| Design Compiler | YES | YES | PARTIAL | PASS | `V-2023.12-SP1`; real mapped synthesis |
| PrimeTime | YES | YES | PARTIAL | PASS | `V-2023.12-SP2`; real netlist timing analysis |
| SpyGlass | YES | UNKNOWN | PARTIAL | NOT_RUN | Version probe unconfirmed |
| VC Formal | YES | UNKNOWN | PARTIAL | NOT_RUN | Version probe unconfirmed |
| Formality | YES | UNKNOWN | PARTIAL | NOT_RUN | `V-2023.12-SP3`; no formal comparison run |
| ICC2 | YES | UNKNOWN | PARTIAL | NOT_RUN | Version probe unconfirmed |
| Fusion Compiler | NO | UNKNOWN | NO | NOT_RUN | `fc_shell`/`FC_HOME` unavailable |
| TestMAX DFT | YES | UNKNOWN | PARTIAL | NOT_RUN | Version probe unconfirmed |
| TestMAX ATPG | YES | UNKNOWN | PARTIAL | NOT_RUN | `V-2023.12-SP5` observed; no ATPG run |
| StarRC | YES | UNKNOWN | PARTIAL | NOT_RUN | Version probe unconfirmed |

## M0–M3 gap matrix

| Milestone | Current status | Remaining gap |
|---|---|---|
| M0: environment audit | **Implemented and unit-tested.** Tool inventory and status dimensions are explicit; no real project configuration/assets exist at this repository root. | Run the probe with an approved project config and explicit license feature names if checkout-level inventory is needed; probe a user-authorized SSH alias. |
| M1: deterministic execution | **Minimum VCS/URG/DC/PrimeTime slice implemented and smoke-tested.** Dry run, manifests, metrics, regression seeds, debug artifact inventory, DC power report and missing-evidence gates exist. | Smoke the actual project with its approved PDK, corners, constraints, SAIF/power assumptions, and signoff criteria. Expand parser formats and add supported adapters for optional tools. |
| M2: verification agent | **Not implemented in this increment.** | Spec-derived testplan, approved TB/SVA generation, failure triage, guided coverage closure, waiver review and traceable closure report. |
| M3: RTL/PPA optimization | **Not implemented or revalidated in this increment.** An existing PPA skill is preserved. | Establish a real target-project baseline, compatible candidate comparisons, functional/equivalence checks, and measured QoR evidence. |

## Probe and validation commands

```bash
python3.12 skills/eda-tool-engineering/scripts/check_environment.py \
  --project-root <project-root> --output <private-report.json>
python3.12 -m pytest -q tests
```

See [M0/M1 validation evidence](milestone1.md) for exact commands and
results. Keep environment JSON and EDA reports in an authorized workspace;
they can contain private path and design metadata.
