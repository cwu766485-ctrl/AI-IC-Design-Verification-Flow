"""Backward-compatible aicflow CLI backed by the shared Stage Runtime DAG."""
import argparse
import copy
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from eda_config import ConfigError, load, sources
from eda_runtime import (_attempts_charged, artifact_record, build_stages, execute_plan, manifest as make_manifest,
                         parse_power, parse_qor, project_contract, save, sha256)
from eda_runner import RunnerError, execute_remote, runner_config
from stage_runtime import StageContractError, save_json


FLOW_PARTS = {"rtl_to_sim": ["sim"], "rtl_to_regression": ["regression"],
              "rtl_to_synth": ["synth"], "rtl_to_synth_sta": ["synth", "sta"],
              "rtl_to_sim_synth": ["sim", "synth"]}
FLOWS = set(FLOW_PARTS) | {"sim", "regression", "coverage", "synth", "sta"}
EDA = Path(__file__).with_name("eda.py")


def _eda_api():
    import eda
    return eda


def _parts(name):
    return FLOW_PARTS.get(name, [name])


def _build(root, name, run_dir, cfg):
    eda = _eda_api()
    combined, inputs_by_flow, options_by_flow = [], {}, {}
    for flow in _parts(name):
        exe = eda.executable(eda.FLOW_TOOL[flow])
        flow_cfg = cfg
        adapter_run_dir = run_dir
        if name == "rtl_to_synth_sta":
            adapter_run_dir = run_dir / flow
            adapter_run_dir.mkdir(parents=True, exist_ok=True)
        if name == "rtl_to_synth_sta" and flow == "sta":
            flow_cfg = copy.deepcopy(cfg)
            flow_cfg.setdefault("flows", {}).setdefault("sta", {})["netlist"] = str(run_dir / "synth" / "netlist.v")
            flow_cfg["flows"]["sta"]["allow_generated_netlist"] = True
        inputs, stages, options = build_stages(flow, root, flow_cfg, adapter_run_dir, exe)
        if name == "rtl_to_synth_sta" and flow == "sta":
            stages[0]["requires"] = ["synthesis"]
        combined.extend(stages)
        inputs_by_flow[flow] = inputs
        options_by_flow[flow] = options
    if len(inputs_by_flow) == 1:
        inputs = next(iter(inputs_by_flow.values()))
        options = next(iter(options_by_flow.values()))
    else:
        inputs = {key: list(dict.fromkeys(value for item in inputs_by_flow.values() for value in item.get(key, [])))
                  for key in ("rtl", "filelists", "include_dirs", "defines")}
        options = {"flows": options_by_flow}
    return inputs, combined, options


def _cache_inputs(root, cfg, inputs, options):
    values = [root / "eda.yaml", Path(__file__).resolve(), EDA.resolve(),
              Path(__file__).with_name("eda_runtime.py"), Path(__file__).with_name("eda_config.py"),
              Path(__file__).with_name("stage_runtime.py")]
    for key in ("rtl", "filelists", "include_dirs"):
        values.extend(inputs.get(key, []))
    def walk(value):
        if isinstance(value, dict):
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)
        elif isinstance(value, str):
            if not value.strip():
                return
            path = Path(value)
            if not path.is_absolute():
                path = root / path
            try:
                path.resolve().relative_to((root / "runs").resolve())
                generated_output = True
            except ValueError:
                generated_output = False
            if path.exists() and not generated_output:
                values.append(path)
    walk(options)
    pdk = cfg.get("pdk", {})
    if isinstance(pdk, dict):
        pdk_root = root / pdk.get("root", ".")
        for name in [pdk.get("target_library"), *pdk.get("link_libraries", [])]:
            if name:
                path = Path(name)
                values.append(path if path.is_absolute() else pdk_root / path)
    if cfg.get("constraints"):
        path = Path(cfg["constraints"])
        values.append(path if path.is_absolute() else root / path)
    return list(dict.fromkeys(Path(x) for x in values))


def _overall_status(records):
    statuses = [record.get("status", "NOT_RUN") for record in records]
    for status in ("FAIL", "ERROR", "BLOCKED"):
        if status in statuses:
            return status
    if statuses and all(status == "PASS" for status in statuses):
        return "PASS"
    return "NOT_RUN"


