# Decisions

Append-only. Newest at the bottom. Each entry: date, milestone, decision, why.

---

## 2026-09-16 · M1 · Scaffold, ingest, profiler

**Raw table layout.** Every dataset is loaded into a DuckDB table `raw` with
all values as `VARCHAR`, plus `_row_id BIGINT` (1-based position among loaded
rows). Blank cells are `NULL`; everything else, including surrounding spaces,
`N/A`, and `007`, is stored exactly. `_row_id` is reserved; a user column with
that name is renamed `_row_id_2`. *Why:* later steps need stable row identity
for lineage and set-aside rows (owner approved adding it in M1).

**One load path for all formats.** Adapters (CSV, XLSX) yield rows of text;
the loader writes them to a normalized UTF-8 temp CSV and DuckDB reads that
with every option spelled out (no type, header, or quote sniffing). *Why:*
Python controls decoding, ragged rows, and header detection; DuckDB does the
bulk load fast. Adding a format means adding an adapter.

**Encoding fallback** is BOM → UTF-8 → cp1252 → latin-1, with no detection
library. *Why:* covers real spreadsheet exports without a dependency; text with
null characters (binary or UTF-16 without BOM) is rejected instead of garbled.

**Empty rows are skipped and counted** (`empty_rows_skipped`). A row with no
values carries no data; reporting the count keeps the step visible.

**Header detection** uses columns whose later values are mostly numbers or
dates: a label on top means header, a number/date on top means data. With no
such column, a header is assumed. `IngestOptions.header` (`auto` | `header` |
`data`) is the "first row is data" toggle (owner decision), and
`DatasetStore.reingest` re-reads the kept source bytes with new options
without a new upload. Known limit: a year used as the only typed column's
name (e.g. `id,2023`) reads as data; the toggle covers it.

**ColumnProfile additions** (owner approved): `position`, `role_confidence`,
`role_note`, `flags`, `uniqueness`, typed `patterns`. `role_note` is a
plain-language reason meant for a hover note in the UI.

**All-blank columns** get role `text`, physical type `empty`, confidence 0,
flag `all_blank`, and a note explaining why nothing can be inferred (owner
decision: no seventh role).

**Role inference** is an ordered rule list in `app/profile/roles.py` driven by
value statistics computed in SQL: blank → date → email → formatted phone →
yes/no → (bare digits + phone name) → code-shaped ID → numeric ID (leading
zeros / sequence / long fixed width) → measure (or number labels when leading
zeros) → category → text. Thresholds are named constants. Column names are
consulted in exactly two ambiguous cases (bare digit strings named like a
phone; long fixed-width numbers named like an ID) and set `name_hint_used`.
The employee `Phone` column is `contact` only because of its name; with
anonymized headers it's `identifier` (owner accepted). Tests profile both
samples with `col_1..col_n` headers to prove the rest comes from values.

**Date min/max** uses the format that reads the most values. If formats tie
and disagree (every day ≤ 12, so day/month order is unknown), no range is
reported. Deciding the order is M3's job.

**Store.** One in-memory DuckDB connection per dataset, oldest evicted past
`MAX_DATASETS` (default 10; env-configurable, as is `MAX_UPLOAD_MB`, default
50). Source bytes are kept for re-reading, so worst-case memory is about
datasets × upload limit. No upload endpoint yet (M6); `tests/test_store.py`
covers the flow the endpoint will wrap.

**Errors.** `AppError` subclasses carry a stable `code`, an HTTP status, and a
user-facing message; FastAPI returns `{code, message}`, declared in OpenAPI so
the frontend's generated types include it.

**Second sample dataset** `data/samples/store_orders.csv` (64 rows, 11
columns) was generated once with a seeded script and committed as data. It
differs from the employee file in structure: numeric sequential IDs,
day-first dates, formatted phones, leading-zero postcodes, currency and
percent values, yes/no answers, a mostly blank free-text column, and spaces in
column names.

**Frontend tooling.** TypeScript is pinned to 5.9 because
`openapi-typescript` 7 (required for generated API types) declares
`typescript@^5` as a peer and doesn't support 6 yet. The current Vite
template ships `oxlint` instead of ESLint; kept as is. `npm run gen:api` exports
OpenAPI from the FastAPI app directly (no running server needed) into
`src/api/openapi.json` and `src/api/schema.d.ts`; both are committed so type
changes show up in diffs.

---

## 2026-09-16 · M2 · Step engine, recipe, lineage, export, upload screen

**Name.** The product is called TidyLab ("Tidy your data. See what it was
hiding."). The GitHub repo and local folder keep their old names (owner
decision). "Golden-file tests" is a testing term and stays.

**Raw table is read-only at the database level** (owner decision). Ingest
writes `raw` into `raw.duckdb` in a per-dataset temp workspace; the session's
in-memory DuckDB attaches it `READ_ONLY` as `source`. Any write to
`source.raw` fails inside DuckDB. Derived tables live in the in-memory `work`
schema. The workspace is deleted on delete, eviction, re-read, and shutdown.
This supersedes the M1 note that `raw` lived in the session's memory.

