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
CASE_RE = re.compile(r"MATRIX_CORE_CASE_PASS id=10\d+ .* cycles=(\d+) .* macs_per_cycle=([0-9.]+)")
TOOL_RE = re.compile(r"Compiler version (V-[^; ]+)")


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
        cases = [(int(cycles), float(rate)) for cycles, rate in CASE_RE.findall(log)]
        expected = len(WORKLOADS)
        status = "PASS" if code == 0 and len(cases) == expected else "FAIL"
        if stage == "latency_gate" and any(cycles > max_latency_cycles for cycles, _ in cases):
            status = "FAIL"
        total_cycles = sum(item[0] for item in cases)
        total_macs = sum(m * n * k for (m, n, k) in WORKLOADS[:len(cases)])
        artifact = run_dir / ("performance-summary.json" if stage == "performance"
                              else "latency-summary.json")
        summary = {"status": status, "seed": int(seed), "workloads": len(cases),
                   "cycles": [item[0] for item in cases],
                   "macs_per_cycle": (total_macs / total_cycles if total_cycles else None),
                   "max_latency_cycles": max_latency_cycles, "command_returncode": code}
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
