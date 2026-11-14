#!/usr/bin/env python3
"""Project adapter for the NMAForge Matrix simulation-performance stages."""

import json
import re
import subprocess
import sys
from pathlib import Path


SEEDS = (20261021, 20261022, 20261023)
WORKLOADS = ((4, 4, 32), (8, 8, 32), (16, 16, 32),
             (16, 32, 32), (32, 32, 64))
PASS_RE = re.compile(r"MATRIX_CORE_RANDOM_PASS .* seed=(\d+)")
CASE_RE = re.compile(r"MATRIX_CORE_CASE_PASS id=(10\d+) .* cycles=(\d+) .* macs_per_cycle=([0-9.]+)")
PROFILE_RE = re.compile(r"^MATRIX_CORE_PROFILE (.+)$", re.MULTILINE)
TOOL_RE = re.compile(r"Compiler version (V-[^; ]+)")
PREFETCH_WAIT_BUCKETS = (
    "prefetch_wait_denial", "prefetch_wait_fifo_full",
    "prefetch_wait_request_grant", "prefetch_wait_outstanding_drain",
    "prefetch_wait_handoff_ready", "prefetch_wait_no_request",
)
PROFILE_TOTAL_FIELDS = (
    "prefetch_wait", *PREFETCH_WAIT_BUCKETS, "arbiter_stall", "banked_denial",
    "line_denial", "scalar_denial", "write", "write_productive",
    "writeback_stall", "write_protection_error",
)
PROFILE_STATE_FIELDS = (
    "a_req", "a_wait", "b_req", "b_wait", "bias_req", "bias_wait",
    "prep_mac", "mac", "write", "next", "done", "error",
    "error_drain", "prefetch_wait",
)
REQUIRED_PROFILE_FIELDS = set(PROFILE_TOTAL_FIELDS) | set(PROFILE_STATE_FIELDS) | {
    "id", "total", "writeback_wait", "response_wait", "outstanding_highwater",
    "fifo_full", "prefetch_a_req", "prefetch_a_drain", "prefetch_b_req",
    "prefetch_b_drain", "prefetch_overlap", "prefetch_completed",
    "a_tile_cache_hits", "max_outstanding",
}


def parse_profiles(log, case_cycles):
    profiles = {}
    for line in PROFILE_RE.findall(log):
        profile = {}
        for field in line.split():
            if "=" not in field:
                raise ValueError("malformed Matrix profile field: " + field)
            key, value = field.split("=", 1)
            try:
                profile[key] = int(value)
            except ValueError as exc:
                raise ValueError("non-integer Matrix profile field: " + key) from exc
        if "id" not in profile or profile["id"] in profiles:
            raise ValueError("missing or duplicate Matrix profile id")
        missing = REQUIRED_PROFILE_FIELDS - set(profile)
        if missing:
            raise ValueError("Matrix profile missing fields: " + ", ".join(sorted(missing)))
        profiles[profile["id"]] = profile

    if set(profiles) != set(case_cycles):
        raise ValueError("Matrix profile IDs do not match benchmark cases")
    for case_id, cycles in case_cycles.items():
        profile = profiles[case_id]
        if profile.get("total") != cycles:
            raise ValueError("Matrix profile total does not match workload cycles for id {}".format(case_id))
        if sum(profile[field] for field in PROFILE_STATE_FIELDS) != cycles:
            raise ValueError("Matrix state-cycle attribution does not balance for id {}".format(case_id))
        if profile.get("prefetch_wait") != sum(profile.get(k, -1) for k in PREFETCH_WAIT_BUCKETS):
            raise ValueError("Matrix prefetch-wait attribution does not balance for id {}".format(case_id))
        if profile.get("write") != sum(profile.get(k, -1) for k in (
                "write_productive", "writeback_stall", "write_protection_error")):
            raise ValueError("Matrix write attribution does not balance for id {}".format(case_id))
        if profile.get("writeback_wait") != profile.get("writeback_stall"):
            raise ValueError("legacy and split writeback-stall counters disagree for id {}".format(case_id))
    return [profiles[case_id] for case_id in sorted(profiles)]


def sum_profile_fields(profiles):
    return {field: sum(profile.get(field, 0) for profile in profiles)
            for field in PROFILE_TOTAL_FIELDS}


