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


def test_qor_analyzer_accepts_simulation_metrics_without_asic_hotspots():
    provenance = {"artifact": "performance-summary.json",
                  "parser_id": "nmaforge-matrix-log", "parser_version": "1"}
    stages = ["regression", "reference_model", "latency_gate", "performance"]
    evidence = {"status": "PASS", "source_revision": "abc123",
                "stages": [{"stage": stage, "status": "PASS",
                            "metric_provenance": ({"workload_cycles": provenance,
                                                   "macs_per_cycle": provenance}
                                                  if stage == "performance" else {})}
                           for stage in stages]}
    result = optimizer.QoRAnalyzer().analyze(
        evidence, {"metrics": {"workload_cycles": 2029, "macs_per_cycle": 45.67}},
        {"workload_cycles": "performance", "macs_per_cycle": "performance"}, stages,
        optimization_mode="simulation_performance")
    assert result["baseline_valid"]
    assert result["metrics"] == {"workload_cycles": 2029, "macs_per_cycle": 45.67}


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


def test_simulation_performance_candidate_uses_workload_metrics_only(tmp_path):
    proposal = {
        "optimization_mode": "simulation_performance",
        "feature_id": "MATRIX-CYCLE-001",
        "hypothesis": "Avoid the terminal ST_DONE bubble after the final tile.",
        "target_hotspot": "done-transition-0",
        "intended_rtl_modification": "Assert completion on the final ST_NEXT transition.",
        "expected_metric_improvement": {"workload_cycles": {"direction": "lower", "target_pct": 5}},
        "functional_risks": ["Completion could be asserted before outstanding writes drain."],
        "timing_risks": ["No ASIC timing claim is made by this experiment."],
        "required_validation_stages": ["regression", "reference_model", "latency_gate", "performance"],
        "validation_commands": {stage: ["make", stage] for stage in
                                ("regression", "reference_model", "latency_gate", "performance")},
    }
    candidate = optimizer.CandidateGenerator().generate(
        proposal, "abc123", valid_patch(tmp_path), ["rtl/compute/matrix/*.v"],
        [{"id": "done-transition-0"}])
    assert candidate["expected_metric_improvement"] == proposal["expected_metric_improvement"]

    proposal["expected_metric_improvement"] = {"setup_wns": {"direction": "higher", "target_pct": 5}}
    with pytest.raises(optimizer.OptimizationInputError, match="only target workload metrics"):
        optimizer.CandidateGenerator().generate(
            proposal, "abc123", valid_patch(tmp_path), ["rtl/compute/matrix/*.v"],
            [{"id": "done-transition-0"}])


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


def test_controller_rejects_failed_gate_even_when_downstream_stages_are_skipped():
    baseline = {"baseline_valid": True, "source_revision": "abc123", "blockers": []}
    stages = [{"stage": "regression", "status": "FAIL"},
              {"stage": "reference_model", "status": "SKIPPED"},
              {"stage": "latency_gate", "status": "SKIPPED"},
              {"stage": "performance", "status": "SKIPPED"}]
    candidate = {"feature_id": "MATRIX-CYCLE-001", "source_revision": "abc123",
                 "required_validation_stages": ["regression", "reference_model",
                                                 "latency_gate", "performance"]}
    result = optimizer.OptimizationController().decide(
        baseline, candidate, {"status": "FAIL", "stages": stages}, {},
        {"candidates_remaining": 2, "runtime_sec": 14370, "retries": 0})
    assert result["decision"] == "REJECT"
    assert result["evidence"] == [
        "candidate failed a required validation gate",
        "regression stage FAIL: no details",
        "reference_model stage SKIPPED: no details",
        "latency_gate stage SKIPPED: no details",
        "performance stage SKIPPED: no details",
    ]
    assert [item["status"] for item in result["stage_evidence"]] == [
        "FAIL", "SKIPPED", "SKIPPED", "SKIPPED"
    ]
    assert result["remaining_budget"]["candidates_remaining"] == 2


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
