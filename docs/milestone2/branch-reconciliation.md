# Branch Reconciliation

## AI-IC-Design-Verification-Flow

The two existing pull requests overlap in the EDA execution surface. PR #1 is
`feature/m3-rtl-ppa-optimization` to `main` at reviewed M3 commit
`308cb5a03d9c7f228ac6fc476383acb59de72d7b`; it includes M0/M1 adapters, M2
verification-closure files, and the M3 bounded PPA evaluator. PR #2 is
`feature/r1-unified-dag-engine` to the M3 feature branch at R1 commit
`de7228f83fded1eb8a64a5c5f75a049b4eeae866`. Shared files include the EDA
runtime, flow engine, PPA adapter, CI workflow, and execution documentation.

The integration branch `feature/m2-r1-verification-integration` has merge
commit `b6cc478c92dc4d0bbe3696f206cca8d9602e9eab`, with M3 `308cb5a` and R1
`de7228f` as parents. It adds the M2 changes in
`ce4741cce3250b2ac4c9bdc9fda66dd6ebcc35dd` and a portable-report path fix in
`458a5a5a41a918df5b5be6c7f20cb54bd51a6452`. The integration PR is
[#3](https://github.com/cwu766485-ctrl/AI-IC-Design-Verification-Flow/pull/3),
targeting `main`; it is OPEN with CLEAN merge state and its pytest check passes.
PR #1 and PR #2 remain OPEN and unchanged. No branch was merged to `main`.

The M3/R1 baseline and M2 closure improvements are reviewed together in PR #3
because the R1 runtime changes M3 adapter execution and M2 now runs through
that same shared stage contract. PR #1/#2 overlap remains visible for review;
they have not been closed automatically.

## NMAForge DMA Patch

NMAForge changes are isolated in worktree `/tmp/nmaforge-m2-coverage-closure`
on `feature/m2-dma-coverage-closure`, based at source revision
`c290eba7697138a4fcf2cbbac9262264849f0aeb`. Commit
`951b4e05c0487e0c3220191ee0317103ad5100b8` changes only the DMA scoreboard,
DMA functional test include, and block simulation Makefile. Its PR is
[#9](https://github.com/cwu766485-ctrl/NMAForge/pull/9), targeting
`feat/shape-adaptive-gemv-v2`; it is OPEN with CLEAN merge state and no CI checks
are configured for the branch. The original NMAForge worktree was not modified;
its pre-existing untracked `novas.conf` and `novas.rc` remain present.

Both repositories have clean committed feature worktrees. `novas.conf`,
`novas.rc`, `verdiLog/`, and generated `runs/` artifacts remain covered by
their repository ignore rules.
