import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "skills/rtl-ppa-optimization/scripts/optimization_readiness.py"
SPEC = importlib.util.spec_from_file_location("optimization_readiness", SCRIPT)
readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readiness)


def test_hierarchy_debug_correlates_checker_protocol_fsm_and_selected_waveform():
    log = "\n".join([
        "FSM_TRACE cycle=100 path=tb.dut.core state=WRITE next=WRITE txn=7",
        "PROTOCOL_TRACE cycle=101 transaction_id=7 path=tb.dut.line valid=1 ready=0",
        "ASSERTION_FAIL cycle=102 checker=MATRIX-CK-4 transaction_id=7 path=tb.dut.core.p_write_stable request_changed=1",
        "FSM_TRACE cycle=103 path=tb.dut.core state=ERROR next=IDLE txn=8",
    ])
    vcd = """$scope module tb $end
$scope module dut $end
$scope module line $end
$var wire 1 ! ready $end
$upscope $end
$upscope $end
$upscope $end
$enddefinitions $end
#1000
0!
#1010
1!
#1020
0!
"""
    result = readiness.HierarchyAwareDebugger().analyze(
        log, ["tb.dut.line.ready"], vcd, clock_period_ticks=10, context_cycles=2)

    assert result["first_failure_cycle"] == 102
    assert result["checker_id"] == "MATRIX-CK-4"
    assert len(result["same_transaction_events"]) == 3
    assert result["waveform_status"] == "PARSED"
    assert [event["cycle"] for event in result["events"] if event["kind"] == "wave_event"] == [100, 101, 102]
    assert result["verdi_query_plan"]["status"] == "READY"


def test_hierarchy_debug_does_not_invent_waveform_or_first_failure():
    result = readiness.HierarchyAwareDebugger().analyze("simulation completed\n")

    assert result["status"] == "NO_STRUCTURED_EVIDENCE"
    assert result["first_failure_cycle"] is None
    assert result["waveform_status"] == "NOT_PROVIDED"


def test_hierarchy_debug_requires_signal_selection_before_reading_vcd():
    result = readiness.HierarchyAwareDebugger().analyze(
        "ASSERTION_FAIL cycle=0 checker=CK-0", vcd_text="$enddefinitions $end\n#0\n1!\n")

    assert result["first_failure_cycle"] == 0
    assert result["waveform_status"] == "NO_MATCHING_SIGNALS"


def test_architecture_search_uses_profile_and_marks_unsupported_changes_unready():
    profile = {
        "status": "PASS",
        "profile_schema": "matrix_cycle_attribution_v1",
        "cycles": [78, 110, 230, 403, 1189], "macs_per_cycle": 46.105,
        "profiles": [{"id": 104, "prefetch_wait": 500,
                      "prefetch_wait_denial": 77,
                      "prefetch_wait_fifo_full": 0,
                      "prefetch_wait_request_grant": 183,
                      "prefetch_wait_outstanding_drain": 180,
                      "prefetch_wait_handoff_ready": 60,
                      "prefetch_wait_no_request": 0,
                      "write": 320, "write_productive": 256,
                      "writeback_stall": 64, "write_protection_error": 0,
                      "line_denial": 64, "fifo_full": 0}],
        "attribution_totals": {"prefetch_wait_outstanding_drain": 283,
                               "prefetch_wait_fifo_full": 0},
    }

    result = readiness.ArchitectureSearch().propose(profile, "source-123")

    assert result["status"] == "EXPERIMENTS_ONLY"
    assert len(result["experiments"]) == 3
    assert all(not item["candidate_ready"] for item in result["experiments"])
    assert result["experiments"][0]["evidence"]["outstanding_drain_cycles"] == 180
    assert "zero" in result["experiments"][2]["rejection_reason"]
    assert result["experiments"][1]["expected_impact"]["area"].startswith("additional")

    profile["profiles"][0]["write"] = 321
    assert readiness.ArchitectureSearch().propose(profile, "source-123")["status"] == "BLOCKED"


def test_cost_engine_selects_debug_directed_regression_and_respects_budget():
    engine = readiness.CostAwareDecisionEngine()
    history = [{"evidence": {"stages": [
        {"stage": "directed", "elapsed_sec": 5},
        {"stage": "regression", "elapsed_sec": 22},
    ]}}]
    commands = {"DEEP_REASONING": ["inspect", "failure.json"],
                "DIRECTED_TEST": ["make", "focused"],
                "regression": ["make", "regress"]}
    missing_root = engine.plan({"feature_id": "F-1"}, {"remaining_runtime_sec": 10}, history,
                               commands=commands)
    directed = engine.plan({"feature_id": "F-1", "testpoint_id": "TP-2",
                            "first_failure_cycle": 20, "checker_id": "CK-1",
                            "reproducible_seed": 7}, {"remaining_runtime_sec": 10},
                           history, commands=commands)
    regression = engine.plan({"feature_id": "F-1", "rtl_change_present": True},
                             {"remaining_runtime_sec": 30}, history,
                             {"directed_test_status": "PASS"}, commands)
    over_budget = engine.plan({"feature_id": "F-1", "rtl_change_present": True},
                              {"remaining_runtime_sec": 10}, history,
                              {"directed_test_status": "PASS"}, commands)

    assert missing_root["action"] == "DEEP_REASONING"
    assert directed["action"] == "DIRECTED_TEST"
    assert directed["cost"]["estimated_eda_seconds"] == 5
    assert regression["action"] == "FULL_REGRESSION"
    assert regression["required_validation_command"] == ["make", "regress"]
    assert over_budget["action"] == "STOP"
    assert directed["cost"]["token_usage"] is None

    zero_cycle = engine.plan({"first_failure_cycle": 0, "checker_id": "CK-0",
                              "reproducible_seed": 1},
                             {"remaining_runtime_sec": 10}, history,
                             commands=commands)
    assert zero_cycle["action"] == "DIRECTED_TEST"


