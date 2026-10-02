# Codex Instructions

Use Ponytail mode: full.

Before making any change:

1. Read `PLAN.md`.
2. Inspect the current repository and relevant files.
3. Run `git status`.
4. Treat the repository on disk as the source of truth.

## Review gates

One file modification = one mandatory review gate.

After modifying a file:

1. run the smallest meaningful validation;
2. show the actual diff;
3. stop for user approval.

Never automatically continue to another file or implementation step.

Do not assume approval.

If a change unexpectedly requires another file, stop before modifying it and explain why.

## Scope

Prefer:

- deletion over addition;
- reuse over reimplementation;
- Python standard library over dependencies;
- native framework features over custom abstractions;
- existing dependencies over new dependencies;
- the fewest files possible;
- the smallest correct diff.

Do not add speculative abstractions, architecture, dependencies, configuration, helpers, interfaces, factories, or future scaffolding.

Do not perform unrelated refactors, cleanup, formatting sweeps, dependency upgrades, renames, or lint fixes.

Do not modify approved behavior unless the current task explicitly requires it.

## Git safety

Do not:

- commit;
- merge;
- rebase;
- reset;
- stash;
- switch branches;
- discard changes;

unless explicitly requested by the user.

Never overwrite changes you did not create.

## Source of truth

Priority when information conflicts:

1. current repository contents;
2. `PLAN.md`;
3. current task prompt.

If `PLAN.md` does not match the repository, stop and report the discrepancy instead of guessing.
