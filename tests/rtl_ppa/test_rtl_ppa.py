import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "skills/rtl-ppa-optimization/scripts/rtl_ppa.py"
SPEC = importlib.util.spec_from_file_location("rtl_ppa", SCRIPT)
rtl_ppa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rtl_ppa)


FAKE_ADAPTER = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

stage, run_dir = sys.argv[1:3]
run_dir = Path(run_dir)
campaign = os.environ["RTL_PPA_CAMPAIGN_ID"]
source = Path(os.environ["RTL_PPA_SOURCE_ROOT"]) / "rtl/top.sv"
optimized = "optimized" in source.read_text()
area = float("nan") if campaign == "nonfinite_metric" and stage == "synthesis" else (80.0 if optimized else 100.0)

if campaign == "candidate_fail_formal" and stage == "formal":
    print("fake formal failure")
    sys.exit(9)

run_dir.mkdir(parents=True, exist_ok=True)
if not (campaign == "missing_artifact" and stage == "synthesis"):
    if campaign == "symlink_artifact":
        (run_dir / "evidence-target.txt").write_text("fake evidence\n")
        (run_dir / "evidence.txt").symlink_to(run_dir / "evidence-target.txt")
    else:
        (run_dir / "evidence.txt").write_text("" if campaign == "empty_artifact" else "fake evidence\n")
