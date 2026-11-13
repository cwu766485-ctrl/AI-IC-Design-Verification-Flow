#!/usr/bin/env python3
"""Evidence gates and bounded decision support for RTL/PPA candidates."""
import fnmatch
import hashlib
import json
import math
from pathlib import Path, PurePosixPath


class OptimizationInputError(ValueError):
    pass


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _diff_paths(patch_path):
    paths = set()
    for line in Path(patch_path).read_text(errors="replace").splitlines():
        if not line.startswith("diff --git "):
            continue
        fields = line.split()
        if len(fields) != 4 or not fields[3].startswith("b/"):
            raise OptimizationInputError("malformed unified diff header")
        value = fields[3][2:]
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise OptimizationInputError("patch contains an unsafe path: " + value)
        paths.add(path.as_posix())
    if not paths:
        raise OptimizationInputError("candidate patch contains no file changes")
    return sorted(paths)


class QoRAnalyzer:
    """Require complete stage and provenance evidence before exposing QoR."""

    def analyze(self, evidence, metrics_document, required_metric_stages,
                required_stages, qor_report=None):
        blockers = []
        if not isinstance(evidence, dict) or evidence.get("status") != "PASS":
            blockers.append("baseline campaign status is not PASS")
        if not isinstance(evidence, dict) or not isinstance(evidence.get("source_revision"), str) or not evidence["source_revision"]:
            blockers.append("baseline source revision is missing")
        if not isinstance(metrics_document, dict) or not isinstance(metrics_document.get("metrics"), dict):
            blockers.append("metrics.json is missing a metrics mapping")
            metrics = {}
        else:
            metrics = metrics_document["metrics"]
        stage_records = evidence.get("stages", []) if isinstance(evidence, dict) else []
        stages = {item.get("stage"): item for item in stage_records if isinstance(item, dict)}
        required_stages = set(required_stages) | set(required_metric_stages.values())
        for stage_id in sorted(required_stages):
            if stages.get(stage_id, {}).get("status") != "PASS":
                blockers.append("required stage did not PASS: " + stage_id)
        metric_provenance = {}
        for metric_name, stage_id in sorted(required_metric_stages.items()):
            value = metrics.get(metric_name)
            if not _finite_number(value):
                blockers.append("required metric is missing or invalid: " + metric_name)
                continue
            stage = stages.get(stage_id, {})
            provenance = stage.get("metric_provenance", {}).get(metric_name)
            if (not isinstance(provenance, dict) or
                    not all(isinstance(provenance.get(key), str) and provenance[key]
                            for key in ("artifact", "parser_id", "parser_version"))):
                blockers.append("metric provenance is missing: " + metric_name)
                continue
            metric_provenance[metric_name] = provenance
        report = qor_report if isinstance(qor_report, dict) else {}
        critical_paths = report.get("critical_paths", [])
        area_hotspots = report.get("area_hotspots", [])
        if not isinstance(critical_paths, list) or not critical_paths or not all(
                isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id") and
                isinstance(item.get("artifact"), str) and item.get("artifact") and
                isinstance(item.get("sha256"), str) and len(item["sha256"]) == 64
                for item in critical_paths):
            blockers.append("structured critical-path evidence is unavailable")
        if not isinstance(area_hotspots, list) or not area_hotspots or not all(
                isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id") and
                isinstance(item.get("artifact"), str) and item.get("artifact") and
                isinstance(item.get("sha256"), str) and len(item["sha256"]) == 64
                for item in area_hotspots):
            blockers.append("structured area-hotspot evidence is unavailable")
        return {
            "baseline_valid": not blockers,
            "source_revision": evidence.get("source_revision") if isinstance(evidence, dict) else None,
            "metrics": {name: metrics[name] for name in required_metric_stages if name in metrics},
            "metric_provenance": metric_provenance,
            "critical_paths": critical_paths,
            "area_hotspots": area_hotspots,
            "blockers": blockers,
        }


