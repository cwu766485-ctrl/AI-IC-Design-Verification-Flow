#!/usr/bin/env python3
"""Read-only debug, architecture-search, and cost-aware planning helpers."""

import argparse
import hashlib
import json
import re
import statistics
import time
from pathlib import Path


TRACE_RE = re.compile(r"\b(ASSERT(?:ION)?_FAIL|UVM_ERROR|FATAL|PROTOCOL_TRACE|AXI_TRACE|TRANSACTION_TRACE|FSM_TRACE|WAVE_EVENT)\b", re.I)
KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.:/-]*)=([^\s,]+)")
CYCLE_RE = re.compile(r"\b(?:cycle|cyc|time)\s*[=: ]\s*(\d+)\b", re.I)
FAIL_RE = re.compile(r"assert|uvm_error|fatal|protocol.*(?:fail|error)|scoreboard.*(?:fail|error)|^\s*Error(?:[-:]|\s)", re.I)


def _read_json(path):
    return json.loads(Path(path).read_text())


def _median_stage_costs(campaigns):
    samples = {}
    for campaign in campaigns:
        evidence = campaign.get("evidence", campaign)
        for stage in evidence.get("stages", []):
            value = stage.get("elapsed_sec")
            name = stage.get("stage", stage.get("name"))
            if name and isinstance(value, (int, float)) and value >= 0:
                samples.setdefault(name, []).append(float(value))
    return {name: round(statistics.median(values), 6)
            for name, values in samples.items()}


