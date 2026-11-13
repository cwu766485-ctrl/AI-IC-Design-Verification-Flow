import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/eda-tool-engineering/scripts"
sys.path.insert(0, str(SCRIPTS))

from eda_runtime import execute_plan, manifest as make_manifest
from stage_runtime import (StageContractError, graph_order, make_stage_input,
                           run_process, validate_stage_input, validate_stage_result)


def valid_input(**changes):
    request = {
        "contract_version": "1.0", "run_id": "r1", "stage_id": "vcs_compile",
        "stage_kind": "compile", "adapter_id": "synopsys.vcs.compile.v1",
        "project": {"name": "fixture", "source_revision": "unknown",
                    "source_tree_sha256": "0" * 64, "ordered_sources": []},
        "argv": [sys.executable, "-c", "pass"],
        "environment": {}, "working_directory": ".", "output_directory": "stages/vcs_compile",
        "expected_artifacts": [], "dependencies": [], "timeout_seconds": 10,
        "budgets": {"run_remaining_seconds": 60},
    }
    request.update(changes)
    return request


def test_published_json_schemas_match_the_runtime_contract():
    schema_dir = ROOT / "docs/schemas"
    input_schema = json.loads((schema_dir / "stage-input.v1.schema.json").read_text())
    result_schema = json.loads((schema_dir / "stage-result.v1.schema.json").read_text())
    Draft202012Validator.check_schema(input_schema)
    Draft202012Validator.check_schema(result_schema)
    Draft202012Validator(input_schema).validate(valid_input())
    assert not Draft202012Validator(input_schema).is_valid(valid_input(unexpected=True))
    result = {"contract_version": "1.0", "run_id": "r1", "stage_id": "vcs_compile",
              "status": "PASS", "error_class": None, "adapter_id": "synopsys.vcs.compile.v1",
              "adapter_supported": True, "exit_code": 0, "started_at": "not-parsed-by-runtime",
              "finished_at": "not-parsed-by-runtime", "source_revision": "unknown",
              "tool_versions": {}, "metrics": {}, "metric_provenance": {},
              "artifacts": [{"path": "proof.rpt", "kind": "file", "size_bytes": 0,
                             "sha256": "0" * 64, "producer_stage": "vcs_compile", "role": "stage_output"}],
              "message": None}
    Draft202012Validator(result_schema).validate(result)
    result["adapter_supported"] = False
    assert not Draft202012Validator(result_schema).is_valid(result)


def test_stage_input_schema_rejects_unknown_fields_and_invalid_values():
    assert validate_stage_input(valid_input())["contract_version"] == "1.0"
    with pytest.raises(StageContractError):
        validate_stage_input(valid_input(unexpected=True))
    with pytest.raises(StageContractError):
        validate_stage_input(valid_input(timeout_seconds=0))
    with pytest.raises(StageContractError):
        validate_stage_input(valid_input(stage_id="Not Valid"))
    with pytest.raises(StageContractError, match="sensitive environment"):
        validate_stage_input(valid_input(environment={"SNPSLMD_LICENSE_FILE": "secret-value"}))


def test_shared_process_runner_applies_nonsecret_stage_environment(tmp_path):
    request = valid_input(argv=[sys.executable, "-c", "import os; print(os.environ['R1_STAGE_MARKER'])"],
                          environment={"R1_STAGE_MARKER": "request-value"})
    record = run_process(request, cwd=str(tmp_path))
    assert record["status"] == "PASS"
    assert record["output"].strip() == "request-value"


def test_pass_result_requires_supported_adapter_tool_and_artifact_provenance():
    result = {"contract_version": "1.0", "run_id": "r1", "stage_id": "vcs_compile",
              "status": "PASS", "error_class": None, "adapter_id": "synopsys.vcs.compile.v1",
              "adapter_supported": True, "exit_code": 0, "started_at": "t0", "finished_at": "t1",
              "source_revision": "sha", "tool_versions": {"vcs": "V-1"}, "metrics": {},
              "metric_provenance": {}, "artifacts": [{"path": "simv", "kind": "file",
              "size_bytes": 1, "sha256": "0" * 64, "producer_stage": "vcs_compile",
              "role": "executable"}], "message": None}
    assert validate_stage_result(result)["status"] == "PASS"
    result["adapter_supported"] = False
    with pytest.raises(StageContractError):
        validate_stage_result(result)


