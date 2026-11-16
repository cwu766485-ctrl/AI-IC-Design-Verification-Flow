#!/usr/bin/env python3
"""Package blinded RTL debug inputs and score a separate agent response.

This utility does not invoke an AI model or EDA tool. The challenge directory
is the only directory intended for the debugging agent; the answer key must be
stored elsewhere and revealed only after the response is frozen.
"""

import argparse
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path


class BenchmarkInputError(ValueError):
    pass


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_below(path, parent):
    try:
        return os.path.commonpath((str(Path(path).resolve()),
                                   str(Path(parent).resolve()))) == str(Path(parent).resolve())
    except ValueError:
        return False


def _write_json(path, payload, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(str(path), flags, 0o600 if private else 0o644)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _load_json(path):
    with Path(path).open() as stream:
        return json.load(stream)


def _validate_expected(expected):
    required = {"root_cause_class", "primary_module", "primary_signal",
                "causal_facts", "patch_invariants", "revalidation_stages"}
    if not isinstance(expected, dict) or set(expected) != required:
        raise BenchmarkInputError("answer key must define exactly the benchmark scoring fields")
    for field in ("root_cause_class", "primary_module", "primary_signal"):
        if not isinstance(expected[field], str) or not expected[field]:
            raise BenchmarkInputError(field + " must be a nonempty string")
    for field in ("causal_facts", "patch_invariants", "revalidation_stages"):
        values = expected[field]
        if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
            raise BenchmarkInputError(field + " must be a list of nonempty strings")
    return expected


def prepare_challenge(spec_path, rtl_root, rtl_paths, log_path, seed,
                      source_revision, destination, answer_key_path,
                      testbench_paths=()):
    spec_path = Path(spec_path).resolve()
    rtl_root = Path(rtl_root).resolve()
    log_path = Path(log_path).resolve()
    destination = Path(destination).resolve()
    answer_key_path = Path(answer_key_path).resolve()
    if not spec_path.is_file() or not log_path.is_file() or not rtl_root.is_dir():
        raise BenchmarkInputError("spec, RTL root, and VCS log must exist")
    if not isinstance(seed, int) or seed < 0 or not source_revision:
        raise BenchmarkInputError("seed and source revision are required")
    if _is_below(answer_key_path, destination):
        raise BenchmarkInputError("answer key must be outside the challenge directory")
    if destination.exists() and any(destination.iterdir()):
        raise BenchmarkInputError("challenge destination must be empty")
    if answer_key_path.exists():
        raise BenchmarkInputError("answer key output already exists")

    source_files = []
    for role, raw_paths in (("rtl_source", rtl_paths), ("testbench_source", testbench_paths)):
        for raw_path in raw_paths:
            relative = Path(raw_path)
            if relative.is_absolute() or ".." in relative.parts:
                raise BenchmarkInputError("source paths must be relative to rtl_root")
            source = (rtl_root / relative).resolve()
            if not _is_below(source, rtl_root) or not source.is_file():
                raise BenchmarkInputError("source is missing or escapes rtl_root: " + str(raw_path))
            source_files.append((role, relative.as_posix(), source))
    if not source_files:
        raise BenchmarkInputError("at least one ordered RTL source is required")

    destination.mkdir(parents=True, exist_ok=True)
    challenge_id = uuid.uuid4().hex
    entries = []

    spec_target = destination / "input" / "design_spec.md"
    spec_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(spec_path, spec_target)
    entries.append({"role": "design_spec", "path": "input/design_spec.md",
                    "sha256": _sha256(spec_target)})

    for role, relative, source in source_files:
        directory = "testbench" if role == "testbench_source" else "rtl"
        target = destination / "input" / directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        entries.append({"role": role, "path": "input/" + directory + "/" + relative,
                        "sha256": _sha256(target)})

    log_target = destination / "input" / "evidence" / "vcs.log"
    log_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(log_path, log_target)
    entries.append({"role": "vcs_log", "path": "input/evidence/vcs.log",
                    "sha256": _sha256(log_target)})

    manifest = {"schema_version": 1, "challenge_id": challenge_id,
                "seed": seed, "source_revision": str(source_revision),
                "inputs": entries,
                "agent_contract": "Return diagnosis.json with root_cause_class, primary_module, primary_signal, causal_facts, patch_invariants, and revalidation_stages. Do not assume a root cause when evidence is incomplete.",
                "response_contract": {"schema_version": 1,
                                      "challenge_id": challenge_id,
                                      "required_fields": ["root_cause_class",
                                                          "primary_module",
                                                          "primary_signal",
                                                          "causal_facts",
                                                          "patch_invariants",
                                                          "revalidation_stages"]}}
    _write_json(destination / "input" / "challenge.json", manifest)
    (destination / "input" / "AGENT_TASK.md").write_text(
        "# Blind RTL Debug Task\n\n"
        "Use only the design specification, ordered DUT RTL and testbench sources, failed seed, and VCS log in this directory.\n"
        "Do not request or infer hidden scoring data. Provide a structured root cause, the smallest safe patch plan, and the regression needed to validate it.\n"
        "Write `diagnosis.json` using the `response_contract` in `challenge.json`.\n"
    )
    return {"status": "PREPARED", "challenge_id": challenge_id,
            "challenge_directory": str(destination / "input"),
            "answer_key_output": str(answer_key_path), "input_count": len(entries)}


def write_answer_key(answer_key_path, challenge_id, expected):
    _validate_expected(expected)
    _write_json(answer_key_path, {"schema_version": 1, "challenge_id": challenge_id,
                                  "expected": expected}, private=True)


def score_response(answer_key_path, prediction_path):
    answer = _load_json(answer_key_path)
    prediction = _load_json(prediction_path)
    if answer.get("schema_version") != 1 or prediction.get("schema_version") != 1:
        raise BenchmarkInputError("unsupported answer or prediction schema")
    if answer.get("challenge_id") != prediction.get("challenge_id"):
        raise BenchmarkInputError("prediction challenge_id does not match answer key")
    expected = answer.get("expected", {})
    exact_fields = ("root_cause_class", "primary_module", "primary_signal")
    detail = {field: prediction.get(field) == expected.get(field) for field in exact_fields}
    set_fields = ("causal_facts", "patch_invariants", "revalidation_stages")
    for field in set_fields:
        actual = prediction.get(field, [])
        if not isinstance(actual, list):
            actual = []
        detail[field] = sorted(set(actual)) == sorted(set(expected.get(field, [])))
    return {"schema_version": 1, "challenge_id": answer["challenge_id"],
            "status": "SCORED", "exact_match": all(detail.values()),
            "criteria": detail,
            "answer_key_sha256": _sha256(answer_key_path),
            "prediction_sha256": _sha256(prediction_path),
            "scoring_note": "This score checks a frozen response against a separate key; it does not prove patch correctness or regression success."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--spec", required=True)
    prepare.add_argument("--rtl-root", required=True)
    prepare.add_argument("--rtl", action="append", required=True,
                         help="ordered DUT RTL path relative to --rtl-root; repeat for each source")
    prepare.add_argument("--testbench", action="append", default=[],
                         help="relevant testbench path relative to --rtl-root; repeat as needed")
    prepare.add_argument("--log", required=True)
    prepare.add_argument("--seed", type=int, required=True)
    prepare.add_argument("--source-revision", required=True)
    prepare.add_argument("--destination", required=True)
    prepare.add_argument("--answer-key-output", required=True)
    prepare.add_argument("--answer-key-json", required=True,
                         help="private JSON document containing the expected scoring fields")
    score = subparsers.add_parser("score")
    score.add_argument("--answer-key", required=True)
    score.add_argument("--prediction", required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        # Validate output separation before copying any challenge inputs.
        destination = Path(args.destination).resolve()
        key_out = Path(args.answer_key_output).resolve()
        key_source = Path(args.answer_key_json).resolve()
        if _is_below(key_out, destination) or _is_below(key_source, destination):
            raise SystemExit("answer key must be outside the challenge directory")
        expected = _load_json(args.answer_key_json)
        _validate_expected(expected)
        result = prepare_challenge(args.spec, args.rtl_root, args.rtl, args.log,
                                   args.seed, args.source_revision,
                                   args.destination, args.answer_key_output,
                                   args.testbench)
        write_answer_key(args.answer_key_output, result["challenge_id"], expected)
    else:
        result = score_response(args.answer_key, args.prediction)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