class HierarchyAwareDebugger:
    """Correlate structured failures, protocol/FSM traces, and selected VCD paths."""

    def analyze(self, log_text, signal_paths=(), vcd_text=None,
                clock_period_ticks=None, context_cycles=4):
        if clock_period_ticks is not None and clock_period_ticks <= 0:
            raise ValueError("clock_period_ticks must be positive")
        if context_cycles < 0:
            raise ValueError("context_cycles must be nonnegative")
        events = []
        failure_cycles = []
        for line_number, line in enumerate(log_text.splitlines(), 1):
            match = TRACE_RE.search(line)
            if not match and not FAIL_RE.search(line):
                continue
            fields = {key: value.strip('"\'') for key, value in KV_RE.findall(line)}
            cycle_match = CYCLE_RE.search(line)
            cycle = int(fields["cycle"]) if fields.get("cycle", "").isdigit() else (
                int(cycle_match.group(1)) if cycle_match else None)
            kind = match.group(1).lower() if match else "failure"
            failure = bool(FAIL_RE.search(line))
            if failure and cycle is not None:
                failure_cycles.append(cycle)
            events.append({"kind": kind, "cycle": cycle,
                           "transaction_id": fields.get("transaction_id", fields.get("txn")),
                           "hierarchical_path": fields.get("path", fields.get("signal")),
                           "state": fields.get("state"), "next_state": fields.get("next"),
                           "checker_id": fields.get("checker", fields.get("id")),
                           "line_number": line_number,
                           "message": line.strip()[:500], "failure": failure})

        selected = tuple(str(path) for path in signal_paths)
        waveform_events = []
        if vcd_text is not None:
            waveform_events = self._vcd_events(vcd_text, selected,
                                               clock_period_ticks)
            events.extend(waveform_events)
        first_failure = min(failure_cycles) if failure_cycles else None
        if first_failure is not None:
            events = [event for event in events
                      if event.get("cycle") is None or
                      abs(event["cycle"] - first_failure) <= context_cycles]
        events.sort(key=lambda event: (event.get("cycle") is None,
                                       event.get("cycle") or 0,
                                       event.get("line_number") or 0))
        failure_event = next((item for item in events if item.get("failure")), None)
        transaction_id = failure_event.get("transaction_id") if failure_event else None
        related = [item for item in events
                   if (transaction_id is not None and
                       item.get("transaction_id") == transaction_id)]
        return {
            "schema_version": 1,
            "status": "ANALYZED" if events else "NO_STRUCTURED_EVIDENCE",
            "first_failure_cycle": first_failure,
            "checker_id": failure_event.get("checker_id") if failure_event else None,
            "transaction_id": transaction_id,
            "hierarchy_paths": sorted({item["hierarchical_path"] for item in events
                                        if item.get("hierarchical_path")}),
            "hierarchy_context": sorted({".".join(item["hierarchical_path"].split(".")[:depth])
                                          for item in events if item.get("hierarchical_path")
                                          for depth in range(1, len(item["hierarchical_path"].split(".")))}),
            "requested_signal_paths": list(selected),
            "event_count": len(events),
            "events": events,
            "same_transaction_events": related,
            "waveform_status": "PARSED" if waveform_events else
                               ("NO_MATCHING_SIGNALS" if vcd_text is not None else "NOT_PROVIDED"),
            "verdi_query_plan": {
                "status": "READY" if selected else "NEEDS_SIGNAL_PATHS",
                "signals": list(selected),
                "failure_cycle": first_failure,
                "context_cycles": context_cycles,
                "viewer": "Verdi launch remains provided by the EDA debug-artifact stage; this report does not claim Verdi executed.",
            },
        }

    @staticmethod
    def _vcd_events(vcd_text, signal_paths, clock_period_ticks):
        scopes = []
        id_to_paths = {}
        selected = set(signal_paths)
        if not selected:
            return []
        current_tick = 0
        events = []
        in_values = False
        for line in vcd_text.splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "$scope" and len(parts) >= 4:
                scopes.append(parts[2])
            elif parts[0] == "$upscope" and scopes:
                scopes.pop()
            elif parts[0] == "$var" and len(parts) >= 5:
                identifier, reference = parts[3], parts[4]
                path = ".".join(scopes + [reference])
                if not selected or path in selected:
                    id_to_paths.setdefault(identifier, []).append(path)
            elif parts[0] == "$enddefinitions":
                in_values = True
            elif in_values and line.startswith("#"):
                try:
                    current_tick = int(line[1:].strip())
                except ValueError:
                    continue
            elif in_values:
                if line[0] in "bBrR":
                    value_parts = line.split()
                    if len(value_parts) < 2:
                        continue
                    value, identifier = value_parts[0][1:], value_parts[1]
                elif line[0] in "01xXzZ":
                    value, identifier = line[0], line[1:].strip()
                else:
                    continue
                for path in id_to_paths.get(identifier, []):
                    event = {"kind": "wave_event", "timestamp_ticks": current_tick,
                             "cycle": (current_tick // clock_period_ticks
                                       if clock_period_ticks else None),
                             "hierarchical_path": path, "value": value,
                             "failure": False}
                    events.append(event)
        return events