def _metrics(flow, records, run_dir, options):
    metrics = {}
    parts = _parts(flow)
    if "synth" in parts or "sta" in parts:
        for design_stage in ("synth", "sta"):
            if design_stage not in parts:
                continue
            output_dir = run_dir / design_stage if flow == "rtl_to_synth_sta" else run_dir
            report_paths = [output_dir / "qor.rpt", output_dir / "area.rpt", output_dir / "timing.rpt", output_dir / "constraints.rpt"]
            qor = parse_qor(report_paths)
            metrics["qor" if design_stage == "synth" else "sta_qor"] = qor
            required = ("area", "wns", "tns") if design_stage == "synth" else ("wns", "tns")
            if any(qor.get(name) is None for name in required):
                return metrics, "BLOCKED", "METRIC_MISSING"
            if design_stage == "synth":
                power = parse_power(output_dir / "power.rpt")
                synth_options = options.get("flows", {}).get("synth", {}) if "flows" in options else options
                power["provenance"] = synth_options.get("power_provenance")
                power["activity_file"] = synth_options.get("activity_file")
                metrics["power"] = power
                if synth_options.get("activity_file") and not any(power.get(k) is not None for k in
                        ("total_dynamic_power", "cell_leakage_power", "total_power")):
                    return metrics, "BLOCKED", "METRIC_MISSING"
    if any(part in parts for part in ("sim", "regression")):
        results = [record for record in records if record.get("name", "").startswith("result_")]
        if results:
            metrics["regression"] = {"tests_total": len(results),
                                      "tests_passed": sum(x.get("status") == "PASS" for x in results),
                                      "tests_failed": sum(x.get("status") == "FAIL" for x in results),
                                      "seeds": [x.get("seed") for x in results]}
        coverage = next((record for record in records if record.get("name") == "coverage_summary"), None)
        if coverage and coverage.get("metrics"):
            metrics["coverage"] = coverage["metrics"]
    return metrics, None, None


