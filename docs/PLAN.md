# PLAN.md — North Star

The build roadmap for this project. `CLAUDE.md` defines *how* we build
(principles, contracts, conventions). This file defines *what* we build and
*in what order*. When they conflict, `CLAUDE.md` wins; flag the conflict.

---

## 1. The goal in one paragraph

Build a client/server web app where a non-technical business user uploads any
CSV or Excel file, reviews plain-language data problems (fixing safe ones in
bulk, reviewing likely ones, answering questions on ambiguous ones), and then
sees **how cleaning changed the answers** to real business questions:
before/after cards, paired charts, the steps responsible for each change, and
the new questions cleaning made possible. It must work on any table, not one dataset.

## 2. What "done" looks like (the demo)

1. User uploads a messy file.
2. The app shows a short summary of the data: what it's about, its size, and the main problems.
3. Issue cards appear, ranked by impact, in business language, grouped by
   tier: *fixed automatically* / *please review* / *we need your call*.
4. User accepts, rejects, or answers each one. The recipe panel updates; any step can be undone.
5. The **"What changed" view** shows:
   - headline cards (before → after, change, "why" links to steps)
   - paired before/after bar charts for breakdowns
   - "Now you can ask" cards for newly possible questions
   - toggling an ask-tier choice updates the affected cards live
6. A short story summarizes the most important changes. Every number links to its card.
7. User downloads the cleaned file and the recipe.
8. The same flow works on a second, structurally different dataset.

## 3. Milestones

Each milestone = one Claude Code session (or a few), ending in a green test run
and a commit. Don't start a milestone until the previous one's acceptance
criteria pass.

| # | Milestone | Target day |
|---|---|---|
| M1 | Scaffold, ingest, profiler | Day 3 |
| M2 | Step engine and recipe | Day 4 |
| M3 | Issue detectors and tiers | Day 4–5 |
| M4 | Questions and before/after comparison | Day 5 |
| M5 | Attribution and unlocked questions | Day 5–6 |
| M6 | API and review UI | Day 6 |
| M7 | "What changed" UI | Day 6–7 |
| M8 | AI layer | Day 7 |
| M9 | Story, second dataset, end-to-end test | Day 7–8 |
| M10 | Hardening, packaging, deploy (feature freeze) | Day 8 |

Days 9–10 are for the README, the video, and demo rehearsal. No new features.

---

### Standard review checklist (apply to every plan Claude proposes)

- Stays inside this milestone's scope. Nothing pulled in from later milestones.
- Matches the folder structure and contracts in `CLAUDE.md`.
- No dataset-specific logic (column names, known values).
- Business logic is pure and separate from the API and I/O layers.
- Tests cover edge cases, and at least two datasets where relevant.
- Every new dependency is justified.
- Open product questions are asked, not decided silently.

---

### M1 — Scaffold, ingest, profiler

**Goal:** a running backend and frontend skeleton; any CSV or Excel file becomes a raw
DuckDB table plus a column profile.

**In scope:** repo scaffold (backend and frontend), tooling (uv, ruff, mypy, pytest,
Vite, TypeScript), a health endpoint, CSV and Excel adapters behind a common
interface, raw table stored with all values as text, the `ColumnProfile` model,
semantic role inference, an in-memory dataset store, and a second small sample dataset.

**Out of scope:** detectors, steps, UI screens beyond a placeholder, AI.

**Status:** done. Owner-approved additions made during M1: `IngestOptions.header`
(the "first row is data" override) and a `_row_id` column on the raw table.
The frontend placeholder was replaced by the upload screen in M2.

**Acceptance criteria:**
- `uv run pytest`, `ruff`, and `mypy` pass. The frontend builds and runs.
- Profiling the employee file gives sensible roles: ID → identifier, Email →
  contact (with low uniqueness noted), Department_Region → category, Salary → measure
  (despite the `N/A` values), Join_Date → date.