class CandidateGenerator:
    REQUIRED_FIELDS = (
        "feature_id", "hypothesis", "target_hotspot", "intended_rtl_modification",
        "expected_ppa_improvement", "functional_risks", "timing_risks",
        "required_validation_stages", "validation_commands",
    )

    def generate(self, proposal, source_revision, patch_path, approved_patch_scope,
                 known_hotspots):
        if not isinstance(proposal, dict):
            raise OptimizationInputError("candidate proposal must be an object")
        missing = [key for key in self.REQUIRED_FIELDS if not proposal.get(key)]
        if missing:
            raise OptimizationInputError("candidate is missing fields: " + ", ".join(missing))
        for key in ("feature_id", "hypothesis", "target_hotspot", "intended_rtl_modification"):
            if not isinstance(proposal[key], str) or not proposal[key].strip():
                raise OptimizationInputError(key + " must be a nonempty string")
        if not isinstance(source_revision, str) or not source_revision:
            raise OptimizationInputError("source revision is required")
        patch_path = Path(patch_path).resolve()
        if not patch_path.is_file() or patch_path.stat().st_size == 0:
            raise OptimizationInputError("candidate patch is missing or empty")
        changed_paths = _diff_paths(patch_path)
        if not isinstance(approved_patch_scope, list):
            raise OptimizationInputError("approved patch scope must be a nonempty string list")
        scope = list(approved_patch_scope)
        if not scope or not all(isinstance(item, str) and item for item in scope):
            raise OptimizationInputError("approved patch scope must be a nonempty string list")
        outside = [path for path in changed_paths
                   if not any(fnmatch.fnmatchcase(path, pattern) for pattern in scope)]
        if outside:
            raise OptimizationInputError("candidate patch exceeds approved scope: " + ", ".join(outside))
        known_ids = {item.get("id") for item in known_hotspots if isinstance(item, dict)}
        if proposal["target_hotspot"] not in known_ids:
            raise OptimizationInputError("target hotspot is not present in QoR evidence")
        for key in ("functional_risks", "timing_risks", "required_validation_stages"):
            if not isinstance(proposal[key], list) or not all(isinstance(item, str) and item for item in proposal[key]):
                raise OptimizationInputError(key + " must be a nonempty string list")
        if not proposal["required_validation_stages"]:
            raise OptimizationInputError("candidate must declare validation stages")
        commands = proposal["validation_commands"]
        if not isinstance(commands, dict) or set(commands) != set(proposal["required_validation_stages"]):
            raise OptimizationInputError("validation_commands must map every required stage")
        for stage, argv in commands.items():
            if (not isinstance(argv, list) or not argv or
                    not all(isinstance(value, str) and value for value in argv)):
                raise OptimizationInputError("validation command argv must be a nonempty string list: " + stage)
        if not isinstance(proposal["expected_ppa_improvement"], dict) or not proposal["expected_ppa_improvement"]:
            raise OptimizationInputError("expected PPA improvement must be a metric mapping")
        for metric, target in proposal["expected_ppa_improvement"].items():
            if (not isinstance(metric, str) or not metric or not isinstance(target, dict) or
                    target.get("direction") not in ("lower", "higher") or
                    not _finite_number(target.get("target_pct")) or target["target_pct"] < 0):
                raise OptimizationInputError("PPA targets require a direction and finite nonnegative target_pct")
        return {
            "source_revision": source_revision,
            "patch_path": str(patch_path),
            "patch_sha256": _sha256(patch_path),
            "changed_paths": changed_paths,
            "approved_patch_scope": scope,
            **proposal,
        }