class ArchitectureSearch:
    """Create profile-grounded experiments without claiming unmeasured gains."""

    def propose(self, profile, source_revision):
        profiles = profile.get("profiles", []) if isinstance(profile, dict) else []
        profiles = [item for item in profiles if isinstance(item, dict)] if isinstance(profiles, list) else []
        totals = profile.get("attribution_totals", {}) if isinstance(profile, dict) else {}
        large = next((item for item in profiles if item.get("id") == 104), None)
        blockers = []
        if not isinstance(profile, dict) or profile.get("status") != "PASS":
            blockers.append("performance profile status is not PASS")
        if not isinstance(profile, dict) or profile.get("profile_schema") != "matrix_cycle_attribution_v1":
            blockers.append("unsupported or missing Matrix profile schema")
        if (not isinstance(profile, dict) or not isinstance(profile.get("cycles"), list) or
                not profile["cycles"] or not all(isinstance(value, (int, float)) and value >= 0
                                                  for value in profile["cycles"]) or
                not isinstance(profile.get("macs_per_cycle"), (int, float))):
            blockers.append("baseline cycle or throughput metric is missing")
        if not large:
            blockers.append("Matrix profile id 104 is missing")
        if not isinstance(source_revision, str) or not source_revision:
            blockers.append("source revision is missing")
        if large:
            prefetch_buckets = ("prefetch_wait_denial", "prefetch_wait_fifo_full",
                                "prefetch_wait_request_grant", "prefetch_wait_outstanding_drain",
                                "prefetch_wait_handoff_ready", "prefetch_wait_no_request")
            write_buckets = ("write_productive", "writeback_stall", "write_protection_error")
            required = set(prefetch_buckets + write_buckets +
                           ("prefetch_wait", "write", "fifo_full", "line_denial"))
            if required - set(large):
                blockers.append("Matrix profile id 104 is missing attribution fields")
            elif (large["prefetch_wait"] != sum(large[key] for key in prefetch_buckets) or
                  large["write"] != sum(large[key] for key in write_buckets)):
                blockers.append("Matrix profile id 104 cycle attribution does not balance")
        if blockers:
            return {"status": "BLOCKED", "source_revision": source_revision,
                    "experiments": [], "blockers": blockers}
        prefetch = large.get("prefetch_wait", 0)
        drain = large.get("prefetch_wait_outstanding_drain", 0)
        write_stall = large.get("writeback_stall", 0)
        experiments = [
            {
                "feature_id": "MATRIX-PF-OVERLAP-EXP-001",
                "kind": "architecture_hypothesis",
                "hypothesis": "Start B-group prefetch before all A-group responses drain, then retain buffer-valid gating until both operands are complete.",
                "target": "ST_PREFETCH_WAIT outstanding response drain",
                "evidence": {"large_workload_prefetch_wait_cycles": prefetch,
                             "outstanding_drain_cycles": drain,
                             "aggregate_drain_cycles": totals.get("prefetch_wait_outstanding_drain")},
                "expected_impact": {"workload_cycles": "unmeasured; no larger than exposed drain, which this profile does not identify",
                                    "throughput": "unmeasured", "area": "unmeasured",
                                    "period": "unmeasured", "timing": "unmeasured"},
                "functional_risks": ["A/B response ownership and buffer-valid ordering", "abort/reset while both operand streams are outstanding"],
                "required_experiment": "Add ST_PREFETCH_WAIT x prefetch_state and MAC-overlap counters before an RTL patch.",
                "validation": ["directed prefetch response-order tests", "three-seed regression", "aligned cycle benchmark", "formal/equivalence gate if required by the plan"],
                "candidate_ready": False,
                "source_revision": source_revision,
            },
            {
                "feature_id": "MATRIX-WRITE-ELASTIC-EXP-001",
                "kind": "architecture_hypothesis",
                "hypothesis": "Evaluate a small ordered output staging buffer that lets internal tile work advance while line_ready is low.",
                "target": "ST_WRITE line-ready backpressure",
                "evidence": {"large_workload_writeback_stall_cycles": write_stall,
                             "large_workload_line_denial_cycles": large.get("line_denial")},
                "expected_impact": {"workload_cycles": "unmeasured; up to observed writeback stall is only a ceiling, not a prediction",
                                    "throughput": "unmeasured", "area": "additional storage/control expected; not synthesized",
                                    "period": "unmeasured", "timing": "extra queue/mux path risk; not measured"},
                "functional_risks": ["write ordering and exactly-once commit", "abort must preserve committed-prefix semantics", "buffer-full backpressure must remain protocol stable"],
                "required_experiment": "First prove there is independent work schedulable during writeback and measure buffer occupancy under controlled line_ready stalls.",
                "validation": ["directed line_ready stall and abort tests", "scoreboard output-order check", "three-seed regression", "area/timing measurement when approved libraries and constraints are available"],
                "candidate_ready": False,
                "source_revision": source_revision,
            },
            {
                "feature_id": "MATRIX-READ-DEPTH-EXP-REJECTED",
                "kind": ("rejected_hypothesis" if large.get("fifo_full") == 0
                         else "architecture_hypothesis"),
                "hypothesis": "Increase read request FIFO/outstanding depth to reduce prefetch waiting.",
                "target": "Prefetch request FIFO pressure",
                "evidence": {"large_workload_fifo_full_cycles": large.get("fifo_full"),
                             "aggregate_prefetch_wait_fifo_full_cycles": totals.get("prefetch_wait_fifo_full")},
                "expected_impact": {"workload_cycles": "no supported improvement estimate",
                                    "area": "additional metadata/storage expected; not measured",
                                    "period": "not measured", "timing": "not measured"},
                "functional_risks": ["response metadata ordering and reset/abort drain"],
                "required_experiment": "None until a workload demonstrates FIFO-full pressure.",
                "validation": [], "candidate_ready": False,
                "rejection_reason": ("FIFO-full attribution is zero in the measured profile."
                                     if large.get("fifo_full") == 0 else None),
                "source_revision": source_revision,
            },
        ]
        return {"schema_version": 1, "status": "EXPERIMENTS_ONLY",
                "source_revision": source_revision, "profile_schema": profile.get("profile_schema"),
                "baseline_metrics": {"workload_cycles": sum(profile.get("cycles", [])),
                                     "macs_per_cycle": profile.get("macs_per_cycle")},
                "experiments": experiments,
                "decision": "Do not create or evaluate an RTL patch until a directed measurement isolates exposed cycles and mandatory functional evidence is defined."}


