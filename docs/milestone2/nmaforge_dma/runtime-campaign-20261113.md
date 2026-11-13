# NMAForge DMA Runtime Campaign: 2026-11-13

Status: regression campaign `PASS`; verification closure `OPEN`.

## Provenance

- Source repository: `cwu766485-ctrl/NMAForge`
- Feature branch: `feature/m2-dma-coverage-closure`
- Source HEAD: `c290eba7697138a4fcf2cbbac9262264849f0aeb`
- Source working-tree changes: `dma_block_scoreboard.svh`, `Makefile`, and `dma_functional_tests.svh`
- Verification plan SHA256: `d2a29af5cc74f390ebb8bd24b6772e8476d29ddaea92b5f21100a0637b6c8174`
- Post-run source revalidation: 49 inputs hashed, including nested SystemVerilog includes; revalidation plan is under `runs/verification-closure/m2-runtime-final-20261113/plan-revalidation/verification-plan.json`
- Positive campaign run ID: `m2-runtime-final-20261113`
- Positive campaign seed: `20261107`
- Negative checker seed: `20261113`
- Tools: VCS `V-2023.12-SP1_Full64`; URG `V-2023.12-SP1`
- Execution command: `verification_closure.py close --max-seeds 1 --run-id m2-runtime-final-20261113 --execute`, followed by checkpoint resume for URG and analysis

## Results

- DMA block regression: 19/19 planned tests passed; UVM error/fatal counts were zero.
- DMA subsystem reset: 1/1 test passed; UVM error/fatal counts were zero.
- Error bins: abort 2, AXI read error 1, SPAD error 1, AXI write error 1, config error 1.
- Reset phase bins: all-four-AR-before-R 3; first-R-beat-accepted 1.
- `DMA-CK-005`: 6 attempts, 0 failures in the positive regression.
- Negative test: the scoreboard received expected error code 1 and deliberately corrupted observed code 3; `DMA_ERROR_ABI` fired and the run printed `CHECKER_EVIDENCE id=DMA-CK-005 attempts=1 failures=1`.
- Closure analysis: `OPEN`, with no run failures and all planned coverage bins hit.

The negative test corrupts the observed checker input; it is not an RTL mutation test. The five error bins are sampled from the observed DUT `error/error_code` interface after existing directed tests.

## Remaining Checker Gaps

| Checker | Evidence status | Blocker |
|---|---|---|
| DMA-CK-001 | OPEN | No machine-readable attempt/failure counters for the reference-model comparison. |
| DMA-CK-002 | OPEN | No machine-readable attempt/failure counters for address/data comparisons. |
| DMA-CK-003 | OPEN | SVA and scoreboard checks exist, but no mapped attempt/failure evidence is exported. |
| DMA-CK-004 | OPEN | No machine-readable attempt/failure counters for write-response and payload checks. |
| DMA-CK-006 | OPEN | Deadlock checker has no mapped attempt/failure counter evidence. |
| DMA-CK-007 | OPEN | Reset queue-drain checker has no mapped attempt/failure counter evidence. |

These gaps are separate from the functional coverage model: all five planned error bins now exist and were hit. No waiver or assertion deletion was introduced.

## Preserved Run Artifacts

The isolated feature worktree is `/tmp/nmaforge-m2-coverage-closure`. Positive campaign artifacts are under `runs/verification-closure/m2-runtime-final-20261113/`, including `manifest.json`, `evidence.json`, `closure-analysis.json`, the budget ledger, checkpoints, attempt records, per-stage logs, VCS binaries, VDBs, and URG HTML reports. The separate negative log is `runs/verification-closure/m2-runtime-final-20261113/negative/negative_checker.log`.

Two earlier URG attempts, `m2-runtime-integration` and `m2-runtime-integration-fix`, remain in the budget ledger with their reservations. The first exposed executable lookup through configured stage `PATH`; the second exposed the difference between URG HTML and text output. Both issues were fixed in the shared Runtime. A further campaign was refused because `max_campaigns=3` was reached; the ledger was not edited to bypass the limit.

The campaign manifest was generated before the complete source-hash traversal fix and therefore contains an incomplete source map. The post-run plan revalidation above records all 49 current RTL, testbench, assertion, and included source files. Refreshing the campaign manifest requires a new budget allocation.
