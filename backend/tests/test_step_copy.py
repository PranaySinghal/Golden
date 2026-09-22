"""How steps read in the recipe panel."""

import pytest

from app.steps.copy import columns_of, describe
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
    ValueMapping,
)

# Words from the machinery that should never reach a business user.
JARGON = ["null", "dedupe", "cast", "parse", "regex", "column_2", "varchar", "sql"]


def test_trim() -> None:
    step = TrimStep(columns=["First_Name", "Last_Name"])

    assert describe(step) == 'Trim spaces around "First_Name" and "Last_Name"'


def test_trim_with_inner_spaces() -> None:
    step = TrimStep(columns=["City"], collapse_inner_spaces=True)

    assert describe(step) == 'Trim spaces around "City" and single spaces between words'


def test_remove_characters() -> None:
    step = RemoveCharactersStep(columns=["Phone"], characters="-", where="leading")

    assert describe(step) == 'Remove "-" from the start of "Phone"'


def test_normalize_case() -> None:
    step = NormalizeCaseStep(columns=["Status"], case="title")

    assert describe(step) == 'Write "Status" in Capital First Letters'


def test_normalize_phone() -> None:
    step = NormalizePhoneStep(columns=["Phone"])

    assert describe(step) == 'Write "Phone" numbers consistently'
    assert columns_of(step) == ["Phone"]


def test_one_replacement() -> None:
    step = MapValuesStep(
        column="Status", mappings=[ValueMapping(from_value="Actve", to_value="Active")]
    )

    assert describe(step) == 'Replace "Actve" with "Active" in "Status"'


def test_merged_spellings() -> None:
    step = MapValuesStep(
        column="Status",
        mappings=[
            ValueMapping(from_value="active", to_value="Active"),
            ValueMapping(from_value="ACTIVE", to_value="Active"),
        ],
        match="ignore_case_and_spaces",
    )

    assert (
        describe(step) == 'Merge 2 spellings into one (ignoring capitals and spacing) in "Status"'
    )


def test_placeholders() -> None:
    step = NullPlaceholdersStep(columns=["Salary"], placeholders=["N/A", "-"])

    assert describe(step) == 'Clear "N/A" and "-" in "Salary"'


def test_numbers_and_dates() -> None:
    assert describe(CastNumberStep(column="Salary")) == 'Read "Salary" as numbers'
    assert describe(ParseDateStep(column="Join_Date", formats=["%m/%d/%Y"])) == (
        'Read "Join_Date" as dates'
    )


def test_split() -> None:
    step = SplitColumnStep(column="Dept_Region", delimiter="-", into=["Dept", "Region"])

    assert describe(step) == 'Split "Dept_Region" into "Dept" and "Region"'


def test_split_dropping_the_original() -> None:
    step = SplitColumnStep(
        column="Dept_Region", delimiter="-", into=["Dept", "Region"], keep_original=False
    )

    assert describe(step).endswith(", and drop the original")


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (DedupeStep(columns=["Employee_ID"]), 'Keep one row per "Employee_ID" (the first one)'),
        (
            DedupeStep(columns=["First_Name", "Email"], keep="last"),
            'Keep one row per "First_Name" and "Email" (the last one)',
        ),
        (DedupeStep(), "Keep only the first of rows that repeat every column"),
    ],
)
def test_dedupe(step: Step, expected: str) -> None:
    assert describe(step) == expected


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (BlankCondition(column="Age"), 'Set aside rows where "Age" is blank'),
        (EqualsCondition(column="Status", value="Left"), 'Set aside rows where "Status" is "Left"'),
        (
            OneOfCondition(column="Status", values=["Left", "Gone"]),
            'Set aside rows where "Status" is "Left" or "Gone"',
        ),
        (
            OutsideRangeCondition(column="Age", min=16, max=90),
            'Set aside rows where "Age" is outside 16 to 90',
        ),
        (
            OutsideRangeCondition(column="Salary", min=0),
            'Set aside rows where "Salary" is below 0',
        ),
        (
            NotMatchingCondition(column="Email", pattern="email"),
            'Set aside rows where "Email" isn\'t an email address',
        ),
        (
            DigitsFewerThanCondition(column="Phone", count=10),
            'Set aside rows where "Phone" has fewer than 10 digits',
        ),
        (RowIdsCondition(row_ids=[1, 2]), "Set aside rows where you picked 2 rows"),
    ],
)
def test_set_aside_conditions(condition: RowCondition, expected: str) -> None:
    assert describe(SetAsideRowsStep(condition=condition)) == expected


def test_clear_values() -> None:
    step = ClearValuesStep(
        column="Phone", condition=DigitsFewerThanCondition(column="Phone", count=10)
    )

    assert describe(step) == 'Clear "Phone" where "Phone" has fewer than 10 digits'


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (
            FillMissingStep(column="Age", strategy="median"),
            'Fill blanks in "Age" with the middle value',
        ),
        (FillMissingStep(column="Age", strategy="mean"), 'Fill blanks in "Age" with the average'),
        (
            FillMissingStep(column="Status", strategy="value", value="Unknown"),
            'Fill blanks in "Status" with "Unknown"',
        ),
    ],
)
def test_fill_missing(step: Step, expected: str) -> None:
    assert describe(step) == expected


def test_columns_of_each_step_shape() -> None:
    assert columns_of(TrimStep(columns=["A", "B"])) == ["A", "B"]
    assert columns_of(CastNumberStep(column="Salary")) == ["Salary"]
    assert columns_of(DedupeStep()) == []
    assert columns_of(SetAsideRowsStep(condition=BlankCondition(column="Age"))) == ["Age"]
    assert columns_of(SetAsideRowsStep(condition=RowIdsCondition(row_ids=[1]))) == []


def test_descriptions_use_no_jargon() -> None:
    steps: list[Step] = [
        TrimStep(columns=["A"]),
        RemoveCharactersStep(columns=["A"], characters="-"),
        NormalizeCaseStep(columns=["A"], case="lower"),
        NormalizePhoneStep(columns=["A"]),
        MapValuesStep(column="A", mappings=[ValueMapping(from_value="x", to_value=None)]),
        NullPlaceholdersStep(columns=["A"], placeholders=["N/A"]),
        CastNumberStep(column="A"),
        ParseDateStep(column="A", formats=["%Y-%m-%d"]),
        SplitColumnStep(column="A", delimiter="-", into=["B", "C"]),
        DedupeStep(),
        SetAsideRowsStep(condition=BlankCondition(column="A")),
        ClearValuesStep(column="A", condition=BlankCondition(column="A")),
        FillMissingStep(column="A", strategy="previous"),
    ]

    for step in steps:
        words = describe(step).lower()
        assert not any(word in words for word in JARGON), describe(step)
