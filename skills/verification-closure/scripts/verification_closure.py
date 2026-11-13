#!/usr/bin/env python3
"""Traceable verification planning and bounded coverage-closure helpers."""
import argparse
import datetime
import hashlib
import html
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import time
from pathlib import Path


class PlanError(ValueError):
    pass


def yaml_load(path):
    try:
        import yaml
    except ImportError:
        ruby = shutil.which("ruby")
        if not ruby:
            raise PlanError("YAML parser unavailable: install PyYAML or Ruby")
        script = "require 'yaml'; require 'json'; puts JSON.generate(YAML.safe_load(File.read(ARGV[0])))"
        result = subprocess.run([ruby, "-e", script, str(path)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True)
        if result.returncode:
            raise PlanError("invalid YAML: " + result.stderr.strip())
        value = json.loads(result.stdout)
    else:
        try:
            value = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise PlanError("invalid YAML: " + str(exc))
    if not isinstance(value, dict):
        raise PlanError("plan must be a YAML mapping")
    return value


def relpath(root, value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def plan_errors(plan, root):
    errors = []
    if plan.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not isinstance(plan.get("project"), str) or not plan["project"].strip():
        errors.append("project must be a nonempty string")
    for path in plan.get("spec_sources", []):
        if not relpath(root, path).is_file():
            errors.append("missing spec source: " + str(path))
    features = plan.get("features")
    if not isinstance(features, list) or not features:
        errors.append("features must be a nonempty list")
        features = []
    ids = set()
    known_tests = set()
    for feature in features:
        if not isinstance(feature, dict):
            errors.append("each feature must be a mapping")
            continue
        fid = feature.get("id")
        if not isinstance(fid, str) or not fid:
            errors.append("feature id is required")
        elif fid in ids:
            errors.append("duplicate id: " + fid)
        else:
            ids.add(fid)
        if not feature.get("name"):
            errors.append(str(fid) + ": name is required")
        refs = feature.get("spec_refs", [])
        if not refs:
            errors.append(str(fid) + ": at least one spec_ref is required")
        for ref in refs:
            if not isinstance(ref, dict) or not ref.get("file") or not ref.get("contains"):
                errors.append(str(fid) + ": spec_ref needs file and contains")
                continue
            path = relpath(root, ref["file"])
            if not path.is_file():
                errors.append(str(fid) + ": missing spec reference file " + str(ref["file"]))
            elif ref["contains"] not in path.read_text(errors="replace"):
                errors.append(str(fid) + ": spec phrase not found in " + str(ref["file"]) + ": " + ref["contains"])
        points = feature.get("testpoints", [])
        if not points:
            errors.append(str(fid) + ": at least one testpoint is required")
        for point in points:
            if not isinstance(point, dict):
                errors.append(str(fid) + ": testpoint must be a mapping")
                continue
            tid = point.get("id")
            if not isinstance(tid, str) or not tid:
                errors.append(str(fid) + ": testpoint id is required")
            elif tid in ids:
                errors.append("duplicate id: " + tid)
            else:
                ids.add(tid)
            if not point.get("stimulus"):
                errors.append(str(tid) + ": stimulus is required")
            tests = point.get("tests", [])
            if not isinstance(tests, list) or not tests or not all(isinstance(x, str) and x for x in tests):
                errors.append(str(tid) + ": tests must be a nonempty string list")
            else:
                known_tests.update(tests)
            checker = point.get("checker", {})
            if not isinstance(checker, dict) or not checker.get("id") or not checker.get("kind") or not checker.get("description"):
                errors.append(str(tid) + ": checker needs id, kind, and description")
            else:
                cid = checker["id"]
                if cid in ids:
                    errors.append("duplicate id: " + cid)
                ids.add(cid)
                if checker.get("scope") not in ("protocol_VIP", "DUT_protocol", "DUT_business", "system_business"):
                    errors.append(str(tid) + ": checker scope must distinguish protocol from DUT behavior")
            goals = point.get("coverage", [])
            if not isinstance(goals, list) or not goals:
                errors.append(str(tid) + ": coverage goals are required")
            for goal in goals:
                if (not isinstance(goal, dict) or not goal.get("group") or not goal.get("point") or
                        not isinstance(goal.get("bins"), list) or not goal["bins"] or
                        not all(isinstance(x, str) and x for x in goal["bins"])):
                    errors.append(str(tid) + ": every coverage goal needs group, point, and bins")
            if point.get("disposition") == "unreachable" and not all(point.get(k) for k in ("rationale", "reviewer")):
                errors.append(str(tid) + ": unreachable needs rationale and reviewer")
    closure = plan.get("closure")
    commands = closure.get("regression_commands") if isinstance(closure, dict) else None
    if not (isinstance(closure, dict) and
            ((isinstance(closure.get("regression_command"), list) and closure["regression_command"]) or
             (isinstance(commands, list) and commands and all(isinstance(x, dict) and isinstance(x.get("argv"), list) and x["argv"] for x in commands)))):
        errors.append("closure needs regression_command or regression_commands with argv lists")
    elif not isinstance(closure.get("seeds"), list) or not closure["seeds"]:
        errors.append("closure.seeds must be a nonempty list")
    else:
        tests = list(closure.get("expected_tests", []))
        for command in closure.get("regression_commands", []):
            tests.extend(command.get("expected_tests", []))
        if tests and not set(tests).issubset(known_tests):
            errors.append("closure.expected_tests includes test names not mapped to testpoints")
    budgets = closure.get("budgets", {}) if isinstance(closure, dict) else {}
    for field, limit in (("max_campaigns", 3), ("max_seeds", 20), ("max_new_tests", 3), ("max_runtime_sec", 7200), ("per_seed_timeout_sec", 1800)):
        value = budgets.get(field, limit)
        if not isinstance(value, int) or value < 1 or value > limit:
            errors.append("closure.budgets." + field + " must be between 1 and " + str(limit))
    return errors


def source_hashes(plan, root):
    paths = set()
    include_dirs = set()
    for value in plan.get("source_hashes", {}):
        normalized = value.split(">/", 1)[1] if value.startswith("<") and ">/" in value else value
        paths.add(relpath(root, normalized))
    for value in plan.get("spec_sources", []):
        paths.add(relpath(root, value))
    for value in plan.get("rtl_sources", []):
        paths.add(relpath(root, value))
    active = set()
    def add_filelist(value, base):
        filelist = relpath(base, value)
        if filelist in active or not filelist.is_file():
            return
        active.add(filelist)
        paths.add(filelist)
        tokens = []
        for raw in filelist.read_text(errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "//")):
                continue
            tokens.extend(shlex.split(line, comments=True))
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in ("-f", "-F") and index + 1 < len(tokens):
                index += 1
                add_filelist(tokens[index], filelist.parent)
            elif token.startswith(("-f", "-F")):
                add_filelist(token[2:], filelist.parent)
            elif token.startswith("+incdir+"):
                for directory in token[len("+incdir+"):].split("+"):
                    include_dirs.add(relpath(filelist.parent, directory))
            elif not token.startswith(("+", "-")):
                source = relpath(filelist.parent, token)
                if source.is_file():
                    paths.add(source)
            index += 1
        active.remove(filelist)
    for value in plan.get("source_filelists", []):
        add_filelist(value, root)
    for feature in plan.get("features", []):
        for ref in feature.get("spec_refs", []):
            paths.add(relpath(root, ref["file"]))
        for point in feature.get("testpoints", []):
            source = point.get("checker", {}).get("source")
            if source:
                paths.add(relpath(root, source))
    pending = [path for path in paths if path.is_file()]
    scanned = set()
    include_pattern = re.compile(r"(?m)^\s*`include\s+\"([^\"]+)\"")
    while pending:
        source = pending.pop()
        if source in scanned:
            continue
        scanned.add(source)
        if source.suffix.lower() not in (".v", ".sv", ".vh", ".svh"):
            continue
        for name in include_pattern.findall(source.read_text(errors="replace")):
            candidates = [source.parent / name] + [directory / name for directory in include_dirs]
            included = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
            if included is not None and included not in paths:
                paths.add(included)
                pending.append(included)
    return {str(path): digest(path) for path in sorted(paths) if path.is_file()}


def normalized_plan(plan, root, plan_path):
    return {"schema_version": plan["schema_version"], "project": plan["project"],
            "plan_source": str(plan_path.resolve()), "project_root": str(root.resolve()),
            "source_revision": plan.get("source_revision"),
            "plan_sha256": digest(plan_path), "source_hashes": source_hashes(plan, root),
            "features": plan["features"], "closure": plan["closure"]}


def render_markdown(data):
    lines = ["# Verification Plan: " + data["project"], "",
             "Source revision: `" + str(data.get("source_revision") or "from project Git worktree") + "`", "",
             "Plan SHA256: `" + data["plan_sha256"] + "`", "",
             "| Feature | Spec reference | Testpoint | Stimulus | Test(s) | Checker | Coverage goals |", "|---|---|---|---|---|---|---|"]
    for feature in data["features"]:
        refs = "; ".join(r["file"] + " — “" + r["contains"] + "”" for r in feature.get("spec_refs", []))
        for point in feature["testpoints"]:
            checker = point["checker"]
            coverage = "; ".join(g["group"] + "." + g["point"] + ": " + ", ".join(g["bins"]) for g in point["coverage"])
            cells = [feature["id"] + " " + feature["name"], refs,
                     point["id"] + " (" + point.get("status", "existing") + ")", point["stimulus"],
                     ", ".join(point["tests"]), checker["id"] + " " + checker["kind"] + "/" + checker["scope"] + ": " + checker["description"], coverage]
            lines.append("| " + " | ".join(x.replace("|", "\\|").replace("\n", " ") for x in cells) + " |")
    lines += ["", "## Closure budget", ""]
    commands = data["closure"].get("regression_commands") or [{"name": "regression", "argv": data["closure"]["regression_command"]}]
    for command in commands:
        lines.append("- " + command.get("name", "regression") + ": `" + " ".join(command["argv"]) + "`")
    lines += [
              "Seeds: `" + ", ".join(str(x) for x in data["closure"]["seeds"]) + "`",
              "Budgets: `" + json.dumps(data["closure"].get("budgets", {}), sort_keys=True) + "`", "",
              "A planned or unmeasured goal is not closed. Protocol VIP checks and DUT business checkers remain separate.", ""]
    return "\n".join(lines)


def plan_command(args):
    root = Path(args.project_root).resolve()
    source = Path(args.plan)
    if not source.is_absolute():
        source = (root / source).resolve()
    plan = yaml_load(source)
    errors = plan_errors(plan, root)
    if errors:
        raise PlanError("\n".join(errors))
    data = normalized_plan(plan, root, source)
    out = Path(args.out_dir)
    if not out.is_absolute():
        out = (root / out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "verification-plan.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (out / "verification-plan.md").write_text(render_markdown(data))
    print(json.dumps({"status": "PASS", "plan": str(out / "verification-plan.json"),
                      "markdown": str(out / "verification-plan.md"), "features": len(data["features"]),
                      "source_hashes": data["source_hashes"]}, indent=2))


def git_info(root):
    def run(*argv):
        p = subprocess.run(["git", "-C", str(root)] + list(argv), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True)
        return p.stdout.strip() if p.returncode == 0 else None
    return {"sha": run("rev-parse", "HEAD"), "working_tree": run("status", "--porcelain")}


def tool_versions(runs):
    text = "\n".join(Path(run["log"]).read_text(errors="replace") for run in runs
                     if run.get("log") and Path(run["log"]).is_file())
    versions = {}
    for name, pattern in (("vcs", r"VCS Coverage Metrics Release\s+([^\s]+)"),
                          ("urg", r"URG Version\s+([^\s]+)")):
        match = re.search(pattern, text, re.I)
        if match:
            versions[name] = match.group(1)
    return versions


def analyzer(plan, evidence, coverage):
    closure = plan.get("closure", {})
    pass_patterns = [re.compile(x) for x in closure.get("pass_patterns", [])]
    fail_patterns = [re.compile(x) for x in closure.get("fail_patterns", [])]
    runs_by_test = {}
    expected_names = list(closure.get("expected_tests", []))
    for command in closure.get("regression_commands", []):
        expected_names.extend(command.get("expected_tests", []))
    for run in evidence.get("runs", []):
        runs_by_test.setdefault(run.get("test"), []).append(run)
        if run.get("test") == "*":
            command_spec = next((item for item in closure.get("regression_commands", [])
                                 if item.get("name") == run.get("command_name")), None)
            mapped_names = (command_spec.get("expected_tests", []) if command_spec else
                            expected_names if not run.get("command_name") else [])
            for test_name in mapped_names:
                runs_by_test.setdefault(test_name, []).append(run)
    all_log_text = "\n".join(Path(x["log"]).read_text(errors="replace") for x in evidence.get("runs", []) if x.get("log") and Path(x["log"]).is_file())
    global_fail = [p.pattern for p in fail_patterns if p.search(all_log_text)]
    missing_pass = [p.pattern for p in pass_patterns if not p.search(all_log_text)]
    checker_metrics = evidence.get("checkers", {})
    bin_metrics = coverage.get("coverage_bins", {})
    coverage_groups = set(coverage.get("coverage_groups", []))
    run_failures = [{"command_name": run.get("command_name"), "status": run.get("status"),
                     "return_code": run.get("return_code"), "reason": run.get("reason")}
                    for run in evidence.get("runs", []) if run.get("status") not in (None, "PASS")]
    findings = []
    for feature in plan["features"]:
        for point in feature["testpoints"]:
            mapped_runs = [run for test in point["tests"] for run in runs_by_test.get(test, [])]
            if not mapped_runs:
                findings.append({"feature_id": feature["id"], "testpoint_id": point["id"],
                                 "classification": "missing_stimulus", "detail": "no run evidence for mapped test(s)"})
                continue
            bad_runs = [r for r in mapped_runs if r.get("status") not in (None, "PASS") or
                        (r.get("return_code") is not None and r.get("return_code") != 0)]
            if bad_runs or global_fail:
                findings.append({"feature_id": feature["id"], "testpoint_id": point["id"],
                                 "classification": "run_failure", "detail": "regression exit/severity gate failed"})
                continue
            checker_id = point["checker"]["id"]
            checker = checker_metrics.get(checker_id)
            if checker is None or checker.get("attempts") is None:
                findings.append({"feature_id": feature["id"], "testpoint_id": point["id"],
                                 "classification": "missing_checker_evidence",
                                 "detail": "checker attempt/failure evidence missing for " + checker_id})
            elif checker.get("failures", 0):
                findings.append({"feature_id": feature["id"], "testpoint_id": point["id"],
                                 "classification": "checker_failure", "detail": checker})
            elif checker.get("attempts", 0) == 0:
                findings.append({"feature_id": feature["id"], "testpoint_id": point["id"],
                                 "classification": "missing_checker", "detail": "checker had no real attempts"})
            for goal in point["coverage"]:
                for bin_name in goal["bins"]:
                    key = ".".join((goal["group"], goal["point"], bin_name))
                    metric = bin_metrics.get(key)
                    if metric is None or metric.get("total") is None:
                        if point.get("disposition") == "unreachable":
                            cls = "unreachable_unreviewed"
                            detail = "coverage metric missing: " + key
                        elif "coverage_groups" in coverage and goal["group"] not in coverage_groups:
                            cls = "missing_coverage_model"
                            detail = "coverage model group missing: " + goal["group"]
                        else:
                            cls = "unmeasured_coverage"
                            detail = "coverage metric missing: " + key
                    elif metric["hit"] >= metric["total"] and metric["total"] > 0:
                        continue
                    else:
                        cls = "unreachable" if point.get("disposition") == "unreachable" and point.get("reviewer") and point.get("rationale") else "missing_stimulus"
                        detail = {"bin": key, "hit": metric.get("hit"), "total": metric.get("total")}
                    findings.append({"feature_id": feature["id"], "testpoint_id": point["id"],
                                     "classification": cls, "detail": detail})
    return {"status": "PASS" if not findings and not global_fail and not missing_pass and not run_failures else "OPEN",
            "global_fail_patterns": global_fail, "missing_pass_patterns": missing_pass,
            "run_failures": run_failures, "findings": findings, "run_count": len(evidence.get("runs", [])),
            "coverage_bins": {key: bin_metrics[key] for key in sorted(bin_metrics)}}


def urg_coverage_metrics(plan, reports):
    goals = {}
    for feature in plan.get("features", []):
        for point in feature.get("testpoints", []):
            for goal in point.get("coverage", []):
                goals.setdefault((goal["group"], goal["point"]), set()).update(goal["bins"])
    counts = {}
    for report in reports:
        for path in Path(report).glob("grp*.html"):
            content = path.read_text(errors="replace")
            title_match = re.search(r"<title>.*?Group\s*::\s*(.*?)</title>", content, re.I)
            if not title_match:
                continue
            group_name = html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip()
            for (group, point), bins in goals.items():
                if group_name != group and not group_name.endswith("::" + group):
                    continue
                pattern = r"User Defined Bins for\s+" + re.escape(point) + r"\b(.*?)</table>"
                for section in re.finditer(pattern, content, re.I | re.S):
                    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", section.group(1), re.I | re.S)
                    for row in rows:
                        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)
                        if len(cells) < 2:
                            continue
                        bin_name = html.unescape(re.sub(r"<[^>]+>", "", cells[0])).strip()
                        count_text = html.unescape(re.sub(r"<[^>]+>", "", cells[1])).strip()
                        if bin_name in bins and count_text.isdigit():
                            key = ".".join((group, point, bin_name))
                            counts[key] = max(counts.get(key, 0), int(count_text))
                cross_pattern = r"Automatically Generated Cross Bins for\s+" + re.escape(point) + r"\b(.*?)</table>"
                for section in re.finditer(cross_pattern, content, re.I | re.S):
                    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", section.group(1), re.I | re.S)
                    for row in rows:
                        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)
                        if len(cells) < 4:
                            continue
                        parts = [html.unescape(re.sub(r"<[^>]+>", "", cell)).strip() for cell in cells[:3]]
                        count_text = html.unescape(re.sub(r"<[^>]+>", "", cells[3])).strip()
                        bin_name = "_".join(parts)
                        if bin_name in bins and count_text.isdigit():
                            key = ".".join((group, point, bin_name))
                            counts[key] = max(counts.get(key, 0), int(count_text))
    return {key: {"hit": 1 if count > 0 else 0, "total": 1, "count": count}
            for key, count in counts.items()}


