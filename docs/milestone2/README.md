# Milestone 2: verification closure

This increment adds the independent `verification-closure` skill and applies
its plan generator to NMAForge DMA using the Spec and testplan as source
evidence. The project snapshot used for the generated plan is NMAForge HEAD
`c290eba7697138a4fcf2cbbac9262264849f0aeb`; source hashes are embedded in the
generated JSON plan.

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

One bounded seed (`20261107`) was run against the isolated NMAForge archive at
`c290eba7697138a4fcf2cbbac9262264849f0aeb`. All 19 block UVM tests and the
subsystem reset test passed their explicit test-name, UVM severity, and process
exit-code gates. URG generated separate block and subsystem reports with VCS /
URG `V-2023.12-SP1`; source hashes include every file in both simulator
filelists. The raw campaign manifest is included in
[`campaign-evidence.json`](nmaforge_dma/campaign-evidence.json); the complete
per-command logs, VCS binaries, VDBs, and URG HTML artifacts remain under
`/tmp/nmaforge_m2_dma_campaign_verified/runs/m2_seed_20261107/`. Its plan hash
matches the generated plan.

The URG parser measured 13 of the plan's 18 unique bins, and all 13 were hit.
That includes both reset phases (counts 3 and 1), 4 KiB crossing, load/store,
transfer shape, gather, length, outstanding reads, and transfer-mode crosses.
The analysis remains `OPEN`: five per-error bins have no covergroup, and the
seven checker IDs do not have machine-readable attempt/failure counters. The
machine-readable results are in
[`closure-analysis.json`](nmaforge_dma/closure-analysis.json). URG process
success and code-coverage percentage are not treated as proof of functional
closure.

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

The NMAForge working tree was inspected read-only. The regression campaign is
run from an isolated archive snapshot so VCS outputs cannot modify that
project tree.
