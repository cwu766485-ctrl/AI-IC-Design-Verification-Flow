import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "skills/rtl-ppa-optimization/scripts/autonomous_optimizer.py"
SPEC = importlib.util.spec_from_file_location("autonomous_optimizer", SCRIPT)
optimizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(optimizer)


def valid_baseline():
    provenance = {"artifact": "synthesis.rpt", "parser_id": "dc-area", "parser_version": "1"}
    return {
        "status": "PASS", "source_revision": "abc123",
        "stages": [{"stage": "regression", "status": "PASS"},
                   {"stage": "synthesis", "status": "PASS",
                    "metric_provenance": {"cell_area": provenance}},
                   {"stage": "sta", "status": "PASS",
                    "metric_provenance": {"setup_wns": {
                        "artifact": "timing.rpt", "parser_id": "pt-wns", "parser_version": "1"}}}],
    }


def valid_proposal():
    return {
        "feature_id": "MATRIX-AREA-001",
        "hypothesis": "Reduce replicated decode logic on the identified hotspot.",
        "target_hotspot": "area-decode-0",
        "intended_rtl_modification": "Share the existing address decode expression.",
        "expected_ppa_improvement": {"cell_area": {"direction": "lower", "target_pct": 5}},
        "functional_risks": ["Decode aliasing could change bank selection."],
        "timing_risks": ["Shared decode fanout could worsen setup timing."],
        "required_validation_stages": ["regression", "formal", "synthesis", "sta", "performance"],
        "validation_commands": {
            "regression": ["make", "core-random-regress"],
            "formal": ["make", "fsm-guards"],
            "synthesis": ["dc_shell", "-f", "synthesis.tcl"],
            "sta": ["pt_shell", "-f", "sta.tcl"],
            "performance": ["make", "matrix-pipeline-benchmark"],
        },
    }


def valid_patch(tmp_path, path="rtl/compute/matrix/core.v"):
    patch = tmp_path / "candidate.diff"
    patch.write_text("diff --git a/{0} b/{0}\n--- a/{0}\n+++ b/{0}\n@@ -1 +1 @@\n-a\n+b\n".format(path))
    return patch


def test_qor_analyzer_requires_all_gates_and_hotspot_evidence():
    analyzer = optimizer.QoRAnalyzer()
    incomplete = analyzer.analyze(valid_baseline(), {"metrics": {"cell_area": 100, "setup_wns": 0.1}},
                                  {"cell_area": "synthesis", "setup_wns": "sta"},
                                  ["regression", "synthesis", "sta"])
    assert not incomplete["baseline_valid"]
    assert "structured critical-path evidence is unavailable" in incomplete["blockers"]
    assert "structured area-hotspot evidence is unavailable" in incomplete["blockers"]


def test_qor_analyzer_accepts_provenanced_metrics_and_structured_hotspots():
    result = optimizer.QoRAnalyzer().analyze(
        valid_baseline(), {"metrics": {"cell_area": 100, "setup_wns": 0.1}},
        {"cell_area": "synthesis", "setup_wns": "sta"}, ["regression", "synthesis", "sta"],
        {"critical_paths": [{"id": "path-0", "artifact": "timing.rpt", "sha256": "a" * 64}],
         "area_hotspots": [{"id": "area-decode-0", "artifact": "area.rpt", "sha256": "b" * 64}]})
    assert result["baseline_valid"]
    assert result["metrics"] == {"cell_area": 100, "setup_wns": 0.1}


def test_candidate_generator_binds_patch_hash_and_approved_scope(tmp_path):
    patch = valid_patch(tmp_path)
    candidate = optimizer.CandidateGenerator().generate(
        valid_proposal(), "abc123", patch, ["rtl/compute/matrix/*.v"],
        [{"id": "area-decode-0"}])
    assert candidate["source_revision"] == "abc123"
    assert candidate["changed_paths"] == ["rtl/compute/matrix/core.v"]
    assert len(candidate["patch_sha256"]) == 64


def test_candidate_generator_rejects_scope_and_unknown_hotspot(tmp_path):
    generator = optimizer.CandidateGenerator()
    with pytest.raises(optimizer.OptimizationInputError, match="exceeds approved scope"):
        generator.generate(valid_proposal(), "abc123", valid_patch(tmp_path), ["rtl/top/*.v"],
                           [{"id": "area-decode-0"}])
    with pytest.raises(optimizer.OptimizationInputError, match="not present in QoR"):
        generator.generate(valid_proposal(), "abc123", valid_patch(tmp_path), ["rtl/**/*.v"], [])
    proposal = valid_proposal()
    proposal["expected_ppa_improvement"] = {"cell_area": {"direction": "lower", "target_pct": float("nan")}}
    with pytest.raises(optimizer.OptimizationInputError, match="finite nonnegative"):
        generator.generate(proposal, "abc123", valid_patch(tmp_path), ["rtl/**/*.v"],
                           [{"id": "area-decode-0"}])


def test_controller_stops_before_candidate_when_baseline_is_incomplete():
    result = optimizer.OptimizationController().decide(
        {"blockers": ["no approved library"]}, valid_proposal(), {"status": "PASS", "stages": []},
        {"decision": "ACCEPT"}, {"candidates_remaining": 3, "runtime_sec": 7200})
    assert result["decision"] == "STOP"
    assert result["feature_id"] == "MATRIX-AREA-001"
    assert result["remaining_budget"]["candidates_remaining"] == 3


