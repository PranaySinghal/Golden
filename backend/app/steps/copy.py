"""How each step reads in the recipe panel, in one place for review.

Business language, no data jargon (CLAUDE.md principle 6): "Keep one row per
Employee_ID", not "dedupe on Employee_ID". Pure: a step in, a sentence out.
"""

from collections.abc import Sequence

from app.steps.models import (
    BlankCondition,
    CastNumberStep,
    ClearValuesStep,
    DedupeStep,
    DigitsFewerThanCondition,
    EqualsCondition,
    FillMissingStep,
    MapValuesStep,
    NormalizeCaseStep,
    NormalizePhoneStep,
    NotMatchingCondition,
    NullPlaceholdersStep,
    OneOfCondition,
    OutsideRangeCondition,
    ParseDateStep,
    RemoveCharactersStep,
    RowCondition,
    RowIdsCondition,
    SetAsideRowsStep,
    SplitColumnStep,
    Step,
    TrimStep,
)

CASE_WORDS = {"lower": "small letters", "upper": "capitals", "title": "Capital First Letters"}
FILL_WORDS = {
    "mean": "the average",
    "median": "the middle value",
    "most_common": "the most common value",
    "previous": "the value above",
}
MATCH_WORDS = {
    "email": "an email address",
    "phone": "a phone number",
    "number": "a number",
    "date": "a date",
}
WHERE_WORDS = {"leading": "the start", "trailing": "the end", "anywhere": "anywhere"}


def listed(names: Sequence[str], joiner: str = "and") -> str:
    """'A', 'A and B', 'A, B and C'."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} {joiner} {names[-1]}"


def quoted(names: Sequence[str], joiner: str = "and") -> str:
    return listed([f'"{name}"' for name in names], joiner)


def columns_of(step: Step) -> list[str]:
    """The columns a step works on, for showing next to its description."""
    match step:
        case (
            TrimStep()
            | RemoveCharactersStep()
            | NormalizeCaseStep()
            | NormalizePhoneStep()
            | NullPlaceholdersStep()
        ):
            return list(step.columns)
        case DedupeStep():
            return list(step.columns or [])
        case SetAsideRowsStep():
            column = getattr(step.condition, "column", None)
            return [column] if column else []
        case _:
            return [step.column]


def describe(step: Step) -> str:
    match step:
        case TrimStep():
            spaces = " and single spaces between words" if step.collapse_inner_spaces else ""
            return f"Trim spaces around {quoted(step.columns)}{spaces}"
        case RemoveCharactersStep():
            where = WHERE_WORDS[step.where]
            characters = listed([f'"{c}"' for c in step.characters], "and")
            return f"Remove {characters} from {where} of {quoted(step.columns)}"
        case NormalizeCaseStep():
            return f"Write {quoted(step.columns)} in {CASE_WORDS[step.case]}"
        case NormalizePhoneStep():
            return f"Write {quoted(step.columns)} numbers consistently"
        case MapValuesStep():
            return f'{_replacements(step)} in "{step.column}"'
        case NullPlaceholdersStep():
            return f"Clear {quoted(step.placeholders, 'and')} in {quoted(step.columns)}"
        case CastNumberStep():
            return f'Read "{step.column}" as numbers'
        case ParseDateStep():
            return f'Read "{step.column}" as dates'
        case SplitColumnStep():
            kept = "" if step.keep_original else ", and drop the original"
            return f'Split "{step.column}" into {quoted(step.into)}{kept}'
        case DedupeStep():
            return _dedupe(step)
        case SetAsideRowsStep():
            return f"Set aside rows where {condition(step.condition)}"
        case ClearValuesStep():
            return f'Clear "{step.column}" where {condition(step.condition)}'
        case FillMissingStep():
            return f'Fill blanks in "{step.column}" with {_fill_value(step)}'


def condition(rule: RowCondition) -> str:
    match rule:
        case RowIdsCondition():
            rows = len(rule.row_ids)
            return f"you picked {rows:,} {'row' if rows == 1 else 'rows'}"
        case BlankCondition():
            return f'"{rule.column}" is blank'
        case EqualsCondition():
            return f'"{rule.column}" is "{_value(rule.value)}"'
        case OneOfCondition():
            return f'"{rule.column}" is {quoted([_value(v) for v in rule.values], "or")}'
        case OutsideRangeCondition():
            return f'"{rule.column}" is {_range(rule)}'
        case NotMatchingCondition():
            return f'"{rule.column}" isn\'t {MATCH_WORDS[rule.pattern]}'
        case DigitsFewerThanCondition():
            return f'"{rule.column}" has fewer than {rule.count} digits'


def _dedupe(step: DedupeStep) -> str:
    kept = "first" if step.keep == "first" else "last"
    if step.columns is None:
        return f"Keep only the {kept} of rows that repeat every column"
    if len(step.columns) == 1:
        return f'Keep one row per "{step.columns[0]}" (the {kept} one)'
    return f"Keep one row per {quoted(step.columns)} (the {kept} one)"


def _replacements(step: MapValuesStep) -> str:
    cleared = [m for m in step.mappings if m.to_value is None]
    if len(step.mappings) == 1:
        one = step.mappings[0]
        if one.to_value is None:
            return f'Clear "{one.from_value}"'
        return f'Replace "{one.from_value}" with "{one.to_value}"'
    if len(cleared) == len(step.mappings):
        return f"Clear {len(step.mappings)} kinds of value"
    loose = " (ignoring capitals and spacing)" if step.match == "ignore_case_and_spaces" else ""
    return f"Merge {len(step.mappings)} spellings into one{loose}"


def _fill_value(step: FillMissingStep) -> str:
    if step.strategy == "value":
        return f'"{_value(step.value)}"'
    return FILL_WORDS[step.strategy]


def _range(rule: OutsideRangeCondition) -> str:
    if rule.min is not None and rule.max is not None:
        return f"outside {_number(rule.min)} to {_number(rule.max)}"
    if rule.min is not None:
        return f"below {_number(rule.min)}"
    assert rule.max is not None
    return f"above {_number(rule.max)}"


def _number(value: float) -> str:
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,}"


def _value(value: str | float | None) -> str:
    if value is None:
        return ""
    return _number(value) if isinstance(value, (int, float)) else value
