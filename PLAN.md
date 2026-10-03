# Chess Trainer

## Status

Project: `chess-trainer`

Target platform: Windows

Application type: local-only single-user web application.

Current implementation state:

- [x] Step 1 — `.gitignore`
- [x] Step 2 — `config.example.json`
- [x] Step 3 — `backend/requirements.txt`
- [x] Step 4 — `backend/import_puzzles.py`
- [x] Step 5 — `backend/core.py`
- [x] Step 6 — `backend/test_core.py`
- [x] Step 7 — `backend/app.py`
- [x] Step 8 — frontend bootstrap
- [x] Step 9 — `frontend/vite.config.ts` Vite development proxy
- [x] Step 10 — Tailwind setup
- [x] Step 11 — minimal shadcn utilities/components actually used (preset + Button)
- [x] Step 12 — Chessground integration
- [ ] Step 13 — one MVP `+page.svelte` (Gate 1 complete; Gate 2 next)

Audit status: complete.

Current frontend gate: **Step 13 Gate 2 — puzzle interaction and result flow**.

Step 13 Gate 1 is complete and user-approved. Gate 2 has not started.

- Lichess importer validation correction: `b249550a37494e650d9510ff11d8a9b5f737a31f`;
- focused importer regression coverage: `b1df31fc56b51ab957e518ef57db581f3d2eadcc`;
- backend regression suite: 12 tests.

---

# Product goal

Build a local application that improves tactical chess pattern recognition using mistakes from the user's own Chess.com games.

Workflow:

1. The user plays games on Chess.com.
2. The user manually clicks Sync.
3. The application fetches recent Chess.com games.
4. Only the configured user's moves are analyzed.
5. Only 15+10 games are eligible.
6. Stockfish analyzes those games locally.
7. Only clear tactical mistakes are retained.
8. Mistakes are classified into a small supported tactical taxonomy.
9. Matching Lichess puzzles are selected from a local puzzle database.
10. A persisted daily list of 20 puzzles is created.
11. The user solves the puzzles on a chessboard.
12. Failed/learned puzzles return through a minimal spaced-repetition system.
13. Old daily sessions remain accessible.

---

# Explicit non-goals

Do not implement unless a later approved plan explicitly adds them:

- authentication;
- multiple users;
- cloud storage;
- Chess.com OAuth;
- automatic background synchronization;
- workers;
- Redis;
- Celery;
- Docker;
- PostgreSQL;
- ORM;
- migration framework;
- settings UI;
- Stockfish installer/downloader;
- statistics dashboard;
- detailed Stockfish UI;
- game-review UI;
- visible centipawn evaluations;
- LLM-based chess analysis;
- notifications;
- API client abstractions;
- global frontend state management;
- architecture for hypothetical future requirements.

---

# Stack

## Frontend

- Svelte 5
- SvelteKit 2
- TypeScript
- Tailwind CSS 4
- shadcn-svelte
- Chessground
- npm

Do not add another UI framework.

Only install/use shadcn components actually required by the UI.

## Backend

- Python 3.14
- FastAPI
- Uvicorn
- python-chess
- SQLite
- Stockfish installed manually on Windows

Prefer Python standard library whenever possible.

HTTP requests should use `urllib.request` unless a demonstrated need requires another dependency.

Tests should use `unittest`.

Do not add pytest unless an actual limitation requires it.

Lichess `.zst` files should use Python 3.14 standard-library Zstandard support.

Do not add a `zstandard` dependency unless the real runtime proves it necessary.

---

# Local execution

Development may use two terminals.

Frontend:

`npm run dev`

Backend:

local Python/Uvicorn command.

Do not create a Windows launcher yet.

---

# Configuration

Use local:

`config.json`

It must not be committed.

Provide:

`config.example.json`

Initial fields:

- `chesscom_username`
- `stockfish_path`
- `initial_games`

Default:

`initial_games = 20`

No settings UI yet.

---

# Databases

Use two SQLite databases.

## `app.db`

Contains local application/user state.

Minimal concepts:

- games;
- tactical mistakes;
- daily sessions;
- session puzzles;
- puzzle spaced-repetition progress.

