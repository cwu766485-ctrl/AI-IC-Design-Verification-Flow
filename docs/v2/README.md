# AI-IC Flow V2: Synopsys-Native RTL-to-GDS

**Specification version:** 2.0-draft
**Status:** audit and design specification; no NM6008 flow has run.

This folder records the read-only NM6008 asset audit, host capability evidence, a versioned Synopsys RTL-to-GDS stage graph, stage contracts, TestMAX integration, agent decision rules, benchmark protocol, and a small implementation backlog. The existing `aicflow` / Stage Runtime remains the only execution runtime. Nothing here claims NM6008 verification, DFT closure, physical signoff, or GDS signoff.

## Documents

- [NM6008 asset audit](nm6008-asset-audit.md)
- [Synopsys capability matrix](synopsys-capability-matrix.md)
- [Stage graph v1 JSON](rtl-to-gds-stage-graph.v1.json) and [schema](../schemas/rtl-to-gds-stage-graph.v1.schema.json)
- [Stage input, output, provenance, cache and recovery contract](stage-contract.md)
- [TestMAX DFT/ATPG integration strategy](testmax-dft-integration.md)
- [Agent decision contract v1](agent-decision-contract.v1.md)
- [NM6008 benchmark specification v1](nm6008-benchmark-spec.v1.md)
- [Ordered implementation backlog](implementation-backlog.md)

## Evidence labels

- **Observed:** directly inspected in the named local workspace or produced by the read-only capability checker.
- **User-provided:** supplied in the task context, not independently corroborated from the historical project.
- **Unknown / unverified:** requires a named license checkout, authorized technology profile, project inputs, or a real stage run.
- **Planned:** design only; no adapter or flow behavior is implied.

Private technology data and machine-specific install paths are deliberately excluded. A tool found on `PATH` is not evidence of license availability, project configuration, or successful execution.
