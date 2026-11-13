"""Deterministic VCS/DC stages and evidence for one EDA run."""
import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
import time
import platform
import tempfile
from pathlib import Path

from eda_config import ConfigError, resolve, sources


STATUSES = ("PASS", "FAIL", "ERROR", "BLOCKED", "NOT_RUN", "SKIPPED")

LICENSE_ERRORS = re.compile(
    r"license (?:checkout|check-out|feature|server)|unable to checkout|"
    r"checkout failed|no such feature|licensed feature.*not available",
    re.I,
)
TOOL_ERRORS = re.compile(r"(?m)^\s*(?:Error(?:[-:]|\s)|Fatal(?:[-:]|\s))", re.I)
DESIGN_ERRORS = re.compile(r"(?i)(?:check_design.{0,80}(?:fail|error)|design.{0,40}(?:not link|unresolved reference)|\b[1-9]\d*\s+design errors?\b)")


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
        with tempfile.TemporaryDirectory(prefix="eda-version-probe-") as probe_cwd:
            p = subprocess.run([exe, option], cwd=probe_cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, universal_newlines=True, timeout=15)
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


def _resolve_verdi():
    verdi = shutil.which("verdi")
    if not verdi and os.environ.get("VERDI_HOME"):
        candidate = Path(os.environ["VERDI_HOME"]) / "bin/verdi"
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            verdi = str(candidate)
    return verdi


