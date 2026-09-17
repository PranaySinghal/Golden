# CLAUDE.md
The build roadmap is in docs/PLAN.md. Read it before any task.
Project instructions for Claude Code. Read this fully before any task.
The human owner makes the product decisions. Your job is to implement them well,
not to redirect the product. If you disagree with a decision, say so and wait.

## Product thesis (fixed; do not change)

Messy data doesn't just look bad. It gives business users wrong answers, and
they can't see it happening. This app cleans any tabular file with the user in
control, then **shows how cleaning changed the answers**.

Target user: a smart, non-technical business user (marketing analyst, sales ops,
business owner). No SQL, no data vocabulary.

Core flow:

```
Ingest → Profile → Detect issues → Propose fixes → Review → Apply (recipe) → Compare answers → Story
```

## Principles (apply to every decision)

1. **Works on any table.** Never hardcode column names, datasets, or domain logic.
   Behavior comes from the profile. A dataset-specific `if` is a bug.
2. **AI proposes, code executes.** The LLM may suggest steps and write wording.
   It never computes numbers and never produces code or SQL. Every number
   shown to the user comes from the engine.
3. **AI sees metadata, not data.** LLM input = profile + stats + a small sample
   (≤ 20 rows). Never send the full file.
4. **Automate what's certain, ask about what's ambiguous.** Every issue has a
   confidence tier: `safe` (batch-applied), `likely` (shown for review),
   `ask` (a plain-language question to the user).
5. **Nothing is destroyed.** The raw table is immutable. The cleaned table is
   derived from raw + recipe. Removed rows are set aside, not deleted.
   Every step is undoable, and every changed value is traceable to its step.
6. **Business language in the UI.** "3 employees appear twice", not
   "duplicate rows detected". No jargon in user-facing strings.
7. **Rank by impact, not count.** Issues and answer changes are ordered by how
   much they move the answers.
8. **Works without an API key.** Rule-based detectors and template wording must
   give a complete, usable experience with `LLM_PROVIDER=none`.

## Non-goals (do not build unless the owner asks)

