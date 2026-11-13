# Verification plan and evidence schema

Use one curated YAML file per verification scope. It is the durable contract
between the specification, stimulus, checkers, and coverage. Do not use a
generated plan as a substitute for reviewing the source requirement.

## Required fields

```yaml
schema_version: 1
project: chip_name
source_revision: optional_git_commit_sha
spec_sources: [docs/spec/SPEC.md]
features:
  - id: DMA-F-001
    name: Tagged out-of-order read completion
    spec_refs:
      - {file: docs/spec/SPEC.md, contains: "four tagged read outstanding"}
    testpoints:
      - id: DMA-TP-001
        stimulus: Fill the four read slots and return R bursts newest first.
        tests: [dma_load_ooo_smoke_test]
        checker:
          id: DMA-CK-001
          kind: reference_model
          scope: DUT_business
          description: Compare every destination word and verify non-FIFO RID completion.
          source: dv/block/dma/env/dma_block_scoreboard.svh
        coverage:
          - group: dma_cmd_cg
            point: cp_outstanding
            bins: [four]
closure:
  regression_command: [make, -C, dv/block/dma/sim, uvm_regress]
  seeds: [20261107, 20261108, 20261109]
  pass_patterns: ["UVM Report Summary", "UVM_ERROR\\s*:\\s*0", "UVM_FATAL\\s*:\\s*0"]
  fail_patterns: ["UVM_ERROR\\s*:\\s*[1-9]", "UVM_FATAL\\s*:\\s*[1-9]", "TEST FAILED"]
  budgets: {max_campaigns: 3, max_seeds: 20, max_new_tests: 3, max_runtime_sec: 7200}
```

Every `spec_refs` entry is checked against the project-relative file and exact
substring. Each testpoint must have a unique ID, one or more executable test
names, one checker with a type and scope, and one or more named functional
coverage goals. Use `checker.scope: protocol_VIP` only for protocol rules;
model DUT business results with a separate scoreboard/reference checker.

Optional `status` values are `existing`, `planned`, `blocked`, or `reviewed`.
An unreachable coverage goal also needs `disposition: unreachable`, a concise
`rationale`, and a `reviewer`; an unhit bin alone cannot be waived.

## Machine-readable coverage evidence

Pass `analyze --coverage-json` a file shaped like this:

```json
{
  "coverage_bins": {
    "dma_cmd_cg.cp_outstanding.four": {"hit": 16, "total": 16},
    "dma_cmd_cg.cp_4k.yes": {"hit": 0, "total": 1}
  },
  "checkers": {
    "DMA-CK-001": {"attempts": 16, "failures": 0}
  }
}
```

Functional bins, assertion attempts, and RTL code coverage are separate
measures. Keep raw URG/VCS reports as artifacts and convert reviewed values to
this small interchange format. The analyzer reports a missing metric as
`unmeasured`, never as zero or PASS. `analyze --urg-report <report-dir>` reads
planned user-defined bins and cross bins from URG HTML; a missing coverage
group is classified as `missing_checker` so a missing model is not mistaken for
unreachable stimulus. The reported bin `count` is the observed sample count;
`hit`/`total` express whether the planned bin was seen at least once.

## Bounded regression campaign

`close --execute` runs the configured `closure.regression_commands` (or the
single `closure.regression_command`), without a shell, from their declared
working directories. It substitutes `{seed}`, `{run_dir}`, and `{seed_dir}` in
arguments and sets `SEED`, `COV_ROOT`, and `VC_RUN_DIR`. Every seed gets a
separate directory and log. All configured pass patterns and expected test
names must appear; any fail pattern or nonzero process status fails the seed. A timeout or license
checkout failure blocks it. The command records a campaign ledger and refuses
to exceed `max_campaigns`, `max_seeds`, or total wall-time budget. For an
archived source snapshot, `source_revision` pins the Git commit while source
hashes preserve content-level identity.

`scaffold` emits a UVM test class using a project-supplied base test, sequence,
and sequencer expression. It emits a draft and package include patch under a
review directory. `--apply` installs those two files into the project and
counts the test against `max_new_tests`. The generated class is only a starting
point: its testpoint-specific assertions and checker evidence must be added
before it can close a feature.