def _coverage_types(value):
    if value is True:
        return "line+cond+tgl+fsm+branch"
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("coverage must be true or a nonempty VCS coverage type string")
    allowed = {"line", "cond", "tgl", "fsm", "branch", "assert", "path", "obc", "sdc", "property_path"}
    kinds = value.split("+")
    if any(x not in allowed for x in kinds):
        raise ConfigError("unsupported VCS code coverage type; use line, cond, tgl, fsm, branch, assert, path, obc, sdc, property_path")
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
        report = run_dir / "coverage-report"
        command = [urg or "urg", "-full64", "-dir", *[str(x) for x in vdbs],
                   "-format", "both", "-report", str(report)]
        functional = bool(flow_cfg.get("functional", False))
        stages = [{"name": "coverage", "command": command, "requires": [],
                   "tool": "urg", "tool_executable": urg,
                   "artifacts": [str(report / "dashboard.html"), str(report / "dashboard.txt")]},
                  {"name": "coverage_summary", "kind": "coverage_summary",
                   "requires": ["coverage"], "report_dir": str(report),
                   "functional": functional,
                   "artifact": str(report / "coverage_metrics.json")}]
        return {"rtl": [], "filelists": [], "include_dirs": [], "defines": []}, stages, {
            "vdb": [str(x) for x in vdbs], "report_dir": str(report), "functional_coverage": functional}

    inputs, fl = _rtl_inputs(root, run_dir, cfg)
    flow_cfg = cfg.get("flows", {}).get("sim", {}) if flow == "regression" else cfg.get("flows", {}).get(flow, {})
    if flow in ("sim", "regression"):
        tb = flow_cfg.get("tb", cfg.get("sim_tb"))
        if not isinstance(tb, str) or not tb:
            raise ConfigError("flows.sim.tb is required")
        tb_path = resolve(root, tb)
        tb_sources = flow_cfg.get("tb_sources", [])
        if not isinstance(tb_sources, list) or not all(isinstance(x, str) and x for x in tb_sources):
            raise ConfigError("flows.sim.tb_sources must be a list of paths")
        tb_paths = [tb_path]
        for item in tb_sources:
            candidate = resolve(root, item)
            if candidate not in tb_paths:
                tb_paths.append(candidate)
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
        match = re.search(r"\bmodule\s+([A-Za-z_][\w$]*)",
                          "\n".join(path.read_text(errors="replace") for path in tb_paths))
        top = flow_cfg.get("top", match.group(1) if match else None)
        if not isinstance(top, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", top):
            raise ConfigError("flows.sim.top required when TB module cannot be discovered")
        simv = run_dir / "simv"
        vcs = executable or shutil.which("vcs")
        cmd = [vcs or "vcs", "-full64", "-sverilog", "-f", str(fl),
               *[str(path) for path in tb_paths], "-top", top, "-o", str(simv)]
        for path in inputs["include_dirs"]:
            cmd.append("+incdir+" + path)
        for define in inputs["defines"]:
            cmd.append("+define+" + define)
        coverage_value = flow_cfg.get("coverage", False)
        functional = bool(flow_cfg.get("functional_coverage", False))
        coverage = bool(coverage_value or functional)
        metrics = _coverage_types(coverage_value if coverage_value else True) if coverage else None
        debug = bool(flow_cfg.get("debug", False))
        if coverage:
            cmd += ["-cm", metrics]
        if debug:
            cmd += ["-kdb", "-debug_access+all"]

        if flow == "sim":
            configured_tests = [{"name": test or "default", "test_name": test,
                                 "seed": seed, "plusargs": plusargs}]
        else:
            configured_tests = flow_cfg.get("tests")
            if not isinstance(configured_tests, list) or not configured_tests:
                raise ConfigError("flows.sim.tests must be a nonempty list for regression")
        names = set()
        for item in configured_tests:
            if not isinstance(item, dict):
                raise ConfigError("each flows.sim.tests entry must be a mapping")
            name = item.get("name")
            item_seed = item.get("seed", seed)
            item_test = item.get("test_name", test)
            item_plusargs = item.get("plusargs", plusargs)
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in names:
                raise ConfigError("regression test names must be unique safe identifiers")
            if not isinstance(item_seed, int) or isinstance(item_seed, bool) or item_seed < 0:
                raise ConfigError("each regression seed must be a nonnegative integer")
            if not isinstance(item_test, str):
                raise ConfigError("each regression test_name must be a string")
            if not isinstance(item_plusargs, list) or not all(isinstance(x, str) for x in item_plusargs):
                raise ConfigError("each regression plusargs value must be a string list")
            names.add(name)

        stages = [{"name": "compile", "command": cmd, "requires": [], "artifact": str(simv),
                   "tool": "vcs", "tool_executable": vcs}]
        result_names, vdbs = [], []
        for item in configured_tests:
            name = item["name"]
            item_seed = item.get("seed", seed)
            item_test = item.get("test_name", test)
            item_plusargs = item.get("plusargs", plusargs)
            sim_name, result_name = "simulate_" + name, "result_" + name
            run = [str(simv), "+ntb_random_seed=%d" % item_seed]
            simulate_stage = {"name": sim_name, "command": run, "requires": ["compile"],
                              "timeout": timeout, "tool": "vcs", "tool_executable": vcs,
                              "log_name": sim_name + ".log", "test_name": item_test,
                              "seed": item_seed, "regression_test": name}
            if coverage:
                vdb = run_dir / "coverage" / name / "simv.vdb"
                vdb.parent.mkdir(parents=True, exist_ok=True)
                run += ["-cm", metrics, "-cm_dir", str(vdb)]
                simulate_stage["artifact"] = str(vdb)
                vdbs.append(vdb)
            if item_test:
                run.append("+UVM_TESTNAME=" + item_test)
            run += [x if x.startswith("+") else "+" + x for x in item_plusargs]
            stages.append(simulate_stage)
            stages.append({"name": result_name, "kind": "simulation_result",
                           "requires": [sim_name], "log_path": str(run_dir / (sim_name + ".log")),
                           "test_name": item_test, "seed": item_seed})
            result_names.append(result_name)
        if coverage:
            urg = _resolve_urg()
            report = run_dir / "coverage-report"
            # Runtime -cm_dir databases contain per-test counters. URG also
            # needs the compile-time database (simv.vdb) for design/shape data.
            coverage_databases = [run_dir / "simv.vdb", *vdbs]
            stages.append({"name": "coverage", "command": [urg or "urg", "-full64", "-dir",
                           *[str(path) for path in coverage_databases], "-format", "both", "-report", str(report)],
                           "requires": result_names, "tool": "urg", "tool_executable": urg,
                           "artifacts": [str(report / "dashboard.html"), str(report / "dashboard.txt")]})
            stages.append({"name": "coverage_summary", "kind": "coverage_summary",
                           "requires": ["coverage"], "report_dir": str(report),
                           "functional": functional,
                           "artifact": str(report / "coverage_metrics.json")})
        if debug:
            stages.append({"name": "debug_artifacts", "kind": "debug_artifacts",
                           "requires": result_names, "kdb_dir": str(run_dir / "simv.daidir"),
                           "run_dir": str(run_dir), "top": top,
                           "viewer_executable": _resolve_verdi(),
                           "artifact": str(run_dir / "debug" / "debug_manifest.json")})
        return inputs, stages, {"tests": configured_tests, "test": test, "seed": seed,
                                "coverage": metrics, "functional_coverage": functional,
                                "debug": debug, "tb": [str(path) for path in tb_paths]}
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
                  "elaborate " + tcl(cfg["top"]), "current_design " + tcl(cfg["top"]), "link",
                  "redirect -file " + tcl(run_dir / "check_design.rpt") + " {check_design}",
                  "read_sdc " + tcl(sdc), "compile_ultra",
                  "write -format verilog -hierarchy -output " + tcl(run_dir / "netlist.v"),
                  "report_qor > " + tcl(run_dir / "qor.rpt"),
                  "report_area > " + tcl(run_dir / "area.rpt"),
                  "report_timing -max_paths 20 > " + tcl(run_dir / "timing.rpt"),
                  "report_constraint -all_violators > " + tcl(run_dir / "constraints.rpt"),
                  "report_power > " + tcl(run_dir / "power.rpt")]
        activity_path = None
        if flow_cfg.get("activity_file"):
            activity_path = _check_file(resolve(root, flow_cfg["activity_file"]), "SAIF activity file")
            instance = flow_cfg.get("activity_instance")
            if not isinstance(instance, str) or not instance.strip():
                raise ConfigError("flows.synth.activity_instance is required with activity_file")
            lines.insert(lines.index("compile_ultra"),
                         "read_saif -input " + tcl(activity_path) + " -instance_name " + tcl(instance))
        lines.append("exit")
        script.write_text("\n".join(lines) + "\n")
        dc = executable or shutil.which("dc_shell")
        return (inputs, [{"name": "synthesis", "command": [dc or "dc_shell", "-f", str(script)],
                          "tool": "dc", "tool_executable": dc,
                          "requires": [], "design_check_artifact": str(run_dir / "check_design.rpt"),
                          "artifacts": [str(run_dir / x) for x in ("netlist.v", "qor.rpt", "area.rpt", "timing.rpt", "constraints.rpt", "check_design.rpt", "power.rpt")] }],
                {"library": str(lib_path), "link_libraries": links, "sdc": str(sdc),
                 "activity_file": str(activity_path) if activity_path else None,
                 "power_provenance": "SAIF" if activity_path else "tool_default_activity_estimate"})
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


