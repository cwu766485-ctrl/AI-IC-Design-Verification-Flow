# M4 Blind RTL Debug Benchmark

## Current status

The benchmark packager and scorer are implemented. A real independent blind
diagnosis is **BLOCKED** on this host: VCS `V-2023.12-SP1_Full64` starts, but
the current license-server connection fails before compilation. The interrupted
run used an isolated archive of NMAForge revision
`409c3a9fd647d4f8c4c881c9bfdaf5d93b7076ee`; it did not write into the source
repository. No diagnosis, patch, or regression result is claimed for this
attempt.

The revised evidence collector was also replayed read-only on the previously
archived seed `20261021` log (SHA-256
`e78e248a9b0d76a73b1a33553907d8e08ef07b87df3c1fa3644dc286e2795069`, source
revision `4b62f8e815bb272ab9b727dff4736cec460e6f21`). It returned
`EVIDENCE_COLLECTED`, left operation-local cycle unknown, and preserved the
simulator timestamp `46470000 ps`. This validates evidence parsing only; the
report explicitly records that no agent diagnosis, patch, or regression ran.

The archived `MATRIX_AGENT_DEBUG_DEMO_2026-11-14.json` is historical evidence,
not a blind benchmark: it contains `known_fault`, manually supplied signal
states, and a diagnosis correctness field derived from those inputs. The
current `EvidenceWorkflowRunner` only collects structured evidence and a
deterministic next-action recommendation. It never asserts an agent root cause.
VCS simulator timestamps are recorded separately from operation-local cycles.

## Information boundary

Each challenge input contains only:

- The design behavior specification.
- Ordered RTL source files from one pinned source revision.
- The failed seed and raw VCS log.
- File hashes and a neutral challenge identifier.

The answer key is created outside the challenge directory with mode `0600`.
Never share the key or its source with the debugging session. Freeze the
agent's structured response before invoking the scorer. Run the candidate
patch and required regression separately; a correct explanation alone does
not pass the debug task.

## Prepare and score

Use an isolated source snapshot and keep both the challenge and private key
outside the source repository. For example:

```bash
python3 skills/rtl-ppa-optimization/scripts/blind_debug_benchmark.py prepare \
  --spec /tmp/matrix-challenge/design_spec.md \
  --rtl-root /tmp/matrix-challenge/source \
  --rtl rtl/compute/matrix/ai_tensor_matrix_core.v \
  --rtl rtl/compute/matrix/ai_tensor_matrix_array.sv \
  --rtl rtl/compute/matrix/ai_tensor_matrix_datapath.v \
  --log /tmp/matrix-challenge/evidence/run_seed_1.log \
  --seed 1 --source-revision <source-sha> \
  --destination /tmp/blind-debug-001 \
  --answer-key-json /private/matrix-key.json \
  --answer-key-output /private/blind-debug-001-answer.json
```

Give a fresh debugging session only `/tmp/blind-debug-001/input/`. It should
write `diagnosis.json` with the root-cause class, primary module/signal, causal
facts, patch invariants, and revalidation stages. After freezing that response,
score it with:

```bash
python3 skills/rtl-ppa-optimization/scripts/blind_debug_benchmark.py score \
  --answer-key /private/blind-debug-001-answer.json \
  --prediction /tmp/blind-debug-001/diagnosis.json
```

The scorer checks exact structured fields and hashes both documents. It does
not verify RTL changes or regression results. Those require a separate review
of the patch, a passing targeted test, and the required regression.

## Safety and evidence rules

- Never edit the original NMAForge worktree. Create snapshots from a pinned Git
  revision and keep outputs under a separate temporary directory.
- Keep RTL, VCS logs, waveforms, proprietary specifications, and private answer
  keys out of this public Flow repository.
- If the licensed VCS rerun cannot run, record `BLOCKED`; do not substitute a
  fake simulator and call it a real debug benchmark.
- Do not claim blind accuracy, patch correctness, or debug efficiency until a
  fresh session sees only the challenge inputs and the modified RTL passes
  validation.
