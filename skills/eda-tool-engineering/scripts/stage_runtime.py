"""Canonical, deterministic process and DAG runtime shared by EDA and PPA.

The EDA and PPA skills may prepare commands and interpret domain reports, but
they must use this module to validate stage requests, launch processes, and
record/reuse stage evidence.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path


CONTRACT_VERSION = "1.0"
STATUSES = {"PASS", "FAIL", "ERROR", "BLOCKED", "NOT_RUN", "SKIPPED"}
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SENSITIVE_ENV_RE = re.compile(r"(?i)(license|token|password|passwd|secret|credential)")


class StageContractError(ValueError):
    pass


def validate_stage_input(value):
    """Validate the strict v1 stage input subset without runtime dependencies."""
    required = {"contract_version", "run_id", "stage_id", "stage_kind", "adapter_id",
                "project", "argv", "environment", "working_directory", "output_directory",
                "expected_artifacts", "dependencies", "timeout_seconds", "budgets"}
    if not isinstance(value, dict) or set(value) - (required | {"input_artifacts", "seed"}) or required - set(value):
        raise StageContractError("stage input has missing or unknown top-level fields")
    if value["contract_version"] != CONTRACT_VERSION:
        raise StageContractError("unsupported stage input contract_version")
    for key in ("run_id", "stage_kind", "adapter_id", "working_directory", "output_directory"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise StageContractError(f"{key} must be a nonempty string")
    if not ID_RE.fullmatch(value["stage_id"]):
        raise StageContractError("stage_id must be a lowercase identifier")
    if not isinstance(value["project"], dict):
        raise StageContractError("project must be an object")
    project = value["project"]
    project_required = {"name", "source_revision", "source_tree_sha256", "ordered_sources"}
    if not project_required.issubset(project):
        raise StageContractError("project is missing source revision/tree or ordered_sources")
    project_allowed = project_required | {"design_top", "testbench_top", "filelists", "includes", "defines", "constraints", "libraries"}
    if set(project) - project_allowed:
        raise StageContractError("project contains unknown fields")
    if (not isinstance(project["name"], str) or not isinstance(project["source_revision"], str) or
            not isinstance(project["source_tree_sha256"], str) or
            not re.fullmatch(r"[a-fA-F0-9]{64}", project["source_tree_sha256"]) or
            not isinstance(project["ordered_sources"], list) or
            not all(isinstance(x, str) for x in project["ordered_sources"])):
        raise StageContractError("project source provenance fields are invalid")
    for key in ("design_top", "testbench_top"):
        if key in project and project[key] is not None and not isinstance(project[key], str):
            raise StageContractError(f"project.{key} must be a string or null")
    for key in ("filelists", "includes"):
        if key in project and (not isinstance(project[key], list) or not all(isinstance(x, str) for x in project[key])):
            raise StageContractError(f"project.{key} must be a string array")
    if "defines" in project and (not isinstance(project["defines"], dict) or
            not all(isinstance(k, str) and isinstance(v, str) for k, v in project["defines"].items())):
        raise StageContractError("project.defines must map strings to strings")
    for key in ("constraints", "libraries"):
        if key in project and (not isinstance(project[key], list)):
            raise StageContractError(f"project.{key} must be an array")
        for record in project.get(key, []):
            if (not isinstance(record, dict) or set(record) != {"path", "sha256"} or
                    not isinstance(record["path"], str) or
                    not re.fullmatch(r"[a-fA-F0-9]{64}", str(record["sha256"]))):
                raise StageContractError(f"project.{key} entries require path and SHA-256")
    if not isinstance(value["argv"], list) or not value["argv"] or not all(isinstance(x, str) and x for x in value["argv"]):
        raise StageContractError("argv must be a nonempty string array")
    if not isinstance(value["environment"], dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value["environment"].items()):
        raise StageContractError("environment must map strings to strings")
    if any(SENSITIVE_ENV_RE.search(key) for key in value["environment"]):
        raise StageContractError("sensitive environment values must be inherited, not serialized in stage input")
    if not isinstance(value["expected_artifacts"], list) or not all(isinstance(x, str) and x for x in value["expected_artifacts"]):
        raise StageContractError("expected_artifacts must be a string array")
    deps = value["dependencies"]
    if not isinstance(deps, list) or len(set(deps)) != len(deps) or not all(isinstance(x, str) and ID_RE.fullmatch(x) for x in deps):
        raise StageContractError("dependencies must be unique stage identifiers")
    timeout = value["timeout_seconds"]
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise StageContractError("timeout_seconds must be positive")
    remaining = value.get("budgets", {}).get("run_remaining_seconds") if isinstance(value.get("budgets"), dict) else None
    if not isinstance(value["budgets"], dict) or set(value["budgets"]) != {"run_remaining_seconds"} or (remaining is not None and
            (not isinstance(remaining, (int, float)) or isinstance(remaining, bool) or remaining < 0)):
        raise StageContractError("budgets.run_remaining_seconds must be nonnegative or null")
    if "seed" in value and value["seed"] is not None and (not isinstance(value["seed"], int) or isinstance(value["seed"], bool)):
        raise StageContractError("seed must be an integer or null")
    if "input_artifacts" in value and not isinstance(value["input_artifacts"], list):
        raise StageContractError("input_artifacts must be an array")
    for record in value.get("input_artifacts", []):
        if not isinstance(record, dict) or set(record) != {"path", "sha256"} or not isinstance(record["path"], str) or not re.fullmatch(r"[a-fA-F0-9]{64}", str(record["sha256"])):
            raise StageContractError("input_artifacts entries require path and SHA-256")
    return value


def validate_stage_result(value):
    required = {"contract_version", "run_id", "stage_id", "status", "error_class", "adapter_id",
                "adapter_supported", "exit_code", "started_at", "finished_at", "source_revision",
                "tool_versions", "metrics", "metric_provenance", "artifacts", "message"}
    if not isinstance(value, dict) or set(value) != required:
        raise StageContractError("stage result has missing or unknown fields")
    if value["contract_version"] != CONTRACT_VERSION or value["status"] not in STATUSES:
        raise StageContractError("invalid stage result version or status")
    if (not isinstance(value["run_id"], str) or not isinstance(value["stage_id"], str) or
            not isinstance(value["adapter_id"], str) or not value["adapter_id"] or
            not isinstance(value["source_revision"], str) or
            (value["error_class"] is not None and not isinstance(value["error_class"], str)) or
            (value["exit_code"] is not None and (not isinstance(value["exit_code"], int) or isinstance(value["exit_code"], bool))) or
            not isinstance(value["started_at"], str) or not isinstance(value["finished_at"], str) or
            (value["message"] is not None and not isinstance(value["message"], str))):
        raise StageContractError("stage result provenance/status fields have invalid types")
    if not isinstance(value["adapter_supported"], bool) or not isinstance(value["tool_versions"], dict):
        raise StageContractError("invalid stage result adapter/tool provenance")
    if not all(isinstance(key, str) and isinstance(version, str) and version
               for key, version in value["tool_versions"].items()):
        raise StageContractError("tool_versions must map names to nonempty strings")
    if not isinstance(value["metrics"], dict) or not isinstance(value["metric_provenance"], dict) or not isinstance(value["artifacts"], list):
        raise StageContractError("metrics, metric_provenance, and artifacts have invalid types")
    for artifact in value["artifacts"]:
        required_artifact = {"path", "kind", "size_bytes", "sha256", "producer_stage", "role"}
        if (not isinstance(artifact, dict) or set(artifact) != required_artifact or
                not isinstance(artifact["path"], str) or artifact["kind"] not in ("file", "directory") or
                not isinstance(artifact["size_bytes"], int) or artifact["size_bytes"] < 0 or
                not re.fullmatch(r"[a-fA-F0-9]{64}", str(artifact["sha256"])) or
                not isinstance(artifact["producer_stage"], str) or not isinstance(artifact["role"], str)):
            raise StageContractError("stage result contains an invalid artifact record")
    for metric, provenance in value["metric_provenance"].items():
        if (not isinstance(metric, str) or not isinstance(provenance, dict) or
                set(provenance) != {"artifact", "parser_id", "parser_version"} or
                not all(isinstance(provenance.get(key), str) and provenance[key]
                        for key in ("artifact", "parser_id", "parser_version"))):
            raise StageContractError("stage metric provenance is incomplete")
    if value["status"] == "PASS" and (not value["adapter_supported"] or value["exit_code"] != 0 or not value["artifacts"]):
        raise StageContractError("PASS requires a supported adapter, exit code zero, and artifacts")
    return value


def make_stage_input(*, run_id, stage_id, stage_kind, adapter_id, project, argv,
                     cwd, output_dir, expected_artifacts=(), dependencies=(), timeout=1800,
                     environment=None, seed=None, budget_seconds=float("inf"), input_artifacts=()):
    # Null means that this caller has no configured run-wide budget.
    budget_seconds = None if budget_seconds == float("inf") else budget_seconds
    return validate_stage_input({
        "contract_version": CONTRACT_VERSION, "run_id": str(run_id), "stage_id": str(stage_id),
        "stage_kind": str(stage_kind), "adapter_id": str(adapter_id), "project": project or {},
        "argv": [str(x) for x in argv], "environment": dict(environment or {}),
        "working_directory": str(cwd), "output_directory": str(output_dir),
        "expected_artifacts": [str(x) for x in expected_artifacts],
        "dependencies": list(dependencies), "timeout_seconds": timeout,
        "budgets": {"run_remaining_seconds": budget_seconds}, "input_artifacts": list(input_artifacts),
        "seed": seed})


def run_process(request, *, cwd, env=None, log_path=None, execute=True, adapter_supported=True):
    """The only subprocess launcher used for EDA/PPA execution stages."""
    validate_stage_input(request)
    started = time.time()
    record = {"status": "NOT_RUN", "error_class": None, "return_code": None,
              "started_at": started, "finished_at": None, "elapsed_sec": 0.0,
              "command": list(request["argv"]), "log": str(log_path) if log_path else None}
    if not adapter_supported:
        record.update(status="BLOCKED", error_class="ADAPTER_UNSUPPORTED", message="adapter capability is not implemented")
    elif not execute:
        record["message"] = "dry run; command was not launched"
    else:
        executable = request["argv"][0]
        local_executable = Path(cwd) / executable if not Path(executable).is_absolute() else Path(executable)
        stage_path = request.get("environment", {}).get("PATH", os.environ.get("PATH"))
        if not ((local_executable.is_file() and os.access(local_executable, os.X_OK)) or
                shutil.which(executable, path=stage_path)):
            record.update(status="BLOCKED", error_class="TOOL_UNAVAILABLE", message="required executable is unavailable")
        else:
            try:
                effective_env = dict(os.environ if env is None else env)
                effective_env.update(request["environment"])
                if log_path:
                    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
                    with Path(log_path).open("w") as stream:
                        proc = subprocess.run(request["argv"], cwd=cwd, env=effective_env, stdout=stream,
                                              stderr=subprocess.STDOUT, timeout=request["timeout_seconds"])
                else:
                    proc = subprocess.run(request["argv"], cwd=cwd, env=effective_env, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, timeout=request["timeout_seconds"])
                    if proc.stdout:
                        record["output"] = proc.stdout.decode(errors="replace") if isinstance(proc.stdout, bytes) else proc.stdout
                record["return_code"] = proc.returncode
                output = ""
                if log_path and Path(log_path).is_file():
                    # Keep status classification bounded; the complete output remains in the log.
                    with Path(log_path).open("rb") as stream:
                        stream.seek(max(0, Path(log_path).stat().st_size - 65536))
                        output = stream.read().decode(errors="replace")
                output += str(record.get("output", ""))
                if re.search(r"(?i)(license.{0,50}(?:fail|denied|unavailable|checkout)|failed to obtain.{0,50}license)", output):
                    record.update(status="BLOCKED", error_class="LICENSE_UNAVAILABLE", message="EDA license unavailable")
                elif proc.returncode == 0:
                    record.update(status="PASS", message=None)
                else:
                    record.update(status="FAIL", error_class="COMMAND_FAILED", message=f"command exited {proc.returncode}")
            except subprocess.TimeoutExpired:
                record.update(status="ERROR", error_class="TIMEOUT", message="stage timed out")
            except FileNotFoundError as exc:
                record.update(status="BLOCKED", error_class="TOOL_UNAVAILABLE", message=str(exc))
            except OSError as exc:
                record.update(status="ERROR", error_class="INTERNAL_ERROR", message=str(exc))
    record["finished_at"] = time.time()
    record["elapsed_sec"] = round(record["finished_at"] - started, 6)
    return record


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_digest(path):
    path = Path(path)
    if path.is_symlink():
        raise StageContractError(f"artifact symlinks are not cacheable: {path}")
    if path.is_file():
        return {"path": str(path), "kind": "file", "size_bytes": path.stat().st_size,
                "sha256": _file_hash(path)}
    if not path.is_dir():
        return {"path": str(path), "exists": False}
    entries = []
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise StageContractError(f"artifact directory contains symlink: {item}")
        if item.is_file():
            entries.append({"path": item.relative_to(path).as_posix(), "size_bytes": item.stat().st_size,
                            "sha256": _file_hash(item)})
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {"path": str(path), "kind": "directory", "size_bytes": sum(x["size_bytes"] for x in entries),
            "entries": len(entries), "inventory_sha256": hashlib.sha256(payload).hexdigest(),
            "tree_sha256": hashlib.sha256(payload).hexdigest()}


def artifact_intact(record):
    path = Path(record.get("path", ""))
    if record.get("kind") == "file":
        return path.is_file() and not path.is_symlink() and _file_hash(path) == record.get("sha256") and path.stat().st_size == record.get("size_bytes")
    if record.get("kind") == "directory":
        try:
            actual = artifact_digest(path)
        except (OSError, StageContractError):
            return False
        return actual.get("tree_sha256") == record.get("tree_sha256", record.get("inventory_sha256"))
    return False


def graph_order(stages):
    ids = [stage.get("id", stage.get("stage_id", stage.get("name"))) for stage in stages]
    if not all(isinstance(x, str) and ID_RE.fullmatch(x) for x in ids) or len(set(ids)) != len(ids):
        raise StageContractError("stage IDs must be unique lowercase identifiers")
    by_id = dict(zip(ids, stages))
    dependencies = {}
    for stage_id, stage in by_id.items():
        deps = stage.get("dependencies", stage.get("requires", []))
        deps = list(deps or [])
        if len(set(deps)) != len(deps) or any(dep not in by_id for dep in deps):
            raise StageContractError(f"stage {stage_id} has duplicate or missing dependencies")
        dependencies[stage_id] = deps
    ready = [stage_id for stage_id in ids if not dependencies[stage_id]]
    result = []
    while ready:
        current = ready.pop(0)
        result.append(current)
        for stage_id in ids:
            if current in dependencies[stage_id]:
                dependencies[stage_id].remove(current)
                if not dependencies[stage_id] and stage_id not in result and stage_id not in ready:
                    ready.append(stage_id)
    if len(result) != len(ids):
        raise StageContractError("stage graph contains a cycle")
    return result


def select_graph(stages, start=None, end=None):
    """Select a topological interval; unsatisfied ancestors before --from block."""
    order = graph_order(stages)
    if start and start not in order:
        raise StageContractError(f"unknown --from stage: {start}")
    if end and end not in order:
        raise StageContractError(f"unknown --to stage: {end}")
    first = order.index(start) if start else 0
    last = order.index(end) if end else len(order) - 1
    if first > last:
        raise StageContractError("--from stage appears after --to stage")
    selected = set(order[first:last + 1])
    by_id = {s.get("id", s.get("stage_id", s.get("name"))): s for s in stages}
    required_before = set()
    def ancestors(node):
        for dep in by_id[node].get("dependencies", by_id[node].get("requires", [])):
            if dep not in selected:
                required_before.add(dep)
            ancestors(dep)
    for node in tuple(selected):
        ancestors(node)
    return [node for node in order if node in selected], [node for node in order if node in required_before]


@contextmanager
def cache_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        try:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        try:
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)