def test_graph_topological_validation_and_cycle_detection():
    stages = [{"id": "source", "dependencies": []}, {"id": "compile", "dependencies": ["source"]}]
    assert graph_order(stages) == ["source", "compile"]
    with pytest.raises(StageContractError, match="missing dependencies"):
        graph_order([{"id": "source", "dependencies": ["absent"]}])
    with pytest.raises(StageContractError, match="cycle"):
        graph_order([{"id": "first", "dependencies": ["second"]},
                     {"id": "second", "dependencies": ["first"]}])


def fake_stage(name, command, artifact, deps=(), adapter_supported=True):
    return {"id": name, "name": name, "stage_kind": "test", "adapter_id": "test." + name + ".v1",
            "command": command, "artifact": str(artifact), "requires": list(deps),
            "dependencies": list(deps), "adapter_supported": adapter_supported,
            "timeout": 10}


def test_dag_adds_required_ancestors_and_skips_dependents_on_failure(tmp_path):
    root = tmp_path / "project"
    runs = root / "runs"
    (runs / "one").mkdir(parents=True)
    counter = root / "counter.txt"
    counter.parent.mkdir(parents=True, exist_ok=True)
    parent = fake_stage("parent", [sys.executable, "-c", "raise SystemExit(9)"], runs / "one/parent.out")
    child = fake_stage("child", [sys.executable, "-c", "raise SystemExit(0)"], runs / "one/child.out", ["parent"])
    records = execute_plan([parent, child], runs / "one", True, root=root, run_id="one", start="child")
    assert [record["status"] for record in records] == ["FAIL", "SKIPPED"]
    assert records[1]["error_class"] == "DEPENDENCY_FAILED"


def test_cache_reuses_only_exact_inputs_and_verified_artifacts(tmp_path):
    root = tmp_path / "project"
    runs = root / "runs"
    script = root / "fake.py"
    input_file = root / "config.txt"
    counter = root / "calls.txt"
    root.mkdir()
    script.write_text("from pathlib import Path\nimport sys\nout=Path(sys.argv[1]); counter=Path(sys.argv[2]); counter.write_text(counter.read_text()+'x' if counter.exists() else 'x'); out.write_text('evidence')\n")
    input_file.write_text("version-a")
    command_template = lambda path: [sys.executable, str(script), str(path / "proof.txt"), str(counter)]

    def run(run_id):
        run_dir = runs / run_id
        run_dir.mkdir(parents=True)
        stage = fake_stage("fake", command_template(run_dir), run_dir / "proof.txt")
        return execute_plan([stage], run_dir, True, root=root, run_id=run_id,
                            cache_inputs=[input_file, script])[0]

    first = run("cold")
    assert first["status"] == "PASS" and not first.get("cache_hit")
    second = run("repeat")
    assert second["status"] == "PASS" and second["cache_hit"]
    assert (runs / "repeat/proof.txt").read_text() == "evidence"
    assert counter.read_text() == "x"
    (runs / "cold/proof.txt").write_text("tampered")
    third = run("tamper_recovery")
    assert third["status"] == "PASS" and not third.get("cache_hit")
    assert (runs / "tamper_recovery/proof.txt").read_text() == "evidence"
    assert counter.read_text() == "xx"
    input_file.write_text("version-b")
    fourth = run("incremental")
    assert fourth["status"] == "PASS" and not fourth.get("cache_hit")
    assert counter.read_text() == "xxx"