def urg_coverage_groups(reports):
    groups = set()
    for report in reports:
        for path in Path(report).glob("grp*.html"):
            content = path.read_text(errors="replace")
            match = re.search(r"<title>.*?Group\s*::\s*(.*?)</title>", content, re.I)
            if match:
                name = html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
                groups.add(name.split("::")[-1])
    return sorted(groups)


def analyze_command(args):
    plan_path = Path(args.plan).resolve()
    plan = yaml_load(plan_path)
    evidence = json.loads(Path(args.evidence).read_text())
    coverage = json.loads(Path(args.coverage_json).read_text()) if args.coverage_json else evidence
    if args.urg_report:
        merged = dict(coverage)
        merged_bins = dict(coverage.get("coverage_bins", {}))
        merged_bins.update(urg_coverage_metrics(plan, args.urg_report))
        merged["coverage_bins"] = merged_bins
        merged["coverage_groups"] = sorted(set(coverage.get("coverage_groups", [])) |
                                            set(urg_coverage_groups(args.urg_report)))
        coverage = merged
    result = analyzer(plan, evidence, coverage)
    result["plan_sha256"] = digest(plan_path)
    result["plan_hash_match"] = evidence.get("plan_sha256") == result["plan_sha256"]
    if not result["plan_hash_match"]:
        result["status"] = "OPEN"
        result["findings"].append({"classification": "plan_mismatch",
                                   "detail": "campaign evidence was generated from a different plan revision"})
    result["urg_reports"] = args.urg_report
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


