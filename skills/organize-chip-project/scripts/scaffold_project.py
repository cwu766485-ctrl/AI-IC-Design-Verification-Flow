#!/usr/bin/env python3
"""Safely add a minimal AI-native chip-project scaffold; never overwrite files."""

import argparse
from pathlib import Path

FILES = {
    "AGENTS.md": """# Project guide

## Purpose and current state

TODO: Describe the chip/IP, maturity, supported configurations, and current status.

## Source-of-truth map

TODO: Link authoritative specs, design sources, verification sources, constraints, and flow configuration.

## Setup and canonical commands

TODO: Record exact environment, build, simulation, regression, lint, synthesis, and result-inspection commands that actually exist.

## Design and verification conventions

TODO: Record hierarchy, tops, clocks/resets, source ordering, test selection, seeds, and acceptance rules.

## Generated, third-party, and protected areas

TODO: Mark generated sources, vendor/PDK/licensed content, secrets, outputs, and files that agents must not modify.

## Validation expectations

TODO: State checks required for documentation, RTL, DV, constraint, and flow changes.

## Active work and known issues

See `docs/exec-plans/active/execution-frontier.md`.
""",
    "docs/project-overview.md": """# Project overview

TODO: Capture purpose, stakeholders, lifecycle stage, variants, top-level blocks, interfaces, clocks/resets, dependencies, and authoritative sources. Mark unknowns explicitly.
""",
    "docs/spec/index.md": """# Specification index

TODO: List normative specifications, versions, owners, requirement identifiers, and their implementation/verification traceability.
""",
    "docs/architecture/index.md": """# Architecture index

TODO: Map hierarchy, interfaces, data/control paths, clock/reset/power domains, parameters, registers, and implementation notes to authoritative documents.
""",
    "docs/verification/strategy.md": """# Verification strategy

TODO: Record scope, environments, test levels, reference models, assertions/formal plan, coverage model, regressions, configurations, exclusions, and signoff criteria.
""",
    "docs/exec-plans/active/execution-frontier.md": """# Execution frontier

## Objective

TODO

## Baseline and evidence

TODO: Record revision, workspace state, environment, commands, outcomes, and log paths.

## Completed

TODO

## Current state and blockers

TODO

## Exact next action

TODO: Give the next command or edit and expected result.

## Acceptance criteria and residual risk

TODO
""",
    ".gitignore": """# Reproducible run outputs (adjust to the project's established policy)
runs/
""",
}

DIRS = [
    "docs/exec-plans/completed",
    "config",
    "rtl",
    "dv",
    "tools",
    "runs",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--apply", action="store_true", help="Create missing items; default is dry-run")
    args = parser.parse_args()
    root = args.root.resolve()

    actions = []
    for directory in DIRS:
        path = root / directory
        if not path.exists():
            actions.append(("mkdir", path, None))
    for relative, content in FILES.items():
        path = root / relative
        if not path.exists():
            actions.append(("write", path, content))

    for action, path, content in actions:
        print(f"{action}: {path}")
        if args.apply:
            if action == "mkdir":
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
    print(("applied" if args.apply else "dry-run") + f": {len(actions)} action(s); existing paths untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
