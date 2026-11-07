# AI IC Design Verification Flow

Three core Codex skills for building AI-native chip design and verification repositories, writing concise repository instructions, and running reproducible Synopsys EDA workflows, plus the existing separately scoped RTL/PPA optimization skill.

## Skills

### `organize-chip-project`

Inspect, create, or conservatively reorganize ASIC, SoC, FPGA, RTL, IP, and DV repositories into an agent-native structure. It adds discoverable project knowledge, execution state, path mapping, and preservation checks without silently deleting or overwriting existing project content.

Example:

```text
Use $organize-chip-project to inspect and safely organize this chip design and verification project into an AI-native repository without losing content or behavior.
```

### `eda-tool-engineering`

Provide a project-independent command interface over a project's `eda.yaml`. Executable adapters cover VCS compile/simulation/regression, URG code and functional coverage extraction, Design Compiler synthesis, and PrimeTime STA. Verdi debug database artifacts are inventoried; the Verdi GUI is not launched. Other listed EDA flows remain planning-only or unsupported until their execution and evidence checks are validated. Generated commands, logs, run manifests, and metrics stay under `runs/`.

Example:

```text
Use $eda-tool-engineering to inspect this project's eda.yaml, validate the environment, and create a dry-run simulation plan.
```

See the [EDA adapter capability matrix](docs/eda-adapter-capabilities.md) for
required inputs and passing evidence, and the [M0 tool capability matrix](docs/tool-capability-matrix.md)
for host installation/license/configuration/test status. Dry-run and planning
results are `NOT_RUN`; they are not verification results.

### `write-agents-md`

Inspect a repository and create or update a concise, evidence-based `AGENTS.md` (80–120 lines, maximum 150) covering sources of truth, paths, commands, modification boundaries, debugging policy, and definition of done.

Example:

```text
Use $write-agents-md to inspect this repository and create an actionable AGENTS.md under 150 lines.
```

### `rtl-ppa-optimization`

The existing PPA campaign skill provides a separate baseline/candidate workflow. Its target-project PPA and optimization acceptance remain unverified until a project-specific baseline, constraints, and Synopsys evidence are available; this M0/M1 increment does not extend that skill.

The two skills work together: `organize-chip-project` establishes the repository's knowledge and execution surfaces, while `eda-tool-engineering` supplies the reproducible EDA execution layer. When an organized project contains `eda.yaml`, the organizer directs the agent to use the EDA skill rather than creating a competing flow.

## Install

Copy or symlink the skill directories into `${CODEX_HOME:-$HOME/.codex}/skills/`:

```text
skills/eda-tool-engineering
skills/organize-chip-project
skills/write-agents-md
skills/rtl-ppa-optimization
```

Restart or reload Codex skill discovery if the new skills are not visible immediately.

## Safety model

- Existing project content is inventoried before structural migration.
- Existing files are not overwritten by the project scaffold.
- Physical moves require path-consumer mapping and proportionate regression checks.
- EDA commands are planned or run in dry-run mode by default.
- Real tool execution requires explicit `--execute` and valid local tools, licenses, libraries, PDKs, and project configuration.

Tool availability and a generated command plan do not prove design correctness or signoff. Always review project configuration and verification evidence.
