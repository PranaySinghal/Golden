# Ideas

Out-of-scope ideas for "if I had more time". Not planned work.

- **Redo** alongside undo in the recipe history.
- **Download set-aside rows** as their own CSV, so removed rows can be reviewed outside the app.
- **Recipe step reordering** (drag to move a step) with validation of the new order.
- **Profile the cleaned table** after a recipe, to show roles changing (e.g. text → number).
- **Remember the header and sheet choice** per file name within a session.
- **Smarter default for unusual values.** Out-of-range issues currently recommend "Keep them"; revisit using context (how extreme, how many, whether the column has a natural range).
- **Date range checks.** Flag dates before 1900 or in the future; needs a date-aware range condition for set aside / clear.
- **Out-of-range for percentages below 0** and other domain-free bounds (e.g. ages over 120 are only detectable as "far from the rest" today).
- **Revisit the question cap** (16 today): check on wider files whether more questions help or clutter.
- **Currency in "before".** Excel turns "$85,000" into a number when opening a CSV; "before" currently follows CLAUDE.md and leaves it out. Reconsider matching Excel.
- **Drop meaningless totals** (e.g. total Age) — likely via AI wording in M8 or a rule for low-variety whole numbers.
- **Name the smallest group of steps** when more than 6 could be responsible together. Today the whole relevant set is reported, which is accurate but long ("caused by these 19 steps"); shrinking the set one step at a time would name the 2–3 that actually matter, for about one query per step.
- **Attribution for large files.** The query cap bounds how many questions are asked, not how long each takes; on a very large file, re-running the recipe per step is the slow part. Could sample rows, or skip attribution above a row count.
- **Say what was checked but didn't change** on answers that stayed put, e.g. "read Salary as numbers, no change" — free from the influence pass, but it adds noise, so it needs a UI decision.
- **Cross-tab files aren't tables.** `1.-Badly-Structured-Sales-Data-1.xlsx` is a pivot export: two header rows (`Segment>>`, `Ship Mode>>`), a stub column, subtotal columns, and a sparse matrix. The app reads it without complaint, but nothing it offers turns it into something you can answer questions about. Unpivoting it — one row per order, ship mode and segment as columns — is the fix, and it's a feature: a new step type, a detector that recognises the shape, and copy explaining it.
- **Two header rows.** When the header spans two rows, the second becomes the first data row and the blank cells under a merged heading become `column_3`, `column_4`… Combining them into `Consumer – Second Class` needs a header-span detector.
- **Subtotal columns double-count.** `Consumer Total` is the sum of the four columns before it, so any total across those columns counts everything twice. Spotting a column that equals the sum of its neighbours would be worth doing before we ever offer to total them.
- **Fifteen "read as numbers" cards in a row.** On a wide numeric file, every column gets its own safe card. They're correct but they bury everything else; grouping them into one ("Read 15 columns as numbers") is a UI change worth making.
- **Change the header or sheet without starting over.** The "first row is data" toggle and the sheet picker only exist on the summary screen. Once you're in the review, changing them means uploading again and losing the recipe.
- **Exact values in "Examples".** A file can store `10.272000000000002` where a spreadsheet shows `10.272`; we show what's stored, because examples are meant to reveal messy values. The column's Range now reads as a person would write it, so the two can look inconsistent. Worth a decision about which one is doing the wrong thing.
- **A recipe carries steps, not decisions.** A suggestion turned down, or an ask-tier answer meaning "leave it alone", adds no step, so re-using a recipe next month asks those questions again. Recording `rejected` and `answers` needs a recipe format v2 and a migration path for v1 files.
- **`keep_row_ids` is positional.** `DedupeStep`/`SetAsideRowsStep` can carry row numbers, which in a replayed recipe refer to *last month's* rows. Nothing populates them today, so it's latent — but a "keep this row" affordance would make replay silently keep arbitrary rows. Strip them on replay, or make them a compatibility problem.
- **Warnings can mean quiet data loss.** "Doesn't look mostly like numbers… many values may end up blank" describes a column of blanks after a *successful* replay. A count of the cells a warning would affect would make it weigh properly against the steps that ran.
- **Drop a `.json` on the drop zone** and have it understood as the steps rather than the data, instead of needing the separate "use those steps again" control.
- **Dark mode.** Colours are already tokens on `:root`, so the switch itself is small. Deferred because it doesn't serve the thesis and M10 is a feature freeze: done properly it means re-checking contrast on every chart (the faded "before" bar especially), the panel highlight and the up/down change colours, in both themes.
