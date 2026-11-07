#!/usr/bin/env python3
"""Run bounded RTL candidate evaluations in isolated source snapshots."""
import argparse
import datetime
import fcntl
import fnmatch
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

EDA_SCRIPTS = Path(__file__).resolve().parents[2] / "eda-tool-engineering" / "scripts"
if str(EDA_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(EDA_SCRIPTS))
from stage_runtime import make_stage_input, run_process, save_json, validate_stage_result


STATUSES = {"PASS", "FAIL", "ERROR", "BLOCKED", "NOT_RUN", "SKIPPED"}
STAGE_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
CANDIDATE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


class PlanError(ValueError):
    pass


class BlockedError(PlanError):
    """The requested evaluation cannot safely or meaningfully proceed."""


def read_text(path, errors=None):
    with Path(path).open("r", errors=errors) as stream:
        return stream.read()


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        ruby = shutil.which("ruby")
        if not ruby:
            raise PlanError("YAML parser unavailable; install PyYAML or Ruby")
        script = "require 'yaml'; require 'json'; puts JSON.generate(YAML.safe_load(File.read(ARGV[0])))"
        result = subprocess.run([ruby, "-e", script, str(path)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True)
        if result.returncode:
            raise PlanError("invalid YAML: " + result.stderr.strip())
        data = json.loads(result.stdout)
    else:
        try:
            data = yaml.safe_load(Path(path).read_text())
        except yaml.YAMLError as exc:
            raise PlanError("invalid YAML: " + str(exc))
    if not isinstance(data, dict):
        raise PlanError("plan must be a YAML mapping")
    return data


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_tree(path):
    path = Path(path)
    if path.is_file():
        return sha256(path)
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise BlockedError("cannot hash symlinked asset: " + str(item))
        if item.is_file():
            rel = str(item.relative_to(path)).replace(os.sep, "/")
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(sha256(item).encode("ascii"))
            digest.update(b"\n")
    return digest.hexdigest()


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root)] + list(args), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
    return result.stdout.strip() if result.returncode == 0 else None


def git_state(root):
    sha = git(root, "rev-parse", "HEAD")
    if not sha:
        raise PlanError("project_root must be inside a Git worktree")
    status = git(root, "status", "--porcelain", "--untracked-files=all") or ""
    return {"sha": sha, "working_tree": status.splitlines(),
            "clean_for_snapshot": not bool(status.strip())}


def safe_project_path(root, value):
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise PlanError("project path escapes project_root: " + str(value))
    return resolved


def safe_relative_path(value, label):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise PlanError(label + " must be a safe relative path: " + str(value))
    return path


def expand_sources(root, patterns):
    found = []
    for pattern in patterns:
        absolute_pattern = str(root / pattern)
        matches = sorted(glob.glob(absolute_pattern, recursive=True))
        if not matches:
            raise PlanError("RTL scope pattern matched no files: " + pattern)
        for match in matches:
            path = Path(match).resolve()
            try:
                path.relative_to(root.resolve())
            except ValueError:
                raise PlanError("RTL source resolves outside project_root: " + match)
            if path.is_file() and path not in found:
                found.append(path)
    if not found:
        raise PlanError("RTL scope resolved to no files")
    return found


def ordered_source_files(root, field, values, errors):
    if not isinstance(values, list) or not values or not all(isinstance(x, str) and x for x in values):
        errors.append(field + " must be a nonempty ordered list of project-relative files")
        return []
    result = []
    for value in values:
        try:
            relative = safe_relative_path(value, field)
            resolved = (root / relative).resolve()
            resolved.relative_to(root.resolve())
            if not resolved.is_file():
                errors.append(field + " file is missing: " + value)
            else:
                result.append(resolved)
        except (PlanError, ValueError) as exc:
            errors.append(str(exc))
    if len(set(result)) != len(result):
        errors.append(field + " must not contain duplicate files")
    return result


def has_module(paths, module):
    pattern = re.compile(r"\bmodule\s+(?:automatic\s+)?" + re.escape(module) + r"\b")
    for path in paths:
        if pattern.search(read_text(path, errors="replace")):
            return True
    return False


def required_stage_ids(plan, candidate=False):
    required_cfg = plan.get("required_stages", {})
    required = list(required_cfg.get("candidate" if candidate else "baseline", [])) if isinstance(required_cfg, dict) else []
    behavior_cfg = plan.get("behavior_contract", "cycle_equivalent")
    behavior = behavior_cfg.get("type") if isinstance(behavior_cfg, dict) else behavior_cfg
    if candidate:
        required.append("formal" if behavior == "cycle_equivalent" else "reference_model")
        if behavior == "transaction_level":
            required.append("latency_gate")
    return list(dict.fromkeys(required))


