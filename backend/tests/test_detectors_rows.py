"""Detectors about rows and records: repeats, shared IDs, out-of-range, contacts, blanks."""

from collections.abc import Callable

import pytest

from app.detectors.models import Issue, Tier
from app.steps.models import (
    ClearValuesStep,
    DedupeStep,
    DigitsFewerThanCondition,
    FillMissingStep,
    NormalizePhoneStep,
    OutsideRangeCondition,
    RemoveCharactersStep,
    SetAsideRowsStep,
)
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]


def csv_file(header: str, rows: list[str]) -> str:
    return header + "\n" + "\n".join(rows) + "\n"


def only(issues: list[Issue]) -> Issue:
    assert len(issues) == 1, [(i.detector, i.columns, i.title) for i in issues]
    return issues[0]


def choice(issue: Issue, label_start: str) -> tuple[bool, list[object]]:
    assert issue.ask is not None
    found = next(c for c in issue.ask.choices if c.label.startswith(label_start))
    return found.recommended, list(found.steps)


# --- duplicates ----------------------------------------------------------------------------


def test_exact_repeats_with_an_id_column_are_safe(make_dataset: MakeDataset) -> None:
    rows = [f"EMP{i},name{i % 5},{i * 10}" for i in range(20)] + ["EMP3,name3,30", "EMP3,name3,30"]
    ds = make_dataset(csv_file("id,name,amount", rows))

    issue = only(ds.issues("duplicates"))

    assert (issue.tier, issue.affected_rows) == (Tier.SAFE, 2)
    assert isinstance(issue.steps[0], DedupeStep)


def test_exact_repeats_without_an_id_column_need_review(make_dataset: MakeDataset) -> None:
    rows = [f"{['tea', 'cake'][i % 2]},{i % 3}" for i in range(12)]
    ds = make_dataset(csv_file("item,qty", rows))

    issues = ds.issues("duplicates")

    assert issues
    assert all(i.tier is Tier.LIKELY for i in issues)
    assert "no ID column" in issues[0].explanation


def test_near_repeats_are_likely_and_counted_separately(make_dataset: MakeDataset) -> None:
    rows = [f"EMP{i},Name{i},x{i}" for i in range(20)]
    rows += ["EMP1,Name1,x1", "emp2 ,NAME2,x2"]
    ds = make_dataset(csv_file("id,name,code", rows))

    by_tier = {i.tier: i for i in ds.issues("duplicates")}
    assert by_tier[Tier.SAFE].affected_rows == 1
    assert by_tier[Tier.LIKELY].affected_rows == 1
    step = by_tier[Tier.LIKELY].steps[0]
    assert isinstance(step, DedupeStep)
    assert step.match == "ignore_case_and_spaces"


def test_rows_differing_in_one_value_are_not_repeats(make_dataset: MakeDataset) -> None:
    ds = make_dataset("name,salary\nAnn,100\nAnn,200\n")

    assert ds.issues("duplicates") == []


# --- identifier repeats --------------------------------------------------------------------------


def test_a_few_repeated_ids_recommend_keeping_the_first(make_dataset: MakeDataset) -> None:
    rows = [f"EMP{1000 + i},{i}" for i in range(40)] + ["EMP1001,999", "EMP1002,998"]
    ds = make_dataset(csv_file("id,amount", rows))

    issue = only(ds.issues("identifier_repeats"))

    assert issue.tier is Tier.ASK
    assert issue.affected_rows == 4
    recommended, steps = choice(issue, "Yes, keep the first")
    assert recommended
    assert isinstance(steps[0], DedupeStep)


