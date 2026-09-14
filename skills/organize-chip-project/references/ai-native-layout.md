# AI-native chip project layout

Use this as a semantic model, not a mandatory physical migration. Existing projects may map established paths into these roles through indexes and `AGENTS.md`.

```text
project/
├── AGENTS.md                         # Fast onboarding, commands, boundaries
├── docs/
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

- `AGENTS.md` is the front door: scope, source-of-truth map, known-good commands, path rules, generated/vendor boundaries, and links to deeper truth. Keep it concise and factual.
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
# Project guide

## Purpose and current state
## Source-of-truth map
## Setup and canonical commands
## Design and verification conventions
## Generated, third-party, and protected areas
## Validation expectations
## Active work and known issues
```

Use exact commands and paths. Explicitly label unknown, unavailable, or unverified statements.
