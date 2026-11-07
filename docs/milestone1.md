# Milestone 1 adapter evidence and migration notes

## Delivered executable slice

`eda.py` retains its public `doctor`, `plan`, `run`, `report`, and `validate`
commands. The verified executable adapters are VCS simulation, URG coverage,
Design Compiler synthesis, and PrimeTime STA. `aicflow` remains the separate
project flow planner/checkpoint facade and invokes the `eda.py` stage API; this
change does not add another EDA runner. The scope boundary is recorded in the
[adapter capability matrix](eda-adapter-capabilities.md), and the proposed
shared input/output contract is in the
[unified execution contract](architecture/unified-execution-contract.md).

## Configuration migration

- Set `flows.sim.tb` to the testbench source and, where discovery is ambiguous,
  `flows.sim.top` to the testbench module. The top-level `top` remains the
  design module used by synthesis and STA.
- Set `flows.sim.coverage: true` or a supported `+`-joined coverage type list
  (for example, `line+cond+tgl`) to enable coverage at compile and simulation
  time and then run URG.
- To extract a prior database without rerunning simulation, add
  `flows.coverage.vdb: runs/<run-id>/simv.vdb`. The path must name a nonempty
  existing VDB directory; a list of VDB directories is also accepted.
- DC needs an existing `pdk.target_library`, optional `pdk.link_libraries`,
  and an existing `constraints` SDC. SystemVerilog is analyzed and elaborated
  using the configured design `top`.
- PrimeTime needs an existing mapped netlist in `flows.sta.netlist`, the same
  target/link library contract, and SDC. It will not choose a “latest” netlist
  implicitly.
- Script-generation-only flows remain plannable. Their `run --execute` result
  is now `BLOCKED` until a supported adapter exists. Formality planning needs
  distinct Golden and Revised input lists; identical paths or content are refused. CDC
  planning does not call lint a CDC result.

Existing successful command lines remain valid. `plan` and `--dry-run` return
`NOT_RUN`, while an executed stage can return `PASS`, `FAIL`, `ERROR`, or
`BLOCKED`. A tool exit code of zero alone is not sufficient for PASS. Manifests
include stage commands, return codes, per-stage tool versions, source/config
hashes, logs, and artifact records. License variable contents are never
serialized.

## Automated validation

The Python test suite uses fake executables and fixture artifacts; it does not
claim licensed-tool behavior. Eleven unit tests cover configuration and ordered
filelists, VCS compile/sim/result semantics, URG VDB/report requirements, DC
and STA command/results, DFT WNS/TNS parsing, failure propagation, missing
artifacts, dry runs, unsupported adapters, resume, and cache behavior.

```bash
python3.12 -m unittest discover -s tests -v
```

Result: **31 tests passed** on this host, including 11 EDA adapter tests and
the RTL PPA tests. GitHub Actions runs the same Python-only test suite without
Synopsys licenses.

## Local Synopsys smoke runs

These runs used newly generated arithmetic RTL and testbench files under
`/tmp`; no external project, installed tool, license file, PDK, or evidence
directory was modified.

| Adapter | Result | Tool version | Evidence |
|---|---|---|---|
| VCS compile + simulate + URG | PASS; all four stages and HTML report present | VCS/URG `V-2023.12-SP1` | `/tmp/aicflow-vcs-urg-real-5wwe8bvx/runs/real_vcs_urg_latest/` |
| Standalone URG extraction | PASS; existing VDB read and HTML report generated | URG `V-2023.12-SP1` | `/tmp/aicflow-vcs-urg-real-5wwe8bvx/runs/real_urg_standalone_final2/` |
| DC synthesis | PASS; mapped netlist and required reports parsed | DC `V-2023.12-SP1` | `/tmp/aicflow-dc-pt-real-uyr4c5u_/runs/dc_final/` |
| PrimeTime STA | PASS; required reports and WNS/TNS parsed | PrimeTime `V-2023.12-SP2` | `/tmp/aicflow-dc-pt-real-uyr4c5u_/runs/pt_final/` |

DC and PrimeTime used the read-only Synopsys-installed example library
`lsi_10k.db`, not the target product PDK. The DC report measured area 137.0
reported area units, WNS 2.0 and TNS 0.0 in the report's timing units for the
tiny fixture; PrimeTime reported the same WNS/TNS values. Those numbers are
smoke evidence only. There has been no validation against a target PDK,
production RTL, licensed project collateral, or signoff criteria. No design
or verification signoff is claimed.

## Remaining limitations and next work

- The execution contract remains a design proposal. `eda.py` and `rtl_ppa.py`
  do not yet submit to one canonical stage runtime.
- `aicflow` currently covers the listed simulation/synthesis flows; arbitrary
  start/end stage selection, generic DAG validation, shared cache semantics,
  and cross-interface budget accounting remain backlog items.
- The common report parser registry, timing units/operating-corner contract,
  and versioned report parser provenance remain incomplete. DC/STA parse only
  the current report patterns and block when required metrics are absent.
- Lint, CDC, Formality execution, VC Formal, DFT/ATPG insertion, APR, power,
  and parasitic extraction are not validated executable adapters in this
  increment.
- A project smoke using its approved target libraries, constraints, and source
  set remains necessary before relying on the results for that project.
