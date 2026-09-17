"""Detectors for individual values: placeholders, numbers, dates, spaces, variants, splits."""

from collections.abc import Callable

import pytest

from app.detectors.category_variants import group_variants, loose_key, one_edit_apart
from app.detectors.combined_columns import part_names
from app.detectors.models import Issue, Tier
from app.steps.models import (
    CastNumberStep,
    MapValuesStep,
    NullPlaceholdersStep,
    ParseDateStep,
    SplitColumnStep,
    TrimStep,
)
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]


def csv_file(header: str, rows: list[str]) -> str:
    return header + "\n" + "\n".join(rows) + "\n"


def only(issues: list[Issue], columns: list[str] | None = None) -> Issue:
    matching = [i for i in issues if columns is None or i.columns == columns]
    assert len(matching) == 1, [(i.detector, i.columns, i.title) for i in issues]
    return matching[0]


# --- placeholders ------------------------------------------------------------------------


def test_placeholders_in_a_number_column_ask_missing_or_zero(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{50000 + i * 10}" for i in range(40)] + ["41,N/A", "42,n/a ", "43,-"]
    ds = make_dataset(csv_file("id,salary", rows))

    issue = only(ds.issues("placeholders"))

    assert issue.tier is Tier.ASK
    assert issue.affected_rows == 3
    assert issue.ask is not None
    labels = [(c.label, c.recommended) for c in issue.ask.choices]
    assert labels == [("Missing", True), ("Zero", False)]
    missing, zero = issue.ask.choices
    assert isinstance(missing.steps[0], NullPlaceholdersStep)
    assert isinstance(zero.steps[0], MapValuesStep)
    assert issue.title.startswith('3 "salary" values say')


def test_placeholders_in_a_category_column_are_likely(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{['North', 'South', 'East'][i % 3]}" for i in range(30)] + ["31,unknown"]
    ds = make_dataset(csv_file("id,region", rows))

    issue = only(ds.issues("placeholders"))

    assert issue.tier is Tier.LIKELY
    assert isinstance(issue.steps[0], NullPlaceholdersStep)


def test_na_is_a_real_code_among_region_codes(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{['NA', 'EU', 'APAC', 'LATAM'][i % 4]}" for i in range(40)]
    ds = make_dataset(csv_file("id,region", rows))

    assert ds.issues("placeholders") == []


def test_no_placeholders_no_issue(make_dataset: MakeDataset) -> None:
    ds = make_dataset(csv_file("id,amount", [f"{i},{i * 3}" for i in range(30)]))

    assert ds.issues("placeholders") == []


# --- numbers as text -----------------------------------------------------------------------


def test_plain_numbers_get_a_safe_read_step_with_nothing_to_change(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(csv_file("id,qty", [f"{i},{i % 7}" for i in range(30)]))

    issue = only(ds.issues("numbers_as_text"))

    assert (issue.tier, issue.affected_rows, issue.title) == (Tier.SAFE, 0, 'Read "qty" as numbers')
    assert isinstance(issue.steps[0], CastNumberStep)


def test_formatted_money_is_safe(make_dataset: MakeDataset) -> None:
    ds = make_dataset(csv_file("id,price", [f'{i},"${i * 1000:,}.50"' for i in range(1, 30)]))

    issue = only(ds.issues("numbers_as_text"))

    assert issue.tier is Tier.SAFE
    assert issue.affected_rows == 29
    step = issue.steps[0]
    assert isinstance(step, CastNumberStep)
    assert (step.decimal_separator, step.allow_k_m_suffix) == (".", False)


def test_thousands_suffix_needs_review(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{50000 + i}" for i in range(20)] + ["21,$85k", "22,$1.2M"]
    ds = make_dataset(csv_file("id,salary", rows))

    issue = only(ds.issues("numbers_as_text"))

    assert issue.tier is Tier.LIKELY
    step = issue.steps[0]
    assert isinstance(step, CastNumberStep)
    assert step.allow_k_m_suffix
    assert '"$85k"' in issue.explanation


def test_decimal_commas_alone_are_read_as_decimals(make_dataset: MakeDataset) -> None:
    ds = make_dataset("id;price\n" + "\n".join(f"{i};{i},50" for i in range(1, 25)) + "\n")

    issue = only(ds.issues("numbers_as_text"))

    step = issue.steps[0]
    assert isinstance(step, CastNumberStep)
    assert step.decimal_separator == ","
    assert issue.tier is Tier.LIKELY


def test_conflicting_comma_styles_ask(make_dataset: MakeDataset) -> None:
    rows = [f'{i},"1,200.50"' for i in range(12)] + [f'{i},"3,5"' for i in range(12, 24)]
    ds = make_dataset(csv_file("id,amount", rows))

    issue = only(ds.issues("numbers_as_text"))

    assert issue.tier is Tier.ASK
    assert issue.ask is not None
    assert [c.label for c in issue.ask.choices] == ["Thousands", "Decimals"]


def test_zip_codes_are_not_numbers(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{['02134', '10001', '07302'][i % 3]}" for i in range(30)]
    ds = make_dataset(csv_file("id,postcode", rows))

    assert all(i.columns != ["postcode"] for i in ds.issues("numbers_as_text"))


# --- dates -----------------------------------------------------------------------------------


def test_month_first_evidence_is_safe_and_stated(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{(i % 12) + 1}/{(i % 28) + 1}/2024" for i in range(40)]
    ds = make_dataset(csv_file("id,joined", rows))

    issue = only(ds.issues("dates"))

    assert issue.tier is Tier.SAFE
    step = issue.steps[0]
    assert isinstance(step, ParseDateStep)
    assert step.formats == ["%m/%d/%Y"]
    assert "only make sense with the month first" in issue.explanation


def test_day_first_evidence(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{(i % 28) + 1:02d}/{(i % 12) + 1:02d}/2024" for i in range(40)]
    ds = make_dataset(csv_file("id,ordered", rows))

    step = only(ds.issues("dates")).steps[0]

    assert isinstance(step, ParseDateStep)
    assert step.formats == ["%d/%m/%Y"]


def test_ambiguous_dates_ask_with_readings(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{(i % 12) + 1:02d}/{(i % 11) + 1:02d}/2024" for i in range(30)]
    ds = make_dataset(csv_file("id,when", rows))

    issue = only(ds.issues("dates"))

    assert issue.tier is Tier.ASK
    assert issue.ask is not None
    month, day = issue.ask.choices
    assert month.label.startswith("Month first (")
    assert "March" in month.label or "January" in month.label
    assert not month.recommended
    assert not day.recommended


def test_conflicting_dates_recommend_a_clear_majority(make_dataset: MakeDataset) -> None:
    month_rows = [f"{i},{(i % 12) + 1}/{13 + (i % 15)}/2024" for i in range(30)]
    ds = make_dataset(csv_file("id,when", [*month_rows, "31,25/01/2024"]))

    issue = only(ds.issues("dates"))

    assert issue.tier is Tier.ASK
    assert issue.ask is not None
    assert [c.recommended for c in issue.ask.choices] == [True, False]


def test_mixed_date_styles_are_likely_and_covered(make_dataset: MakeDataset) -> None:
    rows = (
        [f"{i},{(i % 12) + 1}/{13 + (i % 15)}/2024" for i in range(20)]
        + [f"{i},2023-0{(i % 9) + 1}-15" for i in range(20, 35)]
        + [f'{i},"Mar {(i % 27) + 1}, 2022"' for i in range(35, 45)]
    )
    ds = make_dataset(csv_file("id,when", rows))

    issue = only(ds.issues("dates"))

    assert issue.tier is Tier.LIKELY
    step = issue.steps[0]
    assert isinstance(step, ParseDateStep)
    assert set(step.formats) == {"%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y"}
    assert "mixes 3 date styles" in issue.explanation


def test_a_few_dates_in_a_text_column_are_not_a_date_issue(make_dataset: MakeDataset) -> None:
    rows = [f"{i},note {i}" for i in range(40)] + ["41,1/2/2024", "42,3/4/2024"]
    ds = make_dataset(csv_file("id,comment", rows))

    assert ds.issues("dates") == []


# --- extra spaces and variants -----------------------------------------------------------------


def test_extra_spaces_across_columns_are_one_safe_issue(make_dataset: MakeDataset) -> None:
    teams = ["Sales", "HR", "Ops"]
    rows = [f"{i},{teams[i % 3]},note {i}" for i in range(30)]
    rows += ['31," Ann",Sales Ops', '32,"Sales  Ops",x', '33,HR,"z "']
    ds = make_dataset(csv_file("name,team,notes", rows))

    issue = only(ds.issues("extra_spaces"))

    assert issue.tier is Tier.SAFE
    assert issue.affected_rows == 3
    collapse = [s for s in issue.steps if isinstance(s, TrimStep) and s.collapse_inner_spaces]
    assert collapse
    assert collapse[0].columns == ["team"]


def test_no_spaces_no_issue(make_dataset: MakeDataset) -> None:
    ds = make_dataset("name,team\nAnn,Sales\nBo,HR\n")

    assert ds.issues("extra_spaces") == []


def test_case_and_space_variants_merge_to_the_most_common_spelling(
    make_dataset: MakeDataset,
) -> None:
    values = ["Sales"] * 10 + ["sales"] * 2 + [" SALES "] + ["HR"] * 8 + ["hr"]
    ds = make_dataset(csv_file("id,dept", [f'{i},"{v}"' for i, v in enumerate(values)]))

    issue = only(ds.issues("category_variants"))

    assert issue.tier is Tier.SAFE
    assert issue.affected_rows == 4
    step = issue.steps[0]
    assert isinstance(step, MapValuesStep)
    assert {(m.from_value, m.to_value) for m in step.mappings} == {
        ("Sales", "Sales"),
        ("HR", "HR"),
    }
    ds.apply(step)
    assert set(ds.column("dept")) == {"Sales", "HR"}


def test_similar_spellings_are_likely(make_dataset: MakeDataset) -> None:
    values = ["Home & Garden"] * 6 + ["Home and Garden"] * 2 + ["Electronics"] * 12 + ["Elecronics"]
    ds = make_dataset(csv_file("id,category", [f'{i},"{v}"' for i, v in enumerate(values)]))

    issue = only([i for i in ds.issues("category_variants") if i.tier is Tier.LIKELY])

    step = issue.steps[0]
    assert isinstance(step, MapValuesStep)
    assert {(m.from_value, m.to_value) for m in step.mappings} == {
        ("Home and Garden", "Home & Garden"),
        ("Elecronics", "Electronics"),
    }


def test_two_common_similar_words_are_not_merged(make_dataset: MakeDataset) -> None:
    values = ["Silver"] * 10 + ["Sliver"] * 8 + ["Gold"] * 5
    ds = make_dataset(csv_file("id,finish", [f"{i},{v}" for i, v in enumerate(values)]))

    assert ds.issues("category_variants") == []


def test_identifier_case_variants_are_left_alone(make_dataset: MakeDataset) -> None:
    rows = [f"{i},AB{i:03d}" for i in range(30)] + ["31,ab001"]
    ds = make_dataset(csv_file("id,code", rows))

    assert ds.issues("category_variants") == []


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [("sales", "sails", False), ("silver", "sliver", False), ("elctronics", "electronics", True)],
)
def test_one_edit_apart(a: str, b: str, expected: bool) -> None:
    assert one_edit_apart(a, b) is expected


def test_loose_key() -> None:
    assert loose_key(" Home & Garden!") == loose_key("home and garden")


def test_group_variants_prefers_tidy_spelling_on_ties() -> None:
    exact, _ = group_variants({"Sales ": 3, "Sales": 3})
    assert exact[0].canonical == "Sales"


# --- combined columns ----------------------------------------------------------------------------


def test_combined_column_is_split_with_names_from_the_header(make_dataset: MakeDataset) -> None:
    depts, regions = ["Sales", "HR", "Cloud Tech"], ["Texas", "New York", "Florida", "Ohio"]
    rows = [f"{i},{depts[i % 3]}-{regions[i % 4]}" for i in range(60)]
    ds = make_dataset(csv_file("id,Department_Region", rows))

    issue = only(ds.issues("combined_columns"))

    assert issue.tier is Tier.LIKELY
    step = issue.steps[0]
    assert isinstance(step, SplitColumnStep)
    assert (step.delimiter, step.into) == ("-", ["Department", "Region"])


def test_combined_column_with_an_unhelpful_header(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{['A', 'B'][i % 2]}/{['x', 'y', 'z'][i % 3]}" for i in range(30)]
    ds = make_dataset(csv_file("id,combo", rows))

    step = only(ds.issues("combined_columns")).steps[0]

    assert isinstance(step, SplitColumnStep)
    assert step.into == ["combo part 1", "combo part 2"]


def test_ranges_are_not_combined_columns(make_dataset: MakeDataset) -> None:
    rows = [f"{i},{['3-5', '6-10', '11-20'][i % 3]}" for i in range(30)]
    ds = make_dataset(csv_file("id,tenure", rows))

    assert ds.issues("combined_columns") == []


def test_mostly_unhyphenated_names_are_not_combined(make_dataset: MakeDataset) -> None:
    names = ["Mary-Jane", "Ann", "Bob", "Cy", "Dee", "Eve"]
    ds = make_dataset(csv_file("id,name", [f"{i},{names[i % 6]}" for i in range(30)]))

    assert ds.issues("combined_columns") == []


def test_part_names_avoid_existing_columns() -> None:
    assert part_names("Department_Region", "-", {"region"}) == [
        "Department_Region part 1",
        "Department_Region part 2",
    ]