- Role inference works from value properties (uniqueness, cardinality, patterns,
  parse rates). Column names are only a weak hint.
- Tests cover: an empty file, a header-only file, no header, non-UTF-8 encoding, an all-null column,
  a single column, the size limit, and an Excel file with multiple sheets (first sheet or chosen sheet).

**Prompt:**
```
Read CLAUDE.md and docs/PLAN.md. We are on M1.
Propose a plan for M1 only: scaffold the backend (FastAPI, uv, DuckDB, Pydantic v2,
pytest, ruff, mypy) and frontend (React, TypeScript, Vite), CSV and Excel
ingest into a DuckDB raw table (all values stored as text), an in-memory
dataset store, and the column profiler with semantic role inference.
Also create a small, structurally different second sample dataset for tests.
In your plan include: files you'll create, the Pydantic models, how role
inference decides each role (it must rely on value properties, not column
names), the edge cases you'll test, and any dependency you add with a reason.
Check the plan against M1's acceptance criteria. Don't write code until I approve.
```

---

### M2 — Step engine and recipe

**Goal:** typed, reversible cleaning steps that compile to safe SQL.

**In scope:** the `Step` discriminated union (the initial set from `CLAUDE.md`),
compiling each step to parameterized DuckDB SQL, the `Recipe` model
(ordered steps with enabled flags), applying raw + recipe → cleaned view,
undo/disable, set-aside rows, row-level lineage (which step changed which cell),
and exporting the cleaned CSV and the recipe as JSON.

*Pulled forward from M6 (owner decision):* a basic upload screen: the upload,
dataset, and re-read endpoints, a file summary, a column table (kind, how full,
different values, range, examples, and a hover note explaining each kind), a
sheet picker for Excel, and a "First row has column names" toggle. Also the
product name, TidyLab.