def validate_plan(plan, root):
    errors = []
    if plan.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not isinstance(plan.get("project"), str) or not plan["project"].strip():
        errors.append("project must be a nonempty string")
    for field in ("design_top", "testbench_top"):
        value = plan.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", value):
            errors.append(field + " must be a valid HDL module identifier")
    rtl_order = ordered_source_files(root, "rtl_sources", plan.get("rtl_sources"), errors)
    testbench_order = ordered_source_files(root, "testbench_sources", plan.get("testbench_sources"), errors)
    scope = plan.get("rtl_scope")
    scoped_sources = []
    if not isinstance(scope, list) or not scope or not all(isinstance(x, str) and x for x in scope):
        errors.append("rtl_scope must be a nonempty list of project-relative patterns")
    else:
        try:
            scoped_sources = expand_sources(root, scope)
        except PlanError as exc:
            scoped_sources = []
            errors.append(str(exc))
    if rtl_order and any(path not in scoped_sources for path in rtl_order):
        errors.append("rtl_sources entries must be included by rtl_scope")
    if rtl_order and isinstance(plan.get("design_top"), str) and not has_module(rtl_order, plan["design_top"]):
        errors.append("design_top was not found in ordered rtl_sources")
    if testbench_order and isinstance(plan.get("testbench_top"), str) and not has_module(testbench_order, plan["testbench_top"]):
        errors.append("testbench_top was not found in ordered testbench_sources")
    allowed = plan.get("allowed_patch_paths")
    if not isinstance(allowed, list) or not allowed or not all(isinstance(x, str) and x for x in allowed):
        errors.append("allowed_patch_paths must list the RTL paths candidates may change")
    else:
        for pattern in allowed:
            if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                errors.append("allowed_patch_paths entries must stay inside project_root: " + pattern)
    behavior_cfg = plan.get("behavior_contract", "cycle_equivalent")
    if isinstance(behavior_cfg, dict):
        behavior = behavior_cfg.get("type")
    else:
        behavior = behavior_cfg
    if behavior not in ("cycle_equivalent", "transaction_level"):
        errors.append("behavior_contract must be cycle_equivalent or transaction_level")
    if behavior == "transaction_level":
        latency = plan.get("max_latency_cycles")
        if not isinstance(latency, int) or latency < 1:
            errors.append("transaction_level behavior requires max_latency_cycles >= 1")
    stages = plan.get("stages")
    if not isinstance(stages, list) or not stages:
        errors.append("stages must be a nonempty ordered list")
        stages = []
    stage_ids = set()
    for stage in stages:
        if not isinstance(stage, dict):
            errors.append("each stage must be a mapping")
            continue
        sid = stage.get("id")
        if not isinstance(sid, str) or not STAGE_RE.fullmatch(sid):
            errors.append("stage id must match " + STAGE_RE.pattern)
            continue
        if sid in stage_ids:
            errors.append("duplicate stage id: " + sid)
        stage_ids.add(sid)
        argv = stage.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
            errors.append(sid + ": argv must be a nonempty string list")
        adapter_id = stage.get("adapter_id")
        if not isinstance(adapter_id, str) or not adapter_id.strip():
            errors.append(sid + ": adapter_id must identify the stage adapter")
        timeout = stage.get("timeout_sec", 1800)
        if not isinstance(timeout, int) or timeout < 1 or timeout > 7200:
            errors.append(sid + ": timeout_sec must be between 1 and 7200")
        if not isinstance(stage.get("result_json"), str) or not stage["result_json"]:
            errors.append(sid + ": result_json path is required")
        cwd = stage.get("cwd", ".")
        try:
            safe_project_path(root, cwd)
        except PlanError as exc:
            errors.append(sid + ": " + str(exc))
        modes = stage.get("modes", ["baseline", "candidate"])
        if (not isinstance(modes, list) or not modes or
                not all(isinstance(x, str) for x in modes) or
                not set(modes).issubset({"baseline", "candidate"})):
            errors.append(sid + ": modes must contain baseline and/or candidate")
        pass_patterns = stage.get("pass_patterns", [])
        fail_patterns = stage.get("fail_patterns", [])
        for field in ("pass_patterns", "fail_patterns", "expected_artifacts"):
            values = stage.get(field, [])
            if not isinstance(values, list) or not all(isinstance(x, str) for x in values):
                errors.append(sid + ": " + field + " must be a list of strings")
        for pattern in ((pass_patterns if isinstance(pass_patterns, list) else []) +
                        (fail_patterns if isinstance(fail_patterns, list) else [])):
            try:
                re.compile(pattern)
            except (TypeError, re.error) as exc:
                errors.append(sid + ": invalid log pattern: " + str(exc))
    required_cfg = plan.get("required_stages")
    if not isinstance(required_cfg, dict):
        errors.append("required_stages must define baseline and candidate lists")
        required_cfg = {}
    for mode in ("baseline", "candidate"):
        required_ids = required_cfg.get(mode, [])
        if not isinstance(required_ids, list) or not all(isinstance(x, str) for x in required_ids):
            errors.append("required_stages." + mode + " must be a list of stage IDs")
            continue
        for sid in required_ids:
            if sid not in stage_ids:
                errors.append("required " + mode + " stage is missing: " + str(sid))
        for stage in stages:
            if isinstance(stage, dict) and stage.get("id") in required_ids and mode not in stage.get("modes", ["baseline", "candidate"]):
                errors.append("required stage " + stage.get("id", "?") + " is disabled for " + mode)
    candidate_list = required_cfg.get("candidate", [])
    candidate_required = list(candidate_list) if isinstance(candidate_list, list) else []
    candidate_required.extend(required_stage_ids(plan, candidate=True))
    for sid in candidate_required:
        if sid not in stage_ids:
            errors.append("required candidate stage is missing: " + str(sid))
        else:
            matching = next((stage for stage in stages if stage.get("id") == sid), {})
            if "candidate" not in matching.get("modes", ["baseline", "candidate"]):
                errors.append("required stage " + sid + " is disabled for candidate")
    evidence_stage_ids = set(candidate_required)
    for mode in ("baseline", "candidate"):
        mode_ids = required_cfg.get(mode, [])
        if isinstance(mode_ids, list):
            evidence_stage_ids.update(mode_ids)
    metric_rules = plan.get("metrics")
    if not isinstance(metric_rules, dict) or not metric_rules:
        errors.append("metrics must define the required baseline/candidate comparisons")
    else:
        for name, rule in metric_rules.items():
            if not isinstance(rule, dict) or rule.get("direction") not in ("lower", "higher"):
                errors.append(str(name) + ": metric direction must be lower or higher")
                continue
            if not isinstance(rule.get("unit"), str) or not rule["unit"]:
                errors.append(str(name) + ": metric unit is required")
            if not isinstance(rule.get("source_stage"), str) or rule.get("source_stage") not in stage_ids:
                errors.append(str(name) + ": source_stage must name a configured stage")
            elif rule.get("required", True):
                evidence_stage_ids.add(rule["source_stage"])
            for field in ("min_value", "max_value", "max_regression_pct"):
                value = rule.get(field)
                if value is not None and (not isinstance(value, (int, float)) or
                                          not math.isfinite(float(value)) or
                                          value < 0 and field.endswith("pct")):
                    errors.append(str(name) + ": invalid " + field)
            if "required" in rule and not isinstance(rule["required"], bool):
                errors.append(str(name) + ": required must be a boolean")
    for sid in evidence_stage_ids:
        matching = next((stage for stage in stages if isinstance(stage, dict) and stage.get("id") == sid), {})
        artifacts = matching.get("expected_artifacts", [])
        if not isinstance(artifacts, list) or not artifacts:
            errors.append("required evidence stage " + sid + " must declare expected_artifacts")
    budget = plan.get("budget", {})
    if not isinstance(budget, dict):
        errors.append("budget must be a mapping")
    else:
        for key, default, hard_limit in (("max_candidates", 4, 20),
                                         ("max_runtime_sec", 7200, 86400),
                                         ("max_total_runtime_sec", 28800, 604800)):
            value = budget.get(key, default)
            if not isinstance(value, int) or value < 1 or value > hard_limit:
                errors.append("budget." + key + " must be between 1 and " + str(hard_limit))
    assets = plan.get("read_only_assets", [])
    if not isinstance(assets, list):
        errors.append("read_only_assets must be a list")
    else:
        seen_targets = set()
        for asset in assets:
            if not isinstance(asset, dict) or not isinstance(asset.get("source"), str) or not isinstance(asset.get("target"), str):
                errors.append("each read_only_assets item must define source and target")
                continue
            source = Path(asset["source"])
            resolved = source.resolve() if source.is_absolute() else (root / source).resolve()
            if not resolved.exists():
                errors.append("missing read-only asset: " + str(asset["source"]))
            try:
                relative_target = safe_relative_path(asset["target"], "read_only_assets.target")
                if str(relative_target) in seen_targets:
                    errors.append("duplicate read-only asset target: " + asset["target"])
                seen_targets.add(str(relative_target))
                if (root / relative_target).exists():
                    errors.append("read-only asset target collides with a project path: " + asset["target"])
            except PlanError as exc:
                errors.append(str(exc))
    return errors