def test_unsupported_adapter_and_dry_run_never_pass(tmp_path):
    root = tmp_path / "project"
    run_dir = root / "runs/dry"
    run_dir.mkdir(parents=True)
    should_not_exist = run_dir / "proof.txt"
    not_run = fake_stage("unsupported", [sys.executable, "-c", "open('SHOULD_NOT_RUN','w').write('bad')"],
                         should_not_exist, adapter_supported=False)
    records = execute_plan([not_run], run_dir, True, root=root, run_id="dry")
    assert records[0]["status"] == "BLOCKED"
    assert records[0]["error_class"] == "ADAPTER_UNSUPPORTED"
    dry_dir = root / "runs/plan"
    dry_dir.mkdir()
    planned = fake_stage("planned", [sys.executable, "-c", "raise SystemExit(1)"], dry_dir / "missing")
    record = execute_plan([planned], dry_dir, False, root=root, run_id="plan")[0]
    assert record["status"] == "NOT_RUN"
    assert not (dry_dir / "missing").exists()


def test_cache_key_tracks_seed_configuration_source_library_and_tool_version(tmp_path):
    root = tmp_path / "project"
    runs = root / "runs"
    root.mkdir()
    tool = root / "fake_tool.py"
    counter = root / "calls.txt"
    config = root / "flow.json"
    source = root / "rtl.sv"
    library = root / "slow.db"
    config.write_text('{"param": 4}')
    source.write_text("module top; endmodule\n")
    library.write_text("lib-v1")

    def write_tool(version):
        tool.write_text("#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n"
                        f"if '-version' in sys.argv: print('fake-tool {version}'); sys.exit(0)\n"
                        "out=Path(sys.argv[1]); count=Path(sys.argv[2]); "
                        "count.write_text(count.read_text()+'x' if count.exists() else 'x'); out.write_text('generated')\n")
        tool.chmod(0o755)

    write_tool("v1")

    def execute(run_id, seed=1, option=4):
        run_dir = runs / run_id
        run_dir.mkdir(parents=True)
        stage = fake_stage("synthesis", [str(tool), str(run_dir / "proof.rpt"), str(counter)],
                           run_dir / "proof.rpt")
        stage.update(tool="fake_tool", tool_executable=str(tool), seed=seed,
                     cache_options={"parameter": option})
        return execute_plan([stage], run_dir, True, root=root, run_id=run_id,
                            cache_inputs=[config, source, library])[0]

    assert execute("base")["status"] == "PASS"
    assert execute("same").get("cache_hit") is True
    source.write_text("module top; wire x; endmodule\n")
    assert not execute("source_change").get("cache_hit")
    assert not execute("parameter_change", option=5).get("cache_hit")
    assert not execute("seed_change", seed=2, option=5).get("cache_hit")
    library.write_text("lib-v2")
    assert not execute("library_change", seed=2, option=5).get("cache_hit")
    write_tool("v2")
    assert not execute("tool_change", seed=2, option=5).get("cache_hit")


def test_upstream_artifact_change_invalidates_downstream_stage(tmp_path):
    root = tmp_path / "project"
    runs = root / "runs"
    input_file = root / "input.txt"
    script = root / "generate.py"
    root.mkdir()
    input_file.write_text("one")
    script.write_text("from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text(Path(sys.argv[2]).read_text())\n")

    def workflow(run_id):
        run_dir = runs / run_id
        run_dir.mkdir(parents=True)
        upstream = fake_stage("upstream", [sys.executable, str(script), str(run_dir / "intermediate"), str(input_file)],
                              run_dir / "intermediate")
        downstream = fake_stage("downstream", [sys.executable, "-c",
                               "from pathlib import Path; Path('" + str(run_dir / "final") + "').write_text('ok')"],
                                run_dir / "final", ["upstream"])
        return execute_plan([upstream, downstream], run_dir, True, root=root, run_id=run_id,
                            cache_inputs=[input_file])

    first = workflow("one")
    assert [item["status"] for item in first] == ["PASS", "PASS"]
    second = workflow("two")
    assert [item.get("cache_hit") for item in second] == [True, True]
    input_file.write_text("two")
    third = workflow("three")
    assert [item["status"] for item in third] == ["PASS", "PASS"]
    assert [item.get("cache_hit") for item in third] == [None, None]


