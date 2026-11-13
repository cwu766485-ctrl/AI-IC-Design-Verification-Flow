# Milestone 2: verification closure

This increment adds the independent `verification-closure` skill and applies
its plan generator to NMAForge DMA using the Spec and testplan as source
evidence. The project snapshot used for the generated plan is NMAForge HEAD
`c290eba7697138a4fcf2cbbac9262264849f0aeb`; source hashes are embedded in the
generated JSON plan.

The R1/M3 overlap and GitHub branch disposition are recorded in
[`branch-reconciliation.md`](branch-reconciliation.md).

## Plan result

The curated plan maps six DMA feature groups into seven stable testpoints and
checker IDs. It covers tagged/out-of-order reads, 2-D/gather transfers, burst
and 4 KiB splitting, store IDs and stalls, error/abort recovery, subsystem
reset during accepted reads, and randomized backpressure.

NMAForge already has the UVM pieces expected for this scope: a DMA command
sequencer, AXI responder, passive bus monitors, SPAD model, scoreboard, named
SVA, a 19-test block regression, and a subsystem reset scenario. The skill
records these mappings and generates an additive test class only when a
specific uncovered testpoint needs one. Its `scaffold` command drafts a class
and package include patch; `--apply` performs the integration explicitly and
accounts for the new-test budget.

The initial plan makes a real coverage gap visible: the block scoreboard's
`dma_cmd_cg` covers command direction/shape/gather/length/outstanding/4 KiB,
but has no per-error scenario covergroup. The error tests and their business
checkers exist, so the plan marks the five error-kind bins as planned coverage
work. Coordinated DMA reset already has its own subsystem test and
`dma_reset_phase_cg`; the plan keeps that evidence separate from block-level
abort/error checks.

## Executed campaign

The integrated R1 Stage Runtime ran campaign `m2-runtime-final-20261113` on
seed `20261107`, source revision `c290eba7697138a4fcf2cbbac9262264849f0aeb`,
and plan SHA256 `d2a29af5cc74f390ebb8bd24b6772e8476d29ddaea92b5f21100a0637b6c8174`.
All 19 block tests and the subsystem reset test passed, with zero UVM errors or
fatals in the positive runs. VCS and URG were `V-2023.12-SP1`. The campaign
manifest and analyzer passed their stage gates; closure remains `OPEN` because
six mapped checkers still lack machine-readable attempt/failure evidence.

URG measured all five error bins: `abort=2`, `axi_read_error=1`,
`spad_error=1`, `axi_write_error=1`, and `config_error=1`. Both subsystem reset
bins were hit (counts 3 and 1). `DMA-CK-005` reported 6 attempts and 0
failures. A separate negative run deliberately supplied an incorrect observed
error code; `DMA_ERROR_ABI` fired and CK-005 reported 1 attempt and 1 failure.
This validates the checker response to a corrupted observation, not a mutated
RTL campaign.

The captured campaign manifest predates the source-hash fix and has an
incomplete source map. A post-run plan revalidation hashes 49 current inputs,
including recursively discovered SystemVerilog includes. A fresh campaign to
refresh the manifest was refused because the plan's three-campaign budget is
exhausted; the two blocked URG attempts and their reservations remain recorded.
The exact run IDs, source state, local log/VDB/report paths, bin counts, and
remaining blockers are in
[`runtime-campaign-20261113.md`](nmaforge_dma/runtime-campaign-20261113.md).
The machine-readable closure result is in
[`closure-analysis.json`](nmaforge_dma/closure-analysis.json). URG process
success and code-coverage percentage are not signoff evidence by themselves.

## Commands

Run from this skill repository while pointing `--project-root` at the chip
project:

```bash
python3 skills/verification-closure/scripts/verification_closure.py validate \
  --project-root /path/to/NMAForge \
  --plan skills/verification-closure/references/dma-plan-example.yaml

python3 skills/verification-closure/scripts/verification_closure.py plan \
  --project-root /path/to/NMAForge \
  --plan skills/verification-closure/references/dma-plan-example.yaml \
  --out-dir docs/verification/dma-closure

python3 skills/verification-closure/scripts/verification_closure.py close \
  --project-root /path/to/NMAForge \
  --plan skills/verification-closure/references/dma-plan-example.yaml \
  --max-seeds 3 --execute
```

The bounded campaign runs the block and reset subsystem Makefiles per seed,
creates separate URG reports, records command logs/return codes/tool versions,
and uses a budget ledger. `analyze --urg-report <report-dir>` reads the planned
functional bins from URG HTML. Supply checker attempt/failure counts with
`--coverage-json`; missing metrics stay open. The
generated example plan is [here](nmaforge_dma/verification-plan.md), with the
machine-readable source hashes [here](nmaforge_dma/verification-plan.json).

The original NMAForge worktree was left untouched. The feature branch and all
simulator outputs are isolated in `/tmp/nmaforge-m2-coverage-closure`; VCS
outputs remain under its ignored `runs/` directory.