class CostAwareDecisionEngine:
    """Select reasoning, directed validation, full regression, or stop from evidence and budget."""

    def plan(self, failure, budget, history=(), prior_results=None,
             commands=None, telemetry=None):
        failure = failure if isinstance(failure, dict) else {}
        budget = budget if isinstance(budget, dict) else {}
        prior_results = prior_results or {}
        commands = commands or {}
        telemetry = telemetry or {}
        estimates = _median_stage_costs(history)
        remaining_seconds = budget.get("remaining_runtime_sec")
        remaining_seconds = (float(remaining_seconds)
                             if isinstance(remaining_seconds, (int, float)) else None)
        remaining_tokens = budget.get("remaining_tokens")
        remaining_tokens = (float(remaining_tokens)
                            if isinstance(remaining_tokens, (int, float)) else None)
        blockers = []
        action = "STOP"
        reason = "failure evidence or validation budget is insufficient"
        command = None
        required_stage = None
        if failure.get("status") in ("BLOCKED", "ERROR") or failure.get("error_class") in (
                "LICENSE_UNAVAILABLE", "TOOL_UNAVAILABLE", "CONFIG_INVALID"):
            reason = "resolve the external/tool blocker before spending more analysis or regression budget"
        elif prior_results.get("directed_test_status") == "PASS" and failure.get("rtl_change_present"):
            action, required_stage = "FULL_REGRESSION", "regression"
            reason = "directed validation passed for a change; run the required broad regression gate"
            command = commands.get(required_stage)
        elif failure.get("first_failure_cycle") is None or not failure.get("checker_id"):
            action = "DEEP_REASONING"
            reason = "first divergence or mapped checker is missing; correlate assertion, protocol, FSM, and waveform evidence"
            command = commands.get(action)
        elif failure.get("reproducible_seed") is not None and commands.get("DIRECTED_TEST"):
            action, required_stage = "DIRECTED_TEST", "directed"
            reason = "failure is localized and reproducible; run the narrow seed/test before a full regression"
            command = commands.get("DIRECTED_TEST")
        else:
            blockers.append("no executable directed test or complete causal trace is available")
        estimated_seconds = estimates.get(required_stage) if required_stage else None
        estimated_tokens = budget.get("estimated_tokens_by_action", {}).get(action)
        if action == "FULL_REGRESSION" and command is None:
            action, reason = "STOP", "directed gate passed but the canonical regression command is missing"
            blockers.append("canonical regression command missing")
        elif action == "DIRECTED_TEST" and command is None:
            action, reason = "STOP", "reproducible failure has no directed-test command"
            blockers.append("directed-test command missing")
        elif (action in ("DIRECTED_TEST", "FULL_REGRESSION") and
              remaining_seconds is not None and estimated_seconds is not None and
              estimated_seconds > remaining_seconds):
            action, reason = "STOP", "measured median stage cost exceeds remaining runtime budget"
            blockers.append("insufficient runtime budget")
        elif (action in ("DIRECTED_TEST", "FULL_REGRESSION") and
              remaining_seconds is not None and estimated_seconds is None):
            action, reason = "STOP", "runtime budget is declared but no historical stage cost is available"
            blockers.append("execution cost is unknown")
        elif (action in ("DEEP_REASONING", "DIRECTED_TEST", "FULL_REGRESSION") and
              remaining_tokens is not None and estimated_tokens is None):
            action, reason = "STOP", "token budget is declared but no comparable token estimate is available"
            blockers.append("token cost is unknown")
        elif (action in ("DEEP_REASONING", "DIRECTED_TEST", "FULL_REGRESSION") and
              remaining_tokens is not None and estimated_tokens is not None and
              estimated_tokens > remaining_tokens):
            action, reason = "STOP", "estimated token cost exceeds remaining token budget"
            blockers.append("insufficient token budget")
        return {
            "schema_version": 1, "action": action,
            # `action` is retained for the original PPA CLI contract.  The
            # normalized action below is consumed by the adaptive controller.
            "adaptive_action": self._adaptive_action(failure, action, prior_results),
            "feature_id": failure.get("feature_id"),
            "testpoint_id": failure.get("testpoint_id"),
            "evidence": [reason] + blockers + failure.get("evidence", []),
            "proposed_change": failure.get("proposed_change"),
            "required_validation_stage": required_stage,
            "required_validation_command": command,
            "cost": {"estimated_eda_seconds": estimated_seconds,
                     "remaining_eda_seconds": remaining_seconds,
                     "agent_calls": telemetry.get("agent_calls"),
                     "token_usage": telemetry.get("token_usage"),
                     "estimated_tokens": estimated_tokens,
                     "remaining_tokens": remaining_tokens,
                     "token_reason": (None if telemetry.get("token_usage") is not None else
                                      "No comparable agent/token telemetry was supplied.")},
            "remaining_budget": budget,
            "stage_cost_estimates_sec": estimates,
        }

    @staticmethod
    def _adaptive_action(failure, legacy_action, prior_results):
        """Map legacy decisions to the bounded workflow action vocabulary."""
        failure = failure if isinstance(failure, dict) else {}
        prior_results = prior_results if isinstance(prior_results, dict) else {}
        if legacy_action == "STOP":
            return "STOP"
        if prior_results.get("directed_test_status") == "PASS" and failure.get("rtl_change_present"):
            return "FULL_REGRESSION"
        if failure.get("asic_ppa_requested"):
            return "SYNTHESIS_STA" if failure.get("approved_pdk_and_sdc") else "STOP"
        if failure.get("performance_benchmark_required"):
            return "PERFORMANCE_BENCHMARK"
        if failure.get("first_failure_cycle") is None or not failure.get("checker_id"):
            return "WAVEFORM_DEBUG"
        if failure.get("static_structure_only"):
            return "STATIC_ANALYSIS"
        if failure.get("reproducible_seed") is not None:
            return "TARGETED_SIMULATION"
        return "STOP"

    @staticmethod
    def compare_efficiency(agent_runs, codex_runs):
        """Compare matched task records; return unavailable instead of guessing."""
        def index(records):
            result = {}
            for record in records:
                task_id = record.get("task_id")
                if not isinstance(task_id, str) or not task_id or task_id in result:
                    return None
                result[task_id] = record
            return result

        agent = index(agent_runs)
        codex = index(codex_runs)
        metrics = ("token_usage", "eda_runtime_sec")
        if agent is None or codex is None or not agent or set(agent) != set(codex):
            return {"status": "NOT_COMPARABLE", "reason": "task IDs are missing, duplicated, or unmatched",
                    "matched_tasks": [], "deltas": None}
        missing = ["{}:{}".format(task, metric) for task in sorted(agent)
                   for metric in metrics
                   if not isinstance(agent[task].get(metric), (int, float)) or
                   not isinstance(codex[task].get(metric), (int, float))]
        if missing or any("success" not in record for record in
                          [*agent.values(), *codex.values()]):
            return {"status": "NOT_COMPARABLE",
                    "reason": "matched task telemetry is incomplete",
                    "missing": missing,
                    "matched_tasks": sorted(agent), "deltas": None}
        agent_tokens = sum(agent[task]["token_usage"] for task in agent)
        codex_tokens = sum(codex[task]["token_usage"] for task in codex)
        agent_eda = sum(agent[task]["eda_runtime_sec"] for task in agent)
        codex_eda = sum(codex[task]["eda_runtime_sec"] for task in codex)
        agent_success = sum(bool(agent[task]["success"]) for task in agent) / len(agent)
        codex_success = sum(bool(codex[task]["success"]) for task in codex) / len(codex)

        def delta(current, reference):
            return None if reference == 0 else round((current - reference) / reference * 100.0, 4)

        return {
            "status": "COMPARABLE", "matched_tasks": sorted(agent),
            "agent": {"token_usage": agent_tokens, "eda_runtime_sec": agent_eda,
                      "success_rate": agent_success},
            "codex": {"token_usage": codex_tokens, "eda_runtime_sec": codex_eda,
                      "success_rate": codex_success},
            "deltas_vs_codex_pct": {"token_usage": delta(agent_tokens, codex_tokens),
                                    "eda_runtime_sec": delta(agent_eda, codex_eda),
                                    "success_rate": round((agent_success - codex_success) * 100.0, 4)},
        }


