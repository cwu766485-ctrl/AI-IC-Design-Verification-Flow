import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/eda-tool-engineering/scripts"))
import check_environment as envcheck
import eda_runtime


def test_installed_does_not_imply_licensed_or_tested(tmp_path, monkeypatch):
    monkeypatch.setattr(envcheck, "TOOLS", {"vcs": ("VCS_HOME", "vcs", "-ID")})
    monkeypatch.setattr(envcheck, "_executable", lambda home, name: "/tools/vcs")
    monkeypatch.setattr(envcheck, "_version", lambda exe, flag: {"status": "DETECTED", "version": "V-2023.12"})
    monkeypatch.setattr(envcheck, "_passing_evidence", lambda root: {})
    monkeypatch.setenv("VCS_HOME", "/tools")
    monkeypatch.setenv("SNPSLMD_LICENSE_FILE", "do-not-copy-this-license-server")
    report = envcheck.build_report(tmp_path)
    vcs = report["tools"]["vcs"]
    assert vcs["installed"] == "YES"
    assert vcs["licensed"] == "UNKNOWN"
    assert vcs["tested"]["status"] == "NOT_RUN"
    assert vcs["configured"] == "PARTIAL"
    assert "do-not-copy-this-license-server" not in json.dumps(report)


def test_validated_project_inputs_are_distinct_from_tool_install(tmp_path, monkeypatch):
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl/top.sv").write_text("module top; endmodule\n")
    (tmp_path / "lib.db").write_text("fixture")
    (tmp_path / "top.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    (tmp_path / "eda.yaml").write_text("""name: env_test
top: top
rtl: [rtl/top.sv]
pdk:
  root: .
  target_library: lib.db
constraints: top.sdc
""")
    monkeypatch.setattr(envcheck, "TOOLS", {})
    report = envcheck.build_report(tmp_path)
    assert report["project"]["config_status"] == "PASS"
    assert report["project"]["source_resolution_status"] == "PASS"
    assert report["project"]["assets"] == {"status": "PASS", "library": "YES", "pdk": "YES", "sdc": "YES"}


def test_tool_configuration_requires_a_project_flow_not_just_a_tool_home(tmp_path, monkeypatch):
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl/top.sv").write_text("module top; endmodule\n")
    (tmp_path / "tb.sv").write_text("module tb; endmodule\n")
    (tmp_path / "eda.yaml").write_text("""name: project_cfg
top: top
rtl: [rtl/top.sv]
flows:
  sim: {tb: tb.sv}
""")
    monkeypatch.setattr(envcheck, "TOOLS", {
        "vcs": ("VCS_HOME", "vcs", "-ID"),
        "design_compiler": ("DC_HOME", "dc_shell", "-version"),
    })
    monkeypatch.setattr(envcheck, "_executable", lambda home, name: "/tools/" + name)
    monkeypatch.setattr(envcheck, "_version", lambda exe, flag: {"status": "DETECTED", "version": "V-2023.12"})
    monkeypatch.setenv("VCS_HOME", "/tools/vcs")
    monkeypatch.setenv("DC_HOME", "/tools/dc")
    monkeypatch.setenv("SNPSLMD_LICENSE_FILE", "private-license-endpoint")
    report = envcheck.build_report(tmp_path)
    assert report["tools"]["vcs"]["configured"] == "YES"
    assert report["tools"]["design_compiler"]["installed"] == "YES"
    assert report["tools"]["design_compiler"]["configured"] == "PARTIAL"


def test_passing_tool_run_is_the_only_implicit_license_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(envcheck, "TOOLS", {"vcs": ("VCS_HOME", "vcs", "-ID")})
    monkeypatch.setattr(envcheck, "_executable", lambda home, name: None)
    monkeypatch.setattr(envcheck, "_version", lambda exe, flag: {"status": "NOT_INSTALLED", "version": None})
    runs = tmp_path / "runs" / "run-1"
    runs.mkdir(parents=True)
    (runs / "manifest.json").write_text(json.dumps({
        "status": "PASS", "run_id": "run-1", "flow": "regression",
        "stages": [{"name": "compile", "status": "PASS", "tool": "vcs",
                    "command": ["/tools/vcs"], "return_code": 0,
                    "tool_version": "V-2023.12"}],
    }))
    report = envcheck.build_report(tmp_path)
    vcs = report["tools"]["vcs"]
    assert vcs["installed"] == "NO"
    assert vcs["licensed"] == "YES"
    assert vcs["tested"]["status"] == "PASS"


def test_bookkeeping_stage_does_not_claim_tool_license_checkout(tmp_path):
    runs = tmp_path / "runs" / "run-1"
    runs.mkdir(parents=True)
    (runs / "manifest.json").write_text(json.dumps({
        "status": "PASS", "run_id": "run-1", "flow": "regression",
        "stages": [{"name": "debug_artifacts", "status": "PASS", "tool": "verdi",
                    "command": None, "return_code": None, "viewer_status": "NOT_RUN"}],
    }))
    assert envcheck._passing_evidence(tmp_path) == {}


def test_failed_tool_execution_is_reported_without_license_promotion(tmp_path, monkeypatch):
    monkeypatch.setattr(envcheck, "TOOLS", {"vcs": ("VCS_HOME", "vcs", "-ID")})
    monkeypatch.setattr(envcheck, "_executable", lambda home, name: "/tools/vcs")
    monkeypatch.setattr(envcheck, "_version", lambda exe, flag: {"status": "DETECTED", "version": "V-2023.12"})
    monkeypatch.setenv("VCS_HOME", "/tools")
    monkeypatch.setenv("SNPSLMD_LICENSE_FILE", "private-license-endpoint")
    run = tmp_path / "runs/fail/manifest.json"
    run.parent.mkdir(parents=True)
    run.write_text(json.dumps({"status": "FAIL", "run_id": "fail", "flow": "sim",
                               "stages": [{"tool": "vcs", "command": ["vcs"],
                                           "return_code": 7, "status": "FAIL"}]}))
    report = envcheck.build_report(tmp_path)
    assert report["tools"]["vcs"]["tested"]["status"] == "FAIL"
    assert report["tools"]["vcs"]["licensed"] == "UNKNOWN"


def test_declared_license_feature_probe_is_sanitized(monkeypatch):
    monkeypatch.setattr(envcheck.shutil, "which", lambda name: "/tools/lmutil" if name == "lmutil" else None)
    monkeypatch.delenv("SCL_HOME", raising=False)
    monkeypatch.setattr(envcheck.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="Users of vcs_feature: (Total of 2 licenses issued; Total of 0 licenses in use)\n"))
    assert envcheck._feature_license_status("vcs_feature")[0] == "YES"

    monkeypatch.setattr(envcheck.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stdout="No such feature exists. Secret server details suppressed."))
    status, reason = envcheck._feature_license_status("missing_feature")
    assert status == "NO"
    assert "Secret" not in reason

    monkeypatch.setattr(envcheck.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="Users of vcs_feature: (Total of 2 licenses issued; Total of 2 licenses in use)\n"))
    assert envcheck._feature_license_status("vcs_feature")[0] == "NO"


def test_ssh_probe_requires_explicit_authorized_host(monkeypatch):
    assert envcheck._ssh_probe("-oProxyCommand=unsafe")["status"] == "BLOCKED"
    monkeypatch.setattr(envcheck.shutil, "which", lambda name: "/usr/bin/ssh")
    monkeypatch.setattr(envcheck.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="Linux\nPython 3.12.0\n", stderr=""))
    report = envcheck._ssh_probe("approved-runner")
    assert report["status"] == "PASS"
    assert report["remote_os"] == "Linux"


def test_tool_environment_path_helper_includes_fusion_compiler(tmp_path):
    fc_home = tmp_path / "fc"
    (fc_home / "bin").mkdir(parents=True)
    script = Path(__file__).resolve().parents[1] / "skills/eda-tool-engineering/scripts/eda-env.sh"
    env = {"PATH": "/usr/bin:/bin", "FC_HOME": str(fc_home)}
    result = subprocess.run(["bash", "-c", "source \"$1\"; printf '%s' \"$PATH\"", "test", str(script)],
                            env=env, check=True, text=True, capture_output=True)
    assert result.stdout.split(":")[0] == str(fc_home / "bin")
    assert result.stdout.endswith("/usr/bin:/bin")


def test_version_probes_run_outside_the_project_working_directory(tmp_path, monkeypatch):
    probe = tmp_path / "probe_tool"
    probe.write_text("""#!/usr/bin/env python3
from pathlib import Path
Path('probe_side_effect').write_text('temporary')
print('V-2025.01')
""")
    probe.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    assert envcheck._version(str(probe), "-version")["version"] == "V-2025.01"
    assert not (tmp_path / "probe_side_effect").exists()
    assert eda_runtime.tool_version(str(probe)) == "V-2025.01"
    assert not (tmp_path / "probe_side_effect").exists()
