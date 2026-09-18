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

---

## 2026-09-17 · M5 · Attribution, unlocked questions, fast recompute

**Attribution is measured, not guessed.** For each answer that moved, the
recipe is re-run with one step turned off at a time; a step is credited when
the answer moves without it, and its contribution is how far the answer goes
back (the M4 magnitude, so it's comparable across questions). Turning a step
off also blocks the steps that depended on it, so a step is credited for what
its dependents did. Unchanged answers get no attribution at all
(`attribution_method: "none"`, owner decision): nothing moved, so there's
nothing to explain, and no queries are spent.

**Influence pass** (pure, no queries). A forward pass over the plan records
which columns each step had a hand in: the columns it writes, creates or drops,
plus everything the steps it reads from touched. A step that removes rows, or
feeds one that does, is marked as reaching every question, because row counts
move totals and averages everywhere. Only these steps are ever re-run for a
question. It errs towards including a step: a needless check costs one query,
while a missing one would credit the wrong step.

**Steps that only matter together.** When no single step explains a change, all
the relevant steps are turned off at once; if that moves the answer, and there
are 6 or fewer of them, each pair is checked and the pairs that move it are
reported with `together: true`. Example: trimming spaces and merging spellings
both fold "Active " into "Active", so neither matters alone. Beyond 6 steps the
whole set is reported as one group (see ideas.md — naming the smallest set
would read better).

**Cost.** Attribution is capped at 300 questions per comparison
(`MAX_ATTRIBUTION_QUERIES`). Questions are explained from the highest impact
down; a question that doesn't fit the cap falls back to `"estimated"`, listing
the steps that could have moved it (always a superset of the exact answer). The
cap is charged whether or not an answer is cached, so a comparison explains the
same things no matter what ran before it.

**Variant rows are built once.** Running a recipe's chain of steps costs far
more than an aggregate over its result (94 ms vs 1 ms on the messier sample), so
attribution works one variant at a time: build that variant's rows, ask every
question that needs them, move on. This took the messier file from 33 s to
1.9 s. These are the engine's own scratch tables, dropped at the end; the
cleaned table a user exports is still built from the recipe they kept.

**Answer key.** Answers are cached by (what the rows look like, question id).
The key hashes the base column names and the content of the applied steps in
order, excluding step ids and enabled flags, so a disabled step, a step that was
never added, and a re-added identical step all share answers. The apply
fingerprint still includes ids, because the change log records them.

**Unlocked questions.** A question is unlocked when the raw file can't answer it
at all and the cleaned one can. Columns the recipe created or retyped are
profiled from the cleaned rows (stored as text, so file rules apply), the
ordinary generator runs over them, and candidates are kept only if "before"
really can't answer them — so a question that merely moved is never dressed up
as a new one. Capped at 6, shown separately from changed answers. Examples:
splitting Department_Region unlocks headcount by Department and by Region;
"$1,299.00" read as a number unlocks the total Unit Price; store orders' Order
Date trend stays a changed answer, because some of those dates already read.

**Recompute.** Changing an ask-tier choice carries over every answer and
attribution the changed steps can't reach — matched by what steps do, not by
their ids, since each choice carries its own step objects — and only the
affected questions are asked again. The unlocked list is rebuilt only when a
changed step has a hand in a created or retyped column or removes rows.
Switching back to a previous choice costs nothing. A recomputed comparison
gives what a fresh one would, to the precision the app treats as real: adding
the same doubles in a different order can move the last bit.

**Contract additions** (owner approved): `StepContribution`,
`AnswerDiff.attribution_detail` and `.attribution_method`, `Question.origin`,
and `Comparison` (recipe, key, diffs, queries run, questions recomputed).
`AnswerDiff.unlocked` is now filled in.

**Small changes elsewhere.** Column stats and question generation take the table
to read, defaulting to the raw table, so the cleaned rows can be profiled the
same way. No new dependencies.

---

## 2026-09-17 · M6 · Review API and review UI

**Cards act on issues, not steps** (owner approved, a change from PLAN.md's
`POST /recipe/steps`). The screen shows suggestions and questions, so the API
takes `POST /issues/{id}/accept` (with a `choice_id` for a question) and
`POST /issues/{id}/reject`. Which steps a choice means, and the order they have
to run in, stay on the server with `recipe_for`'s ranking. The recipe panel
still edits steps directly: `PATCH` to turn one off, `DELETE` to remove it,
`POST /recipe/undo` to step back.

**The recipe is the only record of what will happen.** An issue is "applied"
when its steps are in the recipe, "rejected" when the user turned it down, and
"available" otherwise — worked out on each request instead of stored, so the two
can't drift apart. The session keeps only what the recipe can't say: which
answer was chosen, which suggestions were turned down, and which issue each step
came from.

**Certain fixes are applied on arrival** (owner decision). The first request for
the issue list, or for the recipe, seeds the recipe with every safe-tier issue's
steps, and they show as "Already fixed" with an undo. Seeding isn't a user edit,
so it leaves nothing to undo to.

**One request draws the screen.** The issue list carries the recipe with it, and
every action answers with the new recipe, so a click costs one round trip.
Detection and impact scoring take 0.5–2.3 seconds on the samples; they run once
per file, on the first request that needs them, behind a loading state.

**Steps are described, not named.** `app/steps/copy.py` turns a step into a
sentence: "Keep one row per Employee_ID (the first one)", "Clear 'N/A' and '-'
in Salary". A blocked step shows its plain reason in place of its counts. Tested
against a jargon list.

**Previews come from the engine, not a re-implementation.** `app/preview.py`
builds the recipe with and without the steps in question, joins the two on the
row id, and returns up to five rows where something differs, for up to six
touched columns. Rows that would be set aside keep their values and are marked,
rather than reading as changed. The two sides are built as separate statements
so their bound parameters can't collide.

**Validation errors get the same shape as everything else.** FastAPI's field
paths mean nothing to a business user, so a request that doesn't validate comes
back as `{code: "invalid_request", message: …}` like every other error.

**The file lives in the address** (owner decision): `?dataset=<id>`, so a
refresh doesn't lose the work. No router library; the app has two screens.

**Frontend state.** TanStack Query holds server state: `['issues', id]` for the
list and `['preview', id, …]` per card, fetched only when a card is expanded.
Actions write the returned recipe into the cache and re-read the list. A card's
failure shows on that card; a recipe-panel failure shows under the panel.
Queries don't retry a 4xx — a file we can't find won't appear on a second ask.

**Fixed while checking it in the browser:** `count_if` answers NULL when nothing
it looks at is true or false, which crashed the date detector on a file whose
dates are all year-first, and would have crashed a preview of a file with column
names and no rows. Both now `coalesce` to 0, with a test each.

**Downloads and answer impact wait for M7** (owner decision), so the review
screen stays about reviewing.

---

## 2026-09-17 · M7 · "What changed" UI

**The comparison is a view over the engine, not a second implementation.**
`GET /datasets/{id}/compare` calls the M5 engine and turns each `AnswerDiff`
into what a card needs. No number is computed in the API layer; `kind` is the
only thing it decides (no `group_by` → headline, a grain → trend, otherwise a
breakdown). The seven "before" rules are sent with the response, straight from
`before.RULES`, so the explainer can't drift from the rules the answers used.

**One screen, two tabs.** Review and What changed sit under the same file
header and share the recipe panel (owner decision), so "why" can light up a
step without navigating, and a decision can be changed while its effect is on
screen. The decisions strip at the top of the comparison lists the questions
already answered as segmented controls.

**Three layers keep a choice change cheap** (the acceptance criterion is "within
a moment"):
1. `RecipeResponse` now carries `recipe_key`, and the client keys its comparison
   on it. Two recipes that make the same rows share a key, so going back to a
   previous answer is a cache hit with no request at all.
2. On the server, `engine.recompute` carries over every answer and attribution
   the changed steps can't reach. Switching "N/A in Salary" re-answers the
   Salary questions and leaves the rest alone.
3. `keepPreviousData` holds the old cards on screen while the new ones arrive,
   so nothing jumps.

**Charts** (Recharts, a new dependency, named in CLAUDE.md). Paired bars with a
negative `barGap`: the before bar sits faintly behind the after bar, like a
shadow of where the answer was. Up to 8 groups, biggest first, trends in period
order. Each chart is preceded by a visually hidden table of the same numbers.

**A merged spelling gets no bar.** When "Sales " folds into "Sales", drawing it
collapsing to zero would say those rows vanished, which is the opposite of what
happened. It becomes a footnote — "'Sales ' is now counted with 'Sales'" — and
its rows show up inside the target's bar. Groups that really lost their rows do
get a zero bar, footnoted. When every group in a breakdown is new (a column that
didn't exist), one line says so rather than naming them all.

**A missing count is zero; a missing average is nothing.** For counts, "no rows"
really is 0 and is drawn. For averages there is no value at all, so no bar is
drawn — a bar at zero would be a different, false claim. This is why the group
values are nullable rather than defaulted.

**Downloads** live in the recipe panel, on both tabs (owner decision), and go
through fetch so a failure shows our wording rather than raw JSON. The server
names the file (`Messy_Employee_dataset (tidied).csv`) with an RFC 5987 header
so spaces and accents survive. Both use the M2 export code, routed for the first
time here.

**Empty states.** Nothing applied yet → a pointer back to Review. Cleaning
changed nothing → "Your answers came out the same either way," with the number
of questions checked, because that's a real outcome on a tidy file, not a
failure. The summary line above it doesn't repeat the count.

**Deferred to M8:** all wording here is template text; AI rewrites it later.

---

## 2026-09-17 · M8 · AI layer

**Nothing here is required.** With `LLM_PROVIDER=none` — the default — the whole
app works and the entire test suite passes without a key. Every AI test uses a
fake provider, so no test has ever made a network call.

**Asked for after the rules, not instead of them** (owner decision).
`GET /datasets/{id}/ai` is a separate request the screen makes once the
rule-based review is already on it. The review is never slower, and a model that
can't be reached costs nothing but one quiet line.

**A model proposes; the code decides.** A proposed fix has to survive all of
this or it's dropped: it parses into the reply schema (unknown fields refused);
every column it names exists; every step is a real step type whose arguments
validate against that step's own model; the step compiles where it would run;
every value it matches on actually occurs in that column (one count query each);
and it changes something. How many rows a fix touches is **counted here**, by
running the step through the M7 preview machinery — never taken from the model.
Whatever survives is built with the detectors' own `IssueBuilder`, so it gets
stable ids and behaves like any other issue from then on.

**A model never applies anything.** Proposed fixes are capped at the `likely`
tier whatever confidence they claim (owner decision), so they're reviewed like
every other suggestion, with a "Suggested by AI" chip. `Issue.source` says where
a card came from; `DetectorName.AI_SUGGESTION` says which detector didn't.

**No new numbers.** A rewrite may change how something is said, never what it
says. Every figure in a rewritten title or label has to appear in the text it
replaces, compared after normalising how it was written — "1,020" matches
"1020", "2.50" matches "2.5", but "about 12%" against an input that never
mentioned 12 is refused. Jargon and markdown are refused too. Rejection is per
item, so one bad title doesn't lose the rest.

**The payload is a value, not a promise.** `app/ai/payload.py` builds one dict —
column facts, at most five example values each, at most 20 sample rows with
every value cut to 80 characters — so what a model may see is something a test
reads rather than something the code claims. Nothing else ever reaches a
provider: not the file, not the recipe, not a key.

**Providers are one POST each** (owner decision: raw HTTP over two SDKs), behind
a three-method interface with `NoProvider` as the default. The provider is a
FastAPI dependency, so a test stands a fake in its place without a key existing.
`httpx` moves from a dev dependency to a runtime one.

**Prompts are files, versioned**: `app/ai/prompts/<name>.v1.md`, loaded by name
and version, logged by both. One retry when the service stumbles; none when the
reply is malformed, because the model already had the schema.

**Logging says what happened, never what was said**: prompt, version, provider,
outcome, latency, and counts of what was rejected and why. A test asserts no
sample value reaches the log. `app/main.py` now configures the `tidylab` logger,
because the server configures its own and ours was going nowhere.