def recommend_command(args):
    plan = yaml_load(Path(args.plan).resolve())
    analysis = json.loads(Path(args.analysis).read_text())
    closure = plan.get("closure", {})
    budget = args.remaining_budget
    if budget is None:
        configured = closure.get("budgets", {})
        budget = {"campaigns": configured.get("max_campaigns", 0),
                  "seeds": configured.get("max_seeds", 0),
                  "runtime_sec": configured.get("max_runtime_sec", 0),
                  "new_tests": configured.get("max_new_tests", 0)}
    budget_empty = (not any((budget.get("campaigns", 0), budget.get("seeds", 0),
                             budget.get("runtime_sec", 0), budget.get("new_tests", 0))))
    findings = analysis.get("findings", [])
    if analysis.get("status") == "PASS":
        decisions = [{"action": "STOP", "feature_id": None, "testpoint_id": None,
                      "evidence": ["all analyzed checks and planned coverage goals are closed"],
                      "proposed_change": "No source change; preserve the passing evidence baseline.",
                      "validation_commands": [], "expected_impact": "Keep the verified closure state unchanged.",
                      "remaining_budget": budget}]
    elif budget_empty:
        decisions = [{"action": "STOP", "feature_id": None, "testpoint_id": None,
                      "evidence": ["analysis remains open", "all configured closure budgets are exhausted"],
                      "proposed_change": "Request budget renewal after reviewing the open evidence.",
                      "validation_commands": [], "expected_impact": "No unbudgeted regression or source modification.",
                      "remaining_budget": budget}]
    else:
        actions = {"missing_stimulus": "ADD_STIMULUS", "coverage_miss": "ADD_STIMULUS",
                   "missing_coverage_model": "ADD_COVERAGE", "unmeasured_coverage": "ADD_COVERAGE",
                   "checker_failure": "INVESTIGATE_RTL", "run_failure": "INVESTIGATE_RTL",
                   "missing_checker_evidence": "FIX_CHECKER", "missing_checker": "FIX_CHECKER",
                   "unreachable_unreviewed": "REQUEST_SPEC_REVIEW", "unreachable": "REQUEST_SPEC_REVIEW",
                   "plan_mismatch": "STOP"}
        commands = []
        for item in closure.get("regression_commands", []):
            commands.append(" ".join(item.get("argv", [])))
        if not commands and closure.get("regression_command"):
            commands.append(" ".join(closure["regression_command"]))
        decisions = []
        for finding in findings:
            action = actions.get(finding.get("classification"), "INVESTIGATE_RTL")
            if action == "STOP":
                proposal = "Revalidate the verification plan and evidence hashes before generating changes."
            elif action == "ADD_COVERAGE":
                proposal = "Add a coverage sampler driven by the observed DUT response/status, then add a fixture proving each bin can be hit."
            elif action == "ADD_STIMULUS":
                proposal = "Add a directed testpoint stimulus for the uncovered behavior and retain its checker and coverage goal."
            elif action == "FIX_CHECKER":
                proposal = "Instrument or repair the mapped checker so attempts and failures come from actual checker evaluations."
            elif action == "REQUEST_SPEC_REVIEW":
                proposal = "Ask the spec owner to confirm reachability and document a reviewed disposition before waiving the goal."
            else:
                proposal = "Reproduce the failure with the recorded seed, inspect RTL and checker evidence, then propose a scoped fix."
            decisions.append({"action": action, "feature_id": finding.get("feature_id"),
                              "testpoint_id": finding.get("testpoint_id"),
                              "evidence": [finding.get("classification", "unknown"), finding.get("detail")],
                              "proposed_change": proposal, "validation_commands": commands,
                              "expected_impact": "Resolve this finding without weakening checks or excluding coverage.",
                              "remaining_budget": budget})
        if not decisions:
            decisions = [{"action": "STOP", "feature_id": None, "testpoint_id": None,
                          "evidence": ["analysis is open but contains no actionable finding"],
                          "proposed_change": "Review the analysis schema and required evidence sources.",
                          "validation_commands": commands, "expected_impact": "Avoid an unsupported automated edit.",
                          "remaining_budget": budget}]
    result = {"schema_version": 1, "analysis_status": analysis.get("status", "OPEN"),
              "decisions": decisions}
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))
    return 0


