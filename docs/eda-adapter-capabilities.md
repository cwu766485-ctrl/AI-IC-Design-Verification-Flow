# EDA adapter capability matrix

This describes behavior implemented in `eda.py`, not Synopsys product
availability or signoff readiness. `PASS` means the configured stage and its
required evidence checks passed.

| Flow | Implemented behavior | Required inputs and PASS evidence | Capability |
|---|---|---|---|
| `sim` | Separate VCS compile, simulate, and result stages. Testbench top is separate from the design top. | Ordered RTL/filelists, TB source/top, seed/plusargs. `simv`, successful exit, plus `TEST PASSED` or zero-error/zero-fatal UVM summary. | Executable |
| `regression` | Compile once; each named test and seed runs separately with separate logs/VDB. Failed tests block coverage. | `flows.sim.tests` list. All result markers pass; per-test exit, seed, log, and artifact evidence. | Executable |
| `coverage` | URG extracts reports from configured VDBs; it does not rerun simulation. | Existing nonempty VDB directory or list. URG exits cleanly and emits dashboard plus a parseable code summary. | Executable |
| `sim`/`regression` with coverage | VCS compile/runtime instrumentation; URG receives compile design DB plus per-test runtime DBs. Code coverage and functional coverage are separate metrics. | Supported VCS coverage types. Required report and parseable module-definition summary; if functional coverage is requested, parseable group score and at least one group. | Executable |
| `sim`/`regression` with `debug: true` | VCS KDB/debug instrumentation; inventory of KDB/wave files and Verdi launch script. | KDB/debug artifacts recorded. Verdi GUI execution is not implied. | Artifact support; viewer `NOT_RUN` |
| `synth` | DC analyzes/elaborates ordered SystemVerilog sources, links configured libraries, reads SDC, maps, and emits check/QoR/area/timing/constraint/power reports. | Existing target/link libraries and SDC. Netlist, reports, parseable area/WNS/TNS. | Executable |
| `sta` | PrimeTime analyzes only the explicitly configured gate-level netlist under configured libraries and SDC. | Explicit netlist, target/link libraries, SDC. QoR/timing/constraint reports and parseable WNS/TNS. | Executable |
| `formality` | Generates review script only; requires distinct Golden/Revised lists and rejects same paths or file contents. | Golden and Revised inputs. No execution PASS exists. | Planning only |
| `cdc` | Does not treat a SpyGlass lint script as CDC validation. | Reviewed CDC setup and waiver contract are future work. Execution is `BLOCKED`. | Planning only |
| Standalone `debug`, `lint`, `formal`, `dft`, `atpg`, `mbist`, `lbist`, `apr`, `power`, `starrc` | Legacy planning/script generation remains. Several flows contain templates only. | Tool/project-specific inputs and evidence checks are not validated by an executable adapter. | Planning/template; execution `BLOCKED` |

## Status rules

- `NOT_RUN`: plan or command-generation result; never verification PASS.
- `BLOCKED`: unavailable tool/license, unsupported adapter, invalid/missing
  input, missing required artifact/metric, or incomplete report.
- `FAIL`: nonzero tool exit or explicit design-check failure.
- `ERROR`: tool error/fatal in output even if a wrapper exits zero, timeout,
  or unexpected runtime error.
- `SKIPPED`: stage intentionally not run. Dependency stages do not run unless
  all dependencies pass.

## Smoke evidence

The current local smoke used an owned counter RTL/testbench fixture under
`/tmp`: VCS `V-2023.12-SP1` compiled and ran two seeds; URG `V-2023.12-SP1`
reported 80.15% module-definition code coverage and 100% functional group
coverage; DC `V-2023.12-SP1` synthesized the design; PrimeTime `V-2023.12-SP2`
analyzed its mapped netlist. DC and PrimeTime used the read-only Synopsys demo
library `lsi_10k.db`, not a target product PDK. The DC report had incomplete
power characterization; JSON leaves total power null and marks the report
partial. VCS debug/KDB files were inventoried but the Verdi GUI was not
invoked. This is adapter smoke evidence, not project validation or signoff.
