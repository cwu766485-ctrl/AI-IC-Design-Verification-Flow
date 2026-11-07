"""Checkpointed project flow orchestration above the EDA adapters."""
import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from eda_config import ConfigError, load, sources, resolve
from eda_runtime import artifact_record, git_state, save, sha256, tool_version


FLOWS = {"rtl_to_sim": ["sim"], "rtl_to_synth": ["synth"], "rtl_to_sim_synth": ["sim", "synth"]}
EDA = Path(__file__).with_name("eda.py")


def tool_signature(stage):
    name, home = {"sim": ("vcs", "VCS_HOME"), "coverage": ("urg", "VCS_HOME"),
                  "synth": ("dc_shell", "DC_HOME"), "sta": ("pt_shell", "PRIME_HOME")}.get(
                      stage, ("", ""))
    if not name:
        return None
    configured = Path(os.environ[home]) / "bin" / name if os.environ.get(home) else None
    path = configured if configured and configured.is_file() else shutil.which(name)
    if not path:
        return None
    path = Path(path)
    stat = path.stat()
    return [str(path), stat.st_size, stat.st_mtime, tool_version(str(path))]


def fingerprint(root, cfg):
    inputs = sources(root, cfg)
    paths = [root / "eda.yaml", *map(Path, inputs["rtl"]), *map(Path, inputs["filelists"])]
    for directory in map(Path, inputs["include_dirs"]):
        paths.extend(p for p in directory.rglob("*") if p.is_file())
    sim = cfg.get("flows", {}).get("sim", {})
    if sim.get("tb"):
        paths.append(resolve(root, sim["tb"]))
    synth = cfg.get("flows", {}).get("synth", {})
    pdk = cfg.get("pdk", {})
    if synth.get("target_library") or pdk.get("target_library"):
        paths.append(resolve(resolve(root, pdk.get("root", "."), must_exist=False), synth.get("target_library", pdk.get("target_library"))))
    for link in synth.get("link_libraries", pdk.get("link_libraries", [])):
        paths.append(resolve(resolve(root, pdk.get("root", "."), must_exist=False), link))
    if synth.get("sdc") or cfg.get("constraints"):
        paths.append(resolve(root, synth.get("sdc", cfg.get("constraints"))))
    unique_paths = list(dict.fromkeys(p.resolve() for p in paths))
    data = {str(p): sha256(p) for p in unique_paths if p.is_file()}
    data["ordered_sources"] = inputs["rtl"]
    data["source_revision"] = git_state(root)
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def workflow(root, name, run_id, cfg):
    stages = [{"name": flow, "status": "NOT_RUN", "adapter_run_id": None} for flow in FLOWS[name]]
    return {"run_id": run_id, "flow": name, "project": cfg["name"], "status": "NOT_RUN",
            "fingerprint": fingerprint(root, cfg), "git": git_state(root), "stages": stages,
            "tool_signatures": {stage["name"]: tool_signature(stage["name"]) for stage in stages}}


