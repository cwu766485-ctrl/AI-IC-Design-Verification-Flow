# Optimization Readiness Tools

`scripts/optimization_readiness.py` consumes existing campaign artifacts and
produces reviewable JSON. It does not launch simulations, edit RTL, or replace
the shared Stage Runtime.

## Hierarchy-aware failure triage

```sh
python3 skills/rtl-ppa-optimization/scripts/optimization_readiness.py debug \
  --log runs/failing-test.log \
  --vcd runs/failing-test.vcd \
  --signal tb.dut.core.state_r \
  --signal tb.dut.line_ready \
  --clock-period-ticks 1000 \
  --output runs/failure-triage.json
```

The parser correlates `ASSERTION_FAIL`, `UVM_ERROR`, `PROTOCOL_TRACE`,
`TRANSACTION_TRACE`, `FSM_TRACE`, and `WAVE_EVENT` records by cycle and
transaction ID. It can also extract selected hierarchical signals from VCD.
The report names the first failure cycle, checker, nearby trace events,
hierarchical paths, and a Verdi query plan. The existing EDA debug-artifact
stage can launch Verdi with its VCS KDB/FSDB; the helper does not claim that
Verdi ran or that an unparsed FSDB was inspected. VCD-to-cycle conversion
requires an explicit `--clock-period-ticks` value in VCD timestamp units.

When only unstructured simulator output is available, the report keeps the
failure line and reports absent cycle, transaction, or waveform evidence as
unknown. It does not infer an RTL root cause from a process exit code.

## Architecture trade-off search

```sh
python3 skills/rtl-ppa-optimization/scripts/optimization_readiness.py search \
  --profile path/to/performance-summary.json \
  --source-revision <source-sha> \
  --output architecture-search.json
```

The Matrix profile emits two experiment hypotheses (A/B prefetch overlap and
ordered output staging) plus a rejected outstanding-depth hypothesis when the
measured FIFO-full count is zero. Every option records measured evidence,
expected impact by workload cycles/throughput/area/timing, functional risks,
and required validation. Unmeasured metrics stay explicitly unmeasured; the
output marks all entries `candidate_ready: false` until a directed measurement
isolates exposed cycles. Feed a reviewed patch to `CandidateGenerator` and the
existing evaluator only after that evidence exists.

## Cost-aware next action

```sh
python3 skills/rtl-ppa-optimization/scripts/optimization_readiness.py cost \
  --failure failure.json --budget remaining-budget.json \
  --history prior-campaigns.json --prior-results prior-tests.json \
  --commands next-actions.json --telemetry agent-task-telemetry.json \
  --codex-baseline matched-codex-tasks.json --output next-action.json
```

The planner selects `DEEP_REASONING`, `DIRECTED_TEST`, `FULL_REGRESSION`, or
`STOP`. It uses the first divergence/checker, reproducible seed, directed-test
result, required command, measured median stage duration, and remaining EDA
runtime. It never treats an unavailable license/tool as a test failure or
spends regression budget past the declared limit. Token and agent-call costs
remain null without comparable external telemetry. A per-action token estimate
can be supplied in the budget and gates work against remaining tokens. The
optional efficiency comparison requires identical task IDs and complete
success, token, and EDA-runtime fields for both agent and Codex runs; otherwise
it returns `NOT_COMPARABLE`. Record these fields for each task before claiming
cost improvement against a manual baseline.
## End-to-end validation

`optimization_readiness.py validate` runs the debugger, architecture search,
and cost planner over an archived VCS failure and writes one workflow artifact.
The legacy `action` field remains compatible with the PPA CLI; the additional
`adaptive_action` uses `STATIC_ANALYSIS`, `TARGETED_SIMULATION`,
`WAVEFORM_DEBUG`, `FULL_REGRESSION`, `PERFORMANCE_BENCHMARK`, `SYNTHESIS_STA`,
or `STOP`. Missing token or tool telemetry is represented as `null`.
