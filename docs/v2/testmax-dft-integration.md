# TestMAX DFT and ATPG Integration Strategy

**Status:** design only; no NM6008 TestMAX invocation or license checkout was performed.

## Keep experiment modes separate

- **Functional-only replay:** use a functional netlist path with DFT stages explicitly `SKIPPED` and reason `MODE_FUNCTIONAL_ONLY`. It may establish functional-flow reproducibility, but cannot claim scan, ATPG, test coverage, or full-flow closure.
- **Full DFT flow:** requires scan-aware synthesis/insertion, DFT rule checks, physical implementation of the scan design, ATPG against the final scan-chain ordering, and explicit DFT evidence. Missing DFT setup is `BLOCKED`, never silently treated as functional-only.

Never compare a functional-only physical result with a full-DFT physical result as if the implementation and testability overhead were equivalent.

## Inputs required before insertion

Project owners must provide or approve: scan eligibility and exclusions, test protocol, test clocks/resets, scan enable/test mode, chain count/length targets, compression policy (if used), lockup/latch policy, test and functional SDC/MMMC modes, library/test-cell support, DFT rule policy, and any project-specific ATPG fault model. The tool flow must discover and record supported cells and clock/reset semantics. The agent may flag missing fields; it may not invent them.

## Stage sequence and evidence

1. Freeze and hash the functional synthesized netlist, source revision, constraints, libraries and synthesis reports.
2. Run TestMAX DFT configuration/checks and scan insertion as a distinct stage. Preserve scripts, full logs, inserted scan netlist, test protocol/configuration, scan architecture/chain report, DFT rule report and tool/version/license evidence.
3. Run DFT DRC and classify violations. Any unwaived error blocks the next release gate; waivers require owner approval and evidence.
4. Run formal/equivalence between functional synthesized RTL/netlist and scan-inserted netlist under explicit functional/test assumptions. A successful command without a parsed, passing equivalence result is not a pass.
5. Send the scan-aware design through ICC2. If placement reorders chains, freeze the resulting chain manifest and export it as a hashed artifact. Any subsequent chain change invalidates ATPG and dependent test evidence.
6. Run TestMAX ATPG against the final scan order and test protocol. Preserve patterns, fault list/model, fault summary, coverage denominator, detected/possibly-detected/undetected/untestable counts, pattern count, test time estimate, constraints and logs.
7. If the project requires it, simulate generated patterns with the approved testbench/model and compare expected responses. This is a separate gate, not inferred from ATPG coverage.

ATPG may execute after scan order is frozen while physical routing proceeds, but final release joins both branches and checks the exact netlist/chain hashes. It must not consume a pre-reorder netlist when the final design has a different chain order.

## Gate semantics

Report DFT rule status, scan insertion status, scan-cell/chain counts, chain length distribution, ATPG coverage with denominator and fault model, testable/untestable fault counts, pattern count, estimated test time and any pattern simulation result. `PASS` requires all project-defined thresholds and required report sections. Missing reports, unsupported adapter, unknown fault denominator, or no confirmed feature license results in `BLOCKED`/`ERROR`. No default coverage percentage is assumed; no missing value is replaced with zero.

## Initial implementation boundary

Implement only after an authorized reference project has supplied a DFT recipe and license access. Start with one supported scan style and one explicitly named fault model. Add adapter-level fixtures and fake executable tests for parser/status behavior, then separately run a real licensed smoke on a small approved design. Mock tests establish software semantics only; they do not establish TestMAX operation or signoff.

Power analysis is an optional stage until the project owner defines an activity source, thresholds and licensed engine. If a particular release requires power, that gate must explicitly list the power stage as required. Otherwise report power as unavailable/NOT_RUN and make no power signoff claim.
