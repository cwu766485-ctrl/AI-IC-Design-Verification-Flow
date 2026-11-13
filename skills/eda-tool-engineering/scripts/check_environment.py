#!/usr/bin/env python3
"""Read-only Synopsys host/project capability discovery.

The report keeps installation, licensing, project configuration and tested
evidence separate. License server values and tool command output are never
serialized.
"""
import argparse
import concurrent.futures
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from eda_config import ConfigError, load, resolve


TOOLS = {
    "vcs": ("VCS_HOME", "vcs", "-ID"),
    "verdi": ("VERDI_HOME", "verdi", "-version"),
    "urg": ("VCS_HOME", "urg", "-version"),
    "design_compiler": ("DC_HOME", "dc_shell", "-version"),
    "spyglass": ("SPYGLASS_HOME", "sg_shell", "-version"),
    "vc_formal": ("VC_FORMAL_HOME", "vc_static_shell", "-version"),
    "formality": ("FM_HOME", "fm_shell", "-version"),
    "prime_time": ("PRIME_HOME", "pt_shell", "-version"),
    "icc2": ("ICC2_HOME", "icc2_shell", "-version"),
    "fusion_compiler": ("FC_HOME", "fc_shell", "-version"),
    "testmax_dft": ("TESTMAX_HOME", "dft_shell", "-version"),
    "testmax_atpg": ("TESTMAX_HOME", "tmax", "-version"),
    "starrc": ("STARRC_HOME", "starrc_shell", "-version"),
}
LICENSE_ENV = ("SNPSLMD_LICENSE_FILE", "LM_LICENSE_FILE")
VERSION_RE = re.compile(r"\bV-\d{4}\.\d+(?:-SP\d+)?\b")
LICENSED_RE = re.compile(
    r"Users of\s+([^:]+):.*?Total of\s+(\d+)\s+licenses issued.*?"
    r"Total of\s+(\d+)\s+licenses in use", re.I | re.S)
LICENSE_MISSING_RE = re.compile(r"no such feature|cannot find license file|license server (?:down|unavailable)|invalid license", re.I)


def _executable(home_var, name):
    home = os.environ.get(home_var)
    candidate = Path(home) / "bin" / name if home else None
    if candidate and candidate.is_file() and os.access(str(candidate), os.X_OK):
        return str(candidate)
    found = shutil.which(name)
    return found


def _version(exe, flag, timeout=12):
    if not exe:
        return {"status": "NOT_INSTALLED", "version": None}
    try:
        with tempfile.TemporaryDirectory(prefix="eda-capability-probe-") as probe_cwd:
            proc = subprocess.run([exe, flag], cwd=probe_cwd, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, universal_newlines=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "version": None}
    except OSError:
        return {"status": "ERROR", "version": None}
    match = VERSION_RE.search(proc.stdout or "")
    if match:
        # Informational flags in some releases print a version then return 1.
        return {"status": "DETECTED", "version": match.group(0)}
    return {"status": "UNCONFIRMED", "version": None}


