import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EDA = ROOT / "skills/eda-tool-engineering/scripts/eda.py"
FLOW = ROOT / "aicflow"
sys.path.insert(0, str(EDA.parent))
from eda_runtime import run_stage


class MilestoneOne(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ("rtl", "tb", "inc", "libs", "constraints", "bin"):
            (self.root / directory).mkdir()
        (self.root / "rtl/top.sv").write_text("module chip_top; endmodule\n")
        (self.root / "tb/tb_top.sv").write_text("module tb_top; initial begin $display(\"TEST PASSED\"); $finish; end endmodule\n")
        (self.root / "rtl.f").write_text("+incdir+inc\n+define+FROM_LIST\nrtl/top.sv\n")
        (self.root / "libs/slow.db").write_text("fake-library")
        (self.root / "constraints/top.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
        (self.root / "eda.yaml").write_text("""name: smoke
top: chip_top
rtl: []
filelists:
  - rtl.f
include_dirs: []
defines: [FROM_CONFIG]
pdk:
  root: libs
  target_library: slow.db
constraints: constraints/top.sdc
flows:
  sim:
    tb: tb/tb_top.sv
    seed: 42
    plusargs: [CASE=basic]
  synth: {tool: dc}
""")
        vcs = self.root / "bin/vcs"
        vcs.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
if '-version' in sys.argv or '-ID' in sys.argv: print('fake vcs 1'); sys.exit(0)
target = Path(sys.argv[sys.argv.index('-o')+1])
target.write_text('#!/bin/sh\\necho TEST PASSED\\n')
target.chmod(0o755)
""")
        vcs.chmod(0o755)
        dc = self.root / "bin/dc_shell"
        dc.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
if '-version' in sys.argv: print('fake dc 1'); sys.exit(0)
script = Path(sys.argv[sys.argv.index('-f')+1])
for name in ('netlist.v','area.rpt','timing.rpt'):
    (script.parent/name).write_text('generated')
(script.parent/'constraints.rpt').write_text('No constraint violations\\n')
(script.parent/'qor.rpt').write_text('Cell Area: 12.5\\nDesign WNS: -0.2\\nDesign TNS: -1.3\\n')
""")
        dc.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / "bin") + os.pathsep + os.environ["PATH"])
        self.env.pop("VCS_HOME", None)
        self.env.pop("DC_HOME", None)
        self.env.pop("PRIME_HOME", None)

    def call(self, script, *args):
        return subprocess.run([sys.executable, str(script), *args], cwd=self.root, env=self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

    def test_config_and_real_stage_contracts(self):
        sim = self.call(EDA, "run", "--flow", "sim", "--execute")
        self.assertEqual(sim.returncode, 0, sim.stderr + sim.stdout)
        result = json.loads(sim.stdout)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual([x["status"] for x in result["stages"]], ["PASS"] * 3)
        compile_command = result["command"][0]
        self.assertIn("+define+FROM_LIST", compile_command)
        self.assertIn("+define+FROM_CONFIG", compile_command)
        self.assertIn("tb_top", compile_command)
        self.assertEqual(result["seed"], 42)
        self.assertTrue(result["inputs"])
        synth = self.call(EDA, "run", "--flow", "synth", "--execute")
        self.assertEqual(synth.returncode, 0, synth.stderr + synth.stdout)
        qor = json.loads(synth.stdout)["qor"]
        self.assertEqual(qor, {"area": 12.5, "wns": -0.2, "tns": -1.3})

    def test_failure_blocks_downstream_and_resume_retries(self):
        vcs = self.root / "bin/vcs"
        vcs.write_text("#!/bin/sh\nexit 7\n")
        fail = self.call(FLOW, "run", "--flow", "rtl_to_sim_synth", "--execute")
        self.assertNotEqual(fail.returncode, 0)
        self.assertTrue(fail.stdout, fail.stderr)
        data = json.loads(fail.stdout)
        self.assertEqual([x["status"] for x in data["stages"]], ["FAIL", "BLOCKED"])
        run_id = data["run_id"]
        vcs.write_text("#!/bin/sh\nif [ \"$1\" = -version ] || [ \"$1\" = -ID ]; then echo fake-vcs-1; exit 0; fi\nwhile [ \"$1\" != -o ]; do shift; done\nshift\nprintf '#!/bin/sh\\necho TEST PASSED\\n' > \"$1\"\nchmod +x \"$1\"\n")
        resumed = self.call(FLOW, "resume", "--run-id", run_id, "--execute")
        self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
        self.assertEqual(json.loads(resumed.stdout)["status"], "PASS")

    def test_missing_dft_reports_block_validation(self):
        result = self.call(EDA, "validate")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "blocked")
        reports = self.root / "reports"
        reports.mkdir()
        (reports / "dft_pre.rpt").write_text("Total violations: 0\n")
        (reports / "dft_post.rpt").write_text("Total violations: 0\n")
        (reports / "dft_qor.rpt").write_text("Design  WNS: -0.1\nDesign  TNS: -2.0\n")
        result = self.call(EDA, "validate")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["qor"]["tns"], -2.0)

    def test_invalid_config_and_cache(self):
        planned = self.call(FLOW, "plan", "--flow", "rtl_to_sim_synth")
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual([x["status"] for x in json.loads(planned.stdout)["stages"]], ["NOT_RUN", "NOT_RUN"])
        first = self.call(FLOW, "run", "--flow", "rtl_to_sim", "--execute")
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        second = self.call(FLOW, "run", "--flow", "rtl_to_sim", "--execute")
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertTrue(json.loads(second.stdout)["stages"][0]["cache_hit"])
        self.root.joinpath("eda.yaml").write_text("name: [broken]\ntop: chip_top\nrtl: []\n")
        bad = self.call(EDA, "doctor")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("BLOCKED", bad.stderr)

    def test_uvm_summary_zero_is_pass_and_error_is_fail(self):
        log = self.root / "simulate.log"
        log.write_text("UVM Report Summary\nUVM_ERROR : 0\nUVM_FATAL : 0\n")
        self.assertEqual(run_stage({"name": "result", "kind": "simulation_result"}, self.root, True)["status"], "PASS")
        log.write_text("UVM Report Summary\nUVM_ERROR : 1\nUVM_FATAL : 0\n")
        self.assertEqual(run_stage({"name": "result", "kind": "simulation_result"}, self.root, True)["status"], "FAIL")
        log.write_text("NOT TEST PASSED\n")
        self.assertEqual(run_stage({"name": "result", "kind": "simulation_result"}, self.root, True)["status"], "BLOCKED")
        log.write_text("TEST PASSED\n")
        self.assertEqual(run_stage({"name": "result", "kind": "simulation_result"}, self.root, True)["status"], "PASS")

    def test_formality_does_not_compare_identical_golden_and_revised_sources(self):
        revised = self.root / "rtl/revised.sv"
        revised.write_text((self.root / "rtl/top.sv").read_text())
        config = self.root / "eda.yaml"
        config.write_text(config.read_text() + "\n  formality:\n    golden: [rtl/top.sv]\n    revised: [rtl/revised.sv]\n")
        result = self.call(EDA, "plan", "--flow", "formality", "--run-id", "formality_identical")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "NOT_RUN")
        script = Path(plan["generated_script"]).read_text()
        self.assertIn("golden and revised source lists are identical", script)
        self.assertNotIn("read_verilog -golden", script)

    def test_vcs_urg_coverage_requires_runtime_db_and_report(self):
        vcs = self.root / "bin/vcs"
        vcs.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