def parse_power(path):
    """Parse explicit DC power values; absent values stay null, never zero."""
    path = Path(path)
    text = path.read_text(errors="replace") if path.is_file() else ""
    def metric(patterns):
        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.M)
            if match:
                try:
                    value = float(match.group(1))
                    if value == value and abs(value) != float("inf"):
                        return value
                except ValueError:
                    pass
        return None
    dynamic = metric((r"Total Dynamic Power\s*[:=]?\s*([-+\d.eE]+)",))
    leakage = metric((r"Cell Leakage Power\s*[:=]?\s*([-+\d.eE]+)",))
    total = metric((r"(?:Total Power|Total)\s*[:=]?\s*([-+\d.eE]+)\s*(?:n?W|uW|mW|W)?\s*$",))
    units = {}
    for label, key in (("Dynamic Power Units", "dynamic"), ("Leakage Power Units", "leakage")):
        match = re.search(re.escape(label) + r"\s*=\s*([^\s]+)", text, re.I)
        units[key] = match.group(1) if match else None
    report_errors = [line.strip() for line in text.splitlines()
                     if re.match(r"^\s*(?:Error|Fatal)(?:[-:]|\s)", line, re.I)]
    complete = total is not None and dynamic is not None and leakage is not None and not report_errors
    return {
        "total_dynamic_power": dynamic,
        "cell_leakage_power": leakage,
        "total_power": total,
        "units": units,
        "status": "COMPLETE" if complete else "PARTIAL" if any(x is not None for x in (dynamic, leakage, total)) else "UNAVAILABLE",
        "report_errors": report_errors,
        "report_present": bool(text.strip()),
        "source_report": str(path),
    }


