from app.db import ROW_ID_COLUMN
from app.ingest.models import HeaderMode
from app.profile.patterns import looks_typed

_TYPED_COLUMN_SHARE = 0.8


def detect_header(rows: list[list[str | None]]) -> bool:
    """Guess whether the first row holds column names, using only the values.

    A column whose later values are mostly numbers or dates tells us something:
    if its first value is a label, the first row is a header; if its first value
    is also a number or date, the first row is data. Columns that are all text
    carry no signal, so with no signal we assume a header (the common case) and
    the user can override it.
    """
    if len(rows) < 2:
        return True

    first, rest = rows[0], rows[1:]
    header_votes = data_votes = 0
    for index, first_value in enumerate(first):
        if first_value is None or first_value.strip() == "":
            continue
        later = [row[index] for row in rest if index < len(row) and row[index] not in (None, "")]
        if not later:
            continue
        typed_share = sum(looks_typed(v) for v in later if v is not None) / len(later)
        if typed_share < _TYPED_COLUMN_SHARE:
            continue
        if looks_typed(first_value):
            data_votes += 1
        else:
            header_votes += 1

    if header_votes > 0:
        return True
    return data_votes == 0


def resolve_header(mode: HeaderMode, rows: list[list[str | None]]) -> bool:
    if mode is HeaderMode.FIRST_ROW_IS_HEADER:
        return True
    if mode is HeaderMode.FIRST_ROW_IS_DATA:
        return False
    return detect_header(rows)


def clean_column_names(headers: list[str | None], width: int) -> list[str]:
    """Make names usable as unique table columns while staying close to the originals.

    Blank names become column_N. DuckDB treats names case-insensitively, so
    "Name" and "name" count as duplicates and get a _2 suffix. The row id
    column name is reserved.
    """
    names: list[str] = []
    taken: set[str] = {ROW_ID_COLUMN.lower()}
    for index in range(width):
        raw = headers[index] if index < len(headers) else None
        base = raw.strip() if raw is not None else ""
        if base == "":
            base = f"column_{index + 1}"
        name, suffix = base, 2
        while name.lower() in taken:
            name = f"{base}_{suffix}"
            suffix += 1
        taken.add(name.lower())
        names.append(name)
    return names