No user table.

## `puzzles.db`

Contains imported Lichess puzzles.

It must be rebuildable from the official puzzle export.

During normal application usage it is effectively read-only.

The importer stores original Lichess puzzle data.

---

# Chess.com synchronization

Synchronization is manual.

The frontend exposes one Sync action.

## First synchronization

Fetch enough recent archives to obtain:

20 eligible games.

## Later synchronizations

Inspect the:

10 most recent eligible games.

Database uniqueness prevents duplicate imports.

Do not download the user's complete history unnecessarily.

## Eligible games

Only:

15 minutes + 10 second increment.

Equivalent time control:

`900+10`

Include:

- rated games;
- unrated games;
- wins;
- losses;
- draws.

Exclude other time controls.

Analyze only moves played by the configured Chess.com username.

If Chess.com is unavailable:

- local training remains usable;
- synchronization fails cleanly;
- existing data is preserved.

---

# Stockfish analysis

Stockfish is installed manually.

Its executable path comes from `config.json`.

Initial engine setting:

depth 12.

Candidate mistake threshold:

150 centipawns.

A 150 cp loss alone does not create training.

The mistake must also be confidently classified into one supported tactical theme.

Prefer false negatives over incorrect classification.

---

# Supported tactical themes — V1

Only:

- mate;
- fork;
- hanging piece / clear material loss;
- pin;
- discovered attack.

Do not classify general positional mistakes.

Do not attempt to support every tactical pattern.

If classification is uncertain:

skip the mistake.

---

# Lichess puzzle importer

Import the official Lichess puzzle `.csv.zst` into:

`puzzles.db`

Store only fields required by the MVP:

- puzzle ID;
- FEN;
- moves;
- rating;
- relevant themes.

Only keep puzzles matching supported V1 themes.

Exclude:

- promotion puzzles;
- underpromotion puzzles;
- `mateIn1`;
- any puzzle whose actual UCI move sequence contains a promotion.

Do not modify Lichess FEN/Moves during import.

Store the original values.

Use batching.

Use only indexes actually needed by selection queries.

---

# Lichess puzzle semantics

Stored Lichess data represents:

- stored FEN: position before the opponent setup move;
- stored `Moves[0]`: opponent setup move;
- stored `Moves[1]`: first move the training user must find.

When returning a puzzle to the frontend:

1. parse stored FEN with `python-chess`;
2. apply `Moves[0]`;
3. return the resulting FEN;
4. return only `Moves[1:]`.

The frontend must not need `chess.js` merely to reconstruct Lichess puzzle positions.

---

# Puzzle selection

A daily session contains:

20 unique puzzle IDs.

Priority:

1. unfinished puzzles from previous sessions;
2. due spaced-repetition puzzles;
3. new puzzles matching current weaknesses;
4. previously seen matching puzzles only as fallback.

Never duplicate a puzzle merely to reach 20.

If fewer than 20 genuinely eligible unique puzzles exist:

fail clearly instead of duplicating them.

Previous historical sessions must remain unchanged when an unfinished puzzle is carried forward.

## Rating

Use the user's Chess.com rapid rating as the target.

Current implementation derives the target from imported game ratings.

Fallback when no rating exists:

1200.

Initial selection window:

target rating ±400.

Puzzle queries against the large Lichess database must be bounded.

Use small batches while searching candidates rather than loading all matching puzzles into memory.

Current batch size:

50.

Stop searching once 20 unique puzzles are selected.

---

# Daily sessions

A daily session is created only when the user first chooses:

Start training.

Once created:

its 20 puzzle IDs are frozen.

Later Chess.com synchronization on the same day must not alter that session.

New mistakes influence later sessions only.

If today's session already exists:

resume it.

Old sessions remain reopenable.

No statistics page in the MVP.

---

# Spaced repetition

Use this minimal schedule.

Successful first attempts:

3 days → 7 days → 14 days → 30 days → 30 days

Failed first attempt:

1 day.

Failure resets successful progression.

Do not implement SM-2 or another advanced SRS.

---

# Puzzle solving behavior

Use Chessground.

The timer starts when the puzzle position is displayed.