def _urg_metrics(report_dir, functional):
    report_dir = Path(report_dir)
    dashboard = report_dir / "dashboard.txt"
    groups = report_dir / "grpinfo.txt"
    text = dashboard.read_text(errors="replace") if dashboard.is_file() else ""
    group_text = groups.read_text(errors="replace") if groups.is_file() else ""
    def table(value, heading):
        lines = value.splitlines()
        for index, line in enumerate(lines):
            if heading.lower() not in line.lower():
                continue
            following = [item.strip() for item in lines[index + 1:] if item.strip() and
                         not re.fullmatch(r"[-=]+", item.strip())]
            if len(following) < 2:
                return {}
            headers, values = following[0].split(), following[1].split()
            if len(headers) != len(values):
                return {}
            parsed = {}
            for key, item in zip(headers, values):
                try:
                    parsed[key.lower()] = float(item)
                except ValueError:
                    parsed[key.lower()] = None
            return parsed
        return {}
    code_table = table(text, "Total Module Definition Coverage Summary")
    functional_table = table(text, "Total Groups Coverage Summary")
    overall_table = table(text, "Total Coverage Summary")
    group_names = re.findall(r"(?im)^\s*Group\s*:\s*(\S+)", group_text)
    return {
        "parser": "urg-text-v1",
        "code_coverage_percent": code_table.get("score"),
        "code_coverage_by_type_percent": {key: value for key, value in code_table.items() if key != "score"},
        "overall_coverage_score_percent": overall_table.get("score"),
        "functional_coverage_percent": functional_table.get("score") if functional else None,
        "functional_group_count": len(set(group_names)),
        "functional_report_requested": bool(functional),
        "reports": [artifact_record(path) for path in (dashboard, groups, report_dir / "groups.txt", report_dir / "tests.txt") if path.is_file()],
    }


def executable_for(tool):
    homes = {"verdi": "VERDI_HOME"}
    name = {"verdi": "verdi"}.get(tool, tool)
    home = os.environ.get(homes.get(tool, "")) if homes.get(tool) else None
    candidate = Path(home) / "bin" / name if home else None
    if candidate and candidate.is_file() and os.access(str(candidate), os.X_OK):
        return str(candidate)
    return shutil.which(name)


