"""Deterministic VCS/DC stages and evidence for one EDA run."""
import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
import time
from pathlib import Path

from eda_config import ConfigError, resolve, sources


STATUSES = ("PASS", "FAIL", "ERROR", "BLOCKED", "NOT_RUN", "SKIPPED")

LICENSE_ERRORS = re.compile(
    r"license (?:checkout|check-out|feature|server)|unable to checkout|"
    r"checkout failed|no such feature|licensed feature.*not available",
    re.I,
)
TOOL_ERRORS = re.compile(r"(?m)^\s*(?:Error(?:[-:]|\s)|Fatal(?:[-:]|\s))", re.I)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state(root):
    def git(*args):
        p = subprocess.run(["git", "-C", str(root), *args], universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.stdout.strip() if p.returncode == 0 else None
    return {"sha": git("rev-parse", "HEAD"), "working_tree": git("status", "--porcelain")}


def tool_version(exe):
    if not exe:
        return None
    try:
        option = "-ID" if Path(exe).name == "vcs" else "-version"
        p = subprocess.run([exe, option], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=15)
        output = (p.stdout + p.stderr).strip()
        # Several Synopsys releases print a useful version and then exit non-zero
        # for these informational flags. Preserve the version, not the exit code.
        match = re.search(r"\bV-\d{4}\.\d+(?:-SP\d+)?\b", output)
        return match.group(0) if match else (output[:300] if p.returncode == 0 and output else None)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _flow_options(cfg, flow):
    value = cfg.get("flows", {}).get(flow, {})
    if not isinstance(value, dict):
        raise ConfigError(f"flows.{flow} must be a mapping")
    return value


def _check_file(path, description):
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ConfigError(f"{description} is missing or empty: {path}")
    return path


def _artifact_present(path):
    path = Path(path)
    if path.is_dir():
        return any(path.iterdir())
    return path.is_file() and path.stat().st_size > 0


def _resolve_urg():
    urg = shutil.which("urg")
    if not urg and os.environ.get("VCS_HOME"):
        candidate = Path(os.environ["VCS_HOME"]) / "bin/urg"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            urg = str(candidate)
    return urg


def _coverage_types(value):
    if value is True:
        return "line+cond+tgl+fsm+branch"
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("coverage must be true or a nonempty VCS coverage type string")
    allowed = {"line", "cond", "tgl", "fsm", "branch", "assert", "functional"}
    kinds = value.split("+")
    if any(x not in allowed for x in kinds):
        raise ConfigError("unsupported coverage type; use line, cond, tgl, fsm, branch, assert, functional")
    return "+".join(dict.fromkeys(kinds))


def _rtl_inputs(root, run_dir, cfg):
    inputs = sources(root, cfg)
    fl = run_dir / "rtl.f"
    fl.write_text("\n".join(inputs["rtl"]) + "\n")
    return inputs, fl


def build_stages(flow, root, cfg, run_dir, executable):
    if flow == "coverage":
        flow_cfg = _flow_options(cfg, flow)
        vdb_value = flow_cfg.get("vdb")
        values = [vdb_value] if isinstance(vdb_value, str) else vdb_value
        if not isinstance(values, list) or not values or not all(isinstance(x, str) and x for x in values):
            raise ConfigError("flows.coverage.vdb must be a path or a nonempty list of VDB paths")
        vdbs = [resolve(root, value) for value in values]
        # VDBs are directories; reject missing or empty databases before URG.
        if any(not p.exists() or not p.is_dir() or not any(p.iterdir()) for p in vdbs):
            raise ConfigError("each flows.coverage.vdb must be a nonempty directory")
        urg = executable or _resolve_urg()
        report = run_dir / "coverage"
        command = [urg or "urg", "-full64", "-dir", *[str(x) for x in vdbs], "-report", str(report)]
        return {"rtl": [], "filelists": [], "include_dirs": [], "defines": []}, [
            {"name": "coverage", "command": command, "requires": [],
             "tool": "urg", "tool_executable": urg,
             "artifacts": [str(report / "dashboard.html")]}
        ], {"vdb": [str(x) for x in vdbs], "report_dir": str(report)}

    inputs, fl = _rtl_inputs(root, run_dir, cfg)
    flow_cfg = cfg.get("flows", {}).get(flow, {})
    if flow == "sim":
        tb = flow_cfg.get("tb", cfg.get("sim_tb"))
        if not isinstance(tb, str) or not tb:
            raise ConfigError("flows.sim.tb is required")
        tb_path = resolve(root, tb)
        test = flow_cfg.get("test_name", "")
        seed = flow_cfg.get("seed", 1)
        if not isinstance(test, str):
            raise ConfigError("flows.sim.test_name must be a string")
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            raise ConfigError("flows.sim.seed must be a nonnegative integer")
        timeout = flow_cfg.get("timeout_sec")
        if timeout is not None and (not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0):
            raise ConfigError("flows.sim.timeout_sec must be a positive number")
        plusargs = flow_cfg.get("plusargs", [])
        if not isinstance(plusargs, list) or not all(isinstance(x, str) for x in plusargs):
            raise ConfigError("flows.sim.plusargs must be a string list")
        match = re.search(r"\bmodule\s+([A-Za-z_][\w$]*)", tb_path.read_text(errors="replace"))
        top = flow_cfg.get("top", match.group(1) if match else None)
        if not isinstance(top, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", top):
            raise ConfigError("flows.sim.top required when TB module cannot be discovered")
        simv = run_dir / "simv"
        vcs = executable or shutil.which("vcs")
        cmd = [vcs or "vcs", "-full64", "-sverilog", "-f", str(fl),
               str(tb_path), "-top", top, "-o", str(simv)]
        for path in inputs["include_dirs"]:
            cmd.append("+incdir+" + path)
        for define in inputs["defines"]:
            cmd.append("+define+" + define)
        coverage = flow_cfg.get("coverage", False)
        if coverage:
            metrics = _coverage_types(coverage)
            cmd += ["-cm", metrics]
        run = [str(simv), f"+ntb_random_seed={seed}"]
        if coverage:
            # VCS needs runtime instrumentation enabled as well as compile-time
            # instrumentation. Keep the database below this run's directory.
            run += ["-cm", metrics, "-cm_dir", str(run_dir / "simv.vdb")]
        if test:
            run.append("+UVM_TESTNAME=" + str(test))
        run += [x if x.startswith("+") else "+" + x for x in plusargs]
        stages = [{"name": "compile", "command": cmd, "requires": [], "artifact": str(simv),
                   "tool": "vcs", "tool_executable": vcs},
                  {"name": "simulate", "command": run, "requires": ["compile"],
                   "timeout": timeout, "tool": "vcs", "tool_executable": vcs}]
        if coverage:
            stages[1]["artifact"] = str(run_dir / "simv.vdb")
            urg = _resolve_urg()
            stages.append({"name": "coverage", "command": [urg or "urg", "-full64", "-dir", str(run_dir / "simv.vdb"),
                            "-report", str(run_dir / "coverage")], "requires": ["simulate"],
                           "tool": "urg", "tool_executable": urg,
                           "artifact": str(run_dir / "coverage/dashboard.html")})
        stages.append({"name": "result", "kind": "simulation_result", "requires": ["coverage" if coverage else "simulate"]})
        return inputs, stages, {"test": test, "seed": seed, "coverage": coverage, "plusargs": plusargs,
                                "tb": str(tb_path)}
    if flow == "synth":
        pdk = cfg.get("pdk", {})
        library = flow_cfg.get("target_library", pdk.get("target_library"))
        if not isinstance(library, str) or not library:
            raise ConfigError("pdk.target_library is required for synthesis")
        pdk_root_value = pdk.get("root", ".")
        if not isinstance(pdk_root_value, str) or not pdk_root_value:
            raise ConfigError("pdk.root must be a path string")
        pdk_root = resolve(root, pdk_root_value, must_exist=False)
        lib_path = _check_file(resolve(pdk_root, library), "target library")
        link_values = flow_cfg.get("link_libraries", pdk.get("link_libraries", []))
        if not isinstance(link_values, list) or not all(isinstance(x, str) and x for x in link_values):
            raise ConfigError("link_libraries must be a list of path strings")
        links = [str(_check_file(resolve(pdk_root, x), "link library")) for x in link_values]
        sdc_value = flow_cfg.get("sdc", cfg.get("constraints"))
        if not isinstance(sdc_value, str) or not sdc_value:
            raise ConfigError("constraints or flows.synth.sdc is required")
        sdc = _check_file(resolve(root, sdc_value), "SDC constraints")
        script = run_dir / "synth.tcl"
        def tcl(value):
            return "{" + str(value).replace("}", "\\}") + "}"
        lines = ["set_app_var target_library " + tcl(lib_path),
                 "set_app_var link_library [list * " + " ".join(tcl(x) for x in [lib_path, *links]) + "]"]
        for x in inputs["include_dirs"]:
            lines.append("set_app_var search_path [concat $search_path [list " + tcl(x) + "]]")
        for x in inputs["defines"]:
            lines.append("set_app_var hdlin_define_macro [concat $hdlin_define_macro [list " + tcl(x) + "]]")
        lines += ["analyze -format sverilog [list " + " ".join(tcl(x) for x in inputs["rtl"]) + "]",
                  "elaborate " + tcl(cfg["top"]), "current_design " + tcl(cfg["top"]), "link", "check_design",
                  "read_sdc " + tcl(sdc), "compile_ultra",
                  "write -format verilog -hierarchy -output " + tcl(run_dir / "netlist.v"),
                  "report_qor > " + tcl(run_dir / "qor.rpt"),
                  "report_area > " + tcl(run_dir / "area.rpt"),
                  "report_timing -max_paths 20 > " + tcl(run_dir / "timing.rpt"),
                  "report_constraint -all_violators > " + tcl(run_dir / "constraints.rpt"), "exit"]
        script.write_text("\n".join(lines) + "\n")
        dc = executable or shutil.which("dc_shell")
        return (inputs, [{"name": "synthesis", "command": [dc or "dc_shell", "-f", str(script)],
                          "tool": "dc", "tool_executable": dc,
                          "requires": [], "artifacts": [str(run_dir / x) for x in ("netlist.v", "qor.rpt", "area.rpt", "timing.rpt", "constraints.rpt")] }],
                {"library": str(lib_path), "link_libraries": links, "sdc": str(sdc)})
    if flow == "sta":
        pdk = cfg.get("pdk", {})
        library = flow_cfg.get("target_library", pdk.get("target_library"))
        if not isinstance(library, str) or not library:
            raise ConfigError("pdk.target_library is required for STA")
        pdk_root_value = pdk.get("root", ".")
        if not isinstance(pdk_root_value, str) or not pdk_root_value:
            raise ConfigError("pdk.root must be a path string")
        pdk_root = resolve(root, pdk_root_value, must_exist=False)
        lib_path = _check_file(resolve(pdk_root, library), "target library")
        links_value = flow_cfg.get("link_libraries", pdk.get("link_libraries", []))
        if not isinstance(links_value, list) or not all(isinstance(x, str) and x for x in links_value):
            raise ConfigError("flows.sta.link_libraries must be a list of paths")
        links = [_check_file(resolve(pdk_root, x), "link library") for x in links_value]
        netlist_value = flow_cfg.get("netlist")
        if not isinstance(netlist_value, str) or not netlist_value:
            raise ConfigError("flows.sta.netlist must name a synthesized gate-level netlist")
        netlist = _check_file(resolve(root, netlist_value), "STA netlist")
        sdc_value = flow_cfg.get("sdc", cfg.get("constraints"))
        if not isinstance(sdc_value, str) or not sdc_value:
            raise ConfigError("constraints or flows.sta.sdc is required")
        sdc = _check_file(resolve(root, sdc_value), "SDC constraints")
        script = run_dir / "sta.tcl"
        def tcl(value):
            return "{" + str(value).replace("}", "\\}") + "}"
        script.write_text("\n".join([
            "set_app_var target_library " + tcl(lib_path),
            "set_app_var link_library [list * " + " ".join(tcl(x) for x in [lib_path, *links]) + "]",
            "read_verilog " + tcl(netlist),
            "current_design " + tcl(cfg["top"]), "link_design " + tcl(cfg["top"]),
            "read_sdc " + tcl(sdc), "check_timing", "update_timing",
            "report_qor > " + tcl(run_dir / "qor.rpt"),
            "report_timing -delay_type max -max_paths 20 > " + tcl(run_dir / "timing.rpt"),
            "report_constraint -all_violators > " + tcl(run_dir / "constraints.rpt"),
            "exit", ""
        ]))
        pt = executable or shutil.which("pt_shell")
        return (inputs, [{"name": "sta", "command": [pt or "pt_shell", "-f", str(script)],
                          "tool": "pt", "tool_executable": pt,
                          "requires": [], "artifacts": [str(run_dir / x) for x in ("qor.rpt", "timing.rpt", "constraints.rpt")]}],
                {"library": str(lib_path), "link_libraries": [str(x) for x in links],
                 "netlist": str(netlist), "sdc": str(sdc)})
    raise ConfigError(f"no deterministic adapter for {flow}")


def parse_qor(path):
    paths = [Path(path)] if isinstance(path, (str, Path)) else [Path(x) for x in path]
    text = "\n".join(p.read_text(errors="replace") for p in paths if p.is_file())
    def metric(patterns):
        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.M)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass
        return None
    return {
        "area": metric((r"(?:Cell Area|Total cell area|Design area)\s*[:=]\s*([-+\d.eE]+)",)),
        "wns": metric((r"(?:Design\s+WNS|WNS|Critical Path Slack)\s*[:=]\s*([-+\d.eE]+)",
                       r"slack\s*\(VIOLATED\)\s+([-+\d.eE]+)")),
        "tns": metric((r"(?:Design\s+TNS|TNS|Total Negative Slack)\s*[:=]\s*([-+\d.eE]+)",)),
    }


def artifact_record(path):
    path = Path(path)
    record = {"path": str(path), "exists": path.exists()}
    if path.is_file():
        record["size_bytes"] = path.stat().st_size
        if path.stat().st_size:
            record["sha256"] = sha256(path)
    elif path.is_dir():
        record["kind"] = "directory"
        files = sorted(child for child in path.rglob("*") if child.is_file())
        record["entries"] = len(files)
        record["size_bytes"] = sum(child.stat().st_size for child in files)
        inventory = "\n".join(f"{child.relative_to(path)}\0{child.stat().st_size}" for child in files)
        record["inventory_sha256"] = hashlib.sha256(inventory.encode()).hexdigest()
    return record


def _license_failure(log):
    try:
        return bool(LICENSE_ERRORS.search(Path(log).read_text(errors="replace")))
    except OSError:
        return False


def run_stage(stage, run_dir, execute):
    started = time.time()
    record = {"name": stage["name"], "status": "NOT_RUN", "command": stage.get("command"),
              "log": None, "return_code": None, "started_at": started}
    if not execute:
        return record
    if stage.get("kind") == "simulation_result":
        log = run_dir / "simulate.log"
        output = log.read_text(errors="replace") if log.exists() else ""
        if not output:
            record["status"] = "BLOCKED"
        elif re.search(r"(?m)^\s*TEST FAILED\b", output) or re.search(r"(?m)^\s*UVM_(?:ERROR|FATAL)\b(?!\s*:\s*0\s*$)", output):
            record["status"] = "FAIL"
        elif re.search(r"(?m)^\s*TEST PASSED\s*$", output) or ("UVM Report Summary" in output and
                re.search(r"UVM_ERROR\s*:\s*0\b", output) and re.search(r"UVM_FATAL\s*:\s*0\b", output)):
            record["status"] = "PASS"
        else:
            record["status"] = "BLOCKED"
        record["log"] = str(log)
    else:
        log = run_dir / (stage["name"] + ".log")
        record["log"] = str(log)
        try:
            with log.open("w") as stream:
                proc = subprocess.run(stage["command"], cwd=run_dir, stdout=stream, stderr=subprocess.STDOUT,
                                      timeout=stage.get("timeout"))
            record["return_code"] = proc.returncode
            record["tool"] = stage.get("tool")
            if stage.get("tool_executable"):
                record["tool_version"] = tool_version(stage["tool_executable"])
            if proc.returncode == 0:
                if _license_failure(log):
                    record["status"] = "BLOCKED"
                elif TOOL_ERRORS.search(log.read_text(errors="replace")):
                    record["status"] = "FAIL"
                else:
                    record["status"] = "PASS"
            else:
                record["status"] = "BLOCKED" if _license_failure(log) else "FAIL"
            if stage.get("tool_executable") and not record.get("tool_version") and record["status"] == "PASS":
                record["status"] = "BLOCKED"
                record["reason"] = "tool version could not be recorded"
            for artifact in ([stage["artifact"]] if stage.get("artifact") else stage.get("artifacts", [])):
                if not _artifact_present(artifact):
                    if record["status"] == "PASS":
                        record["status"] = "BLOCKED"
                    record.setdefault("missing_artifacts", []).append(artifact)
                else:
                    record.setdefault("artifacts", []).append(artifact_record(artifact))
        except OSError as exc:
            if isinstance(exc, FileNotFoundError):
                record["status"] = "BLOCKED"
                record["error"] = "required executable or input is unavailable"
                record["error_detail"] = str(exc)
            else:
                record["status"] = "ERROR"
                record["error"] = str(exc)
        except subprocess.TimeoutExpired:
            record["status"] = "ERROR"
            record["error"] = "stage timed out"
    record["finished_at"] = time.time()
    return record


def execute_plan(stages, run_dir, execute, resume=None):
    if not execute:
        return [run_stage(stage, run_dir, False) for stage in stages]
    old = {x["name"]: x for x in (resume or {}).get("stages", [])}
    records = []
    for stage in stages:
        prior = old.get(stage["name"])
        if prior and prior.get("status") == "PASS" and _prior_outputs_intact(prior):
            records.append(prior)
            continue
        if any(next(x for x in records if x["name"] == dep)["status"] != "PASS" for dep in stage["requires"]):
            records.append({"name": stage["name"], "status": "BLOCKED", "reason": "dependency failed"})
        else:
            records.append(run_stage(stage, run_dir, execute))
    return records


def _prior_outputs_intact(record):
    expected = record.get("artifacts", [])
    if not expected:
        # Stages with no declared output may be replayed only by rerunning.
        return False
    for artifact in expected:
        path = Path(artifact.get("path", ""))
        if not _artifact_present(path):
            return False
        if artifact.get("sha256") and (not path.is_file() or sha256(path) != artifact["sha256"]):
            return False
        if artifact.get("inventory_sha256") and (not path.is_dir() or
                artifact_record(path).get("inventory_sha256") != artifact["inventory_sha256"]):
            return False
    return True


def manifest(root, run_id, flow, tool, exe, inputs, stages, options, records, run_dir):
    paths = [root / "eda.yaml", *inputs["rtl"], *inputs["filelists"]]
    for key in ("library", "sdc", "tb", "netlist"):
        if key in options:
            paths.append(options[key])
    paths += options.get("link_libraries", [])
    vdb_paths = options.get("vdb", [])
    if isinstance(vdb_paths, str):
        vdb_paths = [vdb_paths]
    paths += [Path(x) for x in vdb_paths]
    artifacts_by_path = {item["path"]: item for item in
                         (artifact_record(p) for p in sorted(run_dir.iterdir()) if p.name != "manifest.json")}
    for record in records:
        for item in record.get("artifacts", []):
            artifacts_by_path[item["path"]] = item
    artifacts = [artifacts_by_path[key] for key in sorted(artifacts_by_path)]
    source_revision = git_state(root)
    tool_versions = {x.get("tool"): x.get("tool_version") for x in records
                     if x.get("tool") and x.get("tool_version")}
    primary_version = tool_version(exe) or tool_versions.get(tool)
    return {"run_id": run_id, "project": root.name, "stage": flow, "flow": flow,
            "git": source_revision, "source_revision": source_revision.get("sha"),
            "test": options.get("test"), "seed": options.get("seed"),
            "status": "PASS" if records and all(x["status"] == "PASS" for x in records) else
                      next((x["status"] for x in records if x["status"] in ("FAIL", "ERROR", "BLOCKED")), "NOT_RUN"),
            "tool": tool, "tool_version": primary_version, "tool_versions": tool_versions,
            "return_code": next((x.get("return_code") for x in reversed(records) if x.get("return_code") is not None), None),
            "command": [x.get("command") for x in stages], "options": options,
            "inputs": {str(p): sha256(p) for p in paths if Path(p).is_file()},
            "input_artifacts": [artifact_record(p) for p in paths if Path(p).is_dir()],
            "environment": {"VCS_HOME": os.environ.get("VCS_HOME"), "DC_HOME": os.environ.get("DC_HOME"),
                            "license_configured": bool(os.environ.get("LM_LICENSE_FILE") or os.environ.get("SNPSLMD_LICENSE_FILE"))},
            "stages": records, "artifacts": artifacts, "timestamp": time.time()}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