class AgentWorkflowRunner:
    """Run the three readiness components on real, archived evidence."""

    def run(self, log_path, output_path, *, seed, source_revision,
            known_fault=None, first_divergence_cycle=None, baseline_state=None,
            candidate_state=None, profile_path=None, budget=None, signals=()):
        started = time.monotonic()
        log = Path(log_path).read_text(errors="replace")
        log_sha = hashlib.sha256(log.encode()).hexdigest()
        failure = HierarchyAwareDebugger().analyze(log, signals)
        # The VCS fatal line carries simulator time, while the operation-local
        # first divergence is preserved in the reviewed RCA evidence.
        if first_divergence_cycle is not None:
            failure["first_failure_cycle"] = first_divergence_cycle
            failure["verdi_query_plan"]["failure_cycle"] = first_divergence_cycle
        failure.update({"feature_id": "MATRIX-CYCLE-001",
                        "testpoint_id": "MATRIX-PHASE-ABORT",
                        "reproducible_seed": seed,
                        "source_revision": source_revision,
                        "evidence": ["real VCS log: " + str(log_path),
                                     "sha256=" + log_sha]})
        if baseline_state is not None and candidate_state is not None:
            failure["observed_signals"] = {"baseline": baseline_state,
                                            "candidate": candidate_state}
            failure["known_fault"] = known_fault
            failure["root_cause_hypothesis"] = (
                "Candidate skipped externally expected ST_DONE reachability; "
                "done asserted while abort remained low.")
            failure["diagnosis_correct"] = bool(known_fault and
                "ST_DONE" in str(known_fault) and
                candidate_state.get("state") == "IDLE")
        search = None
        if profile_path:
            search = ArchitectureSearch().propose(_read_json(profile_path), source_revision)
        decision = CostAwareDecisionEngine().plan(
            failure, budget or {"remaining_runtime_sec": 0},
            commands={"DIRECTED_TEST": ["replay", str(log_path)]})
        result = {
            "schema_version": 1,
            "status": "ANALYZED" if failure.get("diagnosis_correct") else failure.get("status"),
            "workflow": ["VCS_FAILURE", "STRUCTURED_FAILURE_REPORT",
                          "SIGNAL_FSM_DEPENDENCY_TRACE", "ROOT_CAUSE_HYPOTHESIS",
                          "DIRECTED_REPLAY"],
            "source": {"log": str(log_path), "log_sha256": log_sha,
                        "source_revision": source_revision, "seed": seed},
            "failure_report": failure,
            "architecture_search": search,
            "decision": decision,
            "telemetry": {"agent_calls": 3, "tool_calls": 3,
                           "elapsed_sec": round(time.monotonic() - started, 6),
                           "token_usage": None},
            "limitations": ["Verdi was not invoked by this read-only runner.",
                            "Architecture sensitivity variants require controlled DUT knobs.",
                            "ASIC PPA remains blocked without approved libraries and SDC."],
        }
        _write_json(output_path, result)
        return result


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    debug = commands.add_parser("debug")
    debug.add_argument("--log", required=True)
    debug.add_argument("--vcd")
    debug.add_argument("--signal", action="append", default=[])
    debug.add_argument("--clock-period-ticks", type=int)
    debug.add_argument("--context-cycles", type=int, default=4)
    debug.add_argument("--output", required=True)
    search = commands.add_parser("search")
    search.add_argument("--profile", required=True)
    search.add_argument("--source-revision", required=True)
    search.add_argument("--output", required=True)
    cost = commands.add_parser("cost")
    cost.add_argument("--failure", required=True)
    cost.add_argument("--budget", required=True)
    cost.add_argument("--history")
    cost.add_argument("--prior-results")
    cost.add_argument("--commands")
    cost.add_argument("--telemetry")
    cost.add_argument("--codex-baseline")
    cost.add_argument("--output", required=True)
    workflow = commands.add_parser("validate")
    workflow.add_argument("--log", required=True)
    workflow.add_argument("--seed", type=int, required=True)
    workflow.add_argument("--source-revision", required=True)
    workflow.add_argument("--known-fault", required=True)
    workflow.add_argument("--first-divergence-cycle", type=int, required=True)
    workflow.add_argument("--baseline-state", required=True,
                          help="JSON object, e.g. '{\"state\":\"ST_DONE\",\"done\":0}'")
    workflow.add_argument("--candidate-state", required=True)
    workflow.add_argument("--profile")
    workflow.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "debug":
        result = HierarchyAwareDebugger().analyze(
            Path(args.log).read_text(errors="replace"), args.signal,
            Path(args.vcd).read_text(errors="replace") if args.vcd else None,
            args.clock_period_ticks, args.context_cycles)
    elif args.command == "search":
        result = ArchitectureSearch().propose(_read_json(args.profile), args.source_revision)
    elif args.command == "cost":
        engine = CostAwareDecisionEngine()
        telemetry = _read_json(args.telemetry) if args.telemetry else None
        result = engine.plan(
            _read_json(args.failure), _read_json(args.budget),
            _read_json(args.history) if args.history else (),
            _read_json(args.prior_results) if args.prior_results else None,
            _read_json(args.commands) if args.commands else None, telemetry)
        if args.codex_baseline:
            result["efficiency_comparison"] = engine.compare_efficiency(
                (telemetry or {}).get("tasks", []),
                _read_json(args.codex_baseline).get("tasks", []))
    else:
        result = AgentWorkflowRunner().run(
            args.log, args.output, seed=args.seed,
            source_revision=args.source_revision, known_fault=args.known_fault,
            first_divergence_cycle=args.first_divergence_cycle,
            baseline_state=json.loads(args.baseline_state),
            candidate_state=json.loads(args.candidate_state),
            profile_path=args.profile)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    _write_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
