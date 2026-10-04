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

## Browser validation

Browser/UI validation is always manual and performed by the user.

Luna/Codex must never launch, open, control, automate, or otherwise drive a browser for validation, including through Playwright, a cloud browser, or any browser/computer-control tool.

When browser validation is required, the agent must:

1. complete all available non-browser validation;
2. clearly tell the user that manual browser testing is required;
3. list the exact manual test steps and expected outcomes;
4. state that browser validation remains pending;
5. stop and wait for the user's test results before treating that validation as passed or committing a gate that requires browser validation.

Non-browser validation remains allowed, including npm checks/builds, unit tests, API checks, and starting backend/frontend processes when needed.

Never claim a browser smoke test passed unless the user explicitly reports that it passed.

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

## Commit after approval

When the user explicitly approves an implementation step:

1. inspect `git status --short`;
2. stage only the file(s) approved for that step;
3. inspect `git diff --cached`;
4. verify no unrelated or unapproved file is staged;
5. create one dedicated commit for the approved step;
6. show the commit hash, message, and final `git status --short`;
7. stop.

Never include unrelated, unapproved, or previously excluded files in the commit.

If the staged diff contains anything outside the approved step, stop instead of committing.

Use a concise Conventional Commit-style message that describes the approved change.

Do not amend, squash, merge, rebase, reset, or push unless explicitly requested.
