# AI IC Design Verification Flow

Three complementary Codex skills for building AI-native chip design and verification repositories, writing concise repository instructions, and running reproducible Synopsys EDA workflows.

## Skills

### `organize-chip-project`

Inspect, create, or conservatively reorganize ASIC, SoC, FPGA, RTL, IP, and DV repositories into an agent-native structure. It adds discoverable project knowledge, execution state, path mapping, and preservation checks without silently deleting or overwriting existing project content.

Example:

```text
Use $organize-chip-project to inspect and safely organize this chip design and verification project into an AI-native repository without losing content or behavior.
```

### `eda-tool-engineering`

Provide a project-independent command interface for reproducible Synopsys RTL simulation, debug, lint/CDC, formal, synthesis, DFT/ATPG, APR, STA, power, and parasitic-extraction flows. Project facts remain in the project's `eda.yaml`; generated commands, logs, and results stay under `runs/`. VCS simulation and DC synthesis have executable, evidence-checked adapters; other flows retain their existing planning interfaces.

Example:

```text
Use $eda-tool-engineering to inspect this project's eda.yaml, validate the environment, and create a dry-run simulation plan.
```

### `verification-closure`

Build a traceable Spec → Testpoint → Checker → Coverage plan, extend existing UVM environments with reviewable test scaffolds, and run budgeted regression/coverage campaigns. It keeps protocol VIP evidence separate from DUT business checking and records unhit bins as gaps.

```text
Use $verification-closure to map this DMA specification into a UVM test plan, run one bounded regression campaign, and classify coverage gaps.
```

### `write-agents-md`

Inspect a repository and create or update a concise, evidence-based `AGENTS.md` (80–120 lines, maximum 150) covering sources of truth, paths, commands, modification boundaries, debugging policy, and definition of done.

Example:

```text
Use $write-agents-md to inspect this repository and create an actionable AGENTS.md under 150 lines.
```

The two skills work together: `organize-chip-project` establishes the repository's knowledge and execution surfaces, while `eda-tool-engineering` supplies the reproducible EDA execution layer. When an organized project contains `eda.yaml`, the organizer directs the agent to use the EDA skill rather than creating a competing flow.

`verification-closure` is the separate planning and analysis layer. It reuses the project's verification agents and canonical Makefiles, and calls deterministic tool flows only when a plan explicitly configures them.

## Milestone 1 flow engine

From a project with a valid `eda.yaml`, use the root `aicflow` entry point:

```bash
/path/to/this/repo/aicflow doctor
/path/to/this/repo/aicflow plan --flow rtl_to_sim_synth
/path/to/this/repo/aicflow run --flow rtl_to_sim_synth --execute
/path/to/this/repo/aicflow resume --run-id <run-id> --execute
/path/to/this/repo/aicflow report --run-id <run-id>
```

Available pipelines: `rtl_to_sim`, `rtl_to_synth`, `rtl_to_sim_synth`. `plan` never launches EDA tools. `run` also stays in planning mode unless `--execute` is given. A run writes a checkpoint under `runs/<run-id>/` and one manifest per adapter stage. Failed dependencies block later stages. `resume` retries a failed stage and checks the input fingerprint; a changed input requires a new run. A prior passing stage with the same fingerprint can be reused from cache. See [Milestone 1 evidence](docs/milestone1.md) and the [project contract](skills/eda-tool-engineering/references/project-eda-contract.md).

## Install

Copy or symlink the skill directories into `${CODEX_HOME:-$HOME/.codex}/skills/`:

```text
skills/eda-tool-engineering
skills/organize-chip-project
skills/verification-closure
skills/write-agents-md
```

Restart or reload Codex skill discovery if the new skills are not visible immediately.

## Safety model

- Existing project content is inventoried before structural migration.
- Existing files are not overwritten by the project scaffold.
- Physical moves require path-consumer mapping and proportionate regression checks.
- EDA commands are planned or run in dry-run mode by default.
- Real tool execution requires explicit `--execute` and valid local tools, licenses, libraries, PDKs, and project configuration.

Tool availability and a generated command plan do not prove design correctness or signoff. Always review project configuration and verification evidence.
