"""All user-facing wording for issues, in one place for review.

Rules (CLAUDE.md principle 6): business language, no data jargon, and every
number or example comes from the evidence a detector gathered.
"""

from collections.abc import Sequence


def count(value: int) -> str:
    return f"{value:,}"


def quoted(values: Sequence[str], joiner: str = "or") -> str:
    """'"a"', '"a" or "b"', '"a", "b" or "c"'."""
    items = [f'"{value}"' for value in values]
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {joiner} {items[-1]}"


def plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


# --- placeholders ------------------------------------------------------------------


def placeholders_in_numbers(column: str, n: int, tokens: Sequence[str]) -> tuple[str, str, str]:
    title = (
        f'{count(n)} "{column}" {plural(n, "value says", "values say")} '
        f"{quoted(tokens)} instead of a number"
    )
    explanation = (
        "Spreadsheets leave these out of totals and averages. Treating them as missing "
        "keeps averages honest; treating them as zero pulls averages down."
    )
    prompt = f'What should {quoted(tokens)} mean in "{column}"?'
    return title, explanation, prompt


def placeholders_in_labels(column: str, n: int, tokens: Sequence[str]) -> tuple[str, str]:
    title = (
        f'{count(n)} "{column}" {plural(n, "value says", "values say")} '
        f"{quoted(tokens)} instead of a real value"
    )
    explanation = (
        "These are blanks written as words. Clearing them stops them from showing up "
        "as a group of their own."
    )
    return title, explanation


# --- numbers and dates ----------------------------------------------------------------


def numbers_as_text(column: str, n: int, examples: Sequence[str]) -> tuple[str, str]:
    if n == 0:
        return (
            f'Read "{column}" as numbers',
            f'The values in "{column}" are already plain numbers. Reading them as numbers '
            "lets them be added up and averaged.",
        )
    return (
        f'{count(n)} "{column}" {plural(n, "number is", "numbers are")} written as text',
        f"Values like {quoted(examples[:3])} need reading as numbers before they can be "
        "added up or averaged.",
    )


def numbers_with_suffix(column: str, examples: Sequence[str]) -> str:
    return (
        f'Some "{column}" values use "k" or "M" for thousands or millions, like '
        f"{quoted(examples[:2])}. Check that's what they mean before they're read as numbers."
    )


def decimal_comma(column: str, examples: Sequence[str]) -> tuple[str, str, str]:
    return (
        f'"{column}" writes numbers two different ways',
        f"Some values, like {quoted(examples[:2])}, could use a comma for thousands or for "
        "decimals. The answer changes every total.",
        f'In "{column}", what does the comma mean?',
    )


def dates_one_order(
    column: str, order: str, evidence: int, example: str | None, styles: int
) -> tuple[str, str]:
    first, other = ("month", "day") if order == "month" else ("day", "month")
    title = f'"{column}" dates are {first} first'
    explanation = (
        f'{count(evidence)} {plural(evidence, "date", "dates")} like "{example}" only make '
        f"sense with the {first} first, and none only make sense with the {other} first."
    )
    if styles > 1:
        explanation += f" The column mixes {count(styles)} date styles; all are read the same way."
    return title, explanation + " Reading them as dates lets you look at trends over time."


def dates_plain(column: str, styles: int) -> tuple[str, str]:
    if styles > 1:
        return (
            f'"{column}" mixes {count(styles)} date styles',
            "Each style is read on its own terms so every date lines up. Reading them as "
            "dates lets you look at trends over time.",
        )
    return (
        f'Read "{column}" as dates',
        "Reading these values as dates lets you look at trends over time.",
    )


def dates_unreadable(unreadable: int) -> str:
    return (
        f" {count(unreadable)} {plural(unreadable, 'value', 'values')} couldn't be read as a "
        "date and will be left blank."
    )


def dates_ambiguous(column: str, example: str) -> tuple[str, str, str]:
    return (
        f'"{column}" dates could be read two ways',
        f'Every date, like "{example}", works with either the month or the day first, so '
        "the file alone can't settle it.",
        f'In "{column}", which comes first?',
    )


def dates_conflicting(
    column: str, month_evidence: int, day_evidence: int, month_example: str, day_example: str
) -> tuple[str, str, str]:
    return (
        f'"{column}" dates disagree about month and day order',
        f"{count(month_evidence)} {plural(month_evidence, 'date', 'dates')} like "
        f'"{month_example}" only work month first, but {count(day_evidence)} like '
        f'"{day_example}" only work day first.',
        f'In "{column}", which comes first?',
    )


# --- variants and spaces --------------------------------------------------------------------


def variants_case_space(column: str, n: int, example_group: Sequence[str]) -> tuple[str, str]:
    return (
        f'{count(n)} "{column}" {plural(n, "value is", "values are")} written differently '
        "from the rest of their group",
        f"For example, {quoted(example_group, 'and')} look like the same thing. Combining "
        "them keeps each group together, so counts per group come out right.",
    )


def variants_similar(column: str, n: int, example_group: Sequence[str]) -> tuple[str, str]:
    return (
        f'{count(n)} "{column}" {plural(n, "value looks", "values look")} like another value '
        "spelled differently",
        f"For example, {quoted(example_group, 'and')}. Check they mean the same thing before "
        "combining them.",
    )


def extra_spaces(n: int, columns: Sequence[str]) -> tuple[str, str]:
    return (
        f"{count(n)} {plural(n, 'row has', 'rows have')} values with extra spaces",
        f"Spaces before or after values in {quoted(columns, 'and')} make identical values "
        "look different. Removing them is always safe.",
    )


