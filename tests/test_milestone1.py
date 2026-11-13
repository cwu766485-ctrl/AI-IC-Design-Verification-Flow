import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EDA = ROOT / "skills/eda-tool-engineering/scripts/eda.py"
FLOW = ROOT / "aicflow"
sys.path.insert(0, str(EDA.parent))
from eda_runtime import _urg_metrics, parse_power, run_stage
from eda_config import load
import eda_runner
import flow_engine


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
for name in ('netlist.v','area.rpt','timing.rpt','check_design.rpt'):
    (script.parent/name).write_text('generated')
(script.parent/'constraints.rpt').write_text('No constraint violations\\n')
(script.parent/'power.rpt').write_text('Total Dynamic Power: 1.5 mW\\nCell Leakage Power: 0.25 mW\\n')
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
        self.assertEqual(json.loads(synth.stdout)["power"]["total_dynamic_power"], 1.5)

    def test_failure_blocks_downstream_and_resume_retries(self):
        vcs = self.root / "bin/vcs"
        vcs.write_text("#!/bin/sh\nexit 7\n")
        fail = self.call(FLOW, "run", "--flow", "rtl_to_sim_synth", "--execute")
        self.assertNotEqual(fail.returncode, 0)
        self.assertTrue(fail.stdout, fail.stderr)
        data = json.loads(fail.stdout)
        by_id = {x["id"]: x for x in data["stages"]}
        self.assertEqual(by_id["vcs_compile"]["status"], "FAIL")
        self.assertEqual(by_id["dc_synthesis"]["status"], "PASS")
        self.assertEqual(by_id["vcs_simulate_default"]["status"], "SKIPPED")
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
        planned_stages = json.loads(planned.stdout)["stages"]
        self.assertTrue(all(x["status"] == "NOT_RUN" for x in planned_stages))
        self.assertIn("dc_synthesis", [x["id"] for x in planned_stages])
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
(report/'dashboard.txt').write_text('Total Coverage Summary\\nSCORE LINE COND TOGGLE FSM BRANCH GROUP\\n85.0 85.0 -- -- -- -- --\\n\\nTotal Module Definition Coverage Summary\\nSCORE LINE COND TOGGLE FSM BRANCH\\n85.0 85.0 -- -- -- --\\n')
""")
        (self.root / "bin/urg").chmod(0o755)
        config = self.root / "eda.yaml"
        config.write_text(config.read_text().replace("plusargs: [CASE=basic]", "plusargs: [CASE=basic]\n    coverage: line+tgl"))

        result = self.call(EDA, "run", "--flow", "sim", "--execute", "--run-id", "coverage_ok")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["status"], "PASS")
        self.assertEqual([stage["status"] for stage in manifest["stages"]], ["PASS"] * 5)
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

        urg.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
if '-version' in sys.argv: print('fake urg 1'); sys.exit(0)
report = Path(sys.argv[sys.argv.index('-report')+1]); report.mkdir(parents=True)
(report/'dashboard.html').write_text('present')
(report/'dashboard.txt').write_text('unrecognized report format')
""")
        urg.chmod(0o755)
        unparseable = self.call(EDA, "run", "--flow", "sim", "--execute", "--run-id", "coverage_unparseable")
        self.assertNotEqual(unparseable.returncode, 0)
        result = json.loads(unparseable.stdout)
        summary = next(stage for stage in result["stages"] if stage["name"] == "coverage_summary")
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary.get("error_class"), "REPORT_INCOMPLETE", result)

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
(report/'dashboard.txt').write_text('Total Coverage Summary\\nSCORE LINE COND TOGGLE FSM BRANCH GROUP\\n100.0 100.0 -- -- -- -- --\\n\\nTotal Module Definition Coverage Summary\\nSCORE LINE COND TOGGLE FSM BRANCH\\n100.0 100.0 -- -- -- --\\n')
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

    def test_urg_parser_separates_code_and_functional_coverage(self):
        report = self.root / "coverage-report"
        report.mkdir()
        (report / "dashboard.txt").write_text("""Total Coverage Summary
SCORE LINE COND TOGGLE FSM BRANCH GROUP
85.11 94.74 -- 85.71 -- 60.00 100.00

Total Module Definition Coverage Summary
SCORE LINE COND TOGGLE FSM BRANCH
80.15 94.74 -- 85.71 -- 60.00

Total Groups Coverage Summary
SCORE WEIGHT
100.00 1
""")
        (report / "grpinfo.txt").write_text("Group : tb_top::count_cg\n")
        metrics = _urg_metrics(report, functional=True)
        self.assertEqual(metrics["code_coverage_percent"], 80.15)
        self.assertEqual(metrics["code_coverage_by_type_percent"]["line"], 94.74)
        self.assertEqual(metrics["functional_coverage_percent"], 100.0)
        self.assertEqual(metrics["functional_group_count"], 1)
        (report / "grpinfo.txt").write_text("")
        self.assertEqual(_urg_metrics(report, functional=True)["functional_group_count"], 0)

    def test_urg_parser_reads_html_only_reports(self):
        report = self.root / "coverage-html-report"
        report.mkdir()
        (report / "dashboard.html").write_text("""<b>Total Module Definition Coverage Summary</b>
<table><tr><td>SCORE</td><td>LINE</td></tr><tr><td>54.32</td><td>51.13</td></tr></table>
<b>Total Groups Coverage Summary</b><table><tr><td>SCORE</td></tr><tr><td>100.00</td></tr></table>""")
        (report / "grp0.html").write_text("<html><title>Group :: tb_top::dma_error_scenario_cg</title></html>")
        metrics = _urg_metrics(report, functional=True)
        self.assertEqual(metrics["parser"], "urg-html-v1")
        self.assertEqual(metrics["code_coverage_percent"], 54.32)
        self.assertEqual(metrics["functional_coverage_percent"], 100.0)
        self.assertEqual(metrics["functional_group_count"], 1)

    def test_power_parser_keeps_missing_total_unset_and_marks_partial(self):
        report = self.root / "power.rpt"
        report.write_text("""Dynamic Power Units = 100nW
Leakage Power Units = Unitless
Total Dynamic Power = 4.2 nW
Cell Leakage Power = 0.0
Error: incomplete characterization
""")
        metrics = parse_power(report)
        self.assertEqual(metrics["total_dynamic_power"], 4.2)
        self.assertEqual(metrics["cell_leakage_power"], 0.0)
        self.assertIsNone(metrics["total_power"])
        self.assertEqual(metrics["status"], "PARTIAL")
        self.assertTrue(metrics["report_errors"])

    def test_dry_run_does_not_execute_vcs_and_is_not_pass(self):
        result = self.call(EDA, "run", "--flow", "sim", "--dry-run", "--execute", "--run-id", "sim_dry")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["status"], "NOT_RUN")
        self.assertEqual([stage["status"] for stage in manifest["stages"]], ["NOT_RUN"] * 3)
        self.assertFalse((self.root / "runs/sim_dry/simv").exists())

    def test_regression_plan_preserves_per_test_seed_coverage_and_debug_inputs(self):
        config = self.root / "eda.yaml"
        text = config.read_text().replace(
            "    plusargs: [CASE=basic]",
            """    plusargs: [CASE=basic]
    coverage: line+tgl
    functional_coverage: true
    debug: true
    tests:
      - {name: low_seed, seed: 11, plusargs: [MODE=low]}
      - {name: high_seed, seed: 99, plusargs: [MODE=high]}""")
        config.write_text(text)
        result = self.call(EDA, "plan", "--flow", "regression", "--run-id", "regression_plan")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["status"], "NOT_RUN")
        stages = manifest["stages"]
        compile_args = stages[0]["command"]
        self.assertIn("-top", compile_args)
        self.assertEqual(compile_args[compile_args.index("-top") + 1], "tb_top")
        self.assertIn("-kdb", compile_args)
        self.assertEqual(compile_args[compile_args.index("-cm") + 1], "line+tgl")
        sim_low = next(stage for stage in stages if stage["name"] == "simulate_low_seed")
        sim_high = next(stage for stage in stages if stage["name"] == "simulate_high_seed")
        self.assertIn("+ntb_random_seed=11", sim_low["command"])
        self.assertIn("+ntb_random_seed=99", sim_high["command"])
        self.assertNotEqual(sim_low["command"][sim_low["command"].index("-cm_dir") + 1],
                            sim_high["command"][sim_high["command"].index("-cm_dir") + 1])
        self.assertEqual(next(x for x in stages if x["name"] == "coverage_summary")["status"], "NOT_RUN")
        self.assertEqual(next(x for x in stages if x["name"] == "debug_artifacts")["status"], "NOT_RUN")

    def test_aicflow_is_eda_py_compatibility_alias(self):
        result = self.call(FLOW, "plan", "--flow", "rtl_to_regression", "--run-id", "alias_plan")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "NOT_RUN")
        self.assertEqual([stage["id"] for stage in plan["stages"]],
                         ["vcs_compile", "vcs_simulate_default", "simulation_result_default"])

    def test_ssh_runner_forwards_dag_slice_and_budgets_without_local_fallback(self):
        config = self.root / "eda.yaml"
        config.write_text(config.read_text() + "\nrunner:\n  kind: ssh\n  host: approved-runner\n  project_root: /work/chip\n  python: python3\n")
        cfg = load(config)
        (self.root / ".gitignore").write_text("runs/\n")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "remote runner fixture"], cwd=self.root, check=True)
        local_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True).strip()
        original_run = subprocess.run
        ssh_commands = []

        def fake_ssh(host, timeout, remote_command):
            ssh_commands.append(remote_command)
            if "EDA_REMOTE_EXECUTION=1" in remote_command:
                return SimpleNamespace(returncode=0, stdout='{"status":"PASS","run_id":"remote_slice"}\n', stderr="")
            response = {"sha": local_sha, "dirty": False,
                        "config_sha256": eda_runner._sha256(config)}
            return SimpleNamespace(returncode=0, stdout=json.dumps(response) + "\n", stderr="")

        def fake_subprocess_run(argv, **kwargs):
            if argv[0] == "fake-scp":
                destination = Path(argv[-1])
                destination.mkdir(parents=True, exist_ok=True)
                (destination / "manifest.json").write_text(json.dumps({"status": "PASS", "run_id": "remote_slice"}))
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return original_run(argv, **kwargs)

        run_dir = self.root / "runs/remote_slice"
        with patch.object(eda_runner, "_ssh", side_effect=fake_ssh), \
                patch.object(eda_runner.shutil, "which", return_value="fake-scp"), \
                patch.object(eda_runner.subprocess, "run", side_effect=fake_subprocess_run):
            result = eda_runner.execute_remote(self.root, cfg,
                                               "rtl_to_sim_synth", "remote_slice", run_dir,
                                               start="vcs_compile", end="dc_synthesis", budget_seconds=600)
            first_remote = ssh_commands[-1]
            resumed = eda_runner.execute_remote(self.root, cfg, "rtl_to_sim_synth", "remote_slice", run_dir,
                                                command="resume", start="pt_sta", end="pt_sta",
                                                budget_seconds=300)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["runner"]["kind"], "ssh")
        self.assertEqual(result["runner"]["remote_return_code"], 0)
        self.assertTrue((run_dir / "remote-run.log").is_file())
        self.assertIn("--from vcs_compile", first_remote)
        self.assertIn("--to dc_synthesis", first_remote)
        self.assertIn("--budget-seconds 600", first_remote)
        self.assertEqual(resumed["status"], "PASS")
        self.assertIn("eda.py resume", ssh_commands[-1])
        self.assertIn("--from pt_sta", ssh_commands[-1])
        self.assertIn("--budget-seconds 300", ssh_commands[-1])

    def test_composite_flow_routes_ssh_execution_without_local_fallback(self):
        config = self.root / "eda.yaml"
        config.write_text(config.read_text() + "\nrunner:\n  kind: ssh\n  host: approved-runner\n  project_root: /work/chip\n")
        previous_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.dict(os.environ, {"EDA_REMOTE_EXECUTION": ""}), \
                    patch.object(flow_engine, "execute_remote",
                                 return_value={"status": "PASS", "run_id": "ssh-run"}) as remote:
                rc = flow_engine.main(["run", "--flow", "rtl_to_sim_synth", "--from", "vcs_compile",
                                       "--to", "dc_synthesis", "--execute", "--run-id", "ssh-run",
                                       "--budget-seconds", "60"])
        finally:
            os.chdir(previous_cwd)
        self.assertEqual(rc, 0)
        self.assertEqual(remote.call_args.args[2:4], ("rtl_to_sim_synth", "ssh-run"))
        self.assertEqual(remote.call_args.kwargs["start"], "vcs_compile")
        self.assertEqual(remote.call_args.kwargs["end"], "dc_synthesis")
        self.assertEqual(remote.call_args.kwargs["budget_seconds"], 60)
        self.assertFalse((self.root / "runs/ssh-run").exists())

    def test_missing_project_config_is_not_silently_initialized(self):
        config = self.root / "eda.yaml"
        config.unlink()
        result = self.call(EDA, "doctor")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("eda.yaml is missing", result.stderr)
        self.assertFalse(config.exists())

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

    def test_dc_to_pt_uses_shared_dag_and_verified_cache(self):
        config = self.root / "eda.yaml"
        config.write_text(config.read_text() + "\n  sta: {tool: pt}\n")
        pt = self.root / "bin/pt_shell"
        pt.write_text("""#!/usr/bin/env python3
import sys
from pathlib import Path
if '-version' in sys.argv: print('fake pt 1'); sys.exit(0)
script = Path(sys.argv[sys.argv.index('-f')+1]); out = script.parent
(out/'qor.rpt').write_text('Design WNS: -0.1\\nDesign TNS: -0.2\\n')
(out/'timing.rpt').write_text('timing paths\\n')
(out/'constraints.rpt').write_text('No constraint violations\\n')
""")
        pt.chmod(0o755)
        planned = self.call(FLOW, "plan", "--flow", "rtl_to_synth_sta",
                            "--from", "dc_synthesis", "--to", "pt_sta")
        self.assertEqual(planned.returncode, 0, planned.stderr + planned.stdout)
        run = self.call(FLOW, "run", "--flow", "rtl_to_synth_sta", "--execute")
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        result = json.loads(run.stdout)
        stages = {item["id"]: item for item in result["stages"]}
        self.assertEqual(stages["dc_synthesis"]["status"], "PASS")
        self.assertEqual(stages["pt_sta"]["status"], "PASS")
        self.assertEqual(stages["pt_sta"]["dependencies"], ["dc_synthesis"])
        partial = self.call(FLOW, "run", "--flow", "rtl_to_synth_sta", "--from", "pt_sta",
                            "--to", "pt_sta", "--execute")
        self.assertEqual(partial.returncode, 0, partial.stderr + partial.stdout)
        self.assertEqual(json.loads(partial.stdout)["efficiency"]["cache_hits"], 2)

    def test_missing_artifact_exit_code_license_and_unsupported_adapter(self):
        missing = run_stage({"name": "missing", "command": [sys.executable, "-c", "pass"],
                             "requires": [], "artifact": str(self.root / "absent.rpt")}, self.root, True)
        self.assertEqual(missing["status"], "BLOCKED")
        failed = run_stage({"name": "failed", "command": [sys.executable, "-c", "raise SystemExit(13)"],
                            "requires": []}, self.root, True)
        self.assertEqual(failed["status"], "FAIL")
        self.assertEqual(failed["return_code"], 13)
        tool_error = run_stage({"name": "tool_error", "command": [sys.executable, "-c",
                                  "print('Error: internal tool failure')"], "requires": []}, self.root, True)
        self.assertEqual(tool_error["status"], "ERROR")
        self.assertEqual(tool_error["error_class"], "TOOL_REPORTED_ERROR")
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
