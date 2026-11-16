import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "skills/rtl-ppa-optimization/scripts/blind_debug_benchmark.py"
SPEC = importlib.util.spec_from_file_location("blind_debug_benchmark", SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def fixture_tree(tmp_path):
    rtl_root = tmp_path / "rtl"
    (rtl_root / "compute").mkdir(parents=True)
    (rtl_root / "tb").mkdir()
    (rtl_root / "compute/core.sv").write_text("module core; endmodule\n")
    (rtl_root / "tb/core_tb.sv").write_text("module core_tb; endmodule\n")
    spec = tmp_path / "design.md"
    spec.write_text("The core returns one response per accepted request.\n")
    log = tmp_path / "vcs.log"
    log.write_text("UVM_ERROR cycle=19 checker=CK-1 request stalled\n")
    key_source = tmp_path / "answer-source.json"
    expected = {
        "root_cause_class": "protocol_handshake",
        "primary_module": "core",
        "primary_signal": "response_valid",
        "causal_facts": ["accepted request lacks response"],
        "patch_invariants": ["preserve response ordering"],
        "revalidation_stages": ["directed_test", "regression"],
    }
    key_source.write_text(json.dumps(expected))
    return rtl_root, spec, log, key_source, expected


def test_challenge_inputs_exclude_separate_answer_key_and_hash_every_input(tmp_path):
    rtl_root, spec, log, key_source, expected = fixture_tree(tmp_path)
    destination = tmp_path / "agent_input"
    answer_path = tmp_path / "private" / "answer.json"
    result = benchmark.prepare_challenge(
        spec, rtl_root, ["compute/core.sv"], log, 44, "source-sha",
        destination, answer_path, testbench_paths=["tb/core_tb.sv"])
    benchmark.write_answer_key(answer_path, result["challenge_id"], expected)

    manifest = json.loads((destination / "input/challenge.json").read_text())
    assert result["status"] == "PREPARED"
    assert manifest["seed"] == 44
    assert [item["role"] for item in manifest["inputs"]] == [
        "design_spec", "rtl_source", "testbench_source", "vcs_log"]
    assert all(len(item["sha256"]) == 64 for item in manifest["inputs"])
    package_text = "\n".join(path.read_text(errors="replace")
                              for path in (destination / "input").rglob("*") if path.is_file())
    assert "protocol_handshake" not in package_text
    assert "preserve response ordering" not in package_text
    assert answer_path.is_file()
    assert not any("answer" in path.name.lower() for path in (destination / "input").rglob("*"))


def test_answer_key_must_be_outside_challenge_directory(tmp_path):
    rtl_root, spec, log, _, _ = fixture_tree(tmp_path)
    destination = tmp_path / "challenge"
    with pytest.raises(benchmark.BenchmarkInputError, match="outside"):
        benchmark.prepare_challenge(spec, rtl_root, ["compute/core.sv"], log,
                                    1, "source-sha", destination,
                                    destination / "answer.json")


def test_challenge_rejects_rtl_path_escape(tmp_path):
    rtl_root, spec, log, _, _ = fixture_tree(tmp_path)
    with pytest.raises(benchmark.BenchmarkInputError, match="relative"):
        benchmark.prepare_challenge(spec, rtl_root, ["../answer-source.json"], log,
                                    1, "source-sha", tmp_path / "challenge",
                                    tmp_path / "private/answer.json")


def test_frozen_prediction_is_scored_against_matching_private_key(tmp_path):
    challenge_id = "abc123"
    expected = {
        "root_cause_class": "protocol_handshake",
        "primary_module": "core",
        "primary_signal": "response_valid",
        "causal_facts": ["accepted request lacks response"],
        "patch_invariants": ["preserve response ordering"],
        "revalidation_stages": ["directed_test", "regression"],
    }
    answer = tmp_path / "private/answer.json"
    benchmark.write_answer_key(answer, challenge_id, expected)
    prediction = tmp_path / "diagnosis.json"
    prediction.write_text(json.dumps({"schema_version": 1,
                                      "challenge_id": challenge_id, **expected}))

    score = benchmark.score_response(answer, prediction)

    assert score["status"] == "SCORED"
    assert score["exact_match"] is True
    assert all(score["criteria"].values())


def test_prediction_for_wrong_challenge_cannot_be_scored(tmp_path):
    expected = {"root_cause_class": "design", "primary_module": "core",
                "primary_signal": "done", "causal_facts": [],
                "patch_invariants": [], "revalidation_stages": []}
    answer = tmp_path / "answer.json"
    benchmark.write_answer_key(answer, "expected", expected)
    prediction = tmp_path / "prediction.json"
    prediction.write_text(json.dumps({"schema_version": 1, "challenge_id": "other"}))
    with pytest.raises(benchmark.BenchmarkInputError, match="does not match"):
        benchmark.score_response(answer, prediction)
