# NM6008 Project Asset Audit

**Audit type:** read-only workspace inspection
**Audit date:** 2026-11-16
**Target identity:** NM6008 Matrix Multiplier — **not confirmed in the inspected workspaces**

## Findings

| Asset | Finding | Readiness for a reproducible Synopsys run |
|---|---|---|
| Exact NM6008 project/revision | No project identified by the NM6008 name in the inspected local repositories. | BLOCKED: need the authoritative course/project checkout and revision. |
| Closest local RTL candidate | `foundation/de_coding/07_arithmetic_and_datapath/multipliers/matrix_multiplier/matrix_multiplier.v`; one iterative, parameterized signed matrix multiplier. The file hash observed during audit was `90fba5aea650a9caf87ff83f54ef3cb9d83f4fbdce15dd78117a6ffcc09dab2c`; inspected source repository revision was `146a1b3dcdddb960407477d3fe5985993a040462`. | Not identified as NM6008; do not use as its golden design without owner confirmation. |
| Testbench, testplan, seeds | No corresponding project testbench, regression scripts, or testplan were found beside the candidate RTL. | BLOCKED: functional behavior and a pass oracle are not established. |
| Filelists, SDC, synthesis/physical scripts | None found with the candidate RTL. | BLOCKED: no reproducible constraints or tool setup. |
| Libraries and technology profile | A local technology tree contains Synopsys-relevant library/physical collateral categories. No target-project mapping, corner selection, version, or authorization record was established. | BLOCKED: require owner-approved library/PDK profile and hashes; paths/content are intentionally not recorded here. |
| Historical synthesis/physical evidence | No NM6008 reports, netlists, DEF, GDS, or intermediate artifacts were identified in the inspected candidate project. | No comparable baseline. |
| Historical backend and DFT scope | The task context says the course used Innovus and excluded DFT. This was not independently verified from original course scripts/evidence. | Treat as user-provided context only. Innovus results cannot stand in for a Synopsys baseline; the functional-only replay and full DFT flow must be separate cohorts. |

## Exact blockers

1. Identify and provide the authoritative NM6008 project snapshot, revision, and permitted read-only access.
2. Supply RTL, ordered filelists, testbench, expected behavior/checker, testplan, and reproducible seeds.
3. Supply the project-owned synthesis and physical Tcl, SDC/MMMC setup, floorplan/IO assumptions, and DFT intent/configuration.
4. Approve the Synopsys technology/library profile and corners for this use; record content hashes and applicable authorization metadata without copying restricted collateral into this repository.
5. Confirm required feature licenses with actual feature checkout or a minimal authorized tool invocation. Environment variables or executable presence do not prove a license.
6. Confirm whether the reference design is suitable for scan insertion, ATPG, and physical implementation; record explicit waivers as reviewed evidence, never inferred defaults.

## Read-only procedure and preservation

The audit inspected repository names/tree structure, the closest candidate RTL metadata, and the output of `skills/eda-tool-engineering/scripts/check_environment.py`. That checker output was kept in a local temporary file and is not part of this repository. No NM6008 files, source projects, technology data, installed tools, licenses, or historical evidence were modified. No EDA stage was launched against the candidate project because it is not established as NM6008 and lacks required inputs.

The candidate SHA above identifies only the closest local RTL file observed during this audit. It is not a source revision, golden baseline, or claim of NM6008 identity. Recompute all hashes against the authorized project snapshot before any run.