def _execute(root, flow, run_id, cfg, execute, start=None, end=None, resume=None, budget_seconds=float("inf")):
    run_dir = root / "runs" / run_id
    inputs, stages, options = _build(root, flow, run_dir, cfg)
    cache_inputs = _cache_inputs(root, cfg, inputs, options)
    started = time.time()
    stage_project = project_contract(root, cfg, inputs, stages, cache_inputs)
    records = execute_plan(stages, run_dir, execute, resume, root=root, run_id=run_id,
                           project=stage_project, cache_inputs=cache_inputs,
                           start=start, end=end, budget_seconds=budget_seconds)
    result = make_manifest(root, run_id, flow, "composite" if len(_parts(flow)) > 1 else
                           _eda_api().FLOW_TOOL[_parts(flow)[0]], None, inputs, stages, options,
                           records, run_dir)
    result.update(project=cfg.get("name", root.name), flow=flow,
                  stage_order=[stage.get("id", stage.get("name")) for stage in stages],
                  selected_start=start, selected_end=end,
                  budget_seconds=None if budget_seconds == float("inf") else budget_seconds,
                  budget_charged_seconds=round(_attempts_charged(run_dir / "attempts.jsonl"), 6),
                  efficiency={"workflow_elapsed_sec": round(time.time() - started, 6),
                              "eda_stage_elapsed_sec": round(sum(x.get("elapsed_sec", 0) for x in records), 6),
                              "stage_count": sum(1 for x in records if x.get("status") != "NOT_RUN"),
                              "tool_invocations": sum(1 for x in records if x.get("return_code") is not None and not x.get("cache_hit") and not x.get("checkpoint_reuse")),
                              "cache_hits": sum(1 for x in records if x.get("cache_hit")),
                              "checkpoint_reuses": sum(1 for x in records if x.get("checkpoint_reuse")),
                              "agent_invocations": None,
                              "token_usage": None})
    metrics, metric_status, metric_error = _metrics(flow, records, run_dir, options)
    result["metrics"] = metrics
    if metric_status and result.get("status") == "PASS":
        result.update(status=metric_status, error_class=metric_error,
                      reason="required QoR metrics could not be parsed from reports")
    result["artifacts"] = result.get("artifacts", [])
    metrics_path = run_dir / "metrics.json"
    save(metrics_path, {"schema_version": 1, "run_id": run_id, "flow": flow,
                        "status": result["status"], "metrics": metrics,
                        "tool_versions": result.get("tool_versions", {}),
                        "source_revision": result.get("source_revision")})
    result["artifacts"].append(artifact_record(metrics_path))
    save(run_dir / "manifest.json", result)
    checkpoint = {"schema_version": 2, "run_id": run_id, "project": cfg.get("name", root.name),
                  "flow": flow, "status": result["status"], "stages": records,
                  "stage_order": result["stage_order"], "selected_start": start,
                  "selected_end": end,
                  "budget_seconds": None if budget_seconds == float("inf") else budget_seconds,
                  "budget_charged_seconds": round(_attempts_charged(run_dir / "attempts.jsonl"), 6),
                  "manifest": str(run_dir / "manifest.json"),
                  "updated_at": time.time()}
    save_json(run_dir / "checkpoint.json", checkpoint)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aicflow")
    commands = ap.add_subparsers(dest="command")
    commands.add_parser("doctor")
    for command_name in ("plan", "run"):
        parser = commands.add_parser(command_name)
        parser.add_argument("--flow", choices=sorted(FLOWS), required=True)
        parser.add_argument("--run-id")
        parser.add_argument("--from", dest="start")
        parser.add_argument("--to", dest="end")
        parser.add_argument("--budget-seconds", type=float)
        if command_name == "run":
            parser.add_argument("--execute", action="store_true")
    resume = commands.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--execute", action="store_true")
    resume.add_argument("--from", dest="start")
    resume.add_argument("--to", dest="end")
    resume.add_argument("--budget-seconds", type=float)
    report = commands.add_parser("report")
    report.add_argument("--run-id", required=True)
    report.add_argument("--log-tail", nargs="?", const=50, type=int)
    args = ap.parse_args(argv)
    if not args.command:
        ap.error("a command is required")
    root = Path.cwd()
    if args.command == "doctor":
        return subprocess.run([sys.executable, str(EDA), "doctor"], cwd=root).returncode
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.run_id or "") and args.command in ("resume", "report"):
        ap.error("invalid run id")
    if args.command == "report":
        manifest_path = root / "runs" / args.run_id / "manifest.json"
        checkpoint_path = root / "runs" / args.run_id / "checkpoint.json"
        path = manifest_path if manifest_path.is_file() else checkpoint_path
        if not path.is_file():
            print(json.dumps({"status": "BLOCKED", "error": "run evidence not found"}))
            return 1
        data = json.loads(path.read_text())
        if args.log_tail is not None:
            if args.log_tail < 1:
                ap.error("--log-tail must be positive")
            excerpts = {}
            for stage in data.get("stages", []):
                log = stage.get("log")
                if log and Path(log).is_file():
                    lines = Path(log).read_text(errors="replace").splitlines()[-min(args.log_tail, 200):]
                    excerpts[stage.get("id", stage.get("name", "stage"))] = [line[:1000] for line in lines]
            data["log_excerpts"] = excerpts
        print(json.dumps(data, indent=2))
        return 0
    if args.command == "resume":
        checkpoint_path = root / "runs" / args.run_id / "checkpoint.json"
        if not checkpoint_path.is_file():
            print(json.dumps({"status": "BLOCKED", "error": "checkpoint not found"}))
            return 1
        previous = json.loads(checkpoint_path.read_text())
        flow = previous.get("flow")
        if flow not in FLOWS:
            print(json.dumps({"status": "BLOCKED", "error": "checkpoint has no supported flow"}))
            return 1
        run_id = args.run_id
        execute = args.execute
        start, end = args.start or previous.get("selected_start"), args.end or previous.get("selected_end")
        old_budget = previous.get("budget_seconds")
        if args.budget_seconds is not None and args.budget_seconds <= 0:
            ap.error("--budget-seconds must be positive")
        if old_budget is None:
            budget_seconds = args.budget_seconds if args.budget_seconds is not None else float("inf")
        elif args.budget_seconds is None:
            budget_seconds = old_budget
        else:
            budget_seconds = min(old_budget, args.budget_seconds)
    else:
        flow = args.flow
        run_id = args.run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + flow
        execute = args.command == "run" and args.execute
        start, end = args.start, args.end
        if args.budget_seconds is not None and args.budget_seconds <= 0:
            ap.error("--budget-seconds must be positive")
        budget_seconds = args.budget_seconds if args.budget_seconds is not None else float("inf")
        previous = None
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
        ap.error("invalid run id")
    run_dir = root / "runs" / run_id
    try:
        cfg = load(root / "eda.yaml")
        if (args.command in ("run", "resume") and execute and
                os.environ.get("EDA_REMOTE_EXECUTION") != "1"):
            runner = runner_config(cfg)
            if runner.get("kind") == "ssh":
                try:
                    result = execute_remote(root, cfg, flow, run_id, run_dir,
                                            command=args.command, start=start, end=end,
                                            budget_seconds=None if budget_seconds == float("inf") else budget_seconds)
                except RunnerError as exc:
                    result = {"run_id": run_id, "flow": flow, "status": "BLOCKED",
                              "error_class": "SSH_RUNNER_UNAVAILABLE", "reason": str(exc),
                              "runner": {"kind": "ssh"}}
                    if args.command == "run" and not run_dir.exists():
                        run_dir.mkdir(parents=True, exist_ok=True)
                        save(run_dir / "manifest.json", result)
                    print(json.dumps(result, indent=2))
                    return 1
                print(json.dumps(result, indent=2))
                return 0 if result.get("status") in ("PASS", "NOT_RUN") else 1
        if previous is None:
            if run_dir.exists():
                raise ConfigError(f"run already exists: {run_dir}")
            run_dir.mkdir(parents=True)
        result = _execute(root, flow, run_id, cfg, execute, start, end, previous, budget_seconds)
    except (OSError, ConfigError, StageContractError) as exc:
        result = {"run_id": run_id, "flow": flow, "status": "BLOCKED",
                  "error_class": "CONFIG_INVALID", "reason": str(exc)}
        run_dir.mkdir(parents=True, exist_ok=True)
        save(run_dir / "manifest.json", result)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") in ("PASS", "NOT_RUN") else 1


if __name__ == "__main__":
    sys.exit(main())
