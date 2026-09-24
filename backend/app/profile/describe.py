"""One plain sentence about what each row of a file holds, from the profile alone.

It names the kinds of column, in the words the column table already uses (ID,
category, number, date, contact info, text), and the ID column when there is exactly
one. It never guesses what the file is *about* ("employees", "orders") from the
column names: that would be a guess dressed as a fact, and the same file with other
headers would read differently (CLAUDE.md principle 1). No model is involved.
"""

from app.profile.models import ColumnFlag, ColumnProfile, DatasetProfile, SemanticRole

# The order the pieces are read in: what identifies a row first, then when, how
# much, and what kind, with the looser columns last.
_ORDER = (
    SemanticRole.DATE,
    SemanticRole.MEASURE,
    SemanticRole.CATEGORY,
    SemanticRole.CONTACT,
    SemanticRole.TEXT,
)
_WORDS: dict[SemanticRole, tuple[str, str]] = {
    SemanticRole.DATE: ("a date", "dates"),
    SemanticRole.MEASURE: ("a number", "numbers"),
    SemanticRole.CATEGORY: ("a category", "categories"),
    SemanticRole.CONTACT: ("contact info", "kinds of contact info"),
    SemanticRole.TEXT: ("some text", "text columns"),
}


def describe_rows(profile: DatasetProfile) -> str:
    filled = [c for c in profile.columns if ColumnFlag.ALL_BLANK not in c.flags]
    empty = len(profile.columns) - len(filled)
    if not filled:
        return "Every column in this file is empty."

    parts = []
    ids = [c for c in filled if c.semantic_role is SemanticRole.IDENTIFIER]
    if len(ids) == 1:
        parts.append(f"an ID (“{ids[0].name}”)")
    elif ids:
        parts.append(f"{len(ids)} IDs")
    for role in _ORDER:
        count = _count(filled, role)
        if count:
            one, many = _WORDS[role]
            parts.append(one if count == 1 else f"{count} {many}")
    if empty:
        parts.append("an empty column" if empty == 1 else f"{empty} empty columns")
    return f"Each row has {_join(parts)}."


def _count(columns: list[ColumnProfile], role: SemanticRole) -> int:
    return sum(1 for column in columns if column.semantic_role is role)


def _join(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"
