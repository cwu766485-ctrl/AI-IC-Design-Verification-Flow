# M0/M1 audit, validation, and limitations

This increment strengthens the existing `eda-tool-engineering` implementation.
It preserves `organize-chip-project`, `write-agents-md`, and the existing PPA
skill. It does not implement the M2 verification agent or M3 optimization loop.

## Repository and environment audit

Reviewed the repository README, all maintained skill instructions/references,
`eda.py`, `eda-env.sh`, `eda.yaml` examples/contract, legacy flow planners,
adapter scripts, report parsers, and existing pytest/unittest coverage.

- `eda-env.sh` only adds configured Synopsys `bin` paths to `PATH`; it cannot
  establish a license checkout or a valid project setup. It remains unchanged.
- The repository root has no project `eda.yaml`, target library/PDK, or SDC.
  Project-specific EDA execution is therefore not configured at the repo root.
- The read-only M0 probe is
  [`check_environment.py`](../skills/eda-tool-engineering/scripts/check_environment.py).
  It separately records executable installation/version, explicit license
  evidence, configuration/assets, and tested run evidence. It never serializes
  license variable values.
- The host has a local Linux runner and Synopsys VCS, URG, Verdi, DC,
  PrimeTime, SpyGlass, VC Formal, Formality, ICC2, TestMAX, and StarRC
  executables. Fusion Compiler was unavailable. A few vendor version probes
  were inconclusive. Only VCS, URG, DC, and PrimeTime have tool-specific
  license evidence from successful real smoke execution. Other licenses are
  `UNKNOWN`, not inferred from environment variables.
- SSH execution is opt-in for an explicitly authorized alias and requires a
  matching clean remote checkout. SSH behavior has mocked unit tests; no
  authorized remote host was configured or tested here.
- The detailed four-state inventory and milestone gap table are in
  [`tool-capability-matrix.md`](tool-capability-matrix.md).

## Implementation and compatibility

The canonical `eda.py` CLI retains `doctor`, `plan`, `run`, `resume`, `report`,
and `validate`. The root `aicflow` command is a compatibility wrapper into that
CLI. Existing planning interfaces remain; unsupported `run --execute` flows
return `BLOCKED` rather than a false PASS.

Implemented execution slice:

- VCS compile and simulation are distinct dependent stages. The configured TB
  top is used for simulation; regression runs named tests/seeds with separate
  VDBs and result markers.
- URG consumes the compile design DB and per-test runtime DBs. It must produce
  reports with parseable module-definition code coverage. Requested functional
  coverage also requires a parsed group score and at least one group.
- `debug: true` creates VCS KDB/debug data and a Verdi launch script. The
  manifest reports the GUI as `NOT_RUN`; artifact inventory is not a Verdi
  execution/license test.
- DC emits check-design, mapped netlist, QoR, area, timing, constraint, and
  power reports. PrimeTime consumes a pinned netlist and configured libraries
  and SDC. Missing required reports or QoR metrics block the run.
- Power metrics include report units/errors/provenance. Missing total power is
  null. DC default activity is marked as an estimate; it is not signoff power.
- Every run has a unique directory, stage status/exit code, command, tool
  version, seed, Git/source/config hashes, environment summary, logs, artifact
  hashes, and normalized metrics JSON.

Migration details and unsupported capabilities are listed in the
[adapter matrix](eda-adapter-capabilities.md) and the EDA skill's
[project contract](../skills/eda-tool-engineering/references/project-eda-contract.md).

## Automated validation

The tests use fake executables and fixture reports; these tests do not claim
Synopsys validation.

```bash
/tmp/rtl-ppa-test-venv/bin/python -m pytest -q tests
python3.12 -m py_compile \
  skills/eda-tool-engineering/scripts/eda.py \
  skills/eda-tool-engineering/scripts/eda_runtime.py \
  skills/eda-tool-engineering/scripts/eda_runner.py \
  skills/eda-tool-engineering/scripts/check_environment.py
git diff --check
```

Latest Python-only result: **49 passed** using
`/tmp/rtl-ppa-test-venv/bin/python -m pytest -q tests`. `python3.12 -m
py_compile` on the EDA scripts and `git diff --check` also passed. The
GitHub Actions workflow runs the same pytest suite without licensed EDA tools;
its result is reported separately after the branch update.

## Real local Synopsys smoke

An owned counter RTL/testbench, SDC, and temporary `eda.yaml` were created
in a local temporary directory that is not checked into this repository. The environment probe reported the
fixture inputs configured and VCS/URG/DC/PrimeTime installed, licensed, and
tested from successful stage records. Fusion Compiler was unavailable; other
Synopsys tool licenses and the Verdi GUI remain `UNKNOWN`/`NOT_RUN`. No external design, installed tool,
license file, library, PDK, or existing verification evidence was modified.

| Command / run | Result | Tool / evidence |
|---|---|---|
| `eda.py run --flow regression --execute --run-id smoke-regression-final` | **PASS**: VCS compile, 2/2 test seeds, result markers, URG, metrics, and artifact stages all pass. | VCS/URG `V-2023.12-SP1`; code coverage 80.15%, line 94.74%, toggle 85.71%, branch 60.00%; one functional covergroup at 100%. |
| Debug artifacts in the regression | **PASS**: VCS KDB/debug database and launch manifest are present. | Verdi GUI was not started; Verdi license remains unverified. |
| `eda.py run --flow synth --execute --run-id smoke-synth-final` | **PASS**: DC produced a mapped netlist and all required reports; area 50.0, WNS 3.99, TNS 0.0 in report units. | DC `V-2023.12-SP1`; dynamic power 443.2449 nW, leakage report 0.0 unitless, `total_power: null`; power status is `PARTIAL` because the generic library lacks complete power characterization. |
| `eda.py run --flow sta --execute --run-id smoke-sta-final` | **PASS**: PrimeTime consumed the pinned DC netlist and emitted QoR/timing/constraint reports; WNS 8.5, TNS 0.0 in report units. | PrimeTime `V-2023.12-SP2`; same generic example library and temporary SDC. |

The exact run manifests, logs, and reports remain in that local `/tmp` smoke
workspace and are not committed because they contain machine paths and tool
output. The code+functional URG parse exposed and fixed the need to supply
compile-time design metadata alongside per-seed VDBs. No target product PDK,
project timing corner, production RTL, Verdi GUI, formal, CDC, or signoff
validation is claimed.

## Known limitations and next priority

1. Configure an approved small reference project with its own `eda.yaml`,
   target libraries/PDK, corner, SDC, and documented operating conditions; rerun
   the smoke on that project.
2. Resolve target-project power activity and units, then add explicit power
   acceptance criteria. Current generic-library power output is partial.
3. Add/validate optional Synopsys adapters (SpyGlass, VC Formal, Formality,
   DFT/ATPG, APR, StarRC) only when project setup and licenses are available.
4. Continue the shared execution contract, stage DAG/start-end selection,
   checkpoint/cache invalidation, and common parser work in the ordered
   [Milestone 1 backlog](milestone1/backlog.md).
5. Start M2 and M3 only after the approved project execution slice is
   reproducible; this delivery does not claim those agents are complete.