result = {
    "status": "PASS",
    "adapter_id": "test." + stage + ".v1",
    "adapter_supported": campaign != "unsupported_adapter",
    "tool_versions": {"fake-tool": "v2" if campaign == "candidate_tool_v2" else "v1"},
    "metrics": {"cell_area": area} if stage == "synthesis" else {},
    "metric_provenance": ({"cell_area": {"artifact": "evidence.txt", "parser_id": "fake-area", "parser_version": "2" if campaign == "candidate_parser_v2" else "1"}}
                          if stage == "synthesis" and campaign != "missing_metric_provenance" else {}),
    "artifacts": ["evidence.txt"],
}
(run_dir / "stage-result.json").write_text(json.dumps(result) + "\n")
'''


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def git(project, *args):
    return subprocess.run(["git", "-C", str(project), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "rtl-ppa-tests@example.invalid")
    git(root, "config", "user.name", "RTL PPA Tests")
    write(root / "rtl/top.sv", "module top; // baseline\nendmodule\n")
    write(root / "rtl/unused.sv", "module unused; endmodule\n")
    write(root / "dv/tb.sv", "module tb; endmodule\n")
    write(root / "tools/fake_adapter.py", FAKE_ADAPTER)
    external_assets = tmp_path / "approved-inputs"
    write(external_assets / "slow.db", "mock library revision 1\n")
    write(external_assets / "design.sdc", "create_clock -period 10 [get_ports clk]\n")
    plan = {
        "schema_version": 1,
        "project": "temporary-fixture",
        "design_top": "top",
        "testbench_top": "tb",
        "rtl_scope": ["rtl/*.sv"],
        "rtl_sources": ["rtl/top.sv"],
        "testbench_sources": ["dv/tb.sv"],
        "allowed_patch_paths": ["rtl/*.sv"],
        "behavior_contract": "cycle_equivalent",
        "required_stages": {"baseline": ["synthesis"], "candidate": ["synthesis"]},
        "stages": [
            {
                "id": "synthesis",
                "adapter_id": "test.synthesis.v1",
                "modes": ["baseline", "candidate"],
                "argv": [sys.executable, "tools/fake_adapter.py", "synthesis", "{run_dir}", "{source_root}"],
                "timeout_sec": 10,
                "result_json": "{run_dir}/stage-result.json",
                "expected_artifacts": ["{run_dir}/evidence.txt"],
            },
            {
                "id": "formal",
                "adapter_id": "test.formal.v1",
                "modes": ["candidate"],
                "argv": [sys.executable, "tools/fake_adapter.py", "formal", "{run_dir}", "{source_root}"],
                "timeout_sec": 10,
                "result_json": "{run_dir}/stage-result.json",
                "expected_artifacts": ["{run_dir}/evidence.txt"],
            },
        ],
        "metrics": {
            "cell_area": {"source_stage": "synthesis", "direction": "lower", "unit": "um^2"}
        },
        "read_only_assets": [
            {"source": str(external_assets / "slow.db"), "target": "approved/slow.db"},
            {"source": str(external_assets / "design.sdc"), "target": "approved/design.sdc"},
        ],
        "budget": {"max_candidates": 5, "max_runtime_sec": 30, "max_total_runtime_sec": 120},
    }
    write(root / "rtl-ppa-plan.json", json.dumps(plan, indent=2) + "\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")
    return root


def patch_for(project, changed_path="rtl/top.sv", replacement="module top; // optimized\nendmodule\n"):
    old = (project / changed_path).read_text()
    old_lines = old.splitlines()
    new_lines = replacement.splitlines()
    # The test patches one-line RTL files, keeping the hunk intentionally simple.
    patch_lines = ["diff --git a/" + changed_path + " b/" + changed_path,
                  "--- a/" + changed_path, "+++ b/" + changed_path,
                  "@@ -1," + str(len(old_lines)) + " +1," + str(len(new_lines)) + " @@"]
    patch_lines.extend("-" + line for line in old_lines)
    patch_lines.extend("+" + line for line in new_lines)
    patch = project.parent / ("candidate-" + changed_path.replace("/", "_") + ".diff")
    write(patch, "\n".join(patch_lines) + "\n")
    return patch


def invoke(project, runs, command, *extra):
    args = [sys.executable, str(SCRIPT), command,
            "--project-root", str(project), "--plan", str(project / "rtl-ppa-plan.json"),
            "--runs-root", str(runs)]
    if command == "evaluate":
        args += ["--candidate-id", extra[0], "--patch", str(extra[1]),
                 "--baseline", str(runs / "baseline/baseline.json")]
    args.append("--execute")
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def json_doc(path):
    return json.loads(path.read_text())


def make_baseline(project, runs, seed=0):
    cmd = [sys.executable, str(SCRIPT), "baseline", "--project-root", str(project),
           "--plan", str(project / "rtl-ppa-plan.json"), "--runs-root", str(runs),
           "--seed", str(seed), "--execute"]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    return runs / "baseline/baseline.json"


def test_valid_and_invalid_configuration_and_top_identification(project):
    plan = json_doc(project / "rtl-ppa-plan.json")
    assert rtl_ppa.validate_plan(plan, project) == []
    invalid = json.loads(json.dumps(plan))
    invalid["testbench_top"] = "missing_tb"
    assert any("testbench_top was not found" in error
               for error in rtl_ppa.validate_plan(invalid, project))
    invalid = json.loads(json.dumps(plan))
    invalid["rtl_sources"] = ["rtl/missing.sv"]
    assert any("file is missing" in error for error in rtl_ppa.validate_plan(invalid, project))


def test_yaml_configuration_parser_accepts_and_rejects_yaml(tmp_path):
    valid = tmp_path / "valid.yaml"
    write(valid, "schema_version: 1\nitems:\n  - rtl/top.sv\n")
    assert rtl_ppa.load_yaml(valid) == {"schema_version": 1, "items": ["rtl/top.sv"]}
    invalid = tmp_path / "invalid.yaml"
    write(invalid, "schema_version: [unterminated\n")
    with pytest.raises(rtl_ppa.PlanError, match="invalid YAML"):
        rtl_ppa.load_yaml(invalid)


def test_patch_allowlist_and_uncompiled_path_enforcement(project, tmp_path):
    patch = patch_for(project, "rtl/unused.sv", "module unused; // changed\nendmodule\n")
    assert rtl_ppa.check_patch_paths(patch, ["rtl/*.sv"]) == ["rtl/unused.sv"]
    runs = tmp_path / "runs"
    baseline_path = make_baseline(project, runs)
    result = invoke(project, runs, "evaluate", "uncompiled_path", patch)
    assert result.returncode != 0
    assert "outside ordered rtl_sources" in result.stderr
    assert not (runs / "uncompiled_path/comparison.json").exists()
    assert baseline_path.is_file()


def test_successful_baseline_candidate_and_snapshot_isolation(project, tmp_path):
    original = (project / "rtl/top.sv").read_bytes()
    runs = tmp_path / "runs"
    baseline_path = make_baseline(project, runs)
    patch = patch_for(project)
    result = invoke(project, runs, "evaluate", "area_candidate", patch)
    assert result.returncode == 0, result.stderr + result.stdout
    evidence = json_doc(runs / "area_candidate/evidence.json")
    comparison = json_doc(runs / "area_candidate/comparison.json")
    assert evidence["status"] == "PASS"
    assert comparison["status"] == "PASS"
    assert comparison["decision"] == "ACCEPT"
    assert evidence["seed"] == 0
    stage = evidence["stages"][0]
    assert stage["adapter_id"] == "test.synthesis.v1"
    assert stage["metric_provenance"]["cell_area"]["parser_version"] == "1"
    assert str(project) not in " ".join(stage["command"])
    assert str(runs / "area_candidate/source") in " ".join(stage["command"])
    assert stage["artifact_manifest"]
    assert all(item["sha256"] and item["size_bytes"] > 0
               for item in stage["artifact_manifest"])
    assert (project / "rtl/top.sv").read_bytes() == original
    source_manifest = json_doc(runs / "area_candidate/source_manifest.json")
    assert source_manifest["rtl_sources"] == ["rtl/top.sv"]
    assert source_manifest["testbench_sources"] == ["dv/tb.sv"]
    assert json_doc(baseline_path)["status"] == "PASS"


def test_failed_late_candidate_stage_never_accepts_early_metric(project, tmp_path):
    runs = tmp_path / "runs"
    make_baseline(project, runs)
    result = invoke(project, runs, "evaluate", "candidate_fail_formal", patch_for(project))
    assert result.returncode != 0
    evidence = json_doc(runs / "candidate_fail_formal/evidence.json")
    comparison = json_doc(runs / "candidate_fail_formal/comparison.json")
    assert evidence["status"] == "FAIL"
    assert comparison["decision"] == "BLOCKED"
    assert comparison["status"] == "FAIL"
    assert json_doc(runs / "budget.json")["candidates"] == 1


@pytest.mark.parametrize("candidate_id,expected_status", [
    ("missing_artifact", "BLOCKED"),
    ("empty_artifact", "BLOCKED"),
    ("symlink_artifact", "BLOCKED"),
    ("unsupported_adapter", "BLOCKED"),
    ("missing_metric_provenance", "BLOCKED"),
    ("nonfinite_metric", "ERROR"),
])
def test_missing_artifact_unsupported_adapter_and_exit_code(project, tmp_path,
                                                            candidate_id, expected_status):
    runs = tmp_path / "runs"
    make_baseline(project, runs)
    result = invoke(project, runs, "evaluate", candidate_id, patch_for(project))
    assert result.returncode != 0
    evidence = json_doc(runs / candidate_id / "evidence.json")
    stage = evidence["stages"][0]
    assert stage["status"] == expected_status
    assert json_doc(runs / candidate_id / "comparison.json")["decision"] == "BLOCKED"


def test_nonzero_stage_exit_code_is_propagated(project, tmp_path):
    # Make synthesis fail after the plan is committed by using a tiny wrapper
    # executable whose exit is selected through the campaign ID.
    adapter = project / "tools/fake_adapter.py"
    text = adapter.read_text().replace(
        'if campaign == "candidate_fail_formal" and stage == "formal":',
        'if campaign == "candidate_exit_fail" and stage == "synthesis":\n    sys.exit(17)\n\nif campaign == "candidate_fail_formal" and stage == "formal":')
    write(adapter, text)
    git(project, "add", "tools/fake_adapter.py")
    git(project, "commit", "-qm", "allow stage failure fixture")
    runs = tmp_path / "runs"
    make_baseline(project, runs)
    result = invoke(project, runs, "evaluate", "candidate_exit_fail", patch_for(project))
    assert result.returncode != 0
    evidence = json_doc(runs / "candidate_exit_fail/evidence.json")
    assert evidence["status"] == "FAIL"
    assert evidence["stages"][0]["return_code"] == 17


def test_dry_run_is_not_run_and_does_not_create_evidence(project, tmp_path):
    runs = tmp_path / "runs"
    cmd = [sys.executable, str(SCRIPT), "baseline", "--project-root", str(project),
           "--plan", str(project / "rtl-ppa-plan.json"), "--runs-root", str(runs)]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "NOT_RUN"
    assert not runs.exists()


@pytest.mark.parametrize("seed,campaign_id,expected", [
    (8, "seed_mismatch", "seed"),
    (7, "candidate_tool_v2", "tool versions"),
    (7, "candidate_parser_v2", "metric parser provenance"),
])
def test_incompatible_seed_or_tool_provenance_blocks_comparison(project, tmp_path,
                                                                seed, campaign_id, expected):
    runs = tmp_path / "runs"
    make_baseline(project, runs, seed=7)
    patch = patch_for(project)
    cmd = [sys.executable, str(SCRIPT), "evaluate", "--project-root", str(project),
           "--plan", str(project / "rtl-ppa-plan.json"), "--runs-root", str(runs),
           "--seed", str(seed), "--candidate-id", campaign_id,
           "--patch", str(patch), "--baseline", str(runs / "baseline/baseline.json"), "--execute"]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    evidence = json_doc(runs / campaign_id / "evidence.json")
    comparison = json_doc(runs / campaign_id / "comparison.json")
    assert result.returncode != 0
    assert evidence["status"] == "BLOCKED"
    assert expected in evidence["reason"]
    assert comparison["decision"] != "ACCEPT"


def test_changed_library_or_constraint_asset_blocks_comparison(project, tmp_path):
    runs = tmp_path / "runs"
    make_baseline(project, runs)
    plan = json_doc(project / "rtl-ppa-plan.json")
    for asset in plan["read_only_assets"]:
        source = Path(asset["source"])
        source.write_text(source.read_text() + "changed after baseline\n")
    result = invoke(project, runs, "evaluate", "changed_assets", patch_for(project))
    assert result.returncode != 0
    evidence = json_doc(runs / "changed_assets/evidence.json")
    comparison = json_doc(runs / "changed_assets/comparison.json")
    assert evidence["status"] == "BLOCKED"
    assert "asset hashes" in evidence["reason"]
    assert comparison["decision"] == "BLOCKED"


def test_fractional_and_cumulative_budget_accounting(project, tmp_path):
    assert rtl_ppa.remaining_runtime(5.0, 8.0, 0.25, 7.5) == pytest.approx(0.25)
    assert rtl_ppa.remaining_runtime(2.0, 8.0, 0.25, 1.0) == pytest.approx(1.75)
    runs = tmp_path / "runs"
    make_baseline(project, runs)
    baseline = json_doc(runs / "baseline/baseline.json")
    ledger = json_doc(runs / "budget.json")
    assert 0 < baseline["elapsed_sec"] < 1
    assert 0 < ledger["runtime_sec"] < 1
    assert ledger["runtime_sec"] >= baseline["elapsed_sec"]
    assert ledger["runtime_sec"] - baseline["elapsed_sec"] < 0.1


def test_cumulative_budget_exhaustion_blocks_new_campaign(project, tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    plan_hash = rtl_ppa.sha256(project / "rtl-ppa-plan.json")
    (runs / "budget.json").write_text(json.dumps({
        "plan_sha256": plan_hash, "candidates": 2, "runtime_sec": 120.0,
    }))
    cmd = [sys.executable, str(SCRIPT), "baseline", "--project-root", str(project),
           "--plan", str(project / "rtl-ppa-plan.json"), "--runs-root", str(runs), "--execute"]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert result.returncode != 0
    assert "cumulative runtime budget exhausted" in result.stderr
    assert not (runs / "baseline").exists()
    assert json_doc(runs / "budget.json")["runtime_sec"] == 120.0


def test_interrupted_campaign_reservation_is_charged(project, tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    plan_hash = rtl_ppa.sha256(project / "rtl-ppa-plan.json")
    (runs / "budget.json").write_text(json.dumps({
        "plan_sha256": plan_hash, "candidates": 1, "runtime_sec": 0.2,
        "active_campaign": "interrupted", "active_runtime_reservation_sec": 0.4,
    }))
    cmd = [sys.executable, str(SCRIPT), "baseline", "--project-root", str(project),
           "--plan", str(project / "rtl-ppa-plan.json"), "--runs-root", str(runs), "--execute"]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    ledger = json_doc(runs / "budget.json")
    assert ledger["runtime_sec"] >= 0.6
    assert ledger["interrupted_campaigns"] == 1
    assert "active_campaign" not in ledger