class OptimizationController:
    def decide(self, baseline, candidate, evaluation, comparison, budget):
        blockers = baseline.get("blockers", []) if isinstance(baseline, dict) else ["baseline analysis is missing"]
        stages = evaluation.get("stages", []) if isinstance(evaluation, dict) else []
        remaining = dict(budget or {})
        decision, reason = "STOP", "baseline or required evidence is incomplete"
        bounded = (_finite_number(remaining.get("candidates_remaining")) and
                   remaining["candidates_remaining"] > 0 and
                   _finite_number(remaining.get("runtime_sec")) and remaining["runtime_sec"] > 0 and
                   _finite_number(remaining.get("retries", 0)) and remaining.get("retries", 0) >= 0)
        required_stages = candidate.get("required_validation_stages", []) if isinstance(candidate, dict) else []
        stage_map = {item.get("stage"): item for item in stages if isinstance(item, dict)}
        missing_stages = [stage for stage in required_stages if stage not in stage_map]
        if (not blockers and isinstance(baseline, dict) and baseline.get("baseline_valid") is True and
                candidate and evaluation and bounded and not missing_stages and
                candidate.get("source_revision") == baseline.get("source_revision")):
            if evaluation.get("status") == "BLOCKED" or any(
                    stage_map.get(stage, {}).get("status") in ("BLOCKED", "SKIPPED")
                    for stage in required_stages):
                decision, reason = "STOP", "a mandatory validation gate is blocked or failed"
            elif evaluation.get("status") == "FAIL" or any(
                    stage_map.get(stage, {}).get("status") == "FAIL" for stage in required_stages):
                decision, reason = "REJECT", "candidate failed a required validation gate"
            elif evaluation.get("status") == "ERROR" or any(
                    stage_map.get(stage, {}).get("status") == "ERROR" for stage in required_stages):
                if remaining.get("retries", 0) > 0:
                    decision, reason = "RETRY", "evaluation errored and retry budget remains"
                else:
                    decision, reason = "STOP", "evaluation errored and retry budget is exhausted"
            elif any(stage_map.get(stage, {}).get("status") != "PASS" for stage in required_stages):
                decision, reason = "STOP", "a required validation stage has no passing result"
            elif evaluation.get("status") == "PASS":
                result = (comparison or {}).get("decision")
                if result == "ACCEPT":
                    decision, reason = "ACCEPT", "all gates passed and QoR comparison accepted the candidate"
                elif result in ("REJECT", "NO_IMPROVEMENT"):
                    decision, reason = "REJECT", "candidate did not meet the QoR objective"
                elif result in ("REVIEW_TRADEOFF", "CHANGE_STRATEGY"):
                    decision, reason = "CHANGE_STRATEGY", "measured evidence calls for a new optimization strategy"
                else:
                    decision, reason = "STOP", "comparison evidence is incomplete"
        elif not bounded:
            reason = "candidate or runtime budget is missing or exhausted"
        elif missing_stages:
            reason = "required candidate validation stages are missing or not PASS: " + ", ".join(missing_stages)
        elif isinstance(baseline, dict) and candidate and candidate.get("source_revision") != baseline.get("source_revision"):
            reason = "candidate source revision does not match the analyzed baseline"
        return {
            "decision": decision,
            "feature_id": candidate.get("feature_id") if isinstance(candidate, dict) else None,
            "evidence": list(blockers) + [reason],
            "proposed_change": candidate.get("intended_rtl_modification") if isinstance(candidate, dict) else None,
            "required_validation_stages": candidate.get("required_validation_stages", []) if isinstance(candidate, dict) else [],
            "required_validation_commands": candidate.get("validation_commands", {}) if isinstance(candidate, dict) else {},
            "expected_impact": candidate.get("expected_ppa_improvement") if isinstance(candidate, dict) else None,
            "remaining_budget": remaining,
        }


def summarize_benchmarks(campaigns, budget, telemetry=None, human_interventions=0):
    campaigns = list(campaigns)
    comparisons = [item.get("comparison", {}) for item in campaigns]
    evaluations = [item.get("evidence", {}) for item in campaigns]
    successful = sum(1 for item, comparison in zip(evaluations, comparisons)
                     if item.get("status") == "PASS" and comparison.get("decision") == "ACCEPT")
    metric_deltas = {name: [comparison.get("metrics", {}).get(name, {}).get("delta")
                            for comparison in comparisons]
                     for name in ("cell_area", "setup_wns", "int8_throughput")}
    stages = [stage for evidence in evaluations for stage in evidence.get("stages", [])]
    checkpoints = [item.get("checkpoint", {}) for item in campaigns]
    checkpoint_stages = [stage for checkpoint in checkpoints for stage in checkpoint.get("stages", [])]
    runs = [item.get("attempts", []) for item in campaigns]
    attempts = [attempt for group in runs for attempt in group]
    telemetry = telemetry or {}
    return {
        "candidate_count": len(campaigns),
        "successful_candidate_rate": successful / len(campaigns) if campaigns else None,
        "accepted_candidates": successful,
        "metric_deltas": metric_deltas,
        "functional_regressions": sum(1 for stage in stages
                                       if stage.get("stage") in ("regression", "reference_model") and
                                       stage.get("status") == "FAIL"),
        "total_eda_runtime_sec": (budget or {}).get("runtime_sec"),
        "cache_hits": sum(1 for stage in checkpoint_stages if stage.get("cache_hit") or stage.get("checkpoint_reuse")),
        "tool_invocations": sum(1 for attempt in attempts if attempt.get("event") == "START"),
        "agent_calls": telemetry.get("agent_calls"),
        "token_usage": telemetry.get("token_usage"),
        "human_interventions": human_interventions,
        "unavailable_telemetry": [key for key in ("agent_calls", "token_usage") if key not in telemetry],
    }
