# Project EDA contract

`eda.yaml` belongs in each project's root, for example:
`/path/to/project/tsmc28_dft_smoke/eda.yaml`.

```yaml
name: tsmc28_smoke
top: tsmc28_smoke
rtl:
  - rtl/tsmc28_smoke.v
filelists: []
include_dirs: []
defines: []
pdk:
  root: /path/to/pdk/TSMC28
  target_library: path/to/slow.db
constraints: constraints/tsmc28.sdc
flows:
  sim:
    simulator: vcs
    tb: sim/tb.sv
    top: tb_chip
    coverage: line+cond+tgl
    functional_coverage: false
    debug: false
    tests:
      - {name: smoke, test_name: smoke_test, seed: 42, plusargs: []}
  synth: { tool: dc, script: run_dc.tcl }
dft:
  enabled: true
  scan: { chains: 1, compression: false }
  mbist: { enabled: false, controller: vendor_ip }
  lbist: { enabled: false, controller: vendor_ip }
  atpg: { faults: [stuck_at, transition], tool: tmax }
# Optional DFT adapter overrides (paths are relative to project root):
# scan_netlist: netlist/chip_scan.v
# test_protocol: dft/chip.spf
# library_verilog: /path/to/standard_cell.v
```

The parser uses PyYAML when installed, or Ruby's standard YAML parser. It validates required types and paths, resolves filelists and RTL patterns in declared order, and rejects missing sources. Keep secrets (license tokens, passwords) out of this file. The API passes only declared paths and options to adapters.

For executable VCS/DC stages, use the following fields:

```yaml
name: chip
top: chip_top
rtl: [rtl/chip_top.sv]
filelists: [sim/rtl.f]
include_dirs: [rtl/include]
defines: [SYNTHESIS]
pdk:
  root: /installed/pdk
  target_library: lib/slow.db
  link_libraries: [lib/memory.db]
constraints: constraints/chip.sdc
flows:
  sim:
    tb: sim/tb_chip.sv
    top: tb_chip
    test_name: smoke_test
    seed: 42
    plusargs: [CASE=smoke]
    coverage: line+cond+tgl
    functional_coverage: true
    debug: true
    tests:
      - {name: seed_11, test_name: smoke_test, seed: 11, plusargs: [CASE=smoke]}
      - {name: seed_23, test_name: smoke_test, seed: 23, plusargs: [CASE=smoke]}
    timeout_sec: 600
  synth: {tool: dc}
  sta:
    netlist: runs/synthesis/netlist.v
    sdc: constraints/chip.sdc
  coverage:
    vdb: runs/regression/simv.vdb
    functional: true
runner:
  kind: local
# Or, for a clean, matching remote checkout on an authorized SSH host:
# runner:
#   kind: ssh
#   host: approved-eda-runner
#   project_root: /work/chip
#   python: python3
```

`flows.sim.top` is the testbench top and is distinct from the design `top`; it is optional only when the TB module can be discovered. `coverage: true` or a value such as `line+cond+tgl` requests VCS compile and runtime instrumentation followed by URG. Standalone `flows.coverage.vdb` accepts one VDB directory or a nonempty list of VDB directories. DC requires an existing target library and SDC. PrimeTime requires an existing mapped netlist, target library, and SDC. A successful process exit without expected artifacts or QoR metrics is `BLOCKED`. A simulation must print `TEST PASSED` or a UVM summary with zero errors and fatals to receive `PASS`.

`flows.sim.tests` is an ordered list of unique safe names with optional
`test_name`, nonnegative `seed`, and string `plusargs`. `regression` compiles
once, runs each entry in a separate stage/database, and reports a failed test
without running dependent coverage stages. If `functional_coverage` is true,
URG must produce a parseable group summary with at least one covergroup.
VCS `debug: true` retains KDB/debug artifacts and a Verdi launch script; it
does not execute the GUI. `flows.synth.activity_file` requires an explicit
`activity_instance`; without SAIF, tool-default activity estimates are marked
as estimates and cannot be treated as power signoff. Missing or unparseable
power values remain null.

The SSH runner is opt-in and requires explicit `--execute`, an authorized SSH
alias, a clean local tree, and a remote checkout with matching commit and
configuration hashes. It copies the completed run directory back and never
falls back to local execution.

Every run creates `runs/<id>/manifest.json` with `PASS`, `FAIL`, `ERROR`, `BLOCKED`, `NOT_RUN`, or `SKIPPED`, tool return code, per-stage tool versions, commands, relevant input hashes, Git SHA and working tree, seed/test, logs, and artifact records. License variable values are not stored. `doctor` reports tool presence and configuration validity; it does not perform a license checkout.

DFT terminology: `dft` is the orchestration contract; `scan` describes insertion; `mbist` and `lbist` describe controller/IP integration and test modes; `atpg` describes TestMAX pattern generation. A configured MBIST/LBIST block is not evidence of implementation until reports and a post-DFT netlist exist.
