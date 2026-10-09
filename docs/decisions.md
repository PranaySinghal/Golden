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

---

## 2026-09-18 · M9 · Story, a harder dataset, and an end-to-end test

**The story is parts, not a sentence.** A `Story` is sentences of `StoryPart`s,
and only a part carrying a `question_id` may hold a figure. That makes "the
story contains only numbers from computed diffs" something the type enforces
and a test can check character by character, rather than a promise about
wording. On screen each figure is a button that scrolls to the card it came
from.

**What it chooses to say.** Rows first when the row count moved, then the
answers that moved *with a figure* (whatever their rank — a number says more
than "this changed"), at most one breakdown ("came out differently, group by
group", with no figure, because a breakdown has no single number), and at most
two answers the file couldn't give at all before, carrying their new value.
Nothing to say means no panel, which is what the cross-tab file gets.

**AI wording is held to a stricter rule than other copy** (`story_wording.py`):
every figure in a model's story must match a value the engine computed, and is
matched back to the answer it belongs to — the check and the link are the same
step. One unmatched figure rejects the whole story, because half a story isn't
worth showing. The templates then stand.

**Golden files now cover four fixtures**, including the cross-tab, across five
suites: profile, issues, answers, attribution, and the new story. `SAMPLE_FILES`
in `tests/conftest.py` is the one list; a test asserts every file in
`data/samples` is a fixture and every fixture has golden files, so adding a
sample without pinning it fails.

### The generality check: `1.-Badly-Structured-Sales-Data-1.xlsx`

A pivot export, not a table: two header rows, a stub `Order ID` column,
subtotal columns, and a sparse 825 × 16 matrix. **Nothing crashed**, at any
stage, in either header mode. What it did reveal:

**Fixed here**
- *Fifteen near-identical questions.* The missing-values detector asked "what
  should happen to rows with no X?" once per column, including columns that are
  96% empty — where "fill 800 blanks from the 30 values that are there" is bad
  advice, and fifteen of them bury everything else. It now skips columns flagged
  mostly-blank: 30 issues became 16, and the one remaining question is about the
  fullest column. The three original fixtures are unaffected.
- *Float noise in the column summary.* A range read `2.214000000000000 –
  20802.17299999999`, because the profile formatted decimals with `repr`. It now
  uses ten significant digits: `2.214 – 20802.173`. Only this file was affected;
  the other fixtures' values were already clean.

**Left alone, deliberately**
- The file stores `10.272000000000002` where Excel displays `10.272`. Ingest
  keeps what the file says, because the raw table is the record of the upload.
- "Read X as numbers" clears a stray non-numeric value (the leftover second
  header row). That's what the step does, it's visible in the preview and the
  change log, and it's the honest behaviour.
- Everything that would need a new capability — unpivoting, two-row headers,
  spotting subtotal columns, grouping the fifteen safe cards — is in
  `docs/ideas.md`. M9 is not the place for new features.

**Playwright** (`frontend/e2e/flow.spec.ts`) drives the whole circle in one
spec: upload, accept a suggestion, answer a question, read the story, follow a
figure to its card, open "why", and download the cleaned file — asserting the
saved name and that the split actually added columns. Its config starts both
servers itself with `LLM_PROVIDER=none`, so the run needs no key and no manual
setup. CI wiring is M10.

---

## A model's story is asked per recipe, not per file

A review of M9 found the AI story was unreachable in the running app. It was
bundled into the one-shot enhancement, which the review screen asks for at
mount and the server caches for the life of the file. At that moment only the
safe steps have run, so nothing has moved yet — on the employee file the
comparison is literally "every answer matched" — and a story-less result was
cached forever. The prompt, its validation and the whole `story` field were
dead code that no test touched, because the tests called the pure functions
directly.

The rest of what a model offers describes *the file*: which fixes the detectors
missed, how to word an issue. That doesn't change, so asking once is right. A
story describes *the answers*, and those move every time the user accepts,
answers or undoes something. Those are two different lifetimes, and they can't
share one cache.

So `enhance` went back to fixes and wording only, and `tell_story` became its
own call, cached on the session per `recipe_key`. `/ai` still answers with
everything in one response; the client keys its query on the recipe and keeps
the previous reply on screen while a new one is fetched, so improved wording
never flickers back to templates.

Three smaller things fell out of the same review:

- *A story now says which rows it describes.* `Story.recipe_key` carries the
  comparison it was written about, and the screen shows a model's story only
  while that key still matches. Otherwise the template story — which is always
  computed with the cards — wins. Without this, changing a choice left a story
  quoting figures the cards below it no longer showed.
- *A digit in a column name is not a figure.* Every number in an AI story has
  to be one we computed, and anything else throws the story away. But the check
  read digits anywhere in the sentence, including inside a quoted question — and
  this repo's own cross-tab fixture has columns called `column_3` and
  `column_10`. Quoting the question rejected the story. Names that contain a
  digit are now excused, and only those; the sentence around them is still
  checked.
- *Nothing moved means nothing to ask.* The story call was gated on having
  answers rather than on any of them having changed, so a file cleaning didn't
  move still asked a model to write three or four sentences about an empty
  list. It's also why the accept-set now covers only the answers that changed:
  the model is shown those, and a figure from one it never saw is a
  coincidence, not a citation.

**Unrelated, fixed in passing:** `npm test` was red on `main` — Vitest was
picking up the Playwright spec and failing the suite. It now runs only
`src/**/*.test.{ts,tsx}`.

---

## Saved steps, and what a step's identity is

"Download the steps" produced a file nothing could read back. The engine to
replay one — `steps/replay.py`, with compatibility checks, near-miss column
name suggestions and an all-or-nothing guarantee — was complete and tested, and
no route called it. That loop is now closed at both ends: steps can be attached
to an upload, or picked from the recipe panel on a file already open.

**A step's identity is what it does, not which object does it**
(`steps/identity.py`). This is the change everything else rested on. Step ids
are stable rather than unique: `IssueBuilder` derives them from the detector, a
kind and the column names, so next month's file produces *the same ids* as the
recipe saved from last month's. `recipe_ops.add_step` refuses a duplicate id,
which meant the safe-seeding pass in `prepare()` raised on the first
`GET /issues` after any replay — a 422 where the review screen should be. The
same mismatch ran the other way too: a model's fix carries an id detection
never generates, so a card whose work the recipe plainly did would read as
still available.

So `state_of`, `_add_steps`, `_remove_steps` and the preview path all ask "does
the recipe already do this work?" rather than "is this id present". The key
(`model_dump_json(exclude={"id", "enabled"})`) was already written twice, in
`compare/engine.py` and `ai/fixes.py`; both now point at the one definition.
`enabled` stays excluded so a step switched off still counts as answered, which
is how the panel has always read.

Three consequences worth stating:

- **`state_of` hands back the recipe's ids**, not the detected issue's, so the
  panel can be pointed at steps that really exist. Nothing read that field
  before; now it means something.
- **Two cards proposing identical work both read as applied.** That is true —
  the recipe does the thing each describes — and `step_order.recipe_for` has
  always deduped them into one step for the same reason. Removal is where it
  would do damage, so `_remove_steps` leaves alone any step `step_origin`
  attributes to a different card.
- **Safe seeding still runs after a replay**, so the recipe can end up a
  superset of the one downloaded: this month's file may have a certain problem
  last month's didn't. The banner says so rather than implying an exact copy.

**A refused recipe answers 200, with the reasons as a list.** The error handler
serialises `{code, message}` only, and `RecipeIncompatibleError` flattens its
problems into one run-on sentence — but the list is the product: "every reason,
not just the first" is what makes a refusal actionable. There's precedent in
`POST /recipe/undo`, which answers 200 with `can_undo: false`. `applied` is a
required boolean in the generated types, so the screen can't forget to branch
on it. Genuine 4xx still covers what isn't about the recipe's content.

**A bad recipe never costs a good upload.** The dataset is created first and the
steps are applied after, so a refusal leaves a perfectly usable file with a note
attached. `replay_recipe` builds nothing when it refuses, so there is no
half-cleaned state to explain.

**Replacing the recipe is one undoable edit** (`recipe_ops.replace`), so using
saved steps on a file with work already in it is reversible by the panel's
existing "Undo last change" rather than being the one action you couldn't take
back (CLAUDE.md principle 5).

Not carried: a recipe records accepted steps, not decisions. A suggestion
turned down last month, and an ask-tier answer meaning "leave it alone", leave
no trace in the file and come back as fresh questions. Carrying them needs a
format v2 and is in `docs/ideas.md`.

**Update — saved steps are attached at upload only** (owner decision). The
panel's "Use steps from a file" and `POST /recipe/replay` are gone. The panel
sits on the Review and Compare tabs, so it offered to throw away reviewed work
for a file's worth of someone else's; the one honest use, "I forgot to attach
them", is served by uploading again with the steps attached. `recipe_ops.replace`
stays: the upload path still replaces the safe-seeded recipe in one undoable edit.

**Merged-spelling notes fold behind a toggle.** One line per spelling ran to a
dozen under a chart and buried it. The short summaries (new groups, emptied
groups, hidden groups) stay visible; the per-spelling lines sit behind
"Show the N spellings now counted together", styled like "Why?".

---

## A split replaces its column only when every value splits

A split used to keep the original next to its parts (`keep_original` defaulted to
`True` and the detector never set it), so the cleaned file carried
`Department_Region` beside `Department` and `Region`. The detector now sets
`keep_original=False` when *every* filled value splits into exactly two parts —
the count it already takes (`two_part == filled`). If even one value doesn't, the
original stays: that row's parts would be partial, and the original is the only
place its whole text is shown. The raw table is untouched either way, and the
step undoes like any other.

**Questions about a replaced column drop out** (`compare/retired.py`), in both the
answer cards and issue ranking. Otherwise a question like "rows per
Department_Region" reads "Couldn't be answered" after cleaning, which diff scoring
treats as the biggest change there is — so the split would also have jumped to the
top of the review list for removing a column, not for changing an answer. The
parts' own questions still arrive as unlocked ones. The rule is "a column the raw
file has and the recipe's output doesn't", not anything about splits or names.

Saved recipes from before this carry an explicit `keep_original: true`, so they
replay exactly as they were.

---

## M10: one container, a live link, and a ceiling on model calls

**The reviewer's ways in, easiest first:** a live link (Render), one `docker run`,
or `./run.sh` with `uv` and Node. All three run the same thing: FastAPI serving
the built page beside the API on one port.

**FastAPI serves the frontend** when `STATIC_DIR` points at a build
(`api/frontend.py`). A catch-all registered after every API router answers with
the file if there is one and the page otherwise, so reloading any screen works.
`/api/…` paths nothing answers stay JSON 404s rather than becoming the page. It
is left out of the OpenAPI schema, so the generated types don't change. Unset in
development, where Vite serves the page and proxies `/api`.

**Render, free tier** (owner's choice for a take-home link). Vercel doesn't fit:
each file lives in one process's memory for a whole review, uploads go to 50 MB,
and comparisons can run long — serverless functions are stateless between
requests, cap request bodies at a few MB, and time out. The free instance sleeps
when idle (first load ~30–60 s) and has 512 MB, so `render.yaml` lowers
`MAX_UPLOAD_MB` to 25 and `MAX_DATASETS` to 4. The Dockerfile is host-neutral;
moving hosts is one config file.

**Model calls have a per-server ceiling** (`LLM_MAX_CALLS_PER_MINUTE`, default
20; `ai/limiter.py`). Past it the call fails as `RateLimitedError`, a kind of
`ProviderError`, so the existing fallback serves the rule-based wording and the
AI panel shows its usual "couldn't answer" note — quiet, by owner decision. It is
not retried (a retry would only spend more of the budget) and is logged as
`outcome=rate_limited`. One bucket on `app.state`, so every request draws from
the same budget; with no service configured there is nothing to limit.

**Upload edge cases were audited, not changed.** Empty file, header only, one
column, no header, Latin-1, UTF-16, an all-blank column, a PDF, binary named
.csv, a broken .xlsx and an over-limit file all either open and review cleanly
or answer with a plain-language message.

---

## A summary of the file before any cards (demo step 2)

The demo promised "what the data is about, its size, and the main problems" right
after upload; the page showed only a name and "1,020 rows · 12 columns".

**What each row holds** is one sentence from the column roles
(`profile/describe.py`): "Each row has an ID ("Employee_ID"), a date, 2 numbers,
6 categories and 2 kinds of contact info." Same words as the column table (ID,
category, number, date, contact info, text). It **never guesses a subject** —
"a list of employees" would be read off the column names, which is exactly the
dataset-specific inference principle 1 rules out, and would read differently if
the same file had other headers. A test holds every word outside the quoted ID
name to a fixed vocabulary, so a leaked column name fails it. Rule-based, so it
is complete with no key. On the cross-tab file it says "an ID and 15 numbers",
which is honest about what that file is.

**Main problems** are the first three cards of the list the server already
ranked by impact (`rank_issues`), each a link that scrolls to and lights its
card. No second ranking: the header and the list can't disagree.

**The second dataset now runs the whole flow in Playwright** (`store_orders.csv`:
upload → summary → main problem link → accept → What changed → download),
asserting on page structure only, never its column names.

The example-rows table said "Now / After"; it says "Before / After", like the
rest of the app. Inside "Why?" on the What-changed tab, "Now" read as the cleaned
value.

---

## Canvas: adding columns, and ideas for which ones (after M10, owner-requested)

A third tab beside Review and What changed. The owner asked for it after the
feature freeze, so it sits outside M1–M10; `PLAN.md` is the owner's to update.

**A new column is a recipe step, `add_column`** (owner-approved change to the
Step union). It holds a name, optional text for every row, and optionally the
column it goes after. Being a step is what makes it undoable, part of the
download, and part of a saved recipe, with no second mechanism. It ranks last in
`step_order.RANK`, so a column the user adds can never change what an earlier
step compares (a whole-row repeat check, say). `ChangeSpec.source_column` became
optional for it: a column made from nothing has no "before". A blank column logs
no changed cells; placeholder text logs one per row, traced to the step.

**Blank or one placeholder text only.** No formulas, no pasted values: both were
offered and turned down for this version.

**Ideas come from two places and are one list** (`app/semantic/`). The built-in
ones always answer, so the tab is complete with `LLM_PROVIDER=none`. With a
model configured it is shown the header, what each column holds and the first
**five** rows (`suggest_columns.v1`), and asked what the file is about and what
to add. Its ideas are checked one at a time: not already a column, not offered
twice, no jargon or markdown, and **no figure that wasn't in what it was shown**,
in the name, the reason, the placeholder or the summary sentence. Built-in ideas
fill whatever space is left, up to five. The model is asked once per file; the
list is filtered against the table on every request.

**The built-in ideas read column names, and that is a deliberate exception.**
The file summary refuses to guess a subject from headers. Here there is no other
evidence: "this lists organisations" isn't visible in the values. So the words
are general ones (company, vendor, city, price), the same kind of hint
`profile/name_hints.py` uses, and value evidence is used where it exists
(contact columns, currency patterns). A wrong guess costs one unhelpful
suggestion; it never touches data. Three ideas fit any table, so a file that
gives nothing away still gets three.

**A model can't add a column through "suggested fixes".** `ai/fixes.py` rejects
`add_column`: a fix repairs what's there, and new columns are the user's call.

**Nothing is fetched.** An idea can say where its values could come from one day
("a stock price service"); the screen says that isn't connected and the column
starts empty. Connectors are in `ideas.md`.

**Known limit:** the shared jargon check matches inside words, so a model's idea
called "Forecast" is dropped for containing "cast". It falls back to a built-in
idea rather than showing anything wrong.

---

## Connectors: columns looked up from outside services (after M10, owner-requested)

A "Connectors" item beside Home opens a side panel. Three connectors: postal
code → latitude/longitude (Zippopotam.us), company name → stock symbol (the
SEC's public list), stock symbol → latest price (Finnhub). All three are
`none` by default, so the app still sends nothing anywhere out of the box.

**Two exceptions to CLAUDE.md, both owner-approved.**
- *Principle 3 ("AI sees metadata, not data") is about models; connectors do
  send real cell values.* Only the different values of the one chosen column,
  only after a consent prompt that names the service and what is sent, once per
  connector and file. Company names are the exception to the exception: nothing
  from the file is sent, because the SEC list is downloaded whole and matched
  here.
- *"Nothing outlives the server process" no longer holds for looked-up
  answers.* `connectors/cache.py` is one SQLite file holding (provider,
  normalised value, answer, fetched-at) and nothing that says whose file a value
  came from. A test pins its columns. `./run.sh` and the Docker image point it
  at a file under the home folder; anywhere else it is in memory.

**A lookup is two new steps, and compiling them never touches the network.**
`enrich_column` joins the table to a *snapshot* of answers stored in the
session's database (`lookups.enrichments`), by the same spelling-blind key the
values were looked up under. The same recipe and snapshot always give the same
rows. Looking up again makes a new snapshot and swaps the step's id for it, so
it is an ordinary edit: undo brings yesterday's prices back. `resolve_match` is
the user's pick for one ambiguous name. A saved recipe keeps what to look up
and drops the snapshot, on the way out and on the way in, so a recipe replayed
on a new file fetches nothing until the user agrees there.

**The answers table has its own schema.** It first went in `work`, and two
existing tests ("nothing was built for a refused file") failed, rightly: `work`
means "derived from the raw file".

**Looked-up columns stay out of the before/after.** `volatile_columns` tracks
them and anything made from them; they are never profiled for new questions,
and the recipe key ignores which snapshot a step points at, so a refresh
doesn't re-ask the story or move an answer. The one way a looked-up value could
reach an answer is a step that sets rows aside based on it; that is detected
("leaks") and the key then follows the snapshot.

**Detection reads values, with names as a tie-break** (`connectors/detect.py`):
- Postal codes: 90% of values fit a country's format, and for all-digit formats
  the values repeat or start with zero (ids don't). Four-digit codes need the
  name to agree, because years look the same.
- Companies: a fifth of values end like a company (Inc, Ltd, LLC…), or a third
  are on the SEC list once we hold it.
- Stock symbols: 90% are one to five capitals *and* half are on the list.
  Without the list, the name has to agree: "CA, NY, TX" has the same shape.

**Country is a required choice on the Enrich card**, not a card in Review: five
digits fit six countries, nothing is sent until one is picked, none is
preselected. Ambiguous company names *are* ask-tier cards in Review, one per
name, each choice a `resolve_match` step, with "Leave it empty" always offered
and nothing recommended.

**A failed cell is empty and says why.** Found, not found, several matches,
rate limited, timed out, service unavailable, not looked up yet. Only "found"
and "not found" are cached; a busy service is asked again next time.

**One run is bounded three ways and runs inside the request.** At most
`CONNECTOR_MAX_VALUES_PER_RUN` values are sent (cached answers don't count),
each service has its own per-minute budget, and a run stops after
`CONNECTOR_RUN_SECONDS`; whatever is left is "not looked up yet" with a button
to carry on. The plan said "background job with progress"; with the run
bounded this tightly a plain request is simpler and loses nothing but a
progress bar. The session lock is not held while services are asked.

**Prices: one fetch per symbol per trading day**, fresh if fetched since the
latest weekday 09:30 New York. No holiday calendar: on a closed day Finnhub
returns the last close with its own timestamp, and that timestamp is what
"Price as of" shows. Stale prices are marked; refreshing takes a click.

**Known limits.**
- A postal-code column of five digits can already have been read as numbers by
  the "numbers as text" fix. Lookups read such a column by how its values are
  written, but leading zeros are gone by then. The fix shouldn't fire on postal
  codes at all; logged in `ideas.md`.
- Company matching is exact after spelling is normalised. "Google" does not
  find Alphabet. No fuzzy guess, by design.
- The Finnhub and SEC parsers are tested against the documented reply shapes,
  not live calls. Zippopotam's was checked against the live service.

**Each service is switched on per file, by the user** (added on request). A
service the server has set up still starts off for every new file; the user
turns it on in the Connectors panel once a file is open. Before a file is open
the panel only lists what is available. Switching on sends nothing, and the
consent prompt still comes before each connector's first lookup. Switching off
keeps columns already looked up and stops further lookups. Three states, kept
apart on purpose: set up (the server's operator), on for this file (the user),
agreed to send (the user, per connector, seeing what goes).

---

## AI-filled columns, and one cell per looked-up answer (owner-requested)

**A model may now supply cell values. This is a deliberate exception to two
principles.** Principle 2 says AI proposes and code executes; here a model's
answer goes in a cell. Principle 3 says a model sees at most 20 rows; here it
sees every different value of one chosen column (and up to two beside it). The
owner asked for it, knowing both. What keeps it honest:
- **Text only.** A bare number, amount, count or percentage is refused, so
  "every number comes from the engine" still holds.
- **"Not sure" is an answer**, and anything that fails a check becomes "not
  sure": empty cell, reason shown. Never repaired, never guessed.
- **Label columns have a closed list**, proposed with the suggestion. An answer
  off the list is refused. One spelling per label.
- **Preview before fill.** Eight answers are shown first; nothing is added
  until the user says to fill the rest.
- **Marked unverified** on the column heading and in the recipe step. The mark
  is *not* in the downloaded file; see `ideas.md`.
- **Never in the before/after.** It reuses `enrich_column` (connector
  `ai_fill`), so `volatile_columns` already keeps it out of every answer, undo
  works, and a saved recipe keeps what the column means but not the answers.
- **Asked for like any connector**: off per file until switched on, consent
  before the first send, cached so the same question isn't paid for twice.
- **A cell is data, never an instruction.** The prompt says so; more to the
  point, a reply can only ever become a short text value that passed the checks.

**Which suggestions can be filled** is decided when they are suggested
(`suggest_columns.v2`): the model names the one column the answer depends on
and the kind (label, text, website, or none). A plan that doesn't hold together
(no such column, a label column with one label) is dropped and the suggestion
stays a plain empty column. Built-in ideas are never fillable.

**Model: Claude Haiku 5.5 by default** (`claude-haiku-5-5`), at low effort.
Estimated two to three cents per thousand different values from list prices;
not measured. This also became the default for the existing wording prompts.

**The Claude provider was broken and nobody had noticed.** It sent
`temperature: 0.2`, which current Claude models reject, and the default model
id was a generation old. It had only ever been exercised with fakes. Fixed:
no temperature, low effort, room for the model's own working-out in the output
limit. Structured-output mode was considered and left out: our reply models
carry length limits a strict schema may refuse, and that can't be tried
without a key. Replies are parsed and validated as before.

**One cell per looked-up answer** (replaces the two-column shapes above):
- Postal codes give one "Geolocation" cell, `34.0901, -118.4065`.
- Prices are text with a dollar sign, `$261.74`. Finnhub's quote carries no
  currency; symbols from the SEC list are US listings, so dollars are assumed.
  A foreign symbol typed into a ticker column would be mislabelled.
- "Price as of" is gone as a column. The time is kept with each answer and
  shown on hover on the column heading, with "out of date" when stale. The
  downloaded file no longer carries it.
- The answer cache is versioned (`ANSWER_FORMAT`), so answers stored in the old
  two-value shape are asked for again rather than shown wrongly.

**Jargon in labels is matched on whole words.** The shared check matched inside
words and threw out "Finance" for containing "nan". Fixed for label lists only;
the wording check is unchanged (still in `ideas.md`).

---

## Less on screen: a recipe panel that hides, and one card per connector (owner-requested)

**The recipe panel is "Recipe: steps performed" and can be hidden.** Its heading
is a button. Hidden, it becomes a slim bar above the page (name, step count,
both downloads) and the page takes the full width. The downloads stay in reach
on purpose: hiding the steps must not hide the way out. "Why?" on What changed
points at steps in this panel, so it opens the panel again.

**The Connectors panel is one card per service.** Before, the switches sat in a
list at the bottom and the Enrich cards at the top, so using one meant scrolling
between them. Now a card holds the service's symbol and name, its switch, where
it stands for this file ("Found in 'Postcode' · 412 values", "Nothing to look
up in this file", "Added 'Geolocation' · 380 found"), and its action. Services
with something to do in the open file sort first. The consent prompt opens
inside the card it belongs to.

**Detail moved behind the info button, not removed.** What a service adds, who
runs it and exactly what is sent used to be printed on every card. They are now
one hover away on each card and on each consent prompt. The consent prompt
itself is one sentence naming the column, the count and the service. The owner
chose the shorter wording; the facts a user needs before agreeing are still
reachable before they agree.

---

## What broke on eight new files (stress test, owner-requested)

Eight seeded files in `data/eval/`, each built from known-clean data with
specific problems put in, so there is an answer key (`make_files.py`).
`evaluate.py` scores the app against it through the same code a browser request
uses; `--offline` sends nothing anywhere. The offline half is in the test suite
(`tests/test_eval_files.py`). The files: listed companies; UK customers;
German orders (semicolons, decimal commas, Windows-1252); a survey in Excel
with title lines; a 70-column file of look-alikes; six rows with no header;
51,000 events; and a tidy file.

**First run: 13 of 19 injected problems found, three connector offers on
columns that were nothing of the kind, and two slow paths. Fixed:**

- **"1.234,56 €" was not a number.** The number patterns allowed a currency
  sign before a number only. Now after it too (`steps/compile.py`,
  `profile/patterns.py`, `detectors/numbers_as_text.py`).
- **"08933" became 8933.** A postal-code column was a "measure" unless 5% of
  its values started with zero, and was then read as numbers. One leading zero
  in a column where every value has the same number of digits is now enough to
  call it codes (`profile/roles.py`).
- **A phone column typed several ways wasn't a phone column.** 75% formatted
  and 25% bare digits fell under the 80% bar and became free text, so no phone
  check ran. Formatted plus bare digits now counts when at least half are
  formatted.
- **"0207" was never too short.** "Short" was only measured against a column's
  usual length, and numbers from two countries have none. Fewer than seven
  digits is now too short anywhere, with its own wording.
- **Batch numbers and round quantities were offered as postal codes; "Garden
  Group" as a company.** All-digit codes with no leading zero and no telling
  name must now behave like addresses (at least eight different ones, spread
  across areas, not round). "Group", "Co", "Company" and "Holdings" alone no
  longer make a company; "Inc", "Ltd", "LLC" and the like do. Cost: three
  postal codes in an unnamed column are no longer offered. Wrong offers were
  judged worse than a missed one, since a name ("Zip") still settles it.
- **Nine seconds to rank 129 cards on 150 rows.** Impact scoring re-asked every
  question for every card. It now has a ceiling (600 questions, the samples use
  at most 228), spends it on the cards touching the most rows, and ranks the
  rest by rows touched.
- **Date-format search on 51,000 rows** tried every format against every value,
  several times over. Formats are now chosen on an even 5,000-row sample and
  counted once over the whole column. Columns under 5,000 rows are unchanged.

**The live run found the biggest one: no fix a model proposed had ever
survived.** The prompt named the step types but not their arguments, so every
proposal was thrown away as malformed. `suggest_fixes.v2` lists each step's
arguments. With it Claude found things the rules can't: the survey's title
lines sitting among the answers, "No comment." used as a blank, companies
listed twice with different details. Two follow-ons:
- A model reads the file as uploaded, so it re-proposed fixes the certain rules
  had already applied. Proposals are now judged on the table as it stands after
  those (`ai/fixes.py`); one that changes nothing there is dropped.
- A model may no longer be asked to fill a column from a number or a date
  ("Salary band", "Day of week"). That is arithmetic, and the engine's.

**Measured, with the real services (Claude Haiku 5.5, Zippopotam, Finnhub):**
- AI fill: industry 44 of 45 companies (the miss: Meta as "Media"), website 45
  of 45, country from postcode 13 of 13, product category from German product
  names 12 of 12. No "not sure" on these well-known inputs.
- Prices: 45 of 45 symbols. Postal positions: 10 of 10 US and 8 of 8 UK checked
  codes within 25 km.
- Company to ticker was scored against a stand-in list (the SEC list needs a
  contact string that isn't set): 67 of 68 rows, the miss being a deliberately
  mangled "Amazoncom Inc", left blank rather than guessed.

**Open, and the owner's to decide:**
- **Title lines above the header row.** The first row is always the header, so
  the survey's columns are "column_3" and its cards are unreadable. Skipping
  leading title lines changes which rows count as data. The test for it is
  marked as an expected failure.
- **A hundred cards on a wide file.** 62 sparse columns raise 62 "rows have no
  …" questions. Nothing groups or caps them.
- **Zippopotam's German data is wrong for five of eight major cities** (Köln,
  Hamburg, Dresden, Leipzig, Frankfurt come back with another field where the
  latitude should be). The range check catches it and the cell says "not
  found", now remembered as such instead of "try later".
- **A column mixing two countries' postcodes gets no offer**, because no single
  country's format fits 90% of it.
- **AI on the 70-column file took 47 seconds and both the fix and wording
  prompts gave up.** The page doesn't wait for it and keeps its own wording.

**The open questions above, as the owner settled them:**
- **Title lines are skipped.** At the very top of a table at least four
  columns wide, a line filling one or two cells (and no more than half the usual
  number) is a title, not a header (`ingest/header.py`). The lines are kept on
  the file summary and shown with the other reading notes, so nothing vanishes
  silently, and choosing "first row is data" reads the file exactly as it is.
  The survey file now scores 3 of 3 and the set 19 of 19.
- **Cards of one kind fold within their section.** In each tier the first three
  cards of a kind stay in their ranked places and the rest sit behind "Show N
  more like these" (`IssueList.tsx`). The section's count still shows the total,
  and a card that something links to is unfolded with the rest of its kind. Done
  on the page, not the server: every card still exists and is still ranked.
- **German postal data and mixed-country columns are left as they are.**

**One thing under two names is one thing** (`semantic/concepts.py`). Once a
connector has added map positions, share prices or stock symbols, an idea for
the same thing ("Map position", "Latitude and longitude", "Stock price") is no
longer offered, and asking for one by name adds nothing and says where it
already is. The same matching stops the idea list offering a model's "Share
price" beside the built-in "Stock price". Matching is on the words of the name,
which is all a not-yet-made column has; removing the lookup makes the idea
available again.
