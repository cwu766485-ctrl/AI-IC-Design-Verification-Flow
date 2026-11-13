import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/eda-tool-engineering/scripts"))
import eda_runner


def test_runner_config_requires_explicit_safe_ssh_target():
    assert eda_runner.runner_config({}) == {"kind": "local"}
    with pytest.raises(eda_runner.RunnerError):
        eda_runner.runner_config({"runner": {"kind": "ssh", "host": "-oProxyCommand=bad", "project_root": "/work/p"}})
    with pytest.raises(eda_runner.RunnerError):
        eda_runner.runner_config({"runner": {"kind": "ssh", "host": "licensed", "project_root": "relative/project"}})


def test_remote_runner_checks_clean_revision_and_fetches_manifest(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    config = root / "eda.yaml"
    config.write_text("name: remote_test\ntop: top\nrtl: [top.sv]\n")
    (root / "top.sv").write_text("module top; endmodule\n")
    subprocess.run(["git", "-C", str(root), "add", "eda.yaml", "top.sv"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    runner_cfg = {"runner": {"kind": "ssh", "host": "authorized-alias", "project_root": "/work/fixture"}}
    config.write_text("name: remote_test\ntop: top\nrtl: [top.sv]\nrunner:\n  kind: ssh\n  host: authorized-alias\n  project_root: /work/fixture\n")
    subprocess.run(["git", "-C", str(root), "add", "eda.yaml"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "remote config"], check=True)
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    config_hash = eda_runner._sha256(config)
    calls = []

    def fake_ssh(host, timeout, command):
        calls.append(command)
        if len(calls) == 1:
            payload = {"sha": revision, "dirty": False, "config_sha256": config_hash}
        else:
            payload = {"status": "PASS", "run_id": "remote_smoke", "flow": "sim"}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    real_run = subprocess.run
    def fake_run(args, *positional, **kwargs):
        if args[0] == "/fake/scp":
            destination = Path(args[-1])
            (destination / "manifest.json").write_text(json.dumps({
                "status": "PASS", "run_id": "remote_smoke", "artifacts": ["/work/fixture/runs/remote_smoke/a.rpt"]}))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return real_run(args, *positional, **kwargs)

    monkeypatch.setattr(eda_runner, "_ssh", fake_ssh)
    monkeypatch.setattr(eda_runner.shutil, "which", lambda name: "/fake/scp" if name == "scp" else "/fake/ssh")
    monkeypatch.setattr(eda_runner.subprocess, "run", fake_run)
    result = eda_runner.execute_remote(root, runner_cfg, "sim", "remote_smoke", root / "runs/remote_smoke")
    assert result["status"] == "PASS"
    assert result["runner"]["kind"] == "ssh"
    assert result["artifacts"] == [str(root / "runs/remote_smoke/a.rpt")]
    assert "EDA_REMOTE_EXECUTION=1" in calls[1]
    assert "--execute" in calls[1]


def test_remote_runner_rejects_dirty_local_worktree(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "eda.yaml").write_text("name: p\ntop: top\nrtl: [top.sv]\n")
    (root / "top.sv").write_text("module top; endmodule\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
    (root / "local-change").write_text("dirty\n")
    cfg = {"runner": {"kind": "ssh", "host": "authorized", "project_root": "/work/p"}}
    with pytest.raises(eda_runner.RunnerError, match="clean local worktree"):
        eda_runner.execute_remote(root, cfg, "sim", "id", root / "runs/id")