def safe_project_file(root, value):
    path = relpath(root, value)
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise PlanError("project path escapes project root: " + str(value))
    return path


def scaffold_command(args):
    root = Path(args.project_root).resolve()
    identifiers = (args.test_class, args.base_class, args.sequence_class)
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", value) for value in identifiers):
        raise PlanError("test, base, and sequence class names must be SystemVerilog identifiers")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$.]*", args.sequencer_expr):
        raise PlanError("sequencer expression may contain only identifiers and hierarchy dots")
    package = safe_project_file(root, args.package_file)
    include_dir = safe_project_file(root, args.include_dir)
    if not package.is_file():
        raise PlanError("UVM package file does not exist: " + str(package))
    rel_include = os.path.relpath(include_dir / (args.test_class + ".svh"), package.parent).replace(os.sep, "/")
    code = "\n".join([
        "class " + args.test_class + " extends " + args.base_class + ";",
        "    `uvm_component_utils(" + args.test_class + ")",
        "    function new(string name = \"" + args.test_class + "\", uvm_component parent = null);",
        "        super.new(name, parent);",
        "    endfunction",
        "    task run_phase(uvm_phase phase);",
        "        " + args.sequence_class + " seq;",
        "        phase.raise_objection(this);",
        "        seq = " + args.sequence_class + "::type_id::create(\"seq\");",
        "        seq.start(" + args.sequencer_expr + ");",
        "        // TODO: add the planned checker, expected outcome, and completion gate.",
        "        phase.drop_objection(this);",
        "    endtask",
        "endclass",
        ""])
    text = package.read_text()
    include_line = '`include "' + rel_include + '"'
    if include_line in text:
        raise PlanError("package already includes " + rel_include)
    match = re.search(r"(?m)^\s*endpackage\b", text)
    if not match:
        raise PlanError("could not find endpackage in " + str(package))
    patched = text[:match.start()] + "    " + include_line + "\n" + text[match.start():]
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / (args.test_class + ".svh")).write_text(code)
    (out / (args.test_class + ".package.patch")).write_text("--- " + str(package) + "\n+++ " + str(package) + "\n" + include_line + "\n")
    applied = False
    if args.apply:
        ledger_path = safe_project_file(root, args.ledger or "runs/verification-closure/budget.json")
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"campaigns": 0, "seeds": 0, "runtime_sec": 0, "new_tests": 0}
        limit = 3
        if args.plan:
            plan_file = Path(args.plan)
            if not plan_file.is_absolute():
                plan_file = (root / plan_file).resolve()
            limit = yaml_load(plan_file).get("closure", {}).get("budgets", {}).get("max_new_tests", limit)
        if ledger.get("new_tests", 0) + 1 > limit:
            raise PlanError("new-test budget exhausted")
        generated = include_dir / (args.test_class + ".svh")
        if generated.exists():
            raise PlanError("generated test already exists: " + str(generated))
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text(code)
        package.write_text(patched)
        ledger["new_tests"] = ledger.get("new_tests", 0) + 1
        ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
        applied = True
    print(json.dumps({"status": "PASS", "applied": applied, "test": args.test_class,
                      "draft": str(out / (args.test_class + ".svh")), "package": str(package),
                      "include": include_line}, indent=2))