**One CTE chain per recipe.** Stage `s0` is the raw table; each applied step
compiles to a `SELECT` over the previous stage. Three statements run over the
chain: `work.cleaned`, `work.set_aside` (row id, step, reason), and
`work.changes`. Disabled steps never enter the chain, so disabled equals never
added (tested for every step in a 10-step recipe). Results are cached by a
fingerprint of the applied steps.

**SQL safety.** Identifiers come only from the stage schema (derived from the
profile) and are quoted. Every step value is a named bound parameter prefixed
with the step's position. DuckDB rejects unused parameters, so each statement
binds exactly the parameters of the fragments it includes. The only inlined
strings are fixed regex constants and server-generated paths (ATTACH, COPY).

**Blocked steps** (owner decision). An enabled step that can't run is skipped
with a plain-language reason. If it would run with every earlier step on, the
reason says it depends on a step that's turned off or can't run. Adding,
updating, or enabling a step that would be blocked is rejected; turning a step
off is always allowed.

**Lineage stores only changed cells** in `work.changes (row_id, column_name,
step_id, step_index, before, after, kind)`, where kind is changed / cleared /
filled / created. Change rules: text steps compare text; `cast_number` counts
a cell only if the original wasn't already that plain number ("85000" → 85000
is not a change); `parse_date` counts every filled cell; `split_column` records
created cells with the source value as "before". Intermediate stages may be
held in memory while the statement runs; nothing but changed cells is kept.

**Numbers are DOUBLE, dates are DATE/TIMESTAMP** in the cleaned table. Whole
numbers render without ".0" in lineage and exports.

**Row removal** only happens through `dedupe` and `set_aside_rows`; both take
`keep_row_ids` so a single row can be restored with an undoable edit. Blanks
count as equal when deduping. A condition that can't be evaluated keeps the row.

**Undo** is a history of earlier recipes (capped at 100); no redo (owner decision).

**Re-reading a file resets its recipe**, because the columns can change.

**Replay.** A recipe file records the source columns and `requires_columns`
(columns enabled steps read without creating them). Missing columns are
problems (with a near-match suggestion); steps that fail only because an
earlier step failed are folded into that problem; a `cast_number` or
`parse_date` column that doesn't look like numbers or dates is a warning.
An incompatible recipe raises before anything is built.

**CSV export** (owner decision) prefixes `'` to text cells and headers that
start with `= + - @`, tab, or CR unless they're plain numbers, and starts with
a UTF-8 byte order mark so Excel shows accented text correctly.

**Upload screen pulled forward from M6** (owner decision): `POST /api/datasets`,
`GET /api/datasets/{id}`, `POST /api/datasets/{id}/reingest`,
`GET /api/upload-limits`. Oversized uploads that declare their size are turned
away by middleware before the body is read (Starlette parses multipart bodies
before the route runs); the route also enforces the limit while reading.
Settings and the store live on `app.state`, created in the app lifespan.

**Hover notes** are rendered in a portal with fixed positioning so the
scrolling column table can't clip them. They open on hover or focus and close
on leave, blur, Escape, or scroll.

**New dependency:** `python-multipart`, which FastAPI requires to receive file uploads.

---

## 2026-09-16 · M3 · Issue detectors and tiers

**Two new step types and one condition** (owner approved): `remove_characters
{columns, characters, where: leading|trailing|anywhere}` (uses `ltrim`/`rtrim` or
one `replace` per character, all bound) and `clear_values {column, condition}`
(blanks matching values, keeps the row; the condition must check the same
column). New row condition `digits_fewer_than {column, count}`.

**Issue contract additions** (owner approved): `examples` (up to 5 values),
`requires` (issue ids whose steps must run first, e.g. "read Age as numbers"
before "fill Age with the middle value"), and ask-tier questions as
`AskQuestion {prompt, choices[Choice]}` so they don't clash with M4's `Question`.

**Detector shape.** Each detector has `gather` (SQL against the read-only raw
table, returns evidence) and `decide` (pure). Detectors choose columns only by
profile role and patterns; column names are used only in copy and to name split
columns. Tests run detection with anonymized headers: only the name-recognized
Phone checks drop out. Issue, choice, and step ids are hashes, so re-running
detection gives identical ids. `today` is an input for determinism.

**Tiers.** safe = can't change meaning (case/space variants, extra spaces,
reading numbers/dates with clear evidence, exact repeats when an ID column
exists). likely = almost certain (combined columns, similar spellings, stray
"-" on phones, "k"/"M" amounts, near repeats, exact repeats without an ID
column, several date styles). ask = the choice changes answers (placeholders
in numbers, missing values, ambiguous date order, short phones, shared IDs or
contacts, out-of-range values, invalid emails).

**Owner decisions on defaults.** "N/A" in a number column is asked with
"Missing" recommended (left out of both the sum and the count), "Zero" as the
alternative. Out-of-range values recommend "Keep them". Every number column
gets a safe "Read as numbers" issue even when values are already plain, so
later answers use real numbers.

