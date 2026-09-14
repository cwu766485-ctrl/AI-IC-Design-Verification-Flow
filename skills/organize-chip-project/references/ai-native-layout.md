# AI-native chip project layout

Use this as a semantic model, not a mandatory physical migration. Existing projects may map established paths into these roles through indexes and `AGENTS.md`.

```text
project/
├── AGENTS.md                         # Fact-based agent front door; not a blank template
├── docs/
│   ├── ai-native/
│   │   ├── repository-map.md          # Actual path/HDL-role map from repository scan
│   │   ├── design-verification-index.md # RTL vs DV vs flow/protected boundaries
│   │   ├── commands.md                # Existing commands/targets found in repo/CI
│   │   └── inventory.json             # Machine-readable bounded evidence inventory
│   ├── project-overview.md           # Purpose, maturity, configuration, owners
│   ├── spec/                         # Normative requirements and traceability
│   ├── architecture/                 # Design decomposition and interfaces
│   ├── verification/                 # Strategy, test plans, coverage/signoff
│   └── exec-plans/
│       ├── active/
│       │   └── execution-frontier.md # Current state and exact next action
│       └── completed/                # Durable completed plans and evidence
├── rtl/                              # RTL only when this matches project reality
├── dv/                               # Simulation/formal/emulation collateral
├── constraints/                      # Timing, physical, power intent as applicable
├── fw/                               # Embedded software/model code if applicable
├── config/                           # Manifests, variants, tool-neutral inputs
├── skills/                           # Project-local specialized SOPs when justified
├── tools/
│   └── hw                            # Thin canonical dispatcher, not a second flow
└── runs/                             # Reproducible outputs; normally ignored
```

## Meaning of each AI-facing surface

- `AGENTS.md` is the front door: scope, source-of-truth map, known-good commands, path rules, generated/vendor boundaries, and links to deeper truth. Generate it from repository evidence and keep it concise and factual; never leave it as a generic TODO list.
- `docs/ai-native/` is the explicit navigation layer: it provides a factual path map, design/DV/flow split, command index, and machine-readable inventory without relocating functional files just for taxonomy.
- `docs/` is durable knowledge. Separate normative requirements from explanatory architecture and verification evidence.
- `docs/exec-plans/active/execution-frontier.md` is resumable state: objective, baseline, completed work, current blocker, exact next command, acceptance criteria, and relevant logs/commits.
- `config/` makes configurations and source selection explicit. Preserve the existing manifest format when tools already consume one.
- `tools/hw` gives agents a discoverable command interface while delegating to canonical Make/Tcl/Python/EDA flows.
- `runs/` stores outputs with enough provenance to reproduce them: command, tool/version, configuration, seed, source revision, timestamp, status, and logs.
- `skills/` belongs in the project only for project-specific repeated procedures. Do not copy generic user-level skills into every repository.

## Adaptation rules

1. Preserve well-known existing names such as `src`, `design`, `verif`, `tb`, `sim`, or `syn` when renaming would add risk without improving execution.
2. Do not flatten IP blocks. Preserve hierarchy, ownership, and block-local manifests.
3. Avoid copying a file into a new taxonomy while leaving two plausible sources of truth. Prefer an index or explicit canonical marker.
4. Keep vendor IP, PDKs, encrypted models, large data, and submodules at their established boundaries.
5. Document generated-source provenance and regeneration commands. Never disguise generated content as handwritten source.
6. Add only lifecycle areas that exist. For example, omit `fw/` or `constraints/` if irrelevant.

## Minimum AGENTS.md content

```markdown
# <Project name> repository guide

## Purpose and current state
<README/manifest-grounded scope and explicit unknowns>

## Sources of truth
<exact relative paths and their authority>

## Important paths
<RTL, DV, manifest, flow, generated, protected boundaries>

## Before work
<read order and status/frontier>

## Setup and canonical commands
<commands actually found in Make/Just/CI/README>

## Modification policy
<generated/vendor/signoff/test/waiver rules>

## Definition of done
<proportionate validation and frontier update>
```

Use exact commands and paths. Explicitly label unknown, unavailable, or unverified statements. Do not infer a command, verification result, top module, or signoff status from a directory name alone.