def apply_placeholders(value, mapping):
    pattern = re.compile("|".join(re.escape(x) for x in sorted(mapping, key=len, reverse=True)))
    return pattern.sub(lambda match: mapping[match.group(0)], value)


def safe_extract_archive(archive_bytes, destination):
    import io
    root = Path(destination).resolve()
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
        members = archive.getmembers()
        for member in members:
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise PlanError("git archive contains an unsafe path: " + member.name)
            if not (member.isdir() or member.isfile()):
                raise PlanError("git archive contains a non-regular entry: " + member.name)
        for member in members:
            target = root / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise PlanError("could not read source snapshot entry: " + member.name)
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(member.mode & 0o777)


def create_snapshot(project_root, revision, destination, read_only_assets):
    result = subprocess.run(["git", "-C", str(project_root), "archive", "--format=tar", revision],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise PlanError("could not create source snapshot: " + result.stderr.decode("utf-8", "replace"))
    Path(destination).mkdir(parents=True)
    safe_extract_archive(result.stdout, destination)
    asset_hashes = {}
    for asset in read_only_assets:
        source = Path(asset["source"])
        if not source.is_absolute():
            source = (project_root / source).resolve()
        target = Path(destination) / safe_relative_path(asset["target"], "read_only_assets.target")
        if target.exists() or target.is_symlink():
            raise PlanError("snapshot asset target already exists: " + str(target))
        copy_read_only_asset(source, target)
        asset_hashes[asset["target"]] = hash_tree(target)
    return asset_hashes


def copy_read_only_asset(source, target):
    """Copy assets into the isolated snapshot; never expose the originals to EDA tools."""
    source = Path(source)
    if source.is_symlink():
        raise BlockedError("read-only asset source may not be a symlink: " + str(source))
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(source), str(target))
        target.chmod(0o444)
        return
    if not source.is_dir():
        raise BlockedError("read-only asset is not a regular file or directory: " + str(source))
    target.mkdir(parents=True)
    copied_dirs = []
    for current, dirs, files in os.walk(str(source), followlinks=False):
        current_path = Path(current)
        rel = current_path.relative_to(source)
        dest_dir = target / rel
        copied_dirs.append(dest_dir)
        for name in list(dirs):
            item = current_path / name
            if item.is_symlink():
                raise BlockedError("read-only asset contains a symlink: " + str(item))
            (dest_dir / name).mkdir(exist_ok=True)
        for name in files:
            item = current_path / name
            if item.is_symlink() or not item.is_file():
                raise BlockedError("read-only asset contains a non-regular file: " + str(item))
            shutil.copyfile(str(item), str(dest_dir / name))
            (dest_dir / name).chmod(0o444)
    for dest_dir in reversed(copied_dirs):
        try:
            dest_dir.chmod(0o555)
        except OSError:
            pass


def check_patch_paths(patch_path, allowed_patterns):
    changed = []
    for line in read_text(patch_path, errors="replace").splitlines():
        if line.startswith("GIT binary patch") or line.startswith("Binary files "):
            raise BlockedError("binary candidate patches are not supported")
        if line.startswith("new file mode 120000") or line.startswith("old mode 120000") or line.startswith("new mode 120000"):
            raise BlockedError("candidate patches may not create or replace symlinks")
        if line.startswith("--- a/") or line.startswith("+++ b/"):
            name = line[6:].split("\t", 1)[0]
            if name == "/dev/null":
                continue
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise BlockedError("patch contains an unsafe path: " + name)
            if not any(fnmatch.fnmatch(name, pattern) or name.startswith(pattern.rstrip("/") + "/")
                       for pattern in allowed_patterns):
                raise BlockedError("patch changes a path outside allowed_patch_paths: " + name)
            changed.append(name)
    if not changed:
        raise BlockedError("patch contains no changed files")
    return sorted(set(changed))


def artifact_provenance(path, stage_dir):
    """Return content provenance for a nonempty in-stage artifact."""
    path = Path(path)
    if path.is_symlink():
        raise BlockedError("artifact may not be a symlink: " + str(path))
    path = ensure_within(path, stage_dir, "artifact")
    if path.is_file():
        size = path.stat().st_size
        if size == 0:
            raise BlockedError("artifact is empty: " + str(path))
        return {"path": str(path.relative_to(stage_dir)), "kind": "file",
                "size_bytes": size, "sha256": sha256(path)}
    if path.is_dir():
        files = [item for item in path.rglob("*") if item.is_file()]
        if not files:
            raise BlockedError("artifact directory is empty: " + str(path))
        if any(item.is_symlink() for item in path.rglob("*")):
            raise BlockedError("artifact directory contains a symlink: " + str(path))
        return {"path": str(path.relative_to(stage_dir)), "kind": "directory",
                "file_count": len(files),
                "size_bytes": sum(item.stat().st_size for item in files),
                "sha256": hash_tree(path)}
    raise BlockedError("artifact is not a regular file or directory: " + str(path))


def stage_artifact_path(value, mapping, stage_dir, label):
    target = Path(apply_placeholders(value, mapping))
    if not target.is_absolute():
        target = stage_dir / target
    root = Path(stage_dir).resolve()
    current = target
    while current != root and root in current.parents:
        if current.is_symlink():
            raise BlockedError(label + " may not traverse a symlink: " + str(current))
        current = current.parent
    if target == root and target.is_symlink():
        raise BlockedError(label + " may not be a symlink: " + str(target))
    return ensure_within(target, stage_dir, label)


