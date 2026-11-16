# V2 Implementation Backlog

Ordered, reviewable tasks. Everything below is **planned** and depends on resolving the asset and license blockers in the audit. Keep each item as a focused PR on a feature branch; do not merge to `main` automatically.

| Order | Task | Scope | Acceptance gate |
|---|---|---|---|
| V2.0 | NM6008 secure asset manifest and input freeze | Obtain authorized project snapshot; inventory RTL/TB/filelists/SDC/Tcl/library references/reports; hash without copying restricted technology collateral. | Owner confirms project identity; clean immutable snapshot and reviewed manifest; no original project edits. |
| V2.1 | Synopsys technology/project profile | Add project-owned `eda.yaml` and validated profile references for target/top, ordered sources, modes/corners, libraries, constraints and runner. | Invalid/missing required assets block; sensitive paths are not published; configuration tests pass. |
| V2.2 | Functional VCS verification + URG | Use existing adapters/runtime for compile, tests/seeds, regression, coverage collection and Verdi artifact references. | Real licensed smoke on authorized small design; test oracle and required reports parsed; no mock-as-real claim. |
| V2.3 | DC synthesis + Formality gate | Reproducible synthesis with parsed area/timing reports and explicit functional equivalence checks. | Hashed inputs/outputs and reports; missing reports block; successful equivalence is evidence-backed. |
| V2.4 | TestMAX DFT insertion and ATPG | Implement distinct DFT/ATPG adapters, configs, DFT DRC, chain manifest and report parsers. | Licensed scan smoke passes project rules; ATPG reports include denominator/model; functional-only and full-DFT modes are isolated. |
| V2.5 | ICC2 physical stages | Floorplan, place, scan reorder, CTS, route, checkpoint artifacts and stage-specific recovery. | Real authorized tech run on small fixture; stage outputs and QoR reports parse; physical checkpoint restore is verified. |
| V2.6 | StarRC, PrimeTime, power and physical gates | Extraction, post-route STA, available power analysis, physical verification and streamout checks. | Same-corner setup/hold and required DRC/LVS gates pass; GDS provenance and post-export checks recorded; unavailable tools block. |
| V2.7 | NM6008 functional-only golden replay | Execute exact approved project through functional path and establish independent Synopsys baseline. | Repeatable flow and reviewed baseline; no DFT/signoff implication. |
| V2.8 | NM6008 full DFT baseline | Add scan/ATPG and physical rerun, preserving separate functional and DFT evidence. | DFT/ATPG gates pass and scan-aware physical metrics are complete. |
| V2.9 | Agent benchmark and bounded decisions | Implement decision records, blind failure set, cost accounting and B0–B3 repeatable evaluation. | Reviewable ground truth, fixed budgets and evidence; B3 compared to B2 without hidden labels or mutable test score. |

V2.2–V2.6 should extend the shared Stage Runtime and existing CLI. Do not add a competing runner or make planned adapters appear supported in capability reports.