if '-version' in sys.argv or '-ID' in sys.argv: print('fake vcs 1'); sys.exit(0)
target = Path(sys.argv[sys.argv.index('-o')+1])
target.write_text("#!/usr/bin/env python3\\nimport sys\\nfrom pathlib import Path\\nif '-cm_dir' in sys.argv:\\n p=Path(sys.argv[sys.argv.index('-cm_dir')+1]); p.mkdir(parents=True); (p/'data').write_text('vdb')\\nprint('TEST PASSED')\\n")
target.chmod(0o755)
""")
        vcs.chmod(0o755)
        (self.root / "bin/urg").write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
if '-version' in sys.argv: print('fake urg 1'); sys.exit(0)
report = Path(sys.argv[sys.argv.index('-report')+1]); report.mkdir(parents=True)
(report/'dashboard.html').write_text('<html>coverage</html>')
""")
        (self.root / "bin/urg").chmod(0o755)
        config = self.root / "eda.yaml"
        config.write_text(config.read_text().replace("plusargs: [CASE=basic]", "plusargs: [CASE=basic]\n    coverage: line+tgl"))

        result = self.call(EDA, "run", "--flow", "sim", "--execute", "--run-id", "coverage_ok")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["status"], "PASS")
        self.assertEqual([stage["status"] for stage in manifest["stages"]], ["PASS"] * 4)
        self.assertIn("-cm", manifest["command"][0])
        self.assertIn("-cm", manifest["command"][1])
        self.assertEqual(manifest["options"]["coverage"], "line+tgl")
        self.assertTrue(next(x for x in manifest["artifacts"] if x["path"].endswith("dashboard.html"))["sha256"])

        urg = self.root / "bin/urg"
        urg.write_text("#!/bin/sh\nexit 0\n")
        urg.chmod(0o755)
        missing_report = self.call(EDA, "run", "--flow", "sim", "--execute", "--run-id", "coverage_missing")
        self.assertNotEqual(missing_report.returncode, 0)
        self.assertEqual(json.loads(missing_report.stdout)["status"], "BLOCKED")

    def test_standalone_urg_requires_existing_nonempty_vdb(self):
        vdb = self.root / "runs/previous/simv.vdb"
        vdb.mkdir(parents=True)
        (vdb / "coverage.dat").write_text("fixture vdb")
        urg = self.root / "bin/urg"
        urg.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