def substitute(argv, seed, run_dir, seed_dir=None, root=None, cwd=None):
    seed_dir = seed_dir or run_dir.parent
    cwd_path = Path(cwd or root or Path.cwd()).resolve()
    replacements = {"{seed}": str(seed), "{run_dir}": str(run_dir), "{seed_dir}": str(seed_dir),
                   "{run_dir_rel}": os.path.relpath(run_dir, cwd_path),
                   "{seed_dir_rel}": os.path.relpath(seed_dir, cwd_path)}
    return [re.sub("|".join(re.escape(k) for k in sorted(replacements, key=len, reverse=True)),
                   lambda match: replacements[match.group(0)], arg) for arg in argv]


def expand_globs(argv, cwd=None):
    expanded = []
    for arg in argv:
        pattern = arg
        if cwd and not os.path.isabs(pattern):
            pattern = str(Path(cwd) / pattern)
        matches = sorted(__import__("glob").glob(pattern)) if any(c in arg for c in "*?[") else []
        expanded.extend(matches if matches else [arg])
    return expanded


def resolve_tool(argv, env):
    if not argv or "/" in argv[0] or shutil.which(argv[0], path=env.get("PATH")):
        return argv
    for key in ("VCS_HOME", "DC_HOME", "VERDI_HOME", "SPYGLASS_HOME", "VC_FORMAL_HOME", "TESTMAX_HOME"):
        home = env.get(key)
        candidate = Path(home) / "bin" / argv[0] if home else None
        if candidate and candidate.is_file() and os.access(str(candidate), os.X_OK):
            return [str(candidate)] + argv[1:]
    return argv