def run_make(source_root, run_dir, target, variables):
    sim_dir = source_root / "dv/block/compute/matrix/sim"
    command = ["make", "-C", str(sim_dir), target]
    command.extend("{}={}".format(key, value) for key, value in variables.items())
    completed = subprocess.run(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, universal_newlines=True)
    (run_dir / "command.log").write_text(completed.stdout)
    return completed.returncode, completed.stdout


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main(argv):
    if len(argv) != 6:
        raise SystemExit("usage: adapter.py STAGE SOURCE_ROOT RUN_DIR SEED MAX_LATENCY_CYCLES")
    stage, source_arg, run_arg, seed, latency_arg = argv[1:]
    max_latency_cycles = int(latency_arg)
    if max_latency_cycles < 1:
        raise SystemExit("MAX_LATENCY_CYCLES must be positive")
    source_root = Path(source_arg).resolve()
    run_dir = Path(run_arg).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    if stage not in ("regression", "reference_model", "latency_gate", "performance"):
        raise SystemExit("unsupported simulation-performance stage: " + stage)

    if stage in ("regression", "reference_model"):
        out = run_dir / "vcs-regression"
        code, log = run_make(source_root, run_dir, "core-random-regress", {
            "SEEDS": " ".join(str(value) for value in SEEDS),
            "CORE_OUT_DIR": str(out),
        })
        seen = sorted(int(value) for value in PASS_RE.findall(log))
        status = "PASS" if code == 0 and seen == list(SEEDS) else "FAIL"
        artifact = run_dir / "regression-summary.json"
        write_json(artifact, {"status": status, "seeds": seen,
                              "reference_model": "testbench integer model",
                              "command_returncode": code})
        versions = sorted(set(TOOL_RE.findall(log)))
    else:
        out = run_dir / "vcs-benchmark"
        code, log = run_make(source_root, run_dir, "matrix-pipeline-benchmark", {
            "SEED": seed,
            "PIPELINE_ARRAY_SIZE": "16",
            "OUTSTANDING_DEPTH": "4",
            "NEXT_K_PREFETCH_ENABLE": "1",
            "A_TILE_CACHE_ENABLE": "1",
            "PIPELINE_BENCH_OUT": str(out),
        })
        cases = [(int(case_id), int(cycles), float(rate))
                 for case_id, cycles, rate in CASE_RE.findall(log)]
        expected = len(WORKLOADS)
        profiles = []
        profile_error = None
        try:
            profiles = parse_profiles(log, {case_id: cycles for case_id, cycles, _ in cases})
        except ValueError as exc:
            profile_error = str(exc)
        status = "PASS" if code == 0 and len(cases) == expected and profile_error is None else "FAIL"
        if stage == "latency_gate" and any(cycles > max_latency_cycles for _, cycles, _ in cases):
            status = "FAIL"
        total_cycles = sum(item[1] for item in cases)
        total_macs = sum(m * n * k for (m, n, k) in WORKLOADS[:len(cases)])
        artifact = run_dir / ("performance-summary.json" if stage == "performance"
                              else "latency-summary.json")
        summary = {"status": status, "seed": int(seed), "workloads": len(cases),
                   "cycles": [item[1] for item in cases],
                   "macs_per_cycle": (total_macs / total_cycles if total_cycles else None),
                   "max_latency_cycles": max_latency_cycles, "command_returncode": code,
                   "profile_schema": "matrix_cycle_attribution_v1",
                   "profiles": profiles,
                   "attribution_totals": sum_profile_fields(profiles),
                   "profile_validation_error": profile_error}
        write_json(artifact, summary)
        versions = sorted(set(TOOL_RE.findall(log)))

    result = {
        "status": status,
        "adapter_id": "nmaforge.matrix.simulation_performance.{}.v1".format(stage),
        "adapter_supported": True,
        "tool_versions": {"vcs": versions[0] if versions else "VERSION_NOT_FOUND"},
        "metrics": {},
        "metric_provenance": {},
        "artifacts": [artifact.name],
    }
    if stage == "performance" and status == "PASS":
        summary = json.loads(artifact.read_text())
        result["metrics"] = {
            "workload_cycles": sum(summary["cycles"]),
            "macs_per_cycle": summary["macs_per_cycle"],
        }
        result["metric_provenance"] = {
            name: {"artifact": artifact.name, "parser_id": "nmaforge-matrix-log",
                   "parser_version": "1"} for name in result["metrics"]
        }
    write_json(run_dir / "stage-result.json", result)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
