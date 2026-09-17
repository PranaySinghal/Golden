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