**Recommendations follow evidence.** Repeated IDs/contacts recommend keeping
one row when uniqueness ≥ 0.9 and "sharing is fine" when < 0.5 (the employee
file's 64 emails over 1,020 rows). Conflicting date evidence recommends a side
only with a 10× majority.

**Numbers with decimal commas.** The profiler's number pattern doesn't read
"3,50", so such columns look like labels. `numbers_as_text` also checks label
and ID columns and proposes reading them as numbers when ≥80% of values read
with either decimal mark and decimal-comma evidence exists.

**Dedupe fix (changes M2 behavior).** Rows whose compared values are all blank
are never repeats. Found when "keep one row per phone" set aside every row
whose short phone had been cleared. Replaces the M2 rule that blanks match.

**Standard step order** (`detectors/step_order.py`): remove characters/trim →
placeholders → map spellings → split → read numbers/dates → clear values →
dedupe → set aside → fill. `recipe_for(issues, accepted, answers)` pulls in
required issues and drops identical steps. Tests accept every issue and try
every ask choice on all three samples: nothing is blocked.

**Out of range covers numbers only.** Date ranges (years before 1900 or in the
future) need a date condition kind; deferred to `docs/ideas.md`.

**Messier sample.** `data/scripts/make_messy_variant.py` picks columns by profile
role and writes `data/samples/Messy_Employee_dataset_messier.csv` (seed 7):
case and space changes, restyled dates, `$85,000` / `$85k` / placeholder
numbers, 3% exact and 2% near repeat rows. A test re-runs it and compares bytes.

---

## 2026-09-16 · M4 · Questions and before/after comparison

**"Before" ignores case but not spaces** (owner decision, differs from the
CLAUDE.md example). Distinct counts, groups, and filters treat "Sales" and
"sales" as one value and "Sales " as another, the way Excel does. Why: tools
disagree (Excel pivots ignore case; Google Sheets, SQL, and pandas don't), and
"before" shouldn't look worse than the spreadsheet a user already has. The
cleaned answer ("after") merges all three.

| Tool | Sales vs sales | Sales vs "Sales " |
|---|---|---|
| Excel | same | different |
| Google Sheets | different | different |
| SQL, pandas, Power BI | different | different |
| TidyLab after cleaning | same | same |

**Other "before" rules** (all in `app/compare/before.py`, one test each, shown
to users via `RULES`): every uploaded row counts; blanks are skipped; only plain
numbers count (CLAUDE.md, owner-confirmed, so `$85,000` is left out); averages
divide by values read as numbers, so "N/A" is out of both total and count;
dates count only as `yyyy-mm-dd` or US `m/d/yyyy` (owner decision, like Excel
with US settings), which is how day-first dates get misread.

**One evaluator, two readings.** `evaluate(question, reading)` builds one
aggregate SQL query. `BeforeReading` reads the raw table; `AfterReading` reads
the cleaned table, or a recipe's step chain without building a table. Columns a
recipe left as text use the same spreadsheet rules after, so skipping a fix
never quietly improves an answer.

**Question generation** (cap 16, owner decision): row count; distinct IDs;
average and total for each number column (no total for percentages; totals of
columns like Age are kept for now); counts per category for the first 3
categories with 2–25 groups once spelling is ignored; the fullest number column
averaged by the first 2; count and average per month (≤ 24 months) or year for
each date column; distinct contact values; then remaining breakdowns.
Prominence: headline 1.0, averages/totals 0.8, breakdowns 0.6, trends 0.5,
other distinct counts 0.4.

**Contract additions** (owner approved): `Question.id` (hash of the spec),
`grain`, `prominence`; `Answer`, `GroupValue`, `GroupDiff`; `AnswerDiff.magnitude`;
`Issue.moves_answers`.

**Magnitude and impact.** Single values: relative change capped at 1; only one
side answerable is 1. Counts per group: half the sum of absolute changes in each
group's share of rows. Averages per group: row-weighted relative change, with
appearing/disappearing groups counting fully. Impact = prominence × magnitude;
ranked by impact, then prominence, then question order. Changes within 1e-9
relative are rounding noise.

**Groups that appear or disappear.** Groups are matched on the case-insensitive
key. A disappeared group whose key equals a surviving one once spacing is
ignored gets `merged_into` ("Active " → "Active"). Missing groups count as 0 for
counts and have no value for averages. Breakdowns show 20 groups plus "All other
groups"; queries return at most 1,000 groups and roll the rest up in SQL.
Within equal sizes, the blank group sorts last; equally common spellings are
labeled alphabetically.

**Issue impact from answers** (owner decision on ask tiers). Each issue compares
a recipe of only the issues it requires against one that adds its fix, over the
questions it could move (all questions when the fix removes rows). Ask-tier
issues take the choice that moves answers most. Issues that move nothing score
0.01 × share of rows affected. Scoring reads recipe chains directly and never
touches the user's cleaned table. Worked example: "N/A" in Salary scores 0.0188
(average moves 85,155.06 → 83,151.41 only when N/A means zero).

**Performance.** Every answer is one aggregate query; no table comes into
Python. Answers are cached by (reading key, question id): "before" once per
dataset, "after" per recipe fingerprint. A 300k-row file answers all questions
well within the test's limit.
