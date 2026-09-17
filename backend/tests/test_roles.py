"""Role inference on synthetic columns. Each rule has a case where it should fire
and at least one look-alike where it must not."""

import random

import pytest

from app.profile.models import ColumnFlag, PatternKind, PhysicalType, SemanticRole
from tests.conftest import profile_values

rng = random.Random(7)


def repeat(values: list[str], total: int) -> list[str]:
    return [values[i % len(values)] for i in range(total)]


# --- identifier -------------------------------------------------------------


def test_text_codes_are_identifiers() -> None:
    profile = profile_values([f"EMP{1000 + i}" for i in range(50)])

    assert profile.semantic_role is SemanticRole.IDENTIFIER
    assert profile.flags == []
    shape = next(p for p in profile.patterns if p.kind is PatternKind.CODE_SHAPE)
    assert shape.detail == "AAA9999"


def test_codes_with_some_duplicates_are_identifiers_with_low_uniqueness() -> None:
    values = [f"INV-{i:04d}" for i in range(40)] + [f"INV-{i:04d}" for i in range(10)]

    profile = profile_values(values)

    assert profile.semantic_role is SemanticRole.IDENTIFIER
    assert ColumnFlag.LOW_UNIQUENESS in profile.flags


def test_unique_decimals_are_measures_not_identifiers() -> None:
    profile = profile_values([f"{50000 + i * 13.37:.2f}" for i in range(50)])

    assert profile.semantic_role is SemanticRole.MEASURE
    assert profile.physical_type is PhysicalType.DECIMAL


def test_unique_short_integer_amounts_are_measures() -> None:
    profile = profile_values([str(v) for v in rng.sample(range(10_000, 99_999), 50)])

    assert profile.semantic_role is SemanticRole.MEASURE


def test_sequential_integers_are_identifiers() -> None:
    values = [str(100001 + i) for i in range(50)]
    rng.shuffle(values)

    profile = profile_values(values)

    assert profile.semantic_role is SemanticRole.IDENTIFIER


def test_a_few_unique_integers_are_not_called_a_sequence() -> None:
    assert profile_values(["3", "1", "2"]).semantic_role is SemanticRole.MEASURE


def test_long_fixed_width_numbers_are_identifiers_with_low_confidence() -> None:
    values = [str(rng.randint(1_000_000_000, 9_999_999_999)) for _ in range(50)]

    profile = profile_values(values, name="col_7")

    assert profile.semantic_role is SemanticRole.IDENTIFIER
    assert profile.role_confidence == pytest.approx(0.6)
    assert ColumnFlag.NAME_HINT_USED not in profile.flags


def test_long_fixed_width_numbers_named_like_an_id_are_more_confident() -> None:
    values = [str(rng.randint(1_000_000_000, 9_999_999_999)) for _ in range(50)]

    profile = profile_values(values, name="Account ID")

    assert profile.semantic_role is SemanticRole.IDENTIFIER
    assert profile.role_confidence == pytest.approx(0.75)
    assert ColumnFlag.NAME_HINT_USED in profile.flags


def test_unique_codes_with_leading_zeros_are_identifiers() -> None:
    profile = profile_values([f"{i:06d}" for i in range(1, 400, 7)])

    assert profile.semantic_role is SemanticRole.IDENTIFIER


# --- contact ------------------------------------------------------------------


def test_emails_are_contacts() -> None:
    profile = profile_values([f"user{i}@example.com" for i in range(30)])

    assert profile.semantic_role is SemanticRole.CONTACT
    assert ColumnFlag.LOW_UNIQUENESS not in profile.flags


def test_shared_emails_are_contacts_with_low_uniqueness() -> None:
    profile = profile_values(repeat(["a@x.com", "b@x.com", "c@x.com"], 30))

    assert profile.semantic_role is SemanticRole.CONTACT
    assert ColumnFlag.LOW_UNIQUENESS in profile.flags
    assert "3 different values" in profile.role_note


def test_formatted_phones_are_contacts_without_a_name_hint() -> None:
    values = [
        "(415) 555-0134",
        "+44 20 7946 0958",
        "212-555-0199",
        "415.555.0100",
    ] * 5

    profile = profile_values(values, name="col_2")

    assert profile.semantic_role is SemanticRole.CONTACT
    assert ColumnFlag.NAME_HINT_USED not in profile.flags


def test_bare_digit_phones_need_the_name_hint() -> None:
    values = [f"-{rng.randint(1_000_000_000, 9_999_999_999)}" for _ in range(40)]

    hinted = profile_values(values, name="Phone")
    unhinted = profile_values(values, name="col_9")

    assert hinted.semantic_role is SemanticRole.CONTACT
    assert ColumnFlag.NAME_HINT_USED in hinted.flags
    assert unhinted.semantic_role is SemanticRole.IDENTIFIER


