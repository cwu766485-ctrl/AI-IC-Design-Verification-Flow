import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "skills/verification-closure/scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import verification_closure as vc


def plan():
    return {
        "closure": {"pass_patterns": [r"UVM_ERROR\s*:\s*0"], "fail_patterns": [r"UVM_FATAL\s*:\s*[1-9]"],
                    "budgets": {"max_campaigns": 1, "max_seeds": 2, "max_runtime_sec": 100,
                                "max_new_tests": 1},
                    "regression_commands": [{"name": "dma", "expected_tests": ["dma_error_test"]}]},
        "features": [{"id": "DMA-F-ERR", "testpoints": [{
            "id": "DMA-TP-ERR", "tests": ["dma_error_test"],
            "checker": {"id": "DMA-CK-ERR"},
            "coverage": [{"group": "dma_error_scenario_cg", "point": "error_kind",
                          "bins": ["read_slverr"]}],
        }]}],
    }


def evidence():
    return {"status": "PASS", "runs": [{"test": "*", "command_name": "dma", "status": "PASS",
                                               "return_code": 0, "log": None}],
            "checkers": {}, "coverage_bins": {}, "coverage_groups": []}


def test_uvm_pass_alone_does_not_close_checker_or_coverage_gaps():
    result = vc.analyzer(plan(), evidence(), evidence())
    assert result["status"] == "OPEN"
    classes = [finding["classification"] for finding in result["findings"]]
    assert "missing_checker_evidence" in classes
    assert "missing_coverage_model" in classes


def test_existing_coverage_group_with_missing_bin_is_not_a_missing_model():
    coverage = {"coverage_bins": {}, "coverage_groups": ["dma_error_scenario_cg"]}
    result = vc.analyzer(plan(), evidence(), coverage)
    assert [x["classification"] for x in result["findings"]] == [
        "missing_checker_evidence", "unmeasured_coverage"]


def test_checkpoint_reused_pass_without_process_code_is_not_a_run_failure():
    run = evidence()
    run["runs"][0]["return_code"] = None
    result = vc.analyzer(plan(), run, run)
    assert result["status"] == "OPEN"
    assert "run_failure" not in [finding["classification"] for finding in result["findings"]]
    assert "missing_checker_evidence" in [finding["classification"] for finding in result["findings"]]


def test_source_hashes_recompute_normalized_plan_source_paths(tmp_path):
    source = tmp_path / "rtl/dma.sv"
    source.parent.mkdir()
    include = tmp_path / "rtl/dma_checks.svh"
    include.write_text("`define DMA_CHECK 1\n")
    source.write_text('`include "dma_checks.svh"\nmodule dma; endmodule\n')
    hashes = vc.source_hashes({"source_hashes": {
        "<NMAForge-snapshot>/rtl/dma.sv": "stale-embedded-hash"}}, tmp_path)
    assert str(source) in hashes
    assert str(include) in hashes
    assert hashes[str(source)] == vc.digest(source)
    assert hashes[str(include)] == vc.digest(include)


def test_recommendation_is_reviewable_and_keeps_remaining_budget(capsys, tmp_path):
    plan_file = tmp_path / "plan.json"
    analysis_file = tmp_path / "analysis.json"
    plan_file.write_text(json.dumps(plan()))
    analysis_file.write_text(json.dumps({"status": "OPEN", "findings": [
        {"feature_id": "DMA-F-ERR", "testpoint_id": "DMA-TP-ERR",
         "classification": "missing_coverage_model", "detail": "group absent"}]}))
    args = SimpleNamespace(plan=str(plan_file), analysis=str(analysis_file),
                           remaining_budget={"campaigns": 1, "seeds": 1, "runtime_sec": 50, "new_tests": 0},
                           out=None)
    assert vc.recommend_command(args) == 0
    decision = json.loads(capsys.readouterr().out)["decisions"][0]
    assert decision["action"] == "ADD_COVERAGE"
    assert decision["feature_id"] == "DMA-F-ERR"
    assert decision["testpoint_id"] == "DMA-TP-ERR"
    assert decision["remaining_budget"]["runtime_sec"] == 50
    assert "observed DUT response/status" in decision["proposed_change"]


def test_recommendation_stops_when_every_budget_dimension_is_empty(capsys, tmp_path):
    plan_file = tmp_path / "plan.json"
    analysis_file = tmp_path / "analysis.json"
    plan_file.write_text(json.dumps(plan()))
    analysis_file.write_text(json.dumps({"status": "OPEN", "findings": []}))
    args = SimpleNamespace(plan=str(plan_file), analysis=str(analysis_file),
                           remaining_budget={"campaigns": 0, "seeds": 0, "runtime_sec": 0, "new_tests": 0},
                           out=None)
    vc.recommend_command(args)
    assert json.loads(capsys.readouterr().out)["decisions"][0]["action"] == "STOP"