def _debug_artifacts(stage, run_dir):
    kdb = Path(stage["kdb_dir"])
    viewer = stage.get("viewer_executable")
    debug_dir = Path(stage["run_dir"]) / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    waveforms = sorted([*Path(stage["run_dir"]).glob("*.fsdb"), *Path(stage["run_dir"]).glob("*.vpd")])
    command = [viewer or "verdi", "-dbdir", str(kdb)]
    if waveforms:
        command += ["-ssf", str(waveforms[0])]
    launch = debug_dir / "open_verdi.sh"
    launch.write_text("#!/bin/sh\nexec " + " ".join(shlex.quote(str(item)) for item in command) + "\n")
    launch.chmod(0o755)
    db_record = artifact_record(kdb)
    if not _artifact_present(kdb) or not viewer:
        return {"status": "BLOCKED", "error_class": "DEBUG_ARTIFACT_MISSING" if not _artifact_present(kdb) else "TOOL_UNAVAILABLE",
                "reason": "VCS KDB or Verdi executable is missing", "kdb": db_record}
    manifest_path = debug_dir / "debug_manifest.json"
    manifest = {"status": "PASS", "viewer": viewer, "viewer_invocation": command,
                "viewer_execution": "NOT_RUN", "license_status": "UNKNOWN",
                "kdb": db_record, "waveforms": [artifact_record(path) for path in waveforms],
                "launch_script": str(launch)}
    save(manifest_path, manifest)
    return {"status": "PASS", "tool": "verdi", "viewer_status": "NOT_RUN",
            "artifacts": [artifact_record(manifest_path), artifact_record(launch), db_record] +
                         [artifact_record(path) for path in waveforms]}


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
        log = Path(stage.get("log_path", run_dir / "simulate.log"))
        output = log.read_text(errors="replace") if log.exists() else ""
        record.update(log=str(log), test_name=stage.get("test_name"), seed=stage.get("seed"))
        if not output:
            record["status"] = "BLOCKED"
            record["error_class"] = "RESULT_MARKER_MISSING"
        elif re.search(r"(?m)^\s*TEST FAILED\b", output) or re.search(r"(?m)^\s*UVM_(?:ERROR|FATAL)\b(?!\s*:\s*0\s*$)", output):
            record["status"] = "FAIL"
            record["error_class"] = "SIMULATION_CHECK_FAILED"
        elif re.search(r"(?m)^\s*TEST PASSED\s*$", output) or ("UVM Report Summary" in output and
                re.search(r"UVM_ERROR\s*:\s*0\b", output) and re.search(r"UVM_FATAL\s*:\s*0\b", output)):
            record["status"] = "PASS"
        else:
            record["status"] = "BLOCKED"
            record["error_class"] = "RESULT_MARKER_MISSING"
    elif stage.get("kind") == "coverage_summary":
        report_dir = Path(stage["report_dir"])
        dashboard = report_dir / "dashboard.html"
        dashboard_text = report_dir / "dashboard.txt"
        groups = report_dir / "grpinfo.txt"
        if not _artifact_present(dashboard) or not _artifact_present(dashboard_text):
            record.update(status="BLOCKED", error_class="REPORT_MISSING",
                          missing_artifacts=[str(x) for x in (dashboard, dashboard_text) if not _artifact_present(x)])
        elif stage.get("functional") and not _artifact_present(groups):
            record.update(status="BLOCKED", error_class="REPORT_MISSING",
                          missing_artifacts=[str(groups)], reason="functional coverage report was requested")
        else:
            metrics = _urg_metrics(report_dir, stage.get("functional", False))
            if metrics["code_coverage_percent"] is None:
                record.update(status="BLOCKED", error_class="REPORT_INCOMPLETE",
                              reason="URG report has no parseable module-definition code coverage summary",
                              metrics=metrics)
                record["finished_at"] = time.time()
                return record
            if stage.get("functional") and (not metrics["functional_group_count"] or
                                                metrics["functional_coverage_percent"] is None):
                record.update(status="BLOCKED", error_class="REPORT_INCOMPLETE",
                              reason="functional coverage was requested but no parseable covergroup summary was reported",
                              metrics=metrics)
                record["finished_at"] = time.time()
                return record
            metrics_path = Path(stage["artifact"])
            save(metrics_path, metrics)
            record.update(status="PASS", metrics=metrics,
                          artifacts=[artifact_record(path) for path in (dashboard, dashboard_text, metrics_path)] +
                                     ([artifact_record(groups)] if groups.is_file() else []))
    elif stage.get("kind") == "debug_artifacts":
        record.update(_debug_artifacts(stage, run_dir))
    else:
        log = run_dir / stage.get("log_name", stage["name"] + ".log")
        record["log"] = str(log)
        try:
            command = stage.get("command") or []
            if not command:
                record.update(status="BLOCKED", error_class="ADAPTER_UNSUPPORTED",
                              error="stage command is empty")
                record["finished_at"] = time.time()
                return record
            first = str(command[0])
            if not (Path(first).is_file() and os.access(first, os.X_OK)) and not shutil.which(first):
                record.update(status="BLOCKED", error_class="TOOL_UNAVAILABLE",
                              error="required executable is not installed or not on PATH")
                record["finished_at"] = time.time()
                return record
            with log.open("w") as stream:
                proc = subprocess.run(command, cwd=run_dir, stdout=stream, stderr=subprocess.STDOUT,
                                      timeout=stage.get("timeout"))
            record["return_code"] = proc.returncode
            record["tool"] = stage.get("tool")
            if stage.get("tool_executable"):
                record["tool_version"] = tool_version(stage["tool_executable"])
            output = log.read_text(errors="replace") if log.exists() else ""
            if proc.returncode == 0:
                if _license_failure(log):
                    record["status"] = "BLOCKED"
                    record["error_class"] = "LICENSE_UNAVAILABLE"
                elif DESIGN_ERRORS.search(output):
                    record["status"] = "FAIL"
                    record["error_class"] = "DESIGN_CHECK_FAILED"
                elif TOOL_ERRORS.search(output):
                    record["status"] = "ERROR"
                    record["error_class"] = "TOOL_REPORTED_ERROR"
                else:
                    record["status"] = "PASS"
            else:
                record["status"] = "BLOCKED" if _license_failure(log) else "FAIL"
                record["error_class"] = "LICENSE_UNAVAILABLE" if _license_failure(log) else "TOOL_EXECUTION_FAILED"
            check_path = stage.get("design_check_artifact")
            if check_path and record["status"] == "PASS":
                check_file = Path(check_path)
                if not _artifact_present(check_file):
                    record["status"] = "BLOCKED"
                    record["error_class"] = "REPORT_MISSING"
                    record["missing_artifacts"] = [str(check_file)]
                else:
                    check_text = check_file.read_text(errors="replace")
                    if re.search(r"(?im)^\s*(?:Error|Fatal)(?:[-:]|\s)", check_text) or re.search(r"(?i)\b[1-9]\d*\s+errors?\b", check_text):
                        record["status"] = "FAIL"
                        record["error_class"] = "DESIGN_CHECK_FAILED"
            if stage.get("tool_executable") and not record.get("tool_version") and record["status"] == "PASS":
                record["status"] = "BLOCKED"
                record["error_class"] = "VERSION_UNAVAILABLE"
                record["reason"] = "tool version could not be recorded"
            for artifact in ([stage["artifact"]] if stage.get("artifact") else stage.get("artifacts", [])):
                if not _artifact_present(artifact):
                    if record["status"] == "PASS":
                        record["status"] = "BLOCKED"
                        record["error_class"] = "REPORT_MISSING"
                    missing = record.setdefault("missing_artifacts", [])
                    if artifact not in missing:
                        missing.append(artifact)
                else:
                    record.setdefault("artifacts", []).append(artifact_record(artifact))
        except OSError as exc:
            if isinstance(exc, FileNotFoundError):
                record["status"] = "BLOCKED"
                record["error_class"] = "TOOL_UNAVAILABLE"
                record["error"] = "required executable or input is unavailable"
                record["error_detail"] = str(exc)
            else:
                record["status"] = "ERROR"
                record["error_class"] = "EXECUTION_ERROR"
                record["error"] = str(exc)
        except subprocess.TimeoutExpired:
            record["status"] = "ERROR"
            record["error_class"] = "TIMEOUT"
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
    for key in ("library", "sdc", "tb", "netlist", "activity_file"):
        if key in options:
            value = options[key]
            if isinstance(value, list):
                paths.extend(value)
            elif value:
                paths.append(value)
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
            "environment": {"os": platform.system(), "python": platform.python_version(),
                            "license_server_environment_set": bool(os.environ.get("LM_LICENSE_FILE") or os.environ.get("SNPSLMD_LICENSE_FILE")),
                            "tool_home_environment_set": {name: bool(os.environ.get(name)) for name in
                                ("VCS_HOME", "VERDI_HOME", "DC_HOME", "SPYGLASS_HOME", "VC_FORMAL_HOME", "FM_HOME", "PRIME_HOME", "ICC2_HOME", "FC_HOME", "TESTMAX_HOME", "STARRC_HOME")}},
            "stages": records, "artifacts": artifacts, "timestamp": time.time()}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