The timer stops when the full expected sequence is completed.

The frontend receives a position where it is already the user's turn.

The first returned move is the first move the user must find.

After each correct user move:

the application automatically plays the next Lichess opponent move.

Then control returns to the user.

The entire solution sequence must be completed.

## Wrong move

The first wrong move immediately records the puzzle as failed.

The user may immediately retry the puzzle for learning.

However:

a later successful retry must not replace the recorded failure.

Only the first recorded result counts for spaced repetition.

Record at minimum:

- success/failure;
- elapsed time.

On failure:

record elapsed time until the first wrong move.

---

# Frontend scope

The MVP uses one main Svelte page.

Do not create routes without a current requirement.

The page supports:

- manual Chess.com synchronization;
- synchronization loading/error state;
- starting today's training;
- resuming today's training;
- opening an older daily session;
- Chessground board;
- current puzzle number;
- timer;
- move interaction;
- automatic opponent moves;
- retry after failure;
- basic session completion state.

Use local Svelte state unless reuse requirements appear.

No global store.

---

# Backend API

Expose only endpoints required by the MVP frontend:

`POST /api/sync`

`POST /api/sessions/today`

`GET /api/sessions`

`GET /api/sessions/{date}`

`POST /api/sessions/{date}/{position}/result`

Do not add generic CRUD endpoints.

Do not expose games, mistakes, engine evaluations, or settings unless a frontend requirement needs them.

FastAPI handlers remain thin.

Business logic remains outside the HTTP layer.

---

# Backend structure

Prefer the smallest structure.

Current intended backend:

- `backend/import_puzzles.py`
- `backend/core.py`
- `backend/test_core.py`
- `backend/app.py`

Keep domain logic in `core.py` until its actual size/complexity proves a split necessary.

Do not pre-create:

- repositories;
- service classes;
- domain layers;
- database abstractions;
- engine wrappers;
- factories;
- interfaces.

---

# Frontend/backend communication

Use Vite's native development proxy:

`/api` → local FastAPI server.

Use native `fetch`.

Do not add CORS merely for local development if the proxy solves it.

Do not add an API-client abstraction.

---

# Testing philosophy

Use the smallest meaningful tests.

Use Python standard-library `unittest`.

Prioritize regression tests for:

- exact 15+10 filtering;
- game deduplication;
- supported tactical classification;
- uncertain tactical positions being ignored;
- frozen daily sessions;
- puzzle selection priority;
- puzzle uniqueness;
- Lichess puzzle payload transformation;
- SRS intervals;
- first failure not being overwritten by retry success.

Use temporary SQLite databases.

Mock external Chess.com/Stockfish boundaries only when needed.

Do not test trivial framework behavior.

---

# Implementation plan

## Step 1 — `.gitignore`

Status: approved.

Ignore only:

- local config;
- SQLite databases;
- Python virtual environment/cache;
- Node dependencies;
- Svelte build artifacts.

---

## Step 2 — `config.example.json`

Status: approved.

Contains:

- Chess.com username;
- Stockfish executable path;
- `initial_games = 20`.

---

## Step 3 — `backend/requirements.txt`

Status: approved.

Runtime dependencies only:

- FastAPI;
- Uvicorn;
- python-chess.

No HTTP client library, ORM, test framework, or compression package unless later demonstrated necessary.

---

## Step 4 — `backend/import_puzzles.py`

Status: approved.

Responsibilities:

- read Lichess `.csv.zst`;
- validate required CSV columns;
- tolerate malformed rows;
- filter supported tactical themes;
- exclude promotion-related themes;
- inspect actual UCI moves and exclude promotion moves;
- validate the complete FEN + UCI move sequence before storage;
- skip rows with malformed FEN, malformed UCI, or illegal moves anywhere in the sequence;
- exclude `mateIn1`;
- preserve original valid FEN and Moves strings unchanged;
- write required fields into `puzzles.db`;
- batch inserts;
- create only required indexes.

No runtime application logic.

---

## Step 5 — `backend/core.py`

Status: approved.

Responsibilities:

- load and validate local config;
- initialize `app.db`;
- fetch Chess.com archives;
- identify exact 15+10 games;
- deduplicate games;
- parse PGNs;
- analyze only configured user's moves;
- call Stockfish through python-chess;
- use depth 12;
- apply 150 cp threshold;
- conservatively classify supported tactical mistakes;
- store games and mistakes;
- calculate target puzzle rating;
- select puzzles;
- prioritize unfinished → due → new → fallback;
- ensure 20 unique puzzles;
- use ±400 rating window;
- scan large puzzle candidate sets in bounded batches;
- create/resume frozen daily sessions;
- manage SRS;
- persist only the first session result;
- transform raw Lichess FEN/Moves only when returning session payloads.

Do not add HTTP concerns.

---

## Step 6 — `backend/test_core.py`

Status: approved and committed.

Add focused `unittest` coverage for non-trivial core behavior.

Required areas:

- exact 15+10 filtering;
- duplicate games ignored;
- representative supported tactical classifications;
- uncertain positions ignored;
- today's existing session remains frozen;
- unfinished puzzle carry-over;
- due priority;
- 20 unique puzzle IDs;
- candidate batching past filtered rows;
- SRS intervals 1/3/7/14/30;
- failed first attempt remains failed after retry;
- Lichess FEN/move payload transformation.
- importer skips a valid setup move followed by an invalid later move and continues importing;

Use temporary SQLite databases.

No testing dependency.

Current regression suite: 12 tests.

---

## Step 7 — `backend/app.py`

Status: approved and committed.

Create thin FastAPI handlers for only the approved API.

Handlers:

- validate HTTP input;
- call `core.py`;
- return HTTP responses.

Do not duplicate domain logic.

---

## Step 8 — frontend bootstrap

Status: approved and committed.

Use the official SvelteKit bootstrap.

Target:

- Svelte 5;
- SvelteKit 2;
- TypeScript;
- npm.

Because the official generator creates several framework files atomically, bootstrap may be treated as one reviewed operation.

Before running the generator:

show the exact command/options and expected files.

Get approval first.

---

## Step 9 — `frontend/vite.config.ts` — Vite development proxy

Status: approved and committed.

Purpose:

Configure the Vite development server proxy for the backend API.

Behavior:

`/api` → `http://localhost:8000`

Use Vite's native `server.proxy` configuration while preserving the generated SvelteKit/Vite configuration.

---

## Step 10 — Tailwind setup

Status: approved and committed.

Implementation:

- Tailwind CSS 4;
- `@tailwindcss/vite`;
- global `frontend/src/routes/layout.css` import from `frontend/src/routes/+layout.svelte`;
- existing Vite `/api` → `http://localhost:8000` proxy preserved.

Each manually modified file receives its own review gate.

Expected sequence, adjusted only if the generated project proves a file unnecessary:

1. frontend dependency configuration;
2. npm lockfile;
3. Vite configuration (Step 9 — completed);
4. Tailwind setup (Step 10 — completed);
5. minimal shadcn utilities/components actually used (Step 11 — completed with the selected preset and first actually-used Button);
6. Chessground integration (Step 12 — completed);
7. one MVP `+page.svelte` (Step 13 Gate 1 — completed; Gate 2 — current/next).

Frontend requirements:

- `/api` Vite proxy;
- native `fetch`;
- one main route;
- no global store;
- no API abstraction;
- no unused component library installation.

---

## Step 11 — minimal shadcn utilities/components actually used

Status: approved and implemented with minimal scope.

History:

- originally deferred under Ponytail/YAGNI because no current UI consumed a shadcn component;
- later initialized because the user explicitly selected preset `b1ob4f1k` and requested the Button component.

Resolved preset:

- style: `sera`;
- base color: `neutral`;
- font: Inter Variable;
- radius: `0rem`.

Approved commits:

- `fa2a01a64179036df128151a8705207faf7bc2d4` — `chore: initialize shadcn preset`;
- `3850ed7b218128ff71286c1ee3e1856ad964344c` — `feat: add shadcn button component`.

Current scope:

- only the official Button component has been added so far;
- only the components actually required by the UI may be added;
- the full shadcn-svelte component library is not required by this plan.