def test_exhausted_run_budget_blocks_before_launch(tmp_path):
    root = tmp_path / "project"
    run_dir = root / "runs/budget"
    run_dir.mkdir(parents=True)
    marker = run_dir / "must_not_exist"
    stage = fake_stage("limited", [sys.executable, "-c",
                       "from pathlib import Path; Path('" + str(marker) + "').write_text('bad')"], marker)
    record = execute_plan([stage], run_dir, True, root=root, run_id="budget", budget_seconds=0)[0]
    assert record["status"] == "BLOCKED"
    assert record["error_class"] == "BUDGET_EXHAUSTED"
    assert not marker.exists()


def test_manifest_records_untracked_symlink_tree_as_omitted_not_as_required_evidence(tmp_path):
    root = tmp_path / "project"
    run_dir = root / "runs/symlink_case"
    external = tmp_path / "tool_generated"
    run_dir.mkdir(parents=True)
    external.mkdir()
    (external / "artifact.so").write_text("fixture")
    (run_dir / "csrc").symlink_to(external, target_is_directory=True)
    result = make_manifest(root, "symlink_case", "sim", "vcs", None,
                           {"rtl": [], "filelists": []}, [], {}, [], run_dir)
    assert result["status"] == "NOT_RUN"
    assert result["artifacts"] == []
    assert result["omitted_artifacts"] == [{
        "path": str(run_dir / "csrc"),
        "reason": f"artifact symlinks are not cacheable: {run_dir / 'csrc'}",
    }]


def test_concurrent_resume_serializes_budget_and_refreshes_checkpoint(tmp_path):
    root = tmp_path / "project"
    run_dir = root / "runs/shared"
    root.mkdir()
    run_dir.mkdir(parents=True)
    tool = root / "tool.py"
    counter = root / "calls.txt"
    output = run_dir / "proof.rpt"
    tool.write_text("import sys,time\nfrom pathlib import Path\nc=Path(sys.argv[1]); c.write_text(str(int(c.read_text())+1) if c.exists() else '1'); time.sleep(float(sys.argv[3])); Path(sys.argv[2]).write_text('pass')\n")

    initial = fake_stage("work", [sys.executable, str(tool), str(counter), str(output), "0"], output)
    execute_plan([initial], run_dir, True, root=root, run_id="shared", cache_inputs=[tool])
    stage = fake_stage("work", [sys.executable, str(tool), str(counter), str(output), "0.25"], output)
    child = """
import json,sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from eda_runtime import execute_plan
root=Path(sys.argv[2]); run_dir=root/'runs/shared'; stage=json.loads(sys.argv[3])
previous=json.loads((run_dir/'checkpoint.json').read_text())
record=execute_plan([stage],run_dir,True,previous,root=root,run_id='shared',cache_inputs=[root/'tool.py'],budget_seconds=2)[0]
print(json.dumps({'status':record['status'],'checkpoint_reuse':bool(record.get('checkpoint_reuse')),'cache_hit':bool(record.get('cache_hit'))}))
"""
    processes = [subprocess.Popen([sys.executable, "-c", child, str(SCRIPTS), str(root), json.dumps(stage)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)]
    time.sleep(0.03)
    processes.append(subprocess.Popen([sys.executable, "-c", child, str(SCRIPTS), str(root), json.dumps(stage)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
    outputs = [process.communicate(timeout=10) for process in processes]
    assert all(process.returncode == 0 for process in processes), "".join(err for _, err in outputs)
    results = [json.loads(out) for out, _ in outputs]
    assert all(item["status"] == "PASS" for item in results)
    assert sum(item["checkpoint_reuse"] for item in results) == 1
    assert counter.read_text() == "2"