def run_stage(stage, project_root, run_dir, candidate_root, source_manifest_path, seed=None, mode=None):
    stage_dir = run_dir / "stages" / stage["id"]
    stage_dir.mkdir(parents=True)
    cwd_value = stage.get("cwd", ".")
    cwd = ensure_within(candidate_root / cwd_value, candidate_root, "stage cwd")
    mapping = {"{project_root}": str(candidate_root), "{source_root}": str(candidate_root),
               "{candidate_root}": str(candidate_root), "{run_dir}": str(stage_dir),
               "{manifest}": str(source_manifest_path),
               "{seed}": str(seed if seed is not None else 0)}
    argv = [apply_placeholders(value, mapping) for value in stage["argv"]]
    original_root = str(Path(project_root).resolve())
    if any(original_root in value for value in argv):
        raise BlockedError("stage command contains the original project path; use snapshot placeholders")
    inherited_path_vars = [key for key, value in os.environ.items()
                           if key != "PWD" and original_root in value]
    if inherited_path_vars:
        raise BlockedError("inherited environment references the original project path: " +
                           ", ".join(sorted(inherited_path_vars)))
    env = dict(os.environ)
    env.update({"RTL_PPA_PROJECT_ROOT": str(candidate_root), "RTL_PPA_SOURCE_ROOT": str(candidate_root),
                "RTL_PPA_RUN_DIR": str(stage_dir),
                "RTL_PPA_SOURCE_MANIFEST": str(source_manifest_path),
                "RTL_PPA_MODE": mode or "unknown",
                "RTL_PPA_CAMPAIGN_ID": run_dir.name})
    env["PWD"] = str(cwd)
    if seed is not None:
        env["SEED"] = str(seed)
        stage_environment = {key: env[key] for key in (
            "RTL_PPA_PROJECT_ROOT", "RTL_PPA_SOURCE_ROOT", "RTL_PPA_RUN_DIR",
            "RTL_PPA_SOURCE_MANIFEST", "RTL_PPA_MODE", "RTL_PPA_CAMPAIGN_ID", "PWD", "SEED")
            if key in env}
    log_path = stage_dir / "command.log"
    started = time.time()
    status, return_code, reason = "PASS", None, None
    try:
        expected_artifacts = [str(stage_artifact_path(value, mapping, stage_dir, "expected artifact"))
                              for value in stage.get("expected_artifacts", [])]
        try:
            source_data = json.loads(Path(source_manifest_path).read_text())
            source_revision = source_data.get("source_revision", "unknown")
        except (OSError, ValueError):
            source_data = {}
            source_revision = "unknown"
        read_only_assets = source_data.get("read_only_assets", [])
        constraints = [{"path": item["target"], "sha256": item["sha256"]}
                       for item in read_only_assets if str(item.get("target", "")).lower().endswith(".sdc")]
        libraries = [{"path": item["target"], "sha256": item["sha256"]}
                     for item in read_only_assets if Path(str(item.get("target", ""))).suffix.lower()
                     in (".db", ".lib", ".ndm", ".lef")]
        stage_input = make_stage_input(
            run_id=run_dir.name, stage_id=stage["id"], stage_kind=stage.get("kind", "ppa"),
            adapter_id=stage.get("adapter_id", "project.ppa.%s.v1" % stage["id"]),
            project={"name": source_data.get("project", Path(project_root).name),
                     "source_revision": source_revision,
                     "source_tree_sha256": hash_tree(candidate_root),
                     "design_top": source_data.get("design_top"),
                     "testbench_top": source_data.get("testbench_top"),
                     "ordered_sources": source_data.get("rtl_sources", []),
                     "constraints": constraints, "libraries": libraries},
            argv=argv, cwd=cwd, output_dir=stage_dir, expected_artifacts=expected_artifacts,
            dependencies=stage.get("requires", []), timeout=stage.get("timeout_sec", 1800),
            seed=seed, environment=stage_environment,
            budget_seconds=stage.get("remaining_budget_sec", float("inf")),
            input_artifacts=([{"path": str(source_manifest_path), "sha256": sha256(source_manifest_path)}] +
                             [{"path": str(candidate_root / name), "sha256": digest}
                              for name, digest in source_data.get("source_hashes", {}).items()
                              if (candidate_root / name).is_file()] +
                             [{"path": str(candidate_root / item.get("target", "")), "sha256": item["sha256"]}
                              for item in source_data.get("read_only_assets", [])
                              if isinstance(item, dict) and item.get("target") and item.get("sha256")]))
        save_json(stage_dir / "runtime-stage-input.v1.json", stage_input)
        process_record = run_process(stage_input, cwd=str(cwd), env=env, log_path=log_path,
                                     execute=True, adapter_supported=stage.get("adapter_supported", True))
        return_code = process_record["return_code"]
        log_text = read_text(log_path, errors="replace")
        license_missing = re.search(r"license.{0,40}(fail|denied|unavailable|checkout)|failed to obtain.{0,40}license", log_text, re.I)
        fail_patterns = [x for x in stage.get("fail_patterns", []) if re.search(x, log_text)]
        missing_patterns = [x for x in stage.get("pass_patterns", []) if not re.search(x, log_text)]
        result_file = stage_artifact_path(stage["result_json"], mapping, stage_dir,
                                          "stage result JSON")
        if process_record["status"] == "BLOCKED":
            status, reason = "BLOCKED", process_record.get("message") or "shared stage runtime blocked execution"
        elif process_record["status"] == "ERROR":
            status, reason = "ERROR", process_record.get("message") or "shared stage runtime execution error"
        elif license_missing:
            status, reason = "BLOCKED", "EDA license unavailable"
        elif return_code != 0:
            status = "FAIL"
            reason = "command exited nonzero"
        elif fail_patterns:
            status, reason = "FAIL", "failure marker found"
        elif missing_patterns:
            status, reason = "BLOCKED", "required pass marker missing"
        elif not result_file.is_file():
            status, reason = "BLOCKED", "stage result JSON is missing"
        else:
            try:
                data = json.loads(result_file.read_text())
            except (ValueError, OSError) as exc:
                data = {}
                status, reason = "ERROR", "invalid stage result JSON: " + str(exc)
            if status == "PASS":
                if not isinstance(data, dict):
                    status, reason = "ERROR", "stage result JSON must be an object"
                elif data.get("status") not in STATUSES:
                    status, reason = "ERROR", "stage result has no recognized status"
                elif data.get("status") != "PASS":
                    status, reason = data.get("status"), data.get("reason") or "stage result was not PASS"
                elif not isinstance(data.get("metrics", {}), dict) or not isinstance(data.get("artifacts", []), list) or not all(isinstance(x, str) for x in data.get("artifacts", [])):
                    status, reason = "ERROR", "stage metrics must be a mapping and artifacts must be a string list"
                elif any(not valid_metric(value) for value in data.get("metrics", {}).values()):
                    status, reason = "ERROR", "stage metric values must be finite numbers"
                elif data.get("adapter_id") != stage.get("adapter_id"):
                    status, reason = "BLOCKED", "stage adapter identity is missing or does not match the plan"
                elif data.get("adapter_supported") is not True:
                    status, reason = "BLOCKED", "stage adapter reports unsupported functionality"
                elif (not isinstance(data.get("tool_versions"), dict) or not data.get("tool_versions") or
                      not all(isinstance(key, str) and isinstance(value, str) and value
                              for key, value in data.get("tool_versions", {}).items())):
                    status, reason = "BLOCKED", "stage tool_versions provenance is missing"
                else:
                    missing_artifacts = []
                    artifact_records = []
                    artifact_paths = set()
                    for artifact in stage.get("expected_artifacts", []):
                        target = stage_artifact_path(artifact, mapping, stage_dir, "expected artifact")
                        if not target.exists():
                            missing_artifacts.append(str(artifact))
                        else:
                            artifact_paths.add(target)
                            try:
                                artifact_records.append(artifact_provenance(target, stage_dir))
                            except BlockedError as exc:
                                missing_artifacts.append(str(artifact) + " (" + str(exc) + ")")
                    for artifact in data.get("artifacts", []):
                        target = stage_artifact_path(artifact, mapping, stage_dir, "reported artifact")
                        if not target.exists():
                            missing_artifacts.append(str(artifact))
                        else:
                            artifact_paths.add(target)
                            try:
                                artifact_records.append(artifact_provenance(target, stage_dir))
                            except BlockedError as exc:
                                missing_artifacts.append(str(artifact) + " (" + str(exc) + ")")
                    metric_provenance = data.get("metric_provenance", {})
                    if not isinstance(metric_provenance, dict):
                        missing_artifacts.append("metric_provenance must be a mapping")
                    else:
                        for metric_name in data.get("metrics", {}):
                            provenance = metric_provenance.get(metric_name)
                            if (not isinstance(provenance, dict) or
                                    not all(isinstance(provenance.get(key), str) and provenance[key]
                                            for key in ("artifact", "parser_id", "parser_version"))):
                                missing_artifacts.append(metric_name + " metric provenance is missing")
                                continue
                            metric_artifact = stage_artifact_path(
                                provenance["artifact"], mapping, stage_dir, "metric source artifact")
                            if metric_artifact not in artifact_paths:
                                missing_artifacts.append(metric_name + " provenance does not name a reported artifact")
                    if missing_artifacts:
                        status, reason = "BLOCKED", "required artifacts missing: " + ", ".join(missing_artifacts)
                    else:
                        status = "PASS"
    except subprocess.TimeoutExpired:
        status, reason = "BLOCKED", "stage timeout"
    except FileNotFoundError as exc:
        status, reason = "BLOCKED", "tool not found: " + str(exc)
    except PlanError as exc:
        status, reason = "BLOCKED", str(exc)
    except OSError as exc:
        status, reason = "ERROR", str(exc)
    elapsed = round(time.time() - started, 3)
    record = {"stage": stage["id"], "campaign_mode": mode,
              "campaign_id": run_dir.name, "status": status, "return_code": return_code,
              "elapsed_sec": elapsed, "command": argv, "cwd": str(cwd),
              "log": str(log_path), "reason": reason, "seed": seed}
    if "process_record" in locals():
        record["runtime_status"] = process_record.get("status")
        record["runtime_error_class"] = process_record.get("error_class")
    if status == "PASS":
        record["result_json"] = str(result_file)
        record["metrics"] = data.get("metrics", {})
        record["metric_provenance"] = data.get("metric_provenance", {})
        record["artifacts"] = data.get("artifacts", [])
        record["tool_versions"] = data.get("tool_versions", {})
        record["adapter_id"] = data["adapter_id"]
        record["adapter_supported"] = data["adapter_supported"]
        record["artifact_manifest"] = artifact_records + [
            {"path": "result_json", "kind": "file", "size_bytes": result_file.stat().st_size,
             "sha256": sha256(result_file)}]
    try:
        contract_artifacts = []
        for item in record.get("artifact_manifest", []):
            digest = item.get("sha256")
            if digest:
                contract_artifacts.append({"path": item.get("path", ""),
                                           "kind": item.get("kind", "file"),
                                           "size_bytes": item.get("size_bytes", 0),
                                           "sha256": digest, "producer_stage": stage["id"],
                                           "role": "stage_output"})
        try:
            source_revision = json.loads(Path(source_manifest_path).read_text()).get("source_revision", "unknown")
        except (OSError, ValueError):
            source_revision = "unknown"
        status_error = record.get("runtime_error_class") or ("COMMAND_FAILED" if status == "FAIL" else
                        "STAGE_BLOCKED" if status == "BLOCKED" else "INTERNAL_ERROR" if status == "ERROR" else None)
        contract_result = {"contract_version": "1.0", "run_id": run_dir.name,
                           "stage_id": stage["id"], "status": status,
                           "error_class": status_error, "adapter_id": stage_input["adapter_id"],
                           "adapter_supported": stage.get("adapter_supported", True),
                           "exit_code": return_code,
                           "started_at": datetime.datetime.fromtimestamp(started, datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                           "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                           "source_revision": source_revision,
                           "tool_versions": record.get("tool_versions", {}),
                           "metrics": record.get("metrics", {}),
                           "metric_provenance": record.get("metric_provenance", {}),
                           "artifacts": contract_artifacts,
                           "message": reason}
        validate_stage_result(contract_result)
        save_json(stage_dir / "runtime-stage-result.v1.json", contract_result)
        record["runtime_stage_result"] = str(stage_dir / "runtime-stage-result.v1.json")
        record["runtime_stage_result_sha256"] = sha256(stage_dir / "runtime-stage-result.v1.json")
    except (OSError, ValueError, TypeError) as exc:
        if status == "PASS":
            status, reason = "ERROR", "canonical result contract validation failed: " + str(exc)
            record.update(status=status, reason=reason)
    (stage_dir / "runner-record.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def ensure_within(path, root, label):
    path = Path(path).resolve()
    root = Path(root).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise PlanError(label + " must remain inside its stage run directory")
    return path


def collect_metrics(stage_records, metric_rules):
    merged = {}
    by_id = {stage.get("stage"): stage for stage in stage_records}
    for key, rule in metric_rules.items():
        source = by_id.get(rule.get("source_stage"), {})
        if source.get("status") != "PASS":
            continue
        metrics = source.get("metrics", {})
        if key in metrics:
            merged[key] = metrics[key]
    return merged


def source_contract(plan):
    return {"design_top": plan["design_top"], "testbench_top": plan["testbench_top"],
            "rtl_sources": plan["rtl_sources"],
            "testbench_sources": plan["testbench_sources"],
            "behavior_contract": plan["behavior_contract"]}


def baseline_compatibility_error(baseline, candidate, baseline_metrics_doc, candidate_stages):
    checks = [
        (baseline.get("status") == "PASS", "baseline evidence is not PASS"),
        (baseline.get("plan_sha256") == candidate.get("plan_sha256"),
         "baseline was produced from a different plan"),
        (baseline.get("project") == candidate.get("project") and
         baseline.get("behavior_contract") == candidate.get("behavior_contract"),
         "baseline project or behavior contract does not match"),
        (baseline.get("read_only_asset_hashes") == candidate.get("read_only_asset_hashes"),
         "baseline read-only asset hashes do not match candidate assets"),
        (baseline.get("source_revision") == candidate.get("source_revision"),
         "baseline source revision does not match candidate source revision"),
        (baseline.get("base_source_hashes") == candidate.get("base_source_hashes"),
         "baseline source hashes do not match candidate base sources"),
        (baseline.get("source_contract") == candidate.get("source_contract"),
         "baseline source lists or tops do not match candidate"),
        (baseline.get("seed") == candidate.get("seed"),
         "baseline seed does not match candidate seed"),
        (isinstance(baseline_metrics_doc, dict) and
         isinstance(baseline_metrics_doc.get("metrics"), dict),
         "baseline metrics JSON is invalid"),
    ]
    for ok, message in checks:
        if not ok:
            return message
    baseline_stages = {stage.get("stage"): stage for stage in baseline.get("stages", [])
                       if isinstance(stage, dict)}
    candidate_stages = {stage.get("stage"): stage for stage in candidate_stages
                        if isinstance(stage, dict)}
    for stage_id in sorted(set(baseline_stages) & set(candidate_stages)):
        left, right = baseline_stages[stage_id], candidate_stages[stage_id]
        if left.get("status") != "PASS" or right.get("status") != "PASS":
            continue
        if left.get("adapter_id") != right.get("adapter_id"):
            return "stage adapter differs from baseline for " + stage_id
        if left.get("tool_versions") != right.get("tool_versions"):
            return "tool versions differ from baseline for " + stage_id
        if left.get("metric_provenance") != right.get("metric_provenance"):
            return "metric parser provenance differs from baseline for " + stage_id
    return None


def valid_metric(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and
            math.isfinite(float(value)))


def remaining_runtime(per_campaign_limit, total_limit, campaign_elapsed, prior_runtime):
    """Return the tighter remaining wall-clock allowance, preserving fractions."""
    return min(per_campaign_limit - campaign_elapsed,
               total_limit - prior_runtime - campaign_elapsed)


def compare_metrics(rules, baseline, candidate):
    metrics = {}
    missing = []
    gates_pass = True
    improved, regressed = [], []
    for name, rule in rules.items():
        left, right = baseline.get(name), candidate.get(name)
        if left is None or right is None:
            if rule.get("required", True):
                missing.append(name)
            gates_pass = gates_pass and not rule.get("required", True)
            metrics[name] = {"baseline": left, "candidate": right, "unit": rule["unit"], "status": "UNMEASURED"}
            continue
        if not valid_metric(left) or not valid_metric(right):
            missing.append(name + " (non-numeric)")
            gates_pass = False
            metrics[name] = {"baseline": left, "candidate": right, "unit": rule["unit"], "status": "ERROR"}
            continue
        delta = right - left
        delta_pct = (delta / abs(left) * 100.0) if left != 0 else None
        is_better = right < left if rule["direction"] == "lower" else right > left
        is_worse = right > left if rule["direction"] == "lower" else right < left
        if is_better:
            improved.append(name)
        elif is_worse:
            regressed.append(name)
        reasons = []
        if rule.get("min_value") is not None and right < rule["min_value"]:
            reasons.append("below minimum")
        if rule.get("max_value") is not None and right > rule["max_value"]:
            reasons.append("above maximum")
        limit = rule.get("max_regression_pct")
        if limit is not None and is_worse:
            if delta_pct is None or abs(delta_pct) > limit:
                reasons.append("regression exceeds allowance")
        gates_pass = gates_pass and not reasons
        metrics[name] = {"baseline": left, "candidate": right, "delta": delta,
                         "delta_pct": delta_pct, "unit": rule["unit"],
                         "improved": is_better, "status": "PASS" if not reasons else "FAIL",
                         "reasons": reasons}
    if missing:
        decision = "BLOCKED"
    elif not gates_pass:
        decision = "REJECT"
    elif improved and not regressed:
        decision = "ACCEPT"
    elif improved and regressed:
        decision = "REVIEW_TRADEOFF"
    elif regressed:
        decision = "REJECT"
    else:
        decision = "NO_IMPROVEMENT"
    return {"decision": decision, "gates_pass": gates_pass, "missing_metrics": missing,
            "improved_metrics": improved, "regressed_metrics": regressed, "metrics": metrics}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def plan_command(args):
    root = Path(args.project_root).resolve()
    plan_path = Path(args.plan).resolve()
    plan = load_yaml(plan_path)
    errors = validate_plan(plan, root)
    state = git_state(root)
    result = {"status": "PASS" if not errors else "BLOCKED", "errors": errors,
              "project": plan.get("project"), "project_root": str(root),
              "source_revision": state["sha"], "clean_for_snapshot": state["clean_for_snapshot"],
              "design_top": plan.get("design_top"), "testbench_top": plan.get("testbench_top"),
              "rtl_scope_files": [str(x.relative_to(root)) for x in expand_sources(root, plan.get("rtl_scope", []))] if not errors else [],
              "rtl_sources": plan.get("rtl_sources", []),
              "testbench_sources": plan.get("testbench_sources", []),
              "behavior_contract": plan.get("behavior_contract"),
              "candidate_budget": plan.get("budget", {})}
    if errors:
        print(json.dumps(result, indent=2))
        return 1
    result["status"] = "NOT_RUN"
    result["stages"] = [stage["id"] for stage in plan["stages"]]
    print(json.dumps(result, indent=2))
    return 0


def preflight(root, plan):
    state = git_state(root)
    if not state["clean_for_snapshot"]:
        raise BlockedError("source project is dirty; commit or discard changes before evaluation")
    for asset in plan.get("read_only_assets", []):
        path = Path(asset["source"])
        resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
        if not resolved.exists():
            raise BlockedError("missing required read-only asset: " + str(resolved))
    return state


def _execute_campaign_locked(args, mode):
    root = Path(args.project_root).resolve()
    plan_path = Path(args.plan).resolve()
    plan = load_yaml(plan_path)
    errors = validate_plan(plan, root)
    if errors:
        raise BlockedError("invalid plan: " + "; ".join(errors))
    if not args.execute:
        print(json.dumps({"status": "NOT_RUN", "mode": mode, "project": plan["project"],
                          "stages": [s["id"] for s in plan["stages"] if mode in s.get("modes", ["baseline", "candidate"])],
                          "project_root": str(root), "execute_required": True}, indent=2))
        return 0
    campaign_started = time.time()
    campaign_monotonic = time.monotonic()
    state = preflight(root, plan)
    runs_root = Path(args.runs_root).resolve()
    try:
        runs_root.relative_to(root)
    except ValueError:
        pass
    else:
        raise BlockedError("runs_root must be outside project_root to keep source evidence clean")
    runs_root.mkdir(parents=True, exist_ok=True)
    ledger_path = runs_root / "budget.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"candidates": 0, "runtime_sec": 0.0}
    if not isinstance(ledger, dict):
        raise BlockedError("budget ledger must be a JSON object")
    if (not isinstance(ledger.get("candidates", 0), int) or isinstance(ledger.get("candidates", 0), bool) or
            not isinstance(ledger.get("runtime_sec", 0), (int, float)) or
            isinstance(ledger.get("runtime_sec", 0), bool)):
        raise BlockedError("budget ledger counters are invalid")
    if ledger.get("active_campaign"):
        # A process that died while holding the campaign lock is charged its
        # reserved per-campaign budget, preventing interrupted runs from
        # disappearing from cumulative accounting.
        ledger["runtime_sec"] = float(ledger.get("runtime_sec", 0)) + float(ledger.get("active_runtime_reservation_sec", 0))
        ledger["interrupted_campaigns"] = int(ledger.get("interrupted_campaigns", 0)) + 1
        ledger.pop("active_campaign", None)
        ledger.pop("active_runtime_reservation_sec", None)
        write_json(ledger_path, ledger)
    plan_hash = sha256(plan_path)
    if ledger.get("plan_sha256", plan_hash) != plan_hash:
        raise BlockedError("runs_root budget ledger belongs to a different plan")
    ledger["plan_sha256"] = plan_hash
    budget = plan.get("budget", {})
    per_campaign_limit = float(budget.get("max_runtime_sec", 7200))
    total_limit = float(budget.get("max_total_runtime_sec", 28800))
    prior_runtime = float(ledger.get("runtime_sec", 0))
    if not math.isfinite(prior_runtime) or prior_runtime < 0:
        raise BlockedError("budget ledger runtime is invalid")
    if prior_runtime >= total_limit:
        raise BlockedError("cumulative runtime budget exhausted")
    if mode == "candidate":
        if ledger["candidates"] + 1 > budget.get("max_candidates", 4):
            raise BlockedError("candidate budget exhausted")
    run_id = args.candidate_id if mode == "candidate" else "baseline"
    if mode == "candidate" and not CANDIDATE_RE.fullmatch(run_id):
        raise BlockedError("candidate_id must be a simple filesystem-safe identifier")
    output = runs_root / run_id
    if output.exists():
        raise BlockedError("output already exists: " + str(output))
    patch_path = None
    changed_paths = []
    if mode == "candidate":
        patch_path = Path(args.patch).resolve()
        if not patch_path.is_file():
            raise BlockedError("candidate patch does not exist: " + str(patch_path))
        changed_paths = check_patch_paths(patch_path, plan["allowed_patch_paths"])
        uncompiled_paths = sorted(set(changed_paths) - set(plan["rtl_sources"]))
        if uncompiled_paths:
            raise BlockedError("candidate patch changes files outside ordered rtl_sources: " + ", ".join(uncompiled_paths))
        check = subprocess.run(["git", "apply", "--check", str(patch_path)], cwd=str(root),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if check.returncode:
            raise BlockedError("candidate patch does not apply cleanly: " + check.stderr.strip())
    output.mkdir(parents=True)
    runtime_reservation = min(per_campaign_limit, total_limit - prior_runtime)
    ledger["plan_sha256"] = plan_hash
    ledger["active_campaign"] = run_id
    ledger["active_runtime_reservation_sec"] = runtime_reservation
    if mode == "candidate":
        # Failed candidates consume search slots too.
        ledger["candidates"] = ledger.get("candidates", 0) + 1
    write_json(ledger_path, ledger)
    snapshot = output / "source"
    asset_hashes = create_snapshot(root, state["sha"], snapshot, plan.get("read_only_assets", []))
    base_source_hashes = {}
    for path in expand_sources(root, plan["rtl_scope"]):
        base_source_hashes[str(path.relative_to(root))] = sha256(path)
    effective_seed = args.seed if args.seed is not None else 0
    contract = source_contract(plan)
    evidence = {"status": "PASS", "mode": mode, "project": plan["project"],
                "source_revision": state["sha"], "working_tree": state["working_tree"],
                "plan_sha256": sha256(plan_path), "base_source_hashes": base_source_hashes,
                "read_only_asset_hashes": asset_hashes,
                "behavior_contract": plan.get("behavior_contract"), "candidate_id": run_id,
                "seed": effective_seed, "source_contract": contract,
                "stages": [], "started_at": campaign_started}
    if mode == "candidate":
        check = subprocess.run(["git", "apply", "--check", str(patch_path)], cwd=str(snapshot),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if check.returncode:
            raise BlockedError("candidate patch does not apply cleanly: " + check.stderr.strip())
        apply = subprocess.run(["git", "apply", str(patch_path)], cwd=str(snapshot),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if apply.returncode:
            raise BlockedError("could not apply candidate patch to snapshot: " + apply.stderr.strip())
        shutil.copy2(patch_path, output / "rtl_patch.diff")
        evidence["candidate_patch_sha256"] = sha256(patch_path)
        evidence["changed_paths"] = changed_paths
    source_hashes = {}
    for source in expand_sources(snapshot, plan["rtl_scope"]):
        value = str(source.relative_to(snapshot))
        source_hashes[value] = sha256(source)
    for value in plan["rtl_sources"] + plan["testbench_sources"]:
        source_path = snapshot / value
        source_hashes[value] = sha256(source_path)
    evidence["source_hashes"] = source_hashes
    source_manifest = output / "source_manifest.json"
    write_json(source_manifest, {"project": plan["project"], "source_revision": state["sha"],
               "design_top": plan["design_top"], "testbench_top": plan["testbench_top"],
               "rtl_sources": plan["rtl_sources"], "testbench_sources": plan["testbench_sources"],
               "source_hashes": source_hashes, "behavior_contract": plan["behavior_contract"],
               "read_only_assets": [{"target": asset["target"], "sha256": asset_hashes[asset["target"]]}
                                    for asset in plan.get("read_only_assets", [])]})
    write_json(output / "source_revision.json", {"source_revision": state["sha"],
               "base_source_hashes": base_source_hashes, "candidate_source_hashes": source_hashes,
               "read_only_asset_hashes": asset_hashes,
               "candidate_patch_sha256": evidence.get("candidate_patch_sha256"),
               "changed_paths": evidence.get("changed_paths", []), "plan_sha256": evidence["plan_sha256"]})
    started_all = campaign_monotonic
    records = []
    required = set(required_stage_ids(plan, candidate=(mode == "candidate")))
    selected = [stage for stage in plan["stages"] if mode in stage.get("modes", ["baseline", "candidate"])]
    selected_ids = {stage["id"] for stage in selected}
    absent = sorted(required - selected_ids)
    if absent:
        raise PlanError("required stages are disabled for " + mode + ": " + ", ".join(absent))
    for stage in selected:
        campaign_elapsed = time.monotonic() - started_all
        remaining = remaining_runtime(per_campaign_limit, total_limit,
                                       campaign_elapsed, prior_runtime)
        if remaining <= 0:
            records.append({"stage": stage["id"], "status": "BLOCKED", "reason": "campaign runtime budget exhausted"})
            evidence["status"] = "BLOCKED"
            break
        bounded_stage = dict(stage)
        bounded_stage["timeout_sec"] = min(float(stage.get("timeout_sec", 1800)), remaining)
        bounded_stage["remaining_budget_sec"] = remaining
        try:
            record = run_stage(bounded_stage, root, output, snapshot, source_manifest,
                               effective_seed, mode)
        except BlockedError as exc:
            record = {"stage": stage["id"], "campaign_mode": mode, "campaign_id": run_id,
                      "status": "BLOCKED", "return_code": None,
                      "reason": str(exc), "seed": effective_seed}
        except OSError as exc:
            record = {"stage": stage["id"], "campaign_mode": mode, "campaign_id": run_id,
                      "status": "ERROR", "return_code": None,
                      "reason": str(exc), "seed": effective_seed}
        except (ValueError, KeyError, TypeError) as exc:
            record = {"stage": stage["id"], "campaign_mode": mode, "campaign_id": run_id,
                      "status": "ERROR", "return_code": None,
                      "reason": str(exc), "seed": effective_seed}
        records.append(record)
        if record["status"] != "PASS":
            evidence["status"] = record["status"]
            break
    passed_ids = {x["stage"] for x in records if x["status"] == "PASS"}
    for stage in selected:
        if stage["id"] not in {x["stage"] for x in records}:
            records.append({"stage": stage["id"], "status": "SKIPPED", "reason": "dependency stage did not pass"})
    missing_required = sorted(required - passed_ids)
    metrics = {}
    try:
        metrics = collect_metrics(records, plan["metrics"])
    except PlanError as exc:
        evidence["status"] = "ERROR"
        evidence["metric_error"] = str(exc)
    evidence["stages"] = records
    elapsed_exact = max(0.0, time.monotonic() - started_all)
    evidence["elapsed_sec"] = round(elapsed_exact, 6)
    evidence["finished_at"] = time.time()
    if missing_required and evidence["status"] in ("PASS", "NOT_RUN", "SKIPPED"):
        evidence["status"] = "BLOCKED"
        evidence["missing_required_stages"] = missing_required
    write_json(output / "metrics.json", {"metrics": metrics})
    if mode == "baseline":
        if evidence["status"] == "PASS":
            missing_metrics = [key for key, rule in plan["metrics"].items()
                               if rule.get("required", True) and not valid_metric(metrics.get(key))]
            if missing_metrics:
                evidence["status"] = "BLOCKED"
                evidence["missing_required_metrics"] = missing_metrics
        write_json(output / "baseline.json", evidence)
    else:
        if evidence["status"] != "PASS" or missing_required:
            evidence["reason"] = "candidate stages did not all pass; optimization is not evaluated"
            write_json(output / "comparison.json", {
                "status": evidence["status"], "decision": "BLOCKED",
                "reason": evidence["reason"], "candidate_id": run_id})
        else:
            baseline_path = Path(args.baseline).resolve()
            if not baseline_path.is_file():
                evidence["status"] = "BLOCKED"
                evidence["reason"] = "baseline evidence file is missing"
            else:
                try:
                    baseline = json.loads(baseline_path.read_text())
                except (ValueError, OSError):
                    baseline = None
                if not isinstance(baseline, dict):
                    evidence["status"] = "BLOCKED"
                    evidence["reason"] = "baseline evidence JSON is invalid"
                else:
                    baseline_metrics_path = baseline_path.parent / "metrics.json"
                    if not baseline_metrics_path.is_file():
                        evidence["status"] = "BLOCKED"
                        evidence["reason"] = "baseline metrics file is missing"
                    else:
                        try:
                            baseline_metrics_doc = json.loads(baseline_metrics_path.read_text())
                        except (ValueError, OSError):
                            baseline_metrics_doc = None
                        baseline_metrics = baseline_metrics_doc.get("metrics") if isinstance(baseline_metrics_doc, dict) else None
                        compatibility_error = baseline_compatibility_error(
                            baseline, evidence, baseline_metrics_doc, records)
                        if compatibility_error:
                            evidence["status"] = "BLOCKED"
                            evidence["reason"] = compatibility_error
                            write_json(output / "comparison.json", {
                                "status": "BLOCKED", "decision": "BLOCKED",
                                "reason": compatibility_error, "candidate_id": run_id})
                        else:
                            comparison = compare_metrics(plan["metrics"], baseline_metrics, metrics)
                            compare_status = evidence["status"]
                            if compare_status == "PASS" and comparison["decision"] == "BLOCKED":
                                compare_status = "BLOCKED"
                            elif compare_status == "PASS" and comparison["decision"] == "REJECT":
                                compare_status = "FAIL"
                            comparison.update({"status": compare_status,
                                               "baseline_source_revision": baseline.get("source_revision"),
                                               "candidate_source_revision": state["sha"],
                                               "candidate_id": run_id})
                            write_json(output / "comparison.json", comparison)
                            if evidence["status"] == "PASS" and comparison["decision"] == "BLOCKED":
                                evidence["status"] = "BLOCKED"
                                evidence["decision"] = comparison["decision"]
                            elif evidence["status"] == "PASS" and comparison["decision"] == "REJECT":
                                evidence["status"] = "FAIL"
                                evidence["decision"] = comparison["decision"]
    if mode == "candidate" and not (output / "comparison.json").is_file():
        write_json(output / "comparison.json", {
            "status": evidence["status"], "decision": "BLOCKED",
            "reason": evidence.get("reason", "candidate comparison could not be completed"),
            "candidate_id": run_id})
    write_json(output / "evidence.json", evidence)
    elapsed = evidence.get("elapsed_sec", 0.0)
    ledger_elapsed = max(0.0, time.monotonic() - started_all)
    ledger["runtime_sec"] = prior_runtime + ledger_elapsed
    ledger.pop("active_campaign", None)
    ledger.pop("active_runtime_reservation_sec", None)
    write_json(ledger_path, ledger)
    summary = {"status": evidence["status"], "mode": mode, "output": str(output),
               "evidence": str(output / "evidence.json"), "elapsed_sec": elapsed}
    if mode == "candidate" and (output / "comparison.json").is_file():
        summary["comparison"] = json.loads((output / "comparison.json").read_text())
    print(json.dumps(summary, indent=2))
    return 0 if evidence["status"] in ("PASS", "NOT_RUN") else 1


def execute_campaign(args, mode):
    if not args.execute:
        return _execute_campaign_locked(args, mode)
    root = Path(args.project_root).resolve()
    runs_root = Path(args.runs_root).resolve()
    try:
        runs_root.relative_to(root)
    except ValueError:
        pass
    else:
        raise BlockedError("runs_root must be outside project_root to keep source evidence clean")
    runs_root.mkdir(parents=True, exist_ok=True)
    lock_path = runs_root / ".rtl-ppa-budget.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _execute_campaign_locked(args, mode)


def main():
    parser = argparse.ArgumentParser(prog="rtl_ppa.py")
    sub = parser.add_subparsers(dest="command")
    for name in ("validate", "plan"):
        command = sub.add_parser(name)
        command.add_argument("--project-root", required=True)
        command.add_argument("--plan", required=True)
    for name in ("baseline", "evaluate"):
        command = sub.add_parser(name)
        command.add_argument("--project-root", required=True)
        command.add_argument("--plan", required=True)
        command.add_argument("--runs-root", required=True)
        command.add_argument("--execute", action="store_true")
        command.add_argument("--seed", type=int)
        if name == "evaluate":
            command.add_argument("--candidate-id", required=True)
            command.add_argument("--patch", required=True)
            command.add_argument("--baseline", required=True)
    args = parser.parse_args()
    try:
        if args.command in ("validate", "plan"):
            root = Path(args.project_root).resolve()
            plan = load_yaml(Path(args.plan).resolve())
            errors = validate_plan(plan, root)
            if args.command == "validate":
                status = "PASS" if not errors else "BLOCKED"
                print(json.dumps({"status": status, "errors": errors}, indent=2))
                return 0 if not errors else 1
            if errors:
                print(json.dumps({"status": "BLOCKED", "errors": errors}, indent=2))
                return 1
            return plan_command(args)
        if args.command == "baseline":
            return execute_campaign(args, "baseline")
        if args.command == "evaluate":
            return execute_campaign(args, "candidate")
        parser.error("command is required")
    except BlockedError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, indent=2), file=sys.stderr)
        return 1
    except (PlanError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