def _feature_license_status(feature):
    """Probe only a user-declared feature; never print lmstat output or servers."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(feature)):
        return "UNKNOWN", "declared license feature has invalid syntax"
    lmutil = shutil.which("lmutil")
    scl = os.environ.get("SCL_HOME")
    if scl:
        for candidate in (Path(scl) / "bin/lmutil", Path(scl) / "linux64/bin/lmutil"):
            if candidate.is_file() and os.access(str(candidate), os.X_OK):
                lmutil = str(candidate)
                break
    if not lmutil:
        return "UNKNOWN", "lmutil unavailable"
    try:
        proc = subprocess.run([lmutil, "lmstat", "-f", feature], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, universal_newlines=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN", "license query could not complete"
    output = proc.stdout or ""
    match = LICENSED_RE.search(output)
    if match and match.group(1).strip() == feature:
        issued, in_use = int(match.group(2)), int(match.group(3))
        if issued > in_use:
            return "YES", "declared feature has an available license seat"
        return "NO", "declared feature has no available license seat"
    if LICENSE_MISSING_RE.search(output):
        return "NO", "declared feature or license service is unavailable"
    return "UNKNOWN", "license query did not confirm the declared feature"


def _project_assets(root, cfg):
    if cfg is None:
        return {"status": "UNAVAILABLE", "reason": "project eda.yaml is absent",
                "library": "UNKNOWN", "pdk": "UNKNOWN", "sdc": "UNKNOWN"}
    pdk = cfg.get("pdk", {})
    library = pdk.get("target_library")
    pdk_root = pdk.get("root", ".")
    library_path = None
    if isinstance(library, str) and isinstance(pdk_root, str):
        try:
            library_path = resolve(resolve(root, pdk_root, must_exist=False), library, must_exist=False)
        except (ConfigError, OSError):
            pass
    sdc_value = cfg.get("constraints")
    sdc_path = None
    if isinstance(sdc_value, str):
        try:
            sdc_path = resolve(root, sdc_value, must_exist=False)
        except (ConfigError, OSError):
            pass
    library_ok = bool(library_path and library_path.is_file() and library_path.stat().st_size)
    sdc_ok = bool(sdc_path and sdc_path.is_file() and sdc_path.stat().st_size)
    has_pdk_root = bool(isinstance(pdk_root, str) and resolve(root, pdk_root, must_exist=False).is_dir())
    complete = library_ok and sdc_ok and has_pdk_root
    return {"status": "PASS" if complete else "PARTIAL",
            "library": "YES" if library_ok else "NO",
            "pdk": "YES" if has_pdk_root else "NO",
            "sdc": "YES" if sdc_ok else "NO"}


def _passing_evidence(root):
    evidence = {}
    runs = root / "runs"
    if not runs.is_dir():
        return evidence
    for path in sorted(runs.glob("*/manifest.json")):
        try:
            manifest = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if manifest.get("status") != "PASS":
            continue
        for stage in manifest.get("stages", []):
            # A PASS from a bookkeeping stage (for example, writing a Verdi
            # launch script) is not a tool execution or a license checkout.
            if (stage.get("status") != "PASS" or not stage.get("command") or
                    stage.get("return_code") != 0):
                continue
            tool = stage.get("tool")
            if tool:
                key = {"dc": "design_compiler", "pt": "prime_time", "vcs": "vcs", "urg": "urg"}.get(tool, tool)
                evidence[key] = {"status": "PASS", "run_id": manifest.get("run_id"),
                                 "flow": manifest.get("flow"),
                                 "tool_version": stage.get("tool_version"),
                                 "evidence": str(path.relative_to(root))}
    return evidence


def _tested_evidence(root):
    evidence = {}
    runs = root / "runs"
    if not runs.is_dir():
        return evidence
    for path in sorted(runs.glob("*/manifest.json"), key=lambda item: item.stat().st_mtime):
        try:
            manifest = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        grouped = {}
        for stage in manifest.get("stages", []):
            tool = stage.get("tool")
            if not tool:
                continue
            key = {"dc": "design_compiler", "pt": "prime_time", "vcs": "vcs", "urg": "urg"}.get(tool, tool)
            if stage.get("command"):
                grouped.setdefault(key, []).append(stage)
            elif stage.get("viewer_status"):
                evidence[key] = {"status": stage["viewer_status"], "run_id": manifest.get("run_id"),
                                 "reason": "debug artifact stage does not execute the viewer"}
        for key, stages in grouped.items():
            failed = next((stage for stage in stages if stage.get("status") != "PASS" or
                           stage.get("return_code") != 0), None)
            status = failed.get("status", "ERROR") if failed else "PASS"
            evidence[key] = {"status": status, "run_id": manifest.get("run_id"),
                             "flow": manifest.get("flow"), "evidence": str(path.relative_to(root))}
    return evidence


def _tool_project_configured(name, root, cfg, assets, sources_status):
    if cfg is None:
        return False
    flows = cfg.get("flows", {})
    sim = flows.get("sim", {}) if isinstance(flows, dict) else {}
    if not isinstance(sim, dict):
        sim = {}
    if name == "vcs":
        tb = sim.get("tb")
        if not isinstance(tb, str) or not tb.strip() or sources_status != "PASS":
            return False
        tb_paths = [tb, *sim.get("tb_sources", [])] if isinstance(sim.get("tb_sources", []), list) else []
        return bool(tb_paths) and all(resolve(root, item, must_exist=False).is_file() for item in tb_paths)
    if name == "urg":
        coverage = flows.get("coverage", {})
        vdbs = coverage.get("vdb") if isinstance(coverage, dict) else None
        if isinstance(vdbs, str):
            vdbs = [vdbs]
        if isinstance(vdbs, list) and vdbs:
            return all(isinstance(x, str) and x and resolve(root, x, must_exist=False).is_dir()
                       and any(resolve(root, x, must_exist=False).iterdir()) for x in vdbs)
        tb = sim.get("tb")
        return bool((sim.get("coverage") or sim.get("functional_coverage")) and
                    isinstance(tb, str) and resolve(root, tb, must_exist=False).is_file() and
                    sources_status == "PASS")
    if name == "verdi":
        tb = sim.get("tb")
        return (sim.get("debug") is True and isinstance(tb, str) and
                resolve(root, tb, must_exist=False).is_file() and sources_status == "PASS")
    if name == "design_compiler":
        return (isinstance(flows.get("synth"), dict) and assets.get("status") == "PASS" and
                sources_status == "PASS")
    if name == "prime_time":
        sta = flows.get("sta", {})
        if not isinstance(sta, dict) or not isinstance(sta.get("netlist"), str):
            return False
        netlist = resolve(root, sta["netlist"], must_exist=False)
        return netlist.is_file() and assets.get("status") == "PASS" and sources_status == "PASS"
    flow_for_tool = {
        "spyglass": ("lint", "cdc"), "vc_formal": ("formal",),
        "formality": ("formality",), "icc2": ("apr",),
        "fusion_compiler": ("fc",), "testmax_dft": ("dft", "mbist", "lbist"),
        "testmax_atpg": ("atpg",), "starrc": ("starrc",),
    }.get(name, ())
    return any(isinstance(flows.get(flow), dict) for flow in flow_for_tool)


def _ssh_probe(host, timeout=8):
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", host or "") or host.startswith("-"):
        return {"status": "BLOCKED", "reason": "host must be an SSH config alias or user@host token"}
    ssh = shutil.which("ssh")
    if not ssh:
        return {"status": "UNAVAILABLE", "reason": "ssh executable not installed"}
    cmd = [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=%d" % timeout,
           host, "uname -s && python3 --version"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=timeout + 3)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "UNAVAILABLE", "reason": "SSH connection did not complete"}
    if proc.returncode:
        return {"status": "UNAVAILABLE", "reason": "SSH authentication or remote probe failed"}
    lines = (proc.stdout or "").strip().splitlines()
    linux = bool(lines and lines[0].strip() == "Linux")
    python = next((x.strip() for x in lines if x.startswith("Python ")), None)
    return {"status": "PASS" if linux and python else "BLOCKED",
            "remote_os": "Linux" if linux else "UNSUPPORTED",
            "python": python}


def build_report(root, ssh_host=None, probe_licenses=False):
    root = Path(root).resolve()
    cfg_path = root / "eda.yaml"
    cfg = None
    config_status = "UNAVAILABLE"
    config_error = None
    if cfg_path.is_file():
        try:
            cfg = load(cfg_path)
            config_status = "PASS"
        except ConfigError as exc:
            config_status, config_error = "BLOCKED", str(exc)
    env_configured = any(os.environ.get(name) for name in LICENSE_ENV)
    assets = _project_assets(root, cfg)
    if cfg is not None and config_status == "PASS":
        try:
            from eda_config import sources
            sources(root, cfg)
            sources_status = "PASS"
        except ConfigError as exc:
            sources_status, config_error = "BLOCKED", str(exc)
    else:
        sources_status = "UNAVAILABLE" if config_status == "UNAVAILABLE" else "BLOCKED"
    licensed_evidence = _passing_evidence(root)
    tested_evidence = _tested_evidence(root)
    tools = {}
    license_features = cfg.get("environment", {}).get("license_features", {}) if cfg else {}
    if not isinstance(license_features, dict):
        license_features = {}
    def tool_report(item):
        name, (home_var, executable_name, flag) = item
        exe = _executable(home_var, executable_name)
        version = _version(exe, flag)
        installed = "YES" if exe else "NO"
        feature = license_features.get(name)
        if isinstance(feature, str):
            feature = [feature]
        if isinstance(feature, list) and feature and probe_licenses:
            results = [_feature_license_status(str(item)) for item in feature]
            licensed = "YES" if any(item[0] == "YES" for item in results) else (
                "NO" if all(item[0] == "NO" for item in results) else "UNKNOWN")
            license_reason = "configured feature probe"
        elif name in licensed_evidence:
            licensed = "YES"
            license_reason = "successful tool execution in recorded run evidence"
        else:
            licensed = "UNKNOWN"
            license_reason = "license service presence is not a feature checkout"
        tool_home_set = bool(os.environ.get(home_var))
        project_cfg = config_status == "PASS"
        flow_cfg = _tool_project_configured(name, root, cfg, assets, sources_status)
        ready = bool(tool_home_set and env_configured and project_cfg and flow_cfg)
        if name in ("design_compiler", "prime_time"):
            ready = ready and assets.get("status") == "PASS"
        return name, {
            "installed": installed,
            "executable_found": bool(exe),
            "version": version["version"],
            "version_probe": version["status"],
            "licensed": licensed,
            "license_reason": license_reason,
            "configured": "YES" if ready else "PARTIAL" if tool_home_set else "NO",
            "configuration": {"home_environment_set": tool_home_set,
                              "license_server_environment_set": env_configured,
                              "project_eda_yaml_valid": project_cfg,
                              "project_flow_configured": flow_cfg,
                              "required_assets_configured": assets.get("status") == "PASS"
                                  if name in ("design_compiler", "prime_time") else None},
            "tested": tested_evidence.get(name, {"status": "NOT_RUN", "reason": "no tool execution evidence found"})
        }
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(12, len(TOOLS)))) as pool:
        for name, value in pool.map(tool_report, TOOLS.items()):
            tools[name] = value
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "host": {"os": platform.system(), "python": platform.python_version(),
                 "local_linux_runner": "PASS" if platform.system() == "Linux" else "UNAVAILABLE",
                 "ssh_executable_installed": bool(shutil.which("ssh"))},
        "project": {"root": str(root), "config_status": config_status,
                    "source_resolution_status": sources_status, "error": config_error,
                    "assets": assets},
        "license_environment_configured": env_configured,
        "tools": tools,
        "remote_runner": _ssh_probe(ssh_host) if ssh_host else {"status": "NOT_CHECKED", "reason": "pass --ssh-host to probe an authorized host"}
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--ssh-host", help="explicit authorized SSH host/alias to probe")
    parser.add_argument("--probe-licenses", action="store_true",
                        help="probe only license features explicitly listed in eda.yaml")
    parser.add_argument("--output", help="write JSON report to this path (default: stdout)")
    args = parser.parse_args(argv)
    report = build_report(args.project_root, args.ssh_host, args.probe_licenses)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