def test_name_hint_never_overrides_clear_values() -> None:
    amounts = [f"{rng.uniform(10, 900):.2f}" for _ in range(40)]
    labels = repeat(["North", "South", "East"], 40)

    assert profile_values(amounts, name="Phone").semantic_role is SemanticRole.MEASURE
    assert profile_values(labels, name="Region ID").semantic_role is SemanticRole.CATEGORY


# --- date -----------------------------------------------------------------------


def test_day_first_dates() -> None:
    profile = profile_values(["15/03/2024", "01/02/2024", "28/12/2023", "07/07/2024"])

    assert profile.semantic_role is SemanticRole.DATE
    assert profile.physical_type is PhysicalType.DATE
    assert (profile.min_value, profile.max_value) == ("2023-12-28", "2024-07-07")


def test_month_first_dates() -> None:
    profile = profile_values(["4/2/2021", "12/31/2020", "7/17/2022"])

    assert profile.semantic_role is SemanticRole.DATE
    assert (profile.min_value, profile.max_value) == ("2020-12-31", "2022-07-17")


def test_ambiguous_day_month_order_gives_no_range() -> None:
    profile = profile_values(["01/02/2024", "03/04/2024", "05/06/2024"])

    assert profile.semantic_role is SemanticRole.DATE
    assert (profile.min_value, profile.max_value) == (None, None)


def test_iso_datetimes() -> None:
    profile = profile_values(["2024-03-15 09:30:00", "2024-03-16 17:45:10", "2024-01-01 00:00:00"])

    assert profile.semantic_role is SemanticRole.DATE
    assert profile.physical_type is PhysicalType.DATETIME
    assert profile.min_value == "2024-01-01 00:00:00"


def test_dates_with_month_names() -> None:
    profile = profile_values(["15 Mar 2024", "2 Jan 2023", "30 Nov 2024"])

    assert profile.semantic_role is SemanticRole.DATE
    assert (profile.min_value, profile.max_value) == ("2023-01-02", "2024-11-30")


def test_dates_with_a_few_placeholders_are_still_dates() -> None:
    values = [f"2024-01-{d:02d}" for d in range(1, 10)] + ["unknown"]

    assert profile_values(values).semantic_role is SemanticRole.DATE


def test_plain_years_are_not_dates() -> None:
    profile = profile_values(repeat(["2021", "2022", "2023"], 30))

    assert profile.semantic_role is SemanticRole.MEASURE


# --- measure ----------------------------------------------------------------------


def test_numbers_with_placeholder_text_are_measures() -> None:
    values = [f"{60000 + i * 911.5:.2f}" for i in range(40)] + ["N/A"] * 2

    profile = profile_values(values)

    assert profile.semantic_role is SemanticRole.MEASURE
    placeholder = next(p for p in profile.patterns if p.kind is PatternKind.PLACEHOLDER)
    assert (placeholder.match_count, placeholder.detail) == (2, "N/A")
    assert '2 values are text like "N/A"' in profile.role_note


def test_mostly_text_with_some_numbers_is_not_a_measure() -> None:
    values = repeat(["10", "20", "30", "pending", "cancelled", "n/a lost"], 30)

    assert profile_values(values).semantic_role is not SemanticRole.MEASURE


def test_currency_amounts_are_measures() -> None:
    profile = profile_values(["$1,200.50", "$85.00", "$12,000.00", "(€35.10)"])

    assert profile.semantic_role is SemanticRole.MEASURE
    assert {PatternKind.CURRENCY, PatternKind.THOUSANDS_SEPARATOR} <= {
        p.kind for p in profile.patterns
    }
    assert (profile.min_value, profile.max_value) == ("-35.1", "12000")


def test_percentages_are_measures() -> None:
    profile = profile_values(repeat(["0%", "5%", "12.5%"], 12))

    assert profile.semantic_role is SemanticRole.MEASURE
    assert PatternKind.PERCENT in {p.kind for p in profile.patterns}


def test_low_cardinality_integers_are_measures() -> None:
    assert (
        profile_values(repeat(["25", "30", "35", "40"], 40)).semantic_role is SemanticRole.MEASURE
    )


# --- category ----------------------------------------------------------------------


def test_zip_codes_with_leading_zeros_are_categories_not_measures() -> None:
    profile = profile_values(repeat(["02134", "10001", "07302", "60614"], 40))

    assert profile.semantic_role is SemanticRole.CATEGORY
    assert '"02134"' in profile.role_note