def test_widely_shared_contacts_recommend_sharing(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{['a@x.com', 'b@x.com', 'c@x.com'][i % 3]}" for i in range(30)]
    ds = make_dataset(csv_file("id,email", rows))

    issue = only(ds.issues("identifier_repeats"))

    assert issue.title == '3 "email" values are shared by more than one row'
    assert choice(issue, "No, sharing is fine") == (True, [])


def test_fully_identical_rows_are_left_to_the_duplicates_detector(
    make_dataset: MakeDataset,
) -> None:
    rows = [f"EMP{1000 + i},{i}" for i in range(40)] + ["EMP1001,1"]
    ds = make_dataset(csv_file("id,amount", rows))

    assert ds.issues("identifier_repeats") == []


def test_repeating_order_numbers_in_a_line_item_table_are_not_ids(
    make_dataset: MakeDataset,
) -> None:
    rows = [f"SO-{100 + i // 3},item{i},{i}" for i in range(30)]
    ds = make_dataset(csv_file("order,item,qty", rows))

    assert ds.issues("identifier_repeats") == []


# --- out of range ------------------------------------------------------------------------------


def test_a_stray_negative_asks_and_keeps_by_default(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{1000 + i * 7}" for i in range(150)] + ["151,-500"]
    ds = make_dataset(csv_file("id,salary", rows))

    issue = only([i for i in ds.issues("out_of_range") if "negative" in i.title])

    assert issue.tier is Tier.ASK
    assert issue.requires
    assert choice(issue, "Keep them") == (True, [])
    _, set_aside = choice(issue, "Set these rows aside")
    _, clear = choice(issue, "Clear just these values")
    assert isinstance(set_aside[0], SetAsideRowsStep)
    assert isinstance(clear[0], ClearValuesStep)
    assert isinstance(clear[0].condition, OutsideRangeCondition)
    assert clear[0].condition.min == 0


def test_many_negatives_are_normal(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{(i % 10) - 3}" for i in range(100)]
    ds = make_dataset(csv_file("id,balance", rows))

    assert [i for i in ds.issues("out_of_range") if "negative" in i.title] == []


def test_far_away_values_are_flagged(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{30 + (i % 20)}" for i in range(200)] + ["201,999"]
    ds = make_dataset(csv_file("id,age", rows))

    issue = only(ds.issues("out_of_range"))

    assert '"999"' in issue.explanation
    assert issue.affected_rows == 1


def test_evenly_spread_values_are_not_far_away(make_dataset: MakeDataset) -> None:
    ds = make_dataset(csv_file("id,score", [f"{i},{i}" for i in range(1, 1001)]))

    assert ds.issues("out_of_range") == []


def test_percentages_over_100(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{i % 90}%" for i in range(40)] + ["41,150%"]
    ds = make_dataset(csv_file("id,discount", rows))

    titles = [i.title for i in ds.issues("out_of_range")]

    assert '1 "discount" percentage is over 100%' in titles


def test_small_columns_are_not_checked(make_dataset: MakeDataset) -> None:
    ds = make_dataset(csv_file("id,amount", ["1,5", "2,6", "3,-900"]))

    assert ds.issues("out_of_range") == []


# --- contact formats ------------------------------------------------------------------------------


def test_stray_minus_and_short_phones(make_dataset: MakeDataset) -> None:
    rows = [f"{i},-{4155550000 + i}" for i in range(40)] + ["41,-4155550", "42,-41555"]
    ds = make_dataset(csv_file("id,Phone", rows))

    issues = {i.tier: i for i in ds.issues("contact_formats")}

    minus = issues[Tier.LIKELY]
    assert minus.affected_rows == 42
    assert isinstance(minus.steps[0], RemoveCharactersStep)

    short = issues[Tier.ASK]
    assert short.title == '2 "Phone" numbers are shorter than the usual 10 digits'
    recommended, steps = choice(short, "Clear them")
    assert recommended
    assert isinstance(steps[0], ClearValuesStep)
    assert steps[0].condition == DigitsFewerThanCondition(column="Phone", count=10)

    ds.apply(minus.steps[0], steps[0])
    assert ds.column("Phone")[-2:] == [None, None]
    assert ds.column("Phone")[0] == "4155550000"


def test_mixed_international_phones_are_not_short(make_dataset: MakeDataset) -> None:
    phones = ["(415) 555-0134", "+44 20 7946 0958", "+61 2 9876 5432", "212-555-0199"]
    ds = make_dataset(csv_file("id,contact", [f"{i},{phones[i % 4]}" for i in range(40)]))

    # Different lengths for different countries isn't corruption.
    assert not any(issue.tier is Tier.ASK for issue in ds.issues("contact_formats"))


def test_inconsistent_phone_format_is_likely_and_fixable(make_dataset: MakeDataset) -> None:
    rows = (
        [f"{i},(415) 555-0100" for i in range(20)]
        + [f"{i},415-555-0100" for i in range(20, 30)]
        + [f"{i},+44 20 7946 0958" for i in range(30, 40)]
    )
    ds = make_dataset(csv_file("id,Phone", rows))

    issue = only(ds.issues("contact_formats"))

    assert issue.tier is Tier.LIKELY
    # Only the "415-555-0100" rows aren't already written the way the library would.
    assert issue.affected_rows == 10
    step = issue.steps[0]
    assert isinstance(step, NormalizePhoneStep)

    ds.apply(step)
    assert set(ds.column("Phone")) == {"(415) 555-0100", "+44 20 7946 0958"}


def test_a_stray_minus_is_not_also_flagged_as_inconsistent(make_dataset: MakeDataset) -> None:
    # The stray-minus fix already covers these; flagging both would propose two
    # different steps for the same rows.
    rows = [f"{i},-4155550{100 + i}" for i in range(10)]
    ds = make_dataset(csv_file("id,Phone", rows))

    issues = ds.issues("contact_formats")

    assert len(issues) == 1
    assert isinstance(issues[0].steps[0], RemoveCharactersStep)


def test_already_consistent_phones_raise_nothing(make_dataset: MakeDataset) -> None:
    rows = [f"{i},(415) 555-01{i:02d}" for i in range(20)]
    ds = make_dataset(csv_file("id,Phone", rows))

    assert ds.issues("contact_formats") == []


def test_invalid_emails_ask(make_dataset: MakeDataset) -> None:
    rows = [f"{i},user{i}@example.com" for i in range(40)] + ["41,user41@example", "42,nobody"]
    ds = make_dataset(csv_file("id,email", rows))

    issue = only(ds.issues("contact_formats"))

    assert issue.tier is Tier.ASK
    assert issue.affected_rows == 2


def test_tagged_and_subdomain_emails_are_valid(make_dataset: MakeDataset) -> None:
    rows = [f"{i},a.b+tag{i}@mail.example.co.uk" for i in range(40)]
    ds = make_dataset(csv_file("id,email", rows))

    assert ds.issues("contact_formats") == []


# --- missing values -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "expected_labels"),
    [
        (
            [str(20 + i % 30) for i in range(40)],
            ["Leave them blank", "Fill with the middle value", "Set these rows aside"],
        ),
        (
            [["Red", "Blue"][i % 2] for i in range(40)],
            ["Leave them blank", 'Fill with "Unknown"', "Set these rows aside"],
        ),
    ],
)
def test_missing_values_ask_with_choices_by_kind(
    make_dataset: MakeDataset, values: list[str], expected_labels: list[str]
) -> None:
    rows = [f"{i},{v}" for i, v in enumerate(values)] + ["41,", "42,"]
    ds = make_dataset(csv_file("id,value", rows))

    issue = only(ds.issues("missing_values"))

    assert issue.tier is Tier.ASK
    assert issue.affected_rows == 2
    assert issue.ask is not None
    assert [c.label for c in issue.ask.choices] == expected_labels
    assert issue.ask.choices[0].recommended


def test_middle_value_fill_requires_reading_numbers(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{20 + i % 30}" for i in range(40)] + ["41,"]
    ds = make_dataset(csv_file("id,age", rows))

    issue = only(ds.issues("missing_values"))
    reading = only([i for i in ds.issues("numbers_as_text") if i.columns == ["age"]])

    assert issue.requires == [reading.id]
    _, steps = choice(issue, "Fill with the middle value")
    assert isinstance(steps[0], FillMissingStep)


def test_free_text_and_rarely_blank_columns_are_not_flagged(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{['a', 'b'][i % 2]},note number {i}" for i in range(200)] + ["201,,"]
    ds = make_dataset(csv_file("id,flag,notes", rows))

    assert ds.issues("missing_values") == []