def advance(root, data, execute):
    directory = root / "runs" / data["run_id"]
    checkpoint = directory / "checkpoint.json"
    cfg = load(root / "eda.yaml")
    if fingerprint(root, cfg) != data["fingerprint"]:
        data["status"] = "BLOCKED"
        data["reason"] = "inputs changed since checkpoint; start a new run"
        save(checkpoint, data)
        return data
    for idx, stage in enumerate(data["stages"]):
        if stage["status"] == "PASS":
            if _manifest_intact(stage.get("manifest")):
                continue
            stage.update(status="NOT_RUN", reason="prior stage evidence missing or modified")
            stage.pop("manifest", None)
            stage.pop("cache_hit", None)
        if not execute:
            continue
        if idx and data["stages"][idx - 1]["status"] != "PASS":
            stage["status"] = "BLOCKED"
            stage["reason"] = "dependency failed"
            continue
        cache = None
        for item in sorted((root / "runs").glob("*/checkpoint.json"), reverse=True):
            if item == checkpoint:
                continue
            candidate = json.loads(item.read_text())
            if candidate.get("fingerprint") != data["fingerprint"]:
                continue
            if candidate.get("tool_signatures", {}).get(stage["name"]) != tool_signature(stage["name"]):
                continue
            cached = next((x for x in candidate.get("stages", []) if x["name"] == stage["name"]), None)
            if cached and cached["status"] == "PASS" and _manifest_intact(cached.get("manifest")):
                cache = item
                break
        if cache:
            cached = next(x for x in json.loads(cache.read_text())["stages"] if x["name"] == stage["name"])
            stage.update(status="PASS", manifest=cached["manifest"], cache_hit=True)
            save(checkpoint, data)
            continue
        attempt = stage.get("attempt", 0) + 1
        stage["attempt"] = attempt
        adapter_id = f"{data['run_id']}-{stage['name']}-{attempt}"
        stage["adapter_run_id"] = adapter_id
        command = [sys.executable, str(EDA), "run", "--flow", stage["name"], "--execute", "--run-id", adapter_id]
        completed = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        stage["stdout"] = str(directory / f"{stage['name']}.log")
        Path(stage["stdout"]).write_text(completed.stdout + completed.stderr)
        adapter_manifest = root / "runs" / adapter_id / "manifest.json"
        if adapter_manifest.exists():
            result = json.loads(adapter_manifest.read_text())
            stage["status"] = result["status"]
            stage["manifest"] = str(adapter_manifest)
        else:
            stage["status"] = "ERROR"
            stage["reason"] = "adapter did not produce a manifest"
        save(checkpoint, data)
    statuses = [x["status"] for x in data["stages"]]
    data["status"] = "PASS" if all(x == "PASS" for x in statuses) else next((x for x in statuses if x in ("FAIL", "ERROR", "BLOCKED")), "NOT_RUN")
    save(checkpoint, data)
    return data


def _manifest_intact(path):
    if not path or not Path(path).is_file():
        return False
    try:
        manifest = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return False
    if manifest.get("status") != "PASS":
        return False
    artifacts = manifest.get("artifacts", [])
    if not artifacts:
        return False
    for item in artifacts:
        artifact = Path(item.get("path", ""))
        if artifact.is_dir():
            actual = artifact_record(artifact)
            if actual.get("inventory_sha256") != item.get("inventory_sha256"):
                return False
        elif artifact.is_file():
            if item.get("sha256") and sha256(artifact) != item["sha256"]:
                return False
        else:
            return False
    return True


def main():
    ap = argparse.ArgumentParser(prog="aicflow")
    commands = ap.add_subparsers(dest="command")
    commands.add_parser("doctor")
    plan = commands.add_parser("plan"); plan.add_argument("--flow", choices=FLOWS, required=True)
    run = commands.add_parser("run"); run.add_argument("--flow", choices=FLOWS, required=True); run.add_argument("--execute", action="store_true")
    resume = commands.add_parser("resume"); resume.add_argument("--run-id", required=True); resume.add_argument("--execute", action="store_true")
    report = commands.add_parser("report"); report.add_argument("--run-id", required=True)
    args = ap.parse_args()
    if not args.command:
        ap.error("a command is required")
    root = Path.cwd()
    if args.command == "doctor":
        p = subprocess.run([sys.executable, str(EDA), "doctor"], cwd=root)
        return p.returncode
    if args.command in ("report", "resume"):
        if not __import__("re").fullmatch(r"[A-Za-z0-9_.-]+", args.run_id):
            ap.error("invalid run id")
        checkpoint = root / "runs" / args.run_id / "checkpoint.json"
        if not checkpoint.exists():
            print(json.dumps({"status": "BLOCKED", "error": "checkpoint not found"}))
            return 1
        data = json.loads(checkpoint.read_text())
        if args.command == "resume":
            data = advance(root, data, args.execute)
        print(json.dumps(data, indent=2))
        return 0 if args.command == "report" or data["status"] in ("PASS", "NOT_RUN") else 1
    try:
        cfg = load(root / "eda.yaml")
        run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + args.flow
        data = workflow(root, args.flow, run_id, cfg)
    except (OSError, ConfigError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}))
        return 2
    directory = root / "runs" / run_id
    directory.mkdir(parents=True)
    save(directory / "checkpoint.json", data)
    data = advance(root, data, args.command == "run" and args.execute)
    print(json.dumps(data, indent=2))
    return 0 if data["status"] in ("PASS", "NOT_RUN") else 1