def test_controller_rejects_functional_regression_but_stops_on_blocker():
    baseline = optimizer.QoRAnalyzer().analyze(
        valid_baseline(), {"metrics": {"cell_area": 100, "setup_wns": 0.1}},
        {"cell_area": "synthesis", "setup_wns": "sta"}, ["regression", "synthesis", "sta"],
        {"critical_paths": [{"id": "path-0", "artifact": "timing.rpt", "sha256": "a" * 64}],
         "area_hotspots": [{"id": "area-decode-0", "artifact": "area.rpt", "sha256": "b" * 64}]})
    candidate = {**valid_proposal(), "source_revision": "abc123"}
    stage_passes = [{"stage": stage, "status": "PASS"}
                    for stage in candidate["required_validation_stages"]]
    regression_fail = [dict(item, status="FAIL") if item["stage"] == "regression" else item
                       for item in stage_passes]
    regression_blocked = [dict(item, status="BLOCKED") if item["stage"] == "regression" else item
                          for item in stage_passes]
    controller = optimizer.OptimizationController()
    failed_candidate = controller.decide(
        baseline, candidate, {"status": "FAIL", "stages": regression_fail},
        {}, {"candidates_remaining": 2, "runtime_sec": 120})
    blocked_candidate = controller.decide(
        baseline, candidate, {"status": "BLOCKED", "stages": regression_blocked},
        {}, {"candidates_remaining": 2, "runtime_sec": 120})
    assert failed_candidate["decision"] == "REJECT"
    assert blocked_candidate["decision"] == "STOP"


@pytest.mark.parametrize("status,comparison,retries,stage_status,expected", [
    ("PASS", "ACCEPT", 0, "PASS", "ACCEPT"),
    ("PASS", "REJECT", 0, "PASS", "REJECT"),
    ("PASS", "REVIEW_TRADEOFF", 0, "PASS", "CHANGE_STRATEGY"),
    ("ERROR", None, 1, "PASS", "RETRY"),
    ("ERROR", None, 0, "PASS", "STOP"),
    ("BLOCKED", None, 1, "PASS", "STOP"),
    ("FAIL", None, 1, "PASS", "REJECT"),
    ("PASS", "ACCEPT", 0, "NOT_RUN", "STOP"),
])
def test_controller_decisions_require_complete_baseline(status, comparison, retries, stage_status, expected):
    baseline = optimizer.QoRAnalyzer().analyze(
        valid_baseline(), {"metrics": {"cell_area": 100, "setup_wns": 0.1}},
        {"cell_area": "synthesis", "setup_wns": "sta"}, ["regression", "synthesis", "sta"],
        {"critical_paths": [{"id": "path-0", "artifact": "timing.rpt", "sha256": "a" * 64}],
         "area_hotspots": [{"id": "area-decode-0", "artifact": "area.rpt", "sha256": "b" * 64}]})
    candidate = {**valid_proposal(), "source_revision": "abc123"}
    stages = [{"stage": stage, "status": "PASS"}
              for stage in candidate["required_validation_stages"]]
    stages[-1]["status"] = stage_status
    result = optimizer.OptimizationController().decide(
        baseline, candidate, {"status": status, "stages": stages},
        {"decision": comparison} if comparison else {},
        {"retries": retries, "candidates_remaining": 2, "runtime_sec": 120})
    assert result["decision"] == expected
    assert result["required_validation_stages"] == candidate["required_validation_stages"]
    assert result["required_validation_commands"] == candidate["validation_commands"]


def test_controller_does_not_accept_status_without_candidate_stage_records():
    baseline = optimizer.QoRAnalyzer().analyze(
        valid_baseline(), {"metrics": {"cell_area": 100, "setup_wns": 0.1}},
        {"cell_area": "synthesis", "setup_wns": "sta"}, ["regression", "synthesis", "sta"],
        {"critical_paths": [{"id": "path-0", "artifact": "timing.rpt", "sha256": "a" * 64}],
         "area_hotspots": [{"id": "area-decode-0", "artifact": "area.rpt", "sha256": "b" * 64}]})
    candidate = {**valid_proposal(), "source_revision": "abc123"}
    result = optimizer.OptimizationController().decide(
        baseline, candidate, {"status": "PASS", "stages": []}, {"decision": "ACCEPT"},
        {"candidates_remaining": 2, "runtime_sec": 120})
    assert result["decision"] == "STOP"


def test_benchmark_summary_reports_measurement_and_unavailable_agent_telemetry():
    summary = optimizer.summarize_benchmarks(
        [{"evidence": {"status": "PASS", "stages": [{"stage": "regression", "status": "PASS"}]},
          "comparison": {"decision": "ACCEPT", "metrics": {"cell_area": {"delta_pct": -5}}},
          "checkpoint": {"stages": [{"cache_hit": True}]},
          "attempts": [{"event": "START"}]}],
        {"runtime_sec": 17.25}, human_interventions=2)
    assert summary["candidate_count"] == 1
    assert summary["successful_candidate_rate"] == 1
    assert summary["cache_hits"] == 1
    assert summary["tool_invocations"] == 1
    assert summary["agent_calls"] is None
    assert summary["token_usage"] is None
    assert summary["human_interventions"] == 2