if '-version' in sys.argv: print('fake urg 1'); sys.exit(0)
report = Path(sys.argv[sys.argv.index('-report')+1]); report.mkdir(parents=True)
(report/'dashboard.html').write_text('report')
""")
        urg.chmod(0o755)
        config = self.root / "eda.yaml"
        config.write_text(config.read_text() + "\n  coverage:\n    vdb: runs/previous/simv.vdb\n")
        result = self.call(EDA, "run", "--flow", "coverage", "--execute", "--run-id", "urg_standalone")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["status"], "PASS")
        self.assertTrue(manifest["input_artifacts"])

        empty = self.root / "runs/previous/empty.vdb"
        empty.mkdir()
        config.write_text(config.read_text().replace("runs/previous/simv.vdb", "runs/previous/empty.vdb"))
        blocked = self.call(EDA, "run", "--flow", "coverage", "--execute", "--run-id", "urg_empty")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertEqual(json.loads(blocked.stdout)["status"], "BLOCKED")

    def test_dry_run_does_not_execute_vcs_and_is_not_pass(self):
        result = self.call(EDA, "run", "--flow", "sim", "--dry-run", "--execute", "--run-id", "sim_dry")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["status"], "NOT_RUN")
        self.assertEqual([stage["status"] for stage in manifest["stages"]], ["NOT_RUN"] * 3)
        self.assertFalse((self.root / "runs/sim_dry/simv").exists())

    def test_sta_uses_explicit_netlist_library_and_constraints(self):
        (self.root / "netlist.v").write_text("module chip_top(input clk); endmodule\n")
        config = self.root / "eda.yaml"
        config.write_text(config.read_text() + "\n  sta:\n    netlist: netlist.v\n")
        pt = self.root / "bin/pt_shell"
        pt.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
if '-version' in sys.argv: print('fake pt 1'); sys.exit(0)
script = Path(sys.argv[sys.argv.index('-f')+1]); out = script.parent
(out/'qor.rpt').write_text('Design WNS: -0.25\\nDesign TNS: -0.75\\n')
(out/'timing.rpt').write_text('timing paths\\n')
(out/'constraints.rpt').write_text('violators\\n')
""")
        pt.chmod(0o755)
        result = self.call(EDA, "run", "--flow", "sta", "--execute", "--run-id", "sta_ok")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["status"], "PASS")
        self.assertEqual(manifest["qor"]["wns"], -0.25)
        self.assertEqual(manifest["qor"]["tns"], -0.75)
        script = (self.root / "runs/sta_ok/sta.tcl").read_text()
        self.assertIn("read_verilog {" + str(self.root / "netlist.v") + "}", script)
        self.assertIn("read_sdc", script)
        self.assertIn("link_design", script)

    def test_missing_artifact_exit_code_license_and_unsupported_adapter(self):
        missing = run_stage({"name": "missing", "command": [sys.executable, "-c", "pass"],
                             "requires": [], "artifact": str(self.root / "absent.rpt")}, self.root, True)
        self.assertEqual(missing["status"], "BLOCKED")
        failed = run_stage({"name": "failed", "command": [sys.executable, "-c", "raise SystemExit(13)"],
                            "requires": []}, self.root, True)
        self.assertEqual(failed["status"], "FAIL")
        self.assertEqual(failed["return_code"], 13)
        license_failure = run_stage({"name": "license", "command": [sys.executable, "-c",
                                    "import sys; print('License checkout failed'); sys.exit(1)"],
                                     "requires": []}, self.root, True)
        self.assertEqual(license_failure["status"], "BLOCKED")

        unsupported = self.call(EDA, "run", "--flow", "cdc", "--execute", "--run-id", "cdc_unsupported")
        self.assertNotEqual(unsupported.returncode, 0)
        data = json.loads(unsupported.stdout)
        self.assertEqual(data["status"], "BLOCKED")
        self.assertEqual(data["support"], "planning_only")


if __name__ == "__main__":
    unittest.main()
