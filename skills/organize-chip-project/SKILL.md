---
name: organize-chip-project
description: Inspect, create, or safely reorganize ASIC, SoC, FPGA, RTL, IP, and design-verification repositories into an AI-native project structure while preserving every source artifact and existing build, simulation, regression, synthesis, formal, lint, CDC, DFT, and implementation behavior. Use when starting a chip project, onboarding Codex to an existing hardware repository, locating specs/RTL/testbenches/tool flows, creating AGENTS.md and execution-frontier documentation, or restructuring a hardware project without losing content or functionality.
---

# Organize Chip Project

Turn a hardware repository into an Agent-Native repository: an agent entering the root must be able to answer, from project-local files, **what this project is, where source of truth lives, which RTL/DV/flow paths matter, which exact commands are established, what must not change, and what to do next**. Treat preservation of design intent, source content, tool behavior, and reproducibility as hard constraints.

The required deliverable is a fact-based navigation layer, not merely an attractive directory tree. Do not finish after creating blank `docs/`, `rtl/`, or `dv/` directories.

Apply [references/agent-native-quality-bar.md](references/agent-native-quality-bar.md) as the acceptance test for every invocation. It defines the required agent entrance and the questions a new agent must answer without a broad repository search.

## Non-negotiable rules

1. Never delete, overwrite, or silently replace existing project content.
2. Never assume similarly named files are duplicates. Prove equivalence and retain at least one traceable copy.
3. Never move functional files until references, file lists, includes, scripts, manifests, constraints, generated-file policy, and verification commands are understood.
4. Prefer adding navigation and documentation in place over moving files. Reorganize physically only when it has clear value and can be validated.
5. Preserve history when Git is available: use `git mv` for proven moves and keep changes reviewable in small batches.
6. Keep generated outputs, caches, vendor trees, PDK data, credentials, and licensed collateral out of version control unless the existing project explicitly tracks them.
7. Do not claim functional equivalence without evidence. Report unrun or unavailable checks as residual risk.
8. Stop before a destructive, ambiguous, or irreversible action and ask the user for direction.

## Select the path

- **New or essentially empty project:** create the AI-native skeleton with `scripts/scaffold_project.py`. Add only directories relevant to the intended lifecycle, then capture the initial spec and verification strategy.
- **Existing project:** follow the preservation workflow below. Default to an overlay: add `AGENTS.md`, structured docs, navigation, plans, and reproducible command entry points while leaving functional paths intact.
- **Existing `eda.yaml`:** also use the `eda-tool-engineering` skill for EDA execution semantics. Do not replace its canonical flow configuration.

## Existing-project preservation workflow

### 1. Establish boundaries and evidence

Identify the repository root, requested scope, Git state, submodules, symlinks, large/vendor/generated areas, and user changes. Read local `AGENTS.md` files and obey their scoped instructions. Do not absorb a parent workspace or sibling project accidentally.

Run a pre-change snapshot outside the project when possible:

```bash
python3 <skill-dir>/scripts/preservation_guard.py snapshot <project-root> -o /tmp/project-before.json
```

Record available baseline commands without inventing them. Discover them from README files, CI, Makefiles, manifests, simulator scripts, `eda.yaml`, file lists, and recent logs. Run affordable established smoke checks before changing paths. If no baseline passes, preserve its exact failure signature.

### 2. Build a project model

Classify, do not guess. Locate:

- product/IP purpose, top levels, clocks/resets, protocols, parameters, and supported configurations;
- normative specs, architecture/microarchitecture, register descriptions, waivers, and signoff criteria;
- RTL, packages, macros, assertions, analog/mixed-signal models, firmware, constraints, UPF/CPF, and generated sources;
- DV environments, UVM components, tests, sequences, reference models, formal properties, coverage models, test plans, and regressions;
- tool entry points, source ordering, compile defines, include paths, libraries, PDK/vendor dependencies, environment setup, CI, and output locations;
- current status, known failures, ownership boundaries, and files that must not be modified.

Use [references/discovery-and-mapping.md](references/discovery-and-mapping.md) for hardware-specific discovery patterns. Create an explicit old-path → role → proposed-path/action → reference-update → validation mapping before any move.

Generate the fact-based navigation layer after the read-only inventory. Review the dry run first, then apply it:

```bash
python3 <skill-dir>/scripts/generate_agent_native.py <project-root>
python3 <skill-dir>/scripts/generate_agent_native.py <project-root> --apply --update-agents
python3 <skill-dir>/scripts/validate_agent_native.py <project-root>
```

The generator produces these project-local artifacts from actual repository evidence:

- `AGENTS.md` — concise front door with purpose/status evidence, source-of-truth paths, concrete commands found in repository guidance/CI, protected boundaries, and next-action link. It changes only the marked generated block, preserving user-authored sections.
- `docs/ai-native/repository-map.md` — top-level tree, HDL-module inventory, and role-to-path index.
- `docs/ai-native/design-verification-index.md` — separate RTL/design, DV, constraints, manifests, and flow inputs.
- `docs/ai-native/commands.md` — Make/Just targets and executable commands found in README/CI; it never invents a command.
- `docs/ai-native/inventory.json` — machine-readable bounded inventory for later agents/tools.
- `docs/exec-plans/active/execution-frontier.md` — current baseline, next action, and required evidence.

For a pre-existing `AGENTS.md`, use `--update-agents` only after review: text outside the `organize-chip-project:generated` markers belongs to the project and is preserved. Never overwrite a user instruction file with a generic template.

The generator creates missing agent-navigation files but does **not** overwrite an existing project document. Re-run with `--refresh-generated` only to refresh files that already begin with the generator ownership marker. This separation keeps user-authored design knowledge authoritative.

After generation, read the produced `AGENTS.md` and replace/extend its generated facts with additional project-specific evidence from README, manifests, CI, specifications, and tool scripts. A generated outline is the starting point, not the completion criterion. Validate with `validate_agent_native.py`, then apply the five-question completion test in [references/agent-native-quality-bar.md](references/agent-native-quality-bar.md).

### 3. Design the smallest useful AI-native layer

Read [references/ai-native-layout.md](references/ai-native-layout.md). Adapt it to the repository; do not force empty taxonomy or rename established tool conventions just for aesthetics.

At minimum, make these facts quickly discoverable in `AGENTS.md` and its linked indexes:

- what the project is and its current maturity;
- where authoritative specs, RTL/design, DV, constraints, and flows live;
- how to set up, build, simulate, regress, lint, synthesize, and inspect results;
- which files are generated, third-party, security-sensitive, or frozen;
- what is currently being executed and how another agent resumes it.

Create a concise root `AGENTS.md` (typically 80–120 lines and never over 150) and use nested `AGENTS.md` files only where rules differ. Use evidence, not plausible generic prose: write real relative paths, actual Make/Just/CI commands, known variants/tops only when found, and explicit “not discovered” statements otherwise. Put durable truth under `docs/`; put active work state in `docs/exec-plans/active/execution-frontier.md`; put reproducible outputs under `runs/` or retain the project's established output convention.

### 4. Apply changes in safe phases

1. Add documentation, indexes, missing directory scaffolding, and wrappers that delegate to existing commands.
2. Validate that the overlay did not alter functional behavior.
3. Only if valuable, migrate one dependency-closed slice at a time. Update all consumers atomically, including CI and documentation.
4. Never edit generated artifacts as the source of truth; update their generator and regenerate using the established flow.
5. Keep a migration ledger in the active execution plan. Record path mappings, commands, outcomes, exceptions, and rollback instructions.

Do not create parallel competing build systems. A `tools/hw` entry point should call the existing canonical commands unless the user explicitly authorizes convergence on a new interface.

### 5. Prove preservation

After changes, snapshot again and compare:

```bash
python3 <skill-dir>/scripts/preservation_guard.py snapshot <project-root> -o /tmp/project-after.json
python3 <skill-dir>/scripts/preservation_guard.py compare /tmp/project-before.json /tmp/project-after.json
```

Review every missing or changed original artifact. A same-hash move is content preservation, not proof that references still work. Run the same baseline commands with the same environment and relevant seeds/configurations. Add targeted checks for updated paths and flow entry points. For RTL moves, at minimum verify source resolution/elaboration; run simulation/formal/lint/synthesis appropriate to what changed.

Finish with a preservation report containing:

- files added, moved, deliberately modified, and left untouched;
- old-to-new path map and updated consumers;
- pre/post commands with outcomes and artifact/log locations;
- snapshot comparison result;
- checks not run, known baseline failures, and residual risks.

If evidence is incomplete, say “structure migrated; equivalence not fully established,” not “done.”

Do not report the repository as Agent-Native until the quality-bar completion test passes with project-specific evidence.

## New-project workflow

Run the scaffold script in dry-run mode first, then apply:

```bash
python3 <skill-dir>/scripts/scaffold_project.py <project-root>
python3 <skill-dir>/scripts/scaffold_project.py <project-root> --apply
```

Then create the navigation layer with `generate_agent_native.py`. For a genuinely new project, start the root `AGENTS.md` with explicitly labeled unknowns, then replace them as the spec, source tree, and canonical commands are created. Establish one canonical command surface for repeatable flows, preferably configuration-driven. Keep source manifests/configuration separate from ephemeral run artifacts. Capture tool versions, environment assumptions, seeds, configurations, and provenance with each run.

Do not add placeholder RTL or DV that could be mistaken for a real implementation. Do not fabricate requirements, status, commands, ownership, or signoff evidence; mark unknowns explicitly.