Preserve the Ponytail/YAGNI rule: add another shadcn component only when the UI actually needs it.

---

## Step 12 — Chessground integration

Status: approved and committed.

Implementation:

- official package: `@lichess-org/chessground`;
- exact version: `10.4.1`;
- direct Svelte integration without a wrapper;
- official package CSS imported directly;
- lifecycle mount and cleanup implemented;
- current board remains a static integration proof only.

Next frontend gate: Step 13 Gate 2 — puzzle interaction and result flow.

---

## Step 13 — one MVP `+page.svelte`

Status: Gate 1 complete and user-approved. Gate 2 is the current/next implementation gate. Gate 3 remains future work.

### Gate 1 — MVP shell, Button, and board-coordinate refinement

Status: complete and user-approved after desktop visual review.

Approved commit:

- `166069a9c81437b267b1afb55572eac6269e8958` — `feat: build mvp training shell`.

Implemented:

- one MVP page in `frontend/src/routes/+page.svelte`;
- initial session-history loading;
- manual Chess.com Sync action;
- Start / Resume Today;
- historical session reopening;
- loading, status, and error states;
- backend-provided puzzle FEN rendered directly in Chessground;
- one Chessground instance with `viewOnly: true`;
- dominant board sizing at approximately `min(86vh, 100%)`;
- compact desktop left rail with responsive mobile stacking;
- official shadcn-svelte Button for `Sync games` and `Start / Resume Today`;
- `default` and `secondary` variants, both using `size="lg"`;
- semantic `sera` preset theme tokens;
- responsive Chessground rank/file labels using the local `:global(.cg-wrap coords)` override;
- friendly `Backend unavailable or returned an invalid response.` fallback.

The refresh-time button color flash was not reproducible after Button adoption. No unsupported root-cause claim is recorded.

Not included in Gate 1:

- no draggable puzzle interaction;
- no UCI move validation;
- no timer;
- no result submission or persistence;
- no retry behavior;
- no automatic opponent moves;
- no full puzzle-solving loop;
- no Gate 2 or Gate 3 behavior.

### Gate 2 — puzzle interaction and result flow

Status: current/next implementation gate; not started.

This gate remains implementation-only future work and retains the existing puzzle-solving requirements above. Do not mark any of these complete before Gate 2 implementation:

- draggable puzzle interaction;
- expected UCI validation;
- timer;
- first-failure persistence;
- retry behavior;
- automatic opponent solution moves;
- successful result recording;
- full puzzle solving loop.

### Gate 3 — session progression and completion

Status: future work; not started.

Do not mark these complete as part of Gate 2:

- first-unfinished puzzle selection;
- next-puzzle progression;
- multi-puzzle session progression;
- final session-completion state;
- history refresh after progression.

---

# Review protocol

After every file modification:

### Step N — `<file>`

**Change**

One or two sentences maximum.

**Validation**

`<exact command/check performed>`

Result: `<passed / failed / not applicable>`

**Unexpected**

Relevant findings only, otherwise `None`.

**Diff**

```diff
<actual diff>
```

**Review**

Please review this change.

I will not continue to another file or implementation step in this turn.

Then stop.

---

# Git workflow

The repository on disk is the source of truth.

Do not rely on previous chat memory.

At the beginning of every fresh Codex conversation:

1. read `AGENTS.md`;
2. read `PLAN.md`;
3. inspect `git status`;
4. inspect the files relevant to the current step.

Do not automatically commit.

After an implementation step has been explicitly approved, the user may request a commit.

Do not merge, rebase, reset, stash, switch branches, or discard changes without explicit instruction.

For sequential work:

prefer one branch.

Use separate branches only if multiple Codex conversations are intentionally working in parallel on independent file scopes.

---

# Future ideas — not part of MVP

Do not implement or scaffold:

- settings screen;
- direct Chess.com connection/OAuth;
- richer tactical taxonomy;
- visible Stockfish analysis;
- detailed game review;
- statistics;
- weakness trends;
- smarter recommendation weighting;
- Stockfish installer;
- Windows launcher;
- desktop packaging;
- advanced spaced repetition.

Add them only if later requirements justify them.
