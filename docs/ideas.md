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
