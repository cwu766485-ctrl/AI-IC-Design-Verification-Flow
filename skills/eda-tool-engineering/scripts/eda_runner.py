"""Configured local and SSH execution runner helpers for eda.py."""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path


class RunnerError(ValueError):
    pass


def runner_config(cfg):
    value = cfg.get("runner", {"kind": "local"})
    if not isinstance(value, dict):
        raise RunnerError("runner must be a mapping")
    kind = value.get("kind", "local")
    if kind == "local":
        return {"kind": "local"}
    if kind != "ssh":
        raise RunnerError("runner.kind must be local or ssh")
    host = value.get("host")
    remote_root = value.get("project_root")
    python = value.get("python", "python3")
    timeout = value.get("connect_timeout_sec", 10)
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9_.@-]+", host) or host.startswith("-"):
        raise RunnerError("runner.host must be an SSH alias or user@host token")
    if not isinstance(remote_root, str) or not remote_root.startswith("/") or re.search(r"[\s:]", remote_root):
        raise RunnerError("runner.project_root must be an absolute remote path without whitespace or ':'")
    if not isinstance(python, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", python):
        raise RunnerError("runner.python must be an executable name or path")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
        raise RunnerError("runner.connect_timeout_sec must be between 1 and 120")
    return {"kind": "ssh", "host": host, "project_root": remote_root,
            "python": python, "connect_timeout_sec": timeout}


def _git_value(root, *args):
    proc = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ssh(host, timeout, remote_command):
    ssh = shutil.which("ssh")
    if not ssh:
        raise RunnerError("SSH runner is configured but ssh is not installed")
    try:
        proc = subprocess.run([ssh, "-o", "BatchMode=yes", "-o",
                               "ConnectTimeout=%d" % timeout, host, remote_command],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        raise RunnerError("SSH runner timed out")
    except OSError:
        raise RunnerError("SSH runner could not be started")
    return proc


def execute_remote(root, cfg, flow, run_id, run_dir):
    """Run the canonical eda.py command in a matching clean remote checkout.

    The remote project, PDK/library assets and output filesystem remain under
    their remote owner's control. Only the resulting run directory is copied
    back. No local fallback occurs after a remote failure.
    """
    config = runner_config(cfg)
    if config["kind"] != "ssh":
        return None
    root = Path(root).resolve()
    local_sha = _git_value(root, "rev-parse", "HEAD")
    dirty = _git_value(root, "status", "--porcelain")
    config_path = root / "eda.yaml"
    if not local_sha or dirty:
        raise RunnerError("SSH execution requires a committed clean local worktree")
    if not config_path.is_file():
        raise RunnerError("SSH execution requires project eda.yaml")
    remote_root = config["project_root"]
    python = shlex.quote(config["python"])
    remote_root_q = shlex.quote(remote_root)
    probe_code = (
        "import hashlib,json,pathlib,subprocess,sys; r=pathlib.Path(sys.argv[1]); "
        "g=subprocess.run(['git','-C',str(r),'rev-parse','HEAD'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True); "
        "d=subprocess.run(['git','-C',str(r),'status','--porcelain'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True); "
        "p=r/'eda.yaml'; h=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None; "
        "print(json.dumps({'sha':g.stdout.strip() if g.returncode==0 else None,'dirty':bool(d.stdout.strip()) if d.returncode==0 else None,'config_sha256':h}))"
    )
    probe_cmd = "%s -c %s %s" % (python, shlex.quote(probe_code), remote_root_q)
    probe = _ssh(config["host"], config["connect_timeout_sec"], probe_cmd)
    if probe.returncode:
        raise RunnerError("SSH preflight failed; check authorization and remote project path")
    try:
        remote = json.loads(probe.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RunnerError("SSH preflight returned invalid project metadata")
    if remote.get("sha") != local_sha or remote.get("dirty") is not False:
        raise RunnerError("remote checkout must be clean and at the same Git SHA")
    if remote.get("config_sha256") != _sha256(config_path):
        raise RunnerError("remote eda.yaml does not match the local configuration")

    remote_eda = remote_root + "/skills/eda-tool-engineering/scripts/eda.py"
    argv = [config["python"], remote_eda, "run", "--flow", flow,
            "--execute", "--run-id", run_id]
    shell_argv = " ".join(shlex.quote(str(item)) for item in argv)
    command = "cd %s && EDA_REMOTE_EXECUTION=1 %s" % (remote_root_q, shell_argv)
    result = _ssh(config["host"], config["connect_timeout_sec"], command)
    if result.returncode:
        detail = None
        try:
            candidate = json.loads(result.stdout)
            detail = candidate.get("error") or candidate.get("reason")
        except (ValueError, TypeError):
            pass
        raise RunnerError(detail or "remote EDA command failed; inspect its remote run log")
    scp = shutil.which("scp")
    if not scp:
        raise RunnerError("SSH execution finished remotely, but scp is unavailable to retrieve evidence")
    remote_run = "%s:%s/runs/%s/." % (config["host"], remote_root, run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        fetched = subprocess.run([scp, "-r", remote_run, str(run_dir)], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, universal_newlines=True,
                                 timeout=config["connect_timeout_sec"] + 120)
    except (OSError, subprocess.TimeoutExpired):
        raise RunnerError("remote run completed, but evidence retrieval failed")
    if fetched.returncode:
        raise RunnerError("remote run completed, but evidence retrieval failed")
    log_path = run_dir / "remote-run.log"
    log_path.write_text(result.stdout + result.stderr)
    manifest_path = run_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
            def rewrite(value):
                if isinstance(value, str):
                    return value.replace(remote_root, str(root))
                if isinstance(value, list):
                    return [rewrite(item) for item in value]
                if isinstance(value, dict):
                    return {key: rewrite(item) for key, item in value.items()}
                return value
            manifest = rewrite(manifest)
            manifest["runner"] = {"kind": "ssh", "host": config["host"],
                                  "remote_project_root": remote_root,
                                  "evidence_fetch": "PASS"}
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        except (OSError, ValueError):
            raise RunnerError("remote run did not return a valid manifest")
    else:
        raise RunnerError("remote run did not return manifest.json")
    return json.loads(manifest_path.read_text())