def test_cost_engine_stops_on_licensed_tool_blocker():
    result = readiness.CostAwareDecisionEngine().plan(
        {"status": "BLOCKED", "error_class": "LICENSE_UNAVAILABLE",
         "feature_id": "F-2"},
        {"remaining_runtime_sec": 100}, commands={"DIRECTED_TEST": ["make", "focused"]})

    assert result["action"] == "STOP"
    assert "blocker" in result["evidence"][0]


def test_efficiency_comparison_requires_matched_tasks_and_real_telemetry():
    engine = readiness.CostAwareDecisionEngine()
    unavailable = engine.compare_efficiency(
        [{"task_id": "a", "success": True}],
        [{"task_id": "a", "success": True}])
    comparable = engine.compare_efficiency(
        [{"task_id": "a", "token_usage": 80, "eda_runtime_sec": 10, "success": True},
         {"task_id": "b", "token_usage": 120, "eda_runtime_sec": 20, "success": False}],
        [{"task_id": "a", "token_usage": 100, "eda_runtime_sec": 12, "success": True},
         {"task_id": "b", "token_usage": 100, "eda_runtime_sec": 18, "success": True}])

    assert unavailable["status"] == "NOT_COMPARABLE"
    assert comparable["status"] == "COMPARABLE"
    assert comparable["deltas_vs_codex_pct"] == {
        "token_usage": 0.0, "eda_runtime_sec": 0.0, "success_rate": -50.0}


def test_cost_engine_honors_token_estimate_and_keeps_observed_telemetry():
    result = readiness.CostAwareDecisionEngine().plan(
        {"first_failure_cycle": 1, "checker_id": "CK", "reproducible_seed": 1},
        {"remaining_runtime_sec": 10, "remaining_tokens": 100,
         "estimated_tokens_by_action": {"DIRECTED_TEST": 120}},
        [{"evidence": {"stages": [{"stage": "directed", "elapsed_sec": 2}]}}],
        commands={"DIRECTED_TEST": ["make", "focused"]},
        telemetry={"agent_calls": 1, "token_usage": 83})

    assert result["action"] == "STOP"
    assert result["cost"]["token_usage"] == 83
    assert result["cost"]["estimated_tokens"] == 120


def test_cost_engine_exposes_normalized_adaptive_actions_without_breaking_legacy_action():
    engine = readiness.CostAwareDecisionEngine()
    result = engine.plan(
        {"first_failure_cycle": 22, "checker_id": "MATRIX-CK", "reproducible_seed": 20261021},
        {"remaining_runtime_sec": 100},
        [{"evidence": {"stages": [{"stage": "directed", "elapsed_sec": 2}]}}],
        commands={"DIRECTED_TEST": ["make", "focused"]})
    assert result["action"] == "DIRECTED_TEST"
    assert result["adaptive_action"] == "TARGETED_SIMULATION"

    blocked = engine.plan(
        {"asic_ppa_requested": True}, {"remaining_runtime_sec": 100})
    assert blocked["adaptive_action"] == "STOP"


def test_real_workflow_runner_preserves_log_hash_and_diagnosis(tmp_path):
    log = tmp_path / "candidate.log"
    output = tmp_path / "workflow.json"
    log.write_text("Fatal: phase abort target state=11 not reached current=0 done=1\n")
    result = readiness.AgentWorkflowRunner().run(
        log, output, seed=20261021, source_revision="4b62f8e8",
        known_fault="Candidate skipped terminal ST_DONE",
        first_divergence_cycle=22,
        baseline_state={"state": "ST_DONE", "done": 0, "abort": 0},
        candidate_state={"state": "IDLE", "done": 1, "abort": 0})
    assert result["status"] == "ANALYZED"
    assert result["failure_report"]["diagnosis_correct"] is True
    assert result["source"]["seed"] == 20261021
    assert len(result["source"]["log_sha256"]) == 64
    assert json.loads(output.read_text())["workflow"][-1] == "DIRECTED_REPLAY"


def test_cli_search_writes_machine_readable_report(tmp_path):
    profile_path = tmp_path / "profile.json"
    output = tmp_path / "search.json"
    profile_path.write_text(json.dumps({
        "status": "PASS", "profile_schema": "matrix_cycle_attribution_v1",
        "profiles": [{"id": 104, "prefetch_wait": 0,
                      "prefetch_wait_denial": 0, "prefetch_wait_fifo_full": 0,
                      "prefetch_wait_request_grant": 0,
                      "prefetch_wait_outstanding_drain": 0,
                      "prefetch_wait_handoff_ready": 0,
                      "prefetch_wait_no_request": 0,
                      "write": 0, "write_productive": 0,
                      "writeback_stall": 0, "write_protection_error": 0,
                      "line_denial": 0, "fifo_full": 0}],
        "attribution_totals": {}, "cycles": [1], "macs_per_cycle": 1,
    }))

    assert readiness.main(["search", "--profile", str(profile_path),
                           "--source-revision", "abc", "--output", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "EXPERIMENTS_ONLY"
