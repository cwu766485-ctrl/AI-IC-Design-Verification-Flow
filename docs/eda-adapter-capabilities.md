# EDA adapter capability matrix

This matrix describes executable behavior in `eda.py`, not product marketing or
signoff readiness. A `PASS` means the configured command completed and its
required evidence was found. It does not assert design or verification
signoff.

| Flow | Capability | Required project inputs | Passing evidence | Status |
|---|---|---|---|---|
| `sim` | VCS compile, simulation, and test result are separate dependent stages. | Ordered RTL/filelists, `flows.sim.tb`, optional `flows.sim.top`, seed and plusargs. | `simv`, successful simulator exit, and `TEST PASSED` or zero-error/zero-fatal UVM summary. | Executable |
| `coverage` | URG extracts coverage from an existing VDB; it never reruns simulation. | `flows.coverage.vdb`: one nonempty VDB directory or a list of them. | Successful URG exit and nonempty `coverage/dashboard.html`. | Executable |
| `sim` with `coverage` | VCS compile and simulation both receive coverage instrumentation; URG then reads that run's VDB. | `flows.sim.coverage: true` or a `+`-joined supported coverage type list. | Nonempty VDB, URG dashboard, passing simulation result. | Executable |
| `synth` | DC reads ordered SystemVerilog sources, elaborates the configured design top, links libraries, applies SDC, and maps the design. | Existing target/link libraries and SDC; project `top`. | Mapped netlist, QoR/area/timing/constraint reports, parseable area/WNS/TNS, no tool errors. | Executable |
| `sta` | PrimeTime checks an explicit gate-level netlist under configured libraries and SDC. | `flows.sta.netlist`, target/link libraries, SDC, project `top`. | QoR, timing and constraint reports; parseable WNS/TNS; no tool errors. | Executable |
| `formality` | Generates a review script only. It requires separate Golden and Revised lists and refuses identical paths or file contents. | `flows.formality.golden` and `flows.formality.revised`. | No execution PASS is currently available. | Planning only |
| `cdc` | Does not substitute SpyGlass lint for CDC analysis. | A reviewed project CDC script and waiver contract are future work. | Execution returns `BLOCKED`. | Planning only |
| `debug`, `lint`, `formal`, `dft`, `atpg`, `mbist`, `lbist`, `apr`, `power`, `starrc` | Legacy command/script generation is retained, but execution is not classified as a verified adapter in this release. MBIST/LBIST/APR/Power/StarRC also contain templates. | Tool/project-specific inputs vary and are not yet validated by the common adapter contract. | `plan` returns `NOT_RUN`; `run --execute` returns `BLOCKED`. | Planning only or template |

## Status rules

- `NOT_RUN` is the result of planning or command generation. It is never a
  verification PASS.
- `BLOCKED` covers missing tools, licenses, required inputs, unsupported
  adapters, empty/missing required artifacts, and missing required metrics.
- `FAIL` covers nonzero tool exits and explicit tool error/fatal messages.
- `ERROR` covers unexpected runtime errors and timeouts.
- A downstream stage runs only after its dependencies pass. Failed tool logs,
  missing reports, and absent simulation pass markers cannot become `PASS`.

## Smoke evidence

The local smoke used an owned arithmetic RTL/testbench fixture under `/tmp`.
VCS `V-2023.12-SP1` compiled and ran it; URG `V-2023.12-SP1` generated the
HTML dashboard. DC `V-2023.12-SP1` synthesized a small sequential design and
PrimeTime `V-2023.12-SP2` analyzed the resulting mapped netlist. DC and
PrimeTime used the read-only Synopsys example library `lsi_10k.db` shipped with
the installed DC distribution. This validates command construction and report
handling only. It is not a target PDK validation, production timing result, or
design/verification signoff.