def combined_column(
    column: str, delimiter: str, example: str, parts: Sequence[str], replaces: bool = False
) -> tuple[str, str]:
    split = f"Splitting them into {quoted(parts, 'and')}"
    if replaces:
        split += f', which replace "{column}",'
    return (
        f'"{column}" holds two things in one column',
        f'Values like "{example}" join two parts with "{delimiter}". {split} '
        "lets you count and compare each one separately.",
    )


# --- rows ---------------------------------------------------------------------------------------


def exact_repeats(n: int, has_identifier: bool) -> tuple[str, str]:
    explanation = (
        "Every value matches an earlier row, so these rows would be counted twice. "
        "They're set aside, not deleted."
    )
    if not has_identifier:
        explanation += (
            " This file has no ID column, so check whether identical rows could be genuine "
            "before setting them aside."
        )
    return (f"{count(n)} {plural(n, 'row repeats', 'rows repeat')} an earlier row", explanation)


def near_repeats(n: int) -> tuple[str, str]:
    return (
        f"{count(n)} {plural(n, 'row repeats', 'rows repeat')} an earlier row apart from "
        "capital letters or spaces",
        "These rows match an earlier row once capitals and spaces are ignored, so they're "
        "probably the same record typed twice. They're set aside, not deleted.",
    )


def identifier_repeats(
    column: str, values: int, rows: int, contact: bool, examples: Sequence[str]
) -> tuple[str, str, str]:
    shared = "shared by" if contact else "on"
    title = (
        f'{count(values)} "{column}" {plural(values, "value is", "values are")} '
        f"{shared} more than one row"
    )
    explanation = (
        f'{count(rows)} rows share their "{column}" with another row, like '
        f"{quoted(examples[:2])}. "
        "If each should be unique, some of these rows are counted more than once."
    )
    verb = "belong to" if contact else "appear on"
    return title, explanation, f'Should each "{column}" {verb} only one row?'


def out_of_range_negative(column: str, n: int, examples: Sequence[str]) -> tuple[str, str, str]:
    return (
        f'{count(n)} "{column}" {plural(n, "value is", "values are")} negative',
        f'Almost every "{column}" value is zero or more, but {quoted(examples[:3])} '
        f"{plural(n, 'is', 'are')} below zero. That can be a typo, or a value that's meant "
        "to be negative.",
        f'What should happen to the negative "{column}" values?',
    )


def out_of_range_far(column: str, n: int, examples: Sequence[str]) -> tuple[str, str, str]:
    return (
        f'{count(n)} "{column}" {plural(n, "value is", "values are")} far from the rest',
        f'Values like {quoted(examples[:3])} sit well outside where most "{column}" values '
        "fall. Unusual isn't always wrong, but a few extreme values can swing averages.",
        f'What should happen to the unusual "{column}" values?',
    )


def out_of_range_percent(column: str, n: int, examples: Sequence[str]) -> tuple[str, str, str]:
    return (
        f'{count(n)} "{column}" {plural(n, "percentage is", "percentages are")} over 100%',
        f"Values like {quoted(examples[:3])} are above 100%, which is unusual for a percentage.",
        f'What should happen to the "{column}" values over 100%?',
    )


# --- contacts and blanks ------------------------------------------------------------------------


def stray_minus(column: str, n: int, examples: Sequence[str]) -> tuple[str, str]:
    return (
        f'{count(n)} "{column}" {plural(n, "number starts", "numbers start")} with a stray "-"',
        f"Phone numbers don't start with a minus sign, so values like {quoted(examples[:2])} "
        "were probably changed when the file was saved. Removing it keeps the digits.",
    )


def short_phones(column: str, n: int, usual: int, examples: Sequence[str]) -> tuple[str, str, str]:
    return (
        f'{count(n)} "{column}" {plural(n, "number is", "numbers are")} shorter than the usual '
        f"{count(usual)} digits",
        f'Most numbers in "{column}" have {count(usual)} digits. Values like '
        f"{quoted(examples[:2])} have fewer, so digits may be missing.",
        f'What should happen to the short numbers in "{column}"?',
    )


def inconsistent_phone_format(
    column: str, n: int, examples: Sequence[tuple[str, str]]
) -> tuple[str, str]:
    shown = "; ".join(f'"{before}" becomes "{after}"' for before, after in examples[:2])
    return (
        f'{count(n)} "{column}" {plural(n, "number reads", "numbers read")} more clearly '
        "written consistently",
        f'Numbers in "{column}" use different spacing and punctuation for the same shape of '
        f"number. Writing them the same way doesn't change any digits, for example {shown}.",
    )


def invalid_emails(column: str, n: int, examples: Sequence[str]) -> tuple[str, str, str]:
    return (
        f'{count(n)} "{column}" {plural(n, "value doesn't", "values don't")} look like an '
        "email address",
        f"Values like {quoted(examples[:2])} are missing parts of an email address, so "
        "messages to them wouldn't arrive.",
        f'What should happen to these "{column}" values?',
    )


def missing_values(column: str, n: int, kind: str) -> tuple[str, str, str]:
    what = {
        "number": "They're left out of totals and averages unless you fill them.",
        "category": "They don't belong to any group unless you fill them.",
        "date": "They're left out of trends over time.",
    }[kind]
    return (
        f'{count(n)} {plural(n, "row has", "rows have")} no "{column}"',
        f"{what}",
        f'What should happen to rows with no "{column}"?',
    )