def close_command(args):
    root = Path(args.project_root).resolve()
    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = (root / plan_path).resolve()
    plan = yaml_load(plan_path)
    errors = plan_errors(plan, root)
    if errors:
        raise PlanError("\n".join(errors))
    closure = plan["closure"]
    budgets = closure.get("budgets", {})
    max_seeds = min(args.max_seeds or len(closure["seeds"]), budgets.get("max_seeds", 20))
    seeds = closure["seeds"][:max_seeds]
    per_seed_timeout = args.timeout_sec or budgets.get("per_seed_timeout_sec", 1800)
    if per_seed_timeout > budgets.get("per_seed_timeout_sec", 1800):
        raise PlanError("timeout exceeds per_seed_timeout_sec budget")
    commands = closure.get("regression_commands") or [{"name": "regression", "argv": closure["regression_command"],
                                                         "expected_tests": closure.get("expected_tests", [])}]
    if not args.execute:
        print(json.dumps({"status": "NOT_RUN", "commands": commands,
                          "seeds": seeds, "per_seed_timeout_sec": per_seed_timeout,
                          "budgets": budgets}, indent=2))
        return 0
    eda_scripts = Path(__file__).resolve().parents[3] / "skills/eda-tool-engineering/scripts"
    if str(eda_scripts) not in sys.path:
        sys.path.insert(0, str(eda_scripts))
    from eda_runtime import _attempts_charged, _path_fingerprint, execute_plan
    from stage_runtime import cache_lock, save_json

    run_id = args.run_id or (Path(args.out_dir).name if args.resume and args.out_dir else
                             datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ"))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
        raise PlanError("run id may contain only letters, numbers, _, . or -")
    out = Path(args.out_dir) if args.out_dir else Path("runs/verification-closure") / run_id
    if not out.is_absolute():
        out = (root / out).resolve()
    checkpoint_path = out / "checkpoint.json"
    if args.resume and not checkpoint_path.is_file():
        raise PlanError("resume requested but the R1 checkpoint is missing")
    if out.exists() and not args.resume:
        raise PlanError("campaign output already exists; pass --resume to reuse its R1 checkpoint")
    out.mkdir(parents=True, exist_ok=True)

    ledger_path = safe_project_file(root, args.ledger or "runs/verification-closure/budget.json")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    max_runtime = budgets.get("max_runtime_sec", 7200)
    worst_case = len(seeds) * per_seed_timeout
    with cache_lock(ledger_path.with_suffix(".lock")):
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
            "campaigns": 0, "seeds": 0, "runtime_sec": 0.0, "new_tests": 0,
            "reservations": {}}
        ledger.setdefault("reservations", {})
        reservation = ledger["reservations"].get(run_id)
        if args.resume:
            if reservation is None:
                raise PlanError("campaign budget reservation is missing; refusing an uncharged resume")
            reserved_runtime = float(reservation["runtime_sec"])
            charged = _attempts_charged(out / "attempts.jsonl")
            runtime_budget = max(0.0, reserved_runtime - charged)
            if runtime_budget <= 0:
                raise PlanError("campaign runtime reservation exhausted")
        else:
            if ledger["campaigns"] + 1 > budgets.get("max_campaigns", 3):
                raise PlanError("campaign budget exhausted")
            if ledger["seeds"] + len(seeds) > budgets.get("max_seeds", 20):
                raise PlanError("seed budget exhausted")
            if float(ledger["runtime_sec"]) + worst_case > max_runtime:
                raise PlanError("worst-case runtime would exceed campaign budget")
            ledger["campaigns"] += 1
            ledger["seeds"] += len(seeds)
            ledger["runtime_sec"] = float(ledger["runtime_sec"]) + worst_case
            reservation = {"runtime_sec": worst_case, "seeds": len(seeds)}
            ledger["reservations"][run_id] = reservation
            save_json(ledger_path, ledger)
            runtime_budget = worst_case

    commands = closure.get("regression_commands") or [{"name": "regression", "argv": closure["regression_command"],
                                                         "expected_tests": closure.get("expected_tests", [])}]
    coverage_commands = closure.get("coverage_commands", [])
    if not coverage_commands and closure.get("coverage_command"):
        coverage_commands = [{"name": "coverage", "argv": closure["coverage_command"]}]
    eda_bins = [str(Path(os.environ[key]) / "bin") for key in ("VCS_HOME", "DC_HOME")
                if os.environ.get(key) and (Path(os.environ[key]) / "bin").is_dir()]
    inherited_path = os.environ.get("PATH", "")
    stage_path = os.pathsep.join(eda_bins + [inherited_path])
    stage_defs, stage_meta, coverage_reports = [], {}, []
    vdb_inputs = {seed: set() for seed in seeds}
    process_stages_per_seed = max(1, len(commands) + len(coverage_commands))
    stage_timeout = max(1, int(per_seed_timeout / process_stages_per_seed))
    for seed in seeds:
        seed_dir = out / ("seed-" + str(seed))
        for index, command_spec in enumerate(commands):
            name = command_spec.get("name") or ("regression-" + str(index + 1))
            stage_dir = seed_dir / name
            stage_dir.mkdir(parents=True, exist_ok=True)
            cwd_path = safe_project_file(root, command_spec.get("cwd", "."))
            argv = expand_globs(substitute(command_spec["argv"], seed, stage_dir, seed_dir, root, cwd_path), cwd_path)
            env = {"SEED": str(seed), "COV_ROOT": str(stage_dir / "vdb"),
                   "VC_RUN_DIR": str(stage_dir), "PATH": stage_path}
            argv = resolve_tool(argv, dict(os.environ, **env))
            safe_seed = str(seed).replace("-", "neg")
            stage_id = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") + "_s" + safe_seed
            stage = {"id": stage_id, "name": stage_id, "kind": "command", "stage_kind": "regression",
                     "adapter_id": "project.verification.regression.v1", "command": argv,
                     "cwd": str(cwd_path), "log_name": str(stage_dir / "regression.log"),
                     "timeout": stage_timeout, "seed": seed, "environment": env,
                     "expected_tests": command_spec.get("expected_tests", []),
                     "pass_patterns": command_spec.get("pass_patterns", closure.get("pass_patterns", [])),
                     "fail_patterns": command_spec.get("fail_patterns", closure.get("fail_patterns", [])),
                     "requires": [], "dependencies": []}
            cov_root = Path(env["COV_ROOT"])
            artifact_paths = {cov_root} if any("COV_ROOT" in arg for arg in command_spec["argv"]) else set()
            for raw_arg in command_spec["argv"]:
                if ".vdb" not in raw_arg.lower():
                    continue
                expanded = substitute([raw_arg], seed, stage_dir, seed_dir, root, cwd_path)[0]
                candidate = Path(expanded.split("=", 1)[-1])
                candidate = (cwd_path / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
                if any(char in str(candidate) for char in "*?["):
                    candidate = candidate.parent
                artifact_paths.add(candidate)
            vdb_inputs[seed].update(artifact_paths)
            stage_defs.append(stage)
            stage_meta[stage_id] = {"seed": seed, "test": "*", "command_name": name}

        regression_ids = [stage["id"] for stage in stage_defs if stage_meta[stage["id"]]["seed"] == seed]
        for command_spec in coverage_commands:
            name = command_spec.get("name") or "coverage"
            stage_dir = seed_dir / name
            stage_dir.mkdir(parents=True, exist_ok=True)
            cwd_path = safe_project_file(root, command_spec.get("cwd", "."))
            argv = expand_globs(substitute(command_spec["argv"], seed, stage_dir, seed_dir, root, cwd_path), cwd_path)
            argv = resolve_tool(argv, dict(os.environ, PATH=stage_path))
            safe_seed = str(seed).replace("-", "neg")
            stage_id = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") + "_s" + safe_seed
            report_dir = stage_dir / "report"
            command_stage = {"id": stage_id, "name": stage_id, "kind": "command", "stage_kind": "coverage",
                             "adapter_id": "project.verification.coverage.v1", "command": argv,
                             "cwd": str(cwd_path), "log_name": str(stage_dir / "coverage.log"),
                             "timeout": stage_timeout, "seed": seed,
                             "environment": {"SEED": str(seed), "PATH": stage_path},
                             "cache_inputs": [str(path) for path in sorted(vdb_inputs[seed], key=str)],
                             "artifacts": [str(report_dir)], "requires": regression_ids,
                             "dependencies": regression_ids}
            stage_defs.append(command_stage)
            stage_meta[stage_id] = {"seed": seed, "test": "*", "command_name": name}
            report_id = "parse_" + stage_id
            report = {"id": report_id, "name": report_id,
                      "kind": "coverage_summary", "stage_kind": "coverage_analysis",
                      "adapter_id": "project.verification.coverage-summary.v1",
                      "report_dir": str(report_dir), "artifact": str(stage_dir / "coverage-metrics.json"),
                      "functional": False, "seed": seed, "requires": [stage_id],
                      "dependencies": [stage_id]}
            stage_defs.append(report)
            stage_meta[report["id"]] = {"seed": seed, "test": "*", "command_name": "parse_" + name}
            coverage_reports.append(str(report_dir))

    def import_cache_inputs():
        paths = {plan_path.resolve()}
        paths.update(Path(path).resolve() for path in source_hashes(plan, root))
        return sorted(path for path in paths if path.is_file())

    revision = git_info(root)
    if not revision.get("sha"):
        revision["sha"] = plan.get("source_revision") or "unknown"
    source_map = {Path(path).relative_to(root).as_posix(): value
                  for path, value in source_hashes(plan, root).items()}
    source_tree = hashlib.sha256(json.dumps({"plan": digest(plan_path), "sources": source_map},
                                             sort_keys=True).encode()).hexdigest()
    project_record = {"name": plan["project"], "source_revision": revision["sha"],
                      "source_tree_sha256": source_tree,
                      "ordered_sources": sorted(source_map),
                      "filelists": plan.get("source_filelists", [])}
    started = time.time()
    resume = json.loads(checkpoint_path.read_text()) if args.resume else None
    records = execute_plan(stage_defs, out, True, resume, root=root, run_id=run_id,
                           project=project_record, cache_inputs=import_cache_inputs(),
                           budget_seconds=runtime_budget)
    elapsed = round(time.time() - started, 6)
    runs = []
    for record in records:
        if record.get("id") not in stage_meta or record.get("kind") == "coverage_summary":
            continue
        item = {**stage_meta[record["id"]], "status": record.get("status"),
                "return_code": record.get("return_code"), "log": record.get("log"),
                "command": record.get("command"), "elapsed_sec": record.get("elapsed_sec", 0),
                "reason": record.get("reason"), "error_class": record.get("error_class"),
                "missing_tests": record.get("missing_tests", []),
                "failed_patterns": record.get("failed_patterns", [])}
        runs.append(item)
    checkers = {}
    checker_pattern = re.compile(r"CHECKER_EVIDENCE\s+id=([A-Za-z0-9_-]+)\s+attempts=(\d+)\s+failures=(\d+)")
    for item in runs:
        if not item.get("log") or not Path(item["log"]).is_file():
            continue
        for match in checker_pattern.finditer(Path(item["log"]).read_text(errors="replace")):
            data = checkers.setdefault(match.group(1), {"attempts": 0, "failures": 0})
            data["attempts"] += int(match.group(2))
            data["failures"] += int(match.group(3))
    tool_records = [item for item in runs if item.get("log")]
    campaign_status = "PASS" if records and all(x.get("status") == "PASS" for x in records) else next(
        (x.get("status") for x in records if x.get("status") in ("FAIL", "ERROR", "BLOCKED")), "NOT_RUN")
    coverage_bins = urg_coverage_metrics(plan, coverage_reports)
    coverage_groups = urg_coverage_groups(coverage_reports)
    campaign = {"campaign_id": run_id, "project": plan["project"], "plan_sha256": digest(plan_path),
                "git": revision, "source_revision": plan.get("source_revision"),
                "source_hashes": source_map, "status": campaign_status, "runs": runs,
                "commands": commands, "seeds": seeds, "budgets": budgets,
                "tool_versions": tool_versions(tool_records), "checkers": checkers,
                "coverage_bins": coverage_bins, "coverage_groups": coverage_groups,
                "stage_records": records, "started_at": started, "finished_at": time.time(),
                "elapsed_sec": elapsed}
    closure_result = analyzer(plan, campaign, campaign)
    closure_result.update(plan_sha256=digest(plan_path), plan_hash_match=True,
                          urg_reports=coverage_reports)
    artifacts_by_path = {}
    for record in records:
        for artifact in record.get("artifacts", []):
            if artifact.get("exists") is False:
                continue
            artifacts_by_path[artifact["path"]] = artifact
    for seed, paths in vdb_inputs.items():
        for vdb_path in sorted(paths, key=str):
            fingerprints = _path_fingerprint([vdb_path])
            normalized = []
            for item in fingerprints:
                try:
                    relative = Path(item["path"]).relative_to(vdb_path.resolve()).as_posix()
                except ValueError:
                    raise PlanError("VCS coverage artifact resolves outside its VDB: " + item["path"])
                normalized.append({"path": relative, "size_bytes": item["size_bytes"],
                                   "sha256": item["sha256"]})
            inventory = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
            artifacts_by_path[str(vdb_path)] = {
                "path": str(vdb_path), "kind": "vcs_vdb", "exists": vdb_path.is_dir(),
                "cacheable": False, "files": len(normalized),
                "size_bytes": sum(item["size_bytes"] for item in normalized),
                "inventory_sha256": hashlib.sha256(inventory).hexdigest()}
    save_json(out / "evidence.json", campaign)
    save_json(out / "closure-analysis.json", closure_result)
    manifest = {"schema_version": 1, "run_id": run_id, "flow": "verification_closure",
                "project": plan["project"], "status": campaign_status,
                "closure_status": closure_result["status"], "source_revision": revision,
                "source_hashes": source_map, "plan_sha256": digest(plan_path),
                "plan_source": os.path.relpath(plan_path, root), "seeds": seeds,
                "budget_seconds": runtime_budget,
                "budget_charged_seconds": _attempts_charged(out / "attempts.jsonl"),
                "stages": records, "artifacts": [artifacts_by_path[key] for key in sorted(artifacts_by_path)],
                "failure_feedback": [{"stage_id": item.get("id"), "status": item.get("status"),
                                      "error_class": item.get("error_class"),
                                      "reason": item.get("reason"),
                                      "missing_tests": item.get("missing_tests", []),
                                      "failed_patterns": item.get("failed_patterns", [])}
                                     for item in records if item.get("status") != "PASS"]}
    save_json(out / "manifest.json", manifest)
    charged_runtime = _attempts_charged(out / "attempts.jsonl")
    with cache_lock(ledger_path.with_suffix(".lock")):
        ledger = json.loads(ledger_path.read_text())
        reservation = ledger.get("reservations", {}).get(run_id)
        if reservation and campaign_status == "PASS":
            ledger["runtime_sec"] = max(0.0, float(ledger["runtime_sec"]) -
                                        float(reservation["runtime_sec"]) + charged_runtime)
            ledger["seeds"] = max(0, int(ledger["seeds"]) - int(reservation["seeds"]) + len(seeds))
            ledger["reservations"].pop(run_id, None)
            save_json(ledger_path, ledger)
    print(json.dumps({"status": campaign_status, "closure_status": closure_result["status"],
                      "campaign": str(out), "evidence": str(out / "evidence.json"),
                      "manifest": str(out / "manifest.json"),
                      "closure_analysis": str(out / "closure-analysis.json"),
                      "remaining_budget_sec": max(0.0, runtime_budget - charged_runtime),
                      "failure_feedback": manifest["failure_feedback"]}, indent=2))
    return 0 if campaign_status == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(prog="verification_closure.py")
    sub = parser.add_subparsers(dest="command")
    plan = sub.add_parser("plan")
    plan.add_argument("--project-root", required=True)
    plan.add_argument("--plan", required=True)
    plan.add_argument("--out-dir", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--project-root", required=True)
    validate.add_argument("--plan", required=True)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--plan", required=True)
    analyze.add_argument("--evidence", required=True)
    analyze.add_argument("--coverage-json")
    analyze.add_argument("--urg-report", action="append", default=[])
    analyze.add_argument("--out")
    recommend = sub.add_parser("recommend")
    recommend.add_argument("--plan", required=True)
    recommend.add_argument("--analysis", required=True)
    recommend.add_argument("--remaining-budget", type=json.loads)
    recommend.add_argument("--out")
    scaffold = sub.add_parser("scaffold")
    scaffold.add_argument("--project-root", required=True)
    scaffold.add_argument("--test-class", required=True)
    scaffold.add_argument("--base-class", required=True)
    scaffold.add_argument("--sequence-class", required=True)
    scaffold.add_argument("--sequencer-expr", required=True)
    scaffold.add_argument("--package-file", required=True)
    scaffold.add_argument("--include-dir", required=True)
    scaffold.add_argument("--out-dir", required=True)
    scaffold.add_argument("--apply", action="store_true")
    scaffold.add_argument("--plan")
    scaffold.add_argument("--ledger")
    close = sub.add_parser("close")
    close.add_argument("--project-root", required=True)
    close.add_argument("--plan", required=True)
    close.add_argument("--out-dir")
    close.add_argument("--ledger")
    close.add_argument("--max-seeds", type=int)
    close.add_argument("--timeout-sec", type=int)
    close.add_argument("--run-id")
    close.add_argument("--resume", action="store_true")
    close.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "plan":
            plan_command(args)
            return 0
        if args.command == "validate":
            root = Path(args.project_root).resolve()
            path = Path(args.plan)
            if not path.is_absolute():
                path = (root / path).resolve()
            data = yaml_load(path)
            errors = plan_errors(data, root)
            print(json.dumps({"status": "BLOCKED" if errors else "PASS", "errors": errors}, indent=2))
            return 1 if errors else 0
        if args.command == "analyze":
            return analyze_command(args)
        if args.command == "recommend":
            return recommend_command(args)
        if args.command == "scaffold":
            scaffold_command(args)
            return 0
        if args.command == "close":
            return close_command(args)
        parser.error("command is required")
    except (PlanError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