- Chat-with-your-data / natural-language-to-SQL interface
- Auth, user accounts, multi-user collaboration
- Formats beyond CSV and Excel (keep the adapter interface so they're easy to add)
- Database or warehouse connectors
- Persisting datasets beyond the server process lifetime
- Dashboards, dashboard builders, or chart customization
- Any feature not in the current task. Put ideas in `docs/ideas.md` instead.

## Architecture

Client/server monorepo.

- **Backend:** Python 3.12, FastAPI, DuckDB (in-process), Pydantic v2,
  managed with `uv`. Lint/format with `ruff`, type-check with `mypy`, test with `pytest`.
- **Frontend:** React + TypeScript + Vite. TanStack Query for server state.
  Recharts for charts. API types generated from the backend OpenAPI schema
  (`openapi-typescript`); never hand-write API types.
- **LLM:** a provider interface in `backend/app/ai/` with implementations
  selected by `LLM_PROVIDER` (`anthropic` | `gemini` | `none`). Keys live only
  in backend env vars. Never call an LLM from the frontend.

```
backend/
  app/
    main.py          # FastAPI app, routers only
    api/             # HTTP layer: request/response models, no business logic
    ingest/          # file adapters (csv, xlsx) → DuckDB raw table
    profile/         # column stats + semantic role inference
    detectors/       # one module per detector; pure functions
    steps/           # Step types, SQL compilation, recipe apply/undo
    questions/       # Question spec, auto-generation, execution
    compare/         # before/after runs, diffs, ranking, attribution
    ai/              # provider interface, prompts, response validation
    store.py         # in-memory dataset sessions
  tests/
frontend/
  src/
    api/             # generated types + typed client
    features/        # upload, review, compare, story
    components/      # shared UI
data/
  samples/           # small datasets used for tests and demo
  scripts/           # seeded generators for messier variants
docs/
  decisions.md       # architecture/product decisions (append-only)
  ideas.md           # out-of-scope ideas for "if I had more time"
```

## Core contracts

These are the typed spine of the system. Changing them requires owner approval.

- **ColumnProfile**: name, physical type, semantic role
  (`identifier | category | measure | date | contact | text`), fill rate,
  distinct count, detected patterns, min/max, sample values.
- **Issue**: id, detector, column(s), plain-language title and explanation,
  affected row count, confidence tier, impact score, proposed Step(s),
  and for `ask` tier, the question and its options.
- **Step**: a discriminated union with a `type` field. Initial set:
  `trim`, `normalize_case`, `map_values`, `null_placeholders`, `cast_number`,
  `parse_date`, `split_column`, `dedupe`, `set_aside_rows`, `fill_missing`.
  Each Step compiles to parameterized DuckDB SQL. Identifiers are always
  quoted and validated against the profile. No string-built SQL from user or LLM input.
- **Recipe**: an ordered list of Steps with enabled flags. Replayable on a new
  file with a compatible schema.
- **Question**: `{ measure: count | count_distinct | sum | avg, column?, group_by?, filter? }`
  plus a plain-language label.
- **AnswerDiff**: question, before value(s), after value(s), change,
  impact score, and attribution (list of step ids that moved it).
  Also covers **unlocked** questions (not answerable before cleaning).

## Key definitions

- **"Before"** = how a typical spreadsheet reads the raw file: values are
  text as-is; aggregates use only values that parse as plain numbers;
  blanks and placeholder text are excluded from averages; categories match
  exactly (`Sales` ≠ `sales `). Implement this in one place and document it in
  the UI. Do not make "before" artificially bad.
- **Attribution** = for each changed answer, re-run with each step disabled
  and record which steps change the result. Cache results; datasets may be large.
- **Impact score** = relative change in the answer, weighted by how
  prominent the question is (headline counts/totals > breakdowns).

## AI layer rules

- All LLM output is parsed into Pydantic models. Invalid output is rejected
  and falls back to rule-based behavior. Never `eval`, never execute returned text.
- The LLM may only reference columns and values present in the profile.
  Validate this.
- Prompts live in `backend/app/ai/prompts/` as versioned files, not inline strings.
- Wording tasks receive computed numbers as input and must not introduce new
  numbers. Validate that every number in the output appears in the input.
- Log prompt name, version, latency, and validation result (never raw data).

## Code conventions

- Small, pure, typed functions. Business logic has no FastAPI or I/O imports.
- No silent `except`. Errors become typed API errors with user-friendly messages.
- Limit uploads (50 MB default, configurable). Handle empty files, one-column
  files, no header, non-UTF-8 encodings, and all-null columns gracefully.
- Frontend: every async view has loading, empty, and error states.
- No new dependencies without stating why in the task summary.
- Comments explain *why*, not *what*.

## Testing

- Every detector and every Step has unit tests, including edge cases.
- Golden-file tests: `data/samples/*` → expected issues and expected answer diffs.
- At least two structurally different sample datasets must pass. Any test that
  only passes because of one dataset's column names is wrong.
- One Playwright end-to-end test covering upload → review → compare.
- Run lint, type-check, and tests before saying a task is done.

## Commands

(Fill in once the scaffold exists.)

```
# backend
cd backend && uv sync
uv run uvicorn app.main:app --reload
uv run pytest
uv run ruff check . && uv run mypy app

# frontend
cd frontend && npm install
npm run dev
npm run gen:api     # regenerate API types from backend OpenAPI
npm test
npx playwright test
```

## How to work with me

- **Plan first.** For any non-trivial task, propose a short plan (files,
  contracts touched, tests) and wait for approval before writing code.
- **One task at a time.** Stay inside the scope of the current task.
  Do not refactor unrelated code or add "while I'm here" features.
- **Ask when a product decision is needed.** Do not invent product behavior.
- **End each task with a summary:** what changed, what was tested, open
  questions, and any decision worth recording in `docs/decisions.md`.
- **Do not write or edit `README.md` or `PROMPTS.md`.** The owner writes those.