def test_zero_one_columns_are_yes_no_categories() -> None:
    profile = profile_values(repeat(["0", "1", "1"], 30))

    assert profile.semantic_role is SemanticRole.CATEGORY
    assert profile.physical_type is PhysicalType.BOOLEAN


def test_yes_no_with_mixed_case_are_categories() -> None:
    profile = profile_values(repeat(["Yes", "no", "yes", "No"], 20))

    assert profile.semantic_role is SemanticRole.CATEGORY
    assert profile.physical_type is PhysicalType.BOOLEAN
    # Equal counts are ordered by value, and "Yes"/"yes" count as one answer.
    assert profile.role_note == 'Every filled value is a yes/no answer: "No" or "Yes".'


def test_repeated_labels_are_categories() -> None:
    profile = profile_values(
        repeat(["Alice", "Bob", "Chen", "Dana", "Eve", "Femi", "Gus", "Hana"], 100)
    )

    assert profile.semantic_role is SemanticRole.CATEGORY
    assert profile.distinct_count == 8


def test_combined_values_are_noted_as_delimited() -> None:
    values = repeat(["Sales-Texas", "HR-New York", "Cloud Tech-Florida"], 30)

    delimited = next(p for p in profile_values(values).patterns if p.kind is PatternKind.DELIMITED)

    assert delimited.detail == "-"


def test_constant_column_is_flagged() -> None:
    profile = profile_values(["Active"] * 10)

    assert profile.semantic_role is SemanticRole.CATEGORY
    assert ColumnFlag.CONSTANT in profile.flags


# --- text ---------------------------------------------------------------------------


def test_free_text_sentences_are_text() -> None:
    values = [f"Customer {i} asked about delivery on day {i * 3}" for i in range(30)]

    assert profile_values(values).semantic_role is SemanticRole.TEXT


def test_unique_single_words_are_text_not_identifiers() -> None:
    words = [
        "apple",
        "river",
        "castle",
        "orbit",
        "maple",
        "harbor",
        "violet",
        "ember",
        "summit",
        "cedar",
    ]

    assert profile_values(list(words)).semantic_role is SemanticRole.TEXT


# --- blanks ----------------------------------------------------------------------------


def test_all_blank_column() -> None:
    profile = profile_values([None, "", "   ", None])

    assert profile.semantic_role is SemanticRole.TEXT
    assert profile.physical_type is PhysicalType.EMPTY
    assert profile.role_confidence == 0.0
    assert profile.flags == [ColumnFlag.ALL_BLANK]
    assert profile.fill_rate == 0.0
    assert profile.distinct_count == 0
    assert profile.sample_values == []
    assert "All 4 rows are empty" in profile.role_note


def test_column_in_a_file_with_no_rows() -> None:
    profile = profile_values([])

    assert profile.flags == [ColumnFlag.ALL_BLANK]
    assert "no rows" in profile.role_note


def test_mostly_blank_column_is_flagged_and_noted() -> None:
    values = ["a note here", None, None, None, "another note", None]

    profile = profile_values(values)

    assert ColumnFlag.MOSTLY_BLANK in profile.flags
    assert profile.fill_rate == pytest.approx(0.3333)
    assert "Only 33% of rows are filled in." in profile.role_note


def test_whitespace_is_ignored_for_patterns_but_kept_in_samples() -> None:
    profile = profile_values([" 10 ", "20", " 30"])

    assert profile.semantic_role is SemanticRole.MEASURE
    assert " 10 " in profile.sample_values


def test_sample_values_are_capped_and_truncated() -> None:
    long_value = "x" * 200
    profile = profile_values([long_value, *[f"v{i}" for i in range(20)]])

    assert len(profile.sample_values) == 5
    assert all(len(value) <= 80 for value in profile.sample_values)


# --- column names are only a weak hint -------------------------------------------------


@pytest.mark.parametrize("name", ["col_1", "Salary", "Email", "Employee_ID", "Join_Date", "zzz"])
def test_clear_values_get_the_same_role_whatever_the_name(name: str) -> None:
    emails: list[str | None] = [f"u{i}@example.com" for i in range(20)]
    dates: list[str | None] = [f"2024-02-{d:02d}" for d in range(1, 21)]
    amounts = [f"{1000 + i * 17.25:.2f}" for i in range(20)]

    assert profile_values(emails, name).semantic_role is SemanticRole.CONTACT
    assert profile_values(dates, name).semantic_role is SemanticRole.DATE
    assert profile_values(amounts, name).semantic_role is SemanticRole.MEASURE