**Out of scope:** deciding which steps to propose (that's M3), recipe and issue UI, AI.

**Acceptance criteria:**
- Each step type has unit tests, including no-op cases and invalid parameters.
- Raw data is never changed. Disabling a step produces the same result as never adding it.
- A step that depends on a disabled step is marked blocked with a reason, and the rest
  of the recipe still applies.
- Identifiers are validated against the profile. No SQL is built from raw strings.
- A recipe replays on a different file with a compatible schema. On an incompatible one,
  it fails with a clear message.
- Lineage answers "what was this cell before, and which step changed it?"
- The exported CSV neutralizes spreadsheet formulas with a leading `'`.
- A user can upload a CSV or Excel file in the browser, see what each column holds,
  and switch sheets or the header setting.

**Prompt:**
```
Read CLAUDE.md and docs/PLAN.md. M1 is done. We are on M2.
Propose a plan for M2 only: the Step discriminated union, compiling each step
to parameterized DuckDB SQL, the Recipe model, applying raw + recipe to get a
cleaned view, enable/disable/undo, set-aside rows, cell-level lineage, and
exporting the cleaned CSV and the recipe JSON.
Include: the model for each step type and its SQL strategy, how you'll guarantee
the raw table is never changed, how lineage is stored without copying the
whole table per step, how recipe replay checks schema compatibility,
and your test list. Don't write code until I approve.
```

---

### M3 — Issue detectors and tiers

**Goal:** find real problems in any table and propose steps for them, with a confidence tier and impact score.

**In scope:** the detector interface (profile + data → issues), and detectors for
placeholder text used as missing values, numbers stored as text, category variants,
combined columns, date format inference from evidence plus truly ambiguous
dates, exact and likely duplicate records, identifier-like columns that aren't
unique, out-of-range values, and invalid contact formats. Also tier assignment
(safe / likely / ask), `ask`-tier questions with options, and plain-language titles
and explanations from templates (no AI yet). Include a seeded script in
`data/scripts/` that generates a messier variant of a sample file.

**Out of scope:** impact scoring from answer changes (that's M4/M5; use a
placeholder based on affected rows for now), the UI, AI.

**Acceptance criteria:**
- Each detector has tests showing it fires when it should *and* stays quiet when it shouldn't.
- On the employee file: finds `N/A` salaries, the combined Department_Region
  column, non-unique Email, corrupted phones (ask-tier for short ones), missing ages,
  and infers month/day date order with the evidence stated.
- On the messy generated variant: also finds casing and spacing variants, duplicates,
  and mixed formats.
- No detector references a specific column name or dataset.
- Titles use business language. Review the copy against `CLAUDE.md` principle 6.

**Prompt:**
```
Read CLAUDE.md and docs/PLAN.md. M1–M2 are done. We are on M3.
Propose a plan for M3 only: the detector interface, the detector list in PLAN.md,
confidence-tier rules, ask-tier questions and options, template-based
plain-language copy, and a seeded script that makes a messier variant of a
sample file (casing, spaces, mixed dates, duplicates, "$85k"-style numbers).
For each detector include: what it looks for, its thresholds, its tier logic,
the Step(s) it proposes, and one false-positive case you'll test against.
Use a temporary impact score based on affected rows. Don't write code until I approve.
```

---

### M4 — Questions and before/after comparison

**Goal:** automatically ask sensible business questions of any table and compare the answers before and after cleaning.

**In scope:** the `Question` spec, generating questions from the profile
(entity count, totals and averages per measure, breakdowns by category,
trends over dates, capped to a sensible number), the "before" evaluator
(the spreadsheet-like reading defined in `CLAUDE.md`, implemented in one place),
the "after" evaluator on the cleaned view, `AnswerDiff`, a real impact score,
and ranking. Issue impact is updated from the answer changes it causes.

**Out of scope:** attribution per step (M5), the UI, AI.

**Acceptance criteria:**
- The "before" definition lives in one module with tests that document each rule.
- The employee file shows the average-salary shift from treating `N/A` as zero vs. as missing,
  depending on the chosen option.
- Question generation is capped and prioritizes headline questions.
- Diffs handle groups present only before or only after (for example, `sales ` merged into `Sales`).
- Handles large files sensibly (aggregates in SQL, no pulling full tables into Python).

**Prompt:**
```
Read CLAUDE.md and docs/PLAN.md. M1–M3 are done. We are on M4.
Propose a plan for M4 only: the Question spec, generating questions from the
profile (with a cap and priority order), a single "before" evaluator
implementing the spreadsheet-like reading in CLAUDE.md, the "after" evaluator,
AnswerDiff, impact scoring, and ranking; also update issue impact from answer changes.
Include: the question generation rules, the exact "before" rules with a test for
each, how breakdown diffs handle groups that appear or disappear,
the impact formula with a worked example, and performance considerations.
Don't write code until I approve.
```

---

### M5 — Attribution and unlocked questions

**Goal:** explain *why* each answer changed, and show questions that only cleaning made possible.

**In scope:** attribution by re-running with each step disabled (with caching
and a cap on cost), attaching step ids to each `AnswerDiff`, "unlocked"
questions (for example, breakdowns by a column created by `split_column`, or
numeric totals after `cast_number`), and recomputing when an ask-tier choice changes.

**Out of scope:** the UI, AI.

**Acceptance criteria:**
- Each changed answer lists the step(s) responsible, with tests on known cases.
- The employee file: splitting Department_Region produces a "headcount by department" unlocked card.
- Changing one ask-tier option only recomputes what that change affects.
- Attribution cost is bounded and documented (steps × questions).

**Prompt:**
```
Read CLAUDE.md and docs/PLAN.md. M1–M4 are done. We are on M5.
Propose a plan for M5 only: step-level attribution by re-running with each step
disabled, caching and cost limits, attaching attribution to AnswerDiff,
detecting unlocked questions, and recomputing efficiently when a user
changes an ask-tier choice.
Include: the attribution algorithm and its complexity, how you'll handle steps
that only matter together, the caching key, the unlocked-question rules,
and tests. Don't write code until I approve.
```

---

### M6 — API and review UI

**Goal:** the user can upload a file and review issues in the browser.

**In scope:** REST endpoints (proposed shape below; confirm in the plan),
issue cards grouped by tier and sorted by impact, accept/reject/answer
actions, the recipe panel with undo, before/after previews on each card,
and loading, empty, and error states. Builds on the upload screen, data
summary, and generated API types that already exist from M2.

Proposed endpoints (the first three exist since M2):
```
POST   /api/datasets                      upload → dataset id + summary   (done in M2)
GET    /api/datasets/{id}                 summary + column profile        (done in M2)
POST   /api/datasets/{id}/reingest        re-read with sheet/header       (done in M2)
GET    /api/datasets/{id}/issues
GET    /api/datasets/{id}/recipe
POST   /api/datasets/{id}/recipe/steps    add/accept a step (or answer a question)
PATCH  /api/datasets/{id}/recipe/steps/{step_id}   enable/disable/edit
GET    /api/datasets/{id}/preview?step_id=…       before/after sample rows
GET    /api/datasets/{id}/export?format=csv|recipe
```

**Out of scope:** the "what changed" view (M7), AI.

**Acceptance criteria:**
- The full review flow works on both sample datasets in the browser.
- No business logic in route handlers or React components.
- API types are generated, not hand-written.
- The UI copy uses no data jargon.

**Prompt:**
```
Read CLAUDE.md and docs/PLAN.md. M1–M5 are done. We are on M6.
Propose a plan for M6 only: the REST API (start from the endpoints in PLAN.md
and suggest changes if needed) and the review UI, building on the existing
upload screen: issue cards grouped by tier and sorted by impact,
accept/reject/answer actions, the recipe panel with undo, before/after previews,
and loading/empty/error states.
Include: the endpoint list with request/response models, the component tree,
the state management approach, and a sketch of each screen in words.
Don't write code until I approve.
```

---

### M7 — "What changed" UI

**Goal:** the hook. Show the user how cleaning changed their answers.

**In scope:** a compare endpoint, headline before → after cards with "why"
links that highlight the responsible recipe steps, paired before/after bar charts
for breakdowns, "Now you can ask" cards, live updates when an ask-tier
choice changes, a visible "what 'before' means" explanation, and download buttons.

**Out of scope:** AI wording (template text for now), the story panel (M9).

**Acceptance criteria:**
- Cards are ranked by impact. The top 3 are visible without scrolling.
- The before bar is shown faintly behind the after bar. The chart works when groups merge or split.
- Clicking "why" highlights the relevant steps and their previews.
- Changing a choice updates the affected cards within a moment, with no full-page reload.
- Readable on a laptop screen and usable on a narrow screen.

**Prompt:**
```
Read CLAUDE.md and docs/PLAN.md. M1–M6 are done. We are on M7, the core of the demo.
Propose a plan for M7 only: the compare endpoint, headline before → after cards
with "why" links to recipe steps, paired before/after bar charts (Recharts),
"Now you can ask" cards, live updates when an ask-tier choice changes, a
"what 'before' means" explainer, and download buttons.
Include: the layout in words, the chart design for merged/split groups,
how live updates avoid unnecessary recomputation, and the empty state when
cleaning changed nothing. Don't write code until I approve.
```

---

### M8 — AI layer

**Goal:** AI improves suggestions and wording, without ever being required and without ever computing numbers.

**In scope:** the provider interface (`anthropic` | `gemini` | `none`), versioned
prompt files, (a) AI-proposed fixes from profile + stats + a sample of ≤ 20 rows,
validated into `Step` models, only referencing columns and values that exist,
merged with the rule-based issues and labeled "suggested by AI";
(b) plain-language rewording of questions and issue copy, with a check that
no new numbers are introduced; timeouts, fallback to templates, and logging
(no raw data).

**Out of scope:** chat, free-form questions, AI-computed numbers.

**Acceptance criteria:**
- With `LLM_PROVIDER=none`, the app is fully usable, and tests pass without a key.
- Invalid or hallucinated AI output is rejected and tested with fake bad responses.
- The payload sent to the LLM is inspectable and tested to contain no more than the allowed sample.
- A wording output containing a number not in the input is rejected.

**Prompt:**
```
Read CLAUDE.md and docs/PLAN.md. M1–M7 are done. We are on M8.
Propose a plan for M8 only: the LLM provider interface (anthropic, gemini,
none), versioned prompt files, AI-proposed fixes validated into Step models,
AI rewording of question and issue copy with a "no new numbers" check,
timeouts, template fallback, and logging without raw data.
Include: each prompt's input and output schema, the validation rules, how AI
suggestions merge with rule-based issues (and how they're labeled), how the
LLM payload is built and limited, and tests using fake responses (valid,
invalid, hallucinated columns, invented numbers). Don't write code until I approve.
```

---

### M9 — Story, second dataset, end-to-end test

**Goal:** complete the full-circle story and prove it generalizes.

**In scope:** a story panel (3–4 sentences built from the top diffs, with AI wording
when available and templates otherwise, every number linked to its card),
golden-file tests for both sample datasets plus the messy variant
(expected issues and diffs), running the app on at least one of the challenge's
other datasets and fixing what breaks, and one Playwright test: upload → review → compare → download.

**Out of scope:** new detectors or features. Log gaps in `docs/ideas.md` instead.

**Acceptance criteria:**
- The story contains only numbers from computed diffs.
- Golden-file tests pass for all fixture datasets.
- The Playwright test passes locally and in CI.
- Generality findings are written to `docs/decisions.md` (what broke, what changed).

**Prompt:**
```
Read CLAUDE.md and docs/PLAN.md. M1–M8 are done. We are on M9.
Propose a plan for M9 only: the story panel (numbers only from computed diffs,
each linked to its card, AI wording with a template fallback), golden-file tests
for every fixture dataset, a generality check on [DATASET NAME] with fixes for
what breaks, and one Playwright test covering upload → review → compare → download.
Do not add new features; log gaps in docs/ideas.md. Don't write code until I approve.
```

---

### M10 — Hardening, packaging, deploy (feature freeze)

**Goal:** a reviewer can run it with one command or open a live link.

**In scope:** a single Docker image (FastAPI serves the built frontend),
`.env.example`, basic rate limiting on AI calls, upload limits and
friendly errors, a CI workflow (lint, type-check, tests, build), deploy to
a single-container host (for example, Render or Fly), and filling in the
Commands section of `CLAUDE.md`.

**Out of scope:** new features. Anything else goes to `docs/ideas.md`.

**Acceptance criteria:**
- A fresh clone runs by following written steps, tested on a clean checkout.
- The live link works without an AI key configured (template mode), and with one.
- CI is green.

**Prompt:**
```
Read CLAUDE.md and docs/PLAN.md. M1–M9 are done. We are on M10 — feature freeze.
Propose a plan for M10 only: a single Docker image where FastAPI serves the built
frontend, .env.example, AI rate limiting, upload limits and friendly errors,
a GitHub Actions CI workflow (lint, type-check, tests, build), and deployment to
a single-container host. Also list anything that currently makes a fresh
clone fail to run. No new features. Don't write code until I approve.
```

---

## 4. Days 9–10 (owner only)

- README, written by the owner: why this, how AI was used, what next.
- Curate `PROMPTS.md`: highlight 3–5 moments where the AI was redirected.
- Record the 5-minute video: problem → demo → key decision → steering the AI → next.
- Rehearse the 15-minute onsite demo and prep Q&A.
- Submit early and notify the recruiter.

## 5. Change control

This plan can change, but changes are deliberate: the owner updates this
file and records why in `docs/decisions.md`. Claude may propose changes;
it may not apply them silently.
