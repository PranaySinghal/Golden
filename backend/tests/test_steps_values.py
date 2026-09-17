"""Steps that change values: trim, case, mapping, placeholders, numbers, dates, fill."""

import datetime as dt
from collections.abc import Callable

import pytest

from app.steps.apply import StepStatus
from app.steps.models import (
    CastNumberStep,
    FillMissingStep,
    MapValuesStep,
    NormalizeCaseStep,
    NullPlaceholdersStep,
    ParseDateStep,
    TrimStep,
    ValueMapping,
)
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]


def one_column(make_dataset: MakeDataset, values: list[str]) -> Dataset:
    """A file with an id column and one column "v" holding `values` ("" is blank)."""
    lines = [f'{i},"{value}"' if value else f"{i}," for i, value in enumerate(values, 1)]
    return make_dataset("id,v\n" + "\n".join(lines) + "\n")


# --- trim -------------------------------------------------------------------------------------


def test_trim_strips_edges_and_blanks_whitespace_only_cells(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["  Sales ", "\tHR", "Sales", "   ", ""])

    result = ds.apply(TrimStep(columns=["v"]))

    assert ds.column("v") == ["Sales", "HR", "Sales", None, None]
    assert result.outcomes[0].cells_changed == 3
    kinds = [change[5] for change in ds.changes()]
    assert kinds == ["changed", "changed", "cleared"]


def test_trim_collapses_inner_spaces_only_when_asked(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["New   York", " a  b "])

    ds.apply(TrimStep(columns=["v"]))
    assert ds.column("v") == ["New   York", "a  b"]

    ds.apply(TrimStep(columns=["v"], collapse_inner_spaces=True))
    assert ds.column("v") == ["New York", "a b"]


def test_trim_on_clean_data_changes_nothing(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["a", "b"])

    result = ds.apply(TrimStep(columns=["v", "v"]))

    assert result.outcomes[0].cells_changed == 0
    assert ds.changes() == []


# --- normalize_case ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("lower", ["sales team", "émile", None]),
        ("upper", ["SALES TEAM", "ÉMILE", None]),
        ("title", ["Sales Team", "Émile", None]),
    ],
)
def test_normalize_case(make_dataset: MakeDataset, case: str, expected: list[str | None]) -> None:
    ds = one_column(make_dataset, ["sALES team", "émile", ""])

    ds.apply(NormalizeCaseStep.model_validate({"columns": ["v"], "case": case}))

    assert ds.column("v") == expected


# --- map_values -------------------------------------------------------------------------------


def test_map_values_exact(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["sales", "Sales", "HR", "hr "])

    ds.apply(
        MapValuesStep(
            column="v",
            mappings=[ValueMapping(from_value="sales", to_value="Sales")],
        )
    )

    assert ds.column("v") == ["Sales", "Sales", "HR", "hr "]


def test_map_values_ignoring_case_and_spaces(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["sales", " SALES  ", "HR", "hr "])

    ds.apply(
        MapValuesStep(
            column="v",
            match="ignore_case_and_spaces",
            mappings=[
                ValueMapping(from_value="Sales", to_value="Sales"),
                ValueMapping(from_value="hr", to_value="Human Resources"),
            ],
        )
    )

    assert ds.column("v") == ["Sales", "Sales", "Human Resources", "Human Resources"]


def test_map_values_to_blank_and_leaves_unmapped_alone(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["test", "real", ""])

    ds.apply(MapValuesStep(column="v", mappings=[ValueMapping(from_value="test", to_value=None)]))

    assert ds.column("v") == [None, "real", None]


def test_map_values_treats_sql_and_param_syntax_as_data(make_dataset: MakeDataset) -> None:
    hostile = "'); DROP TABLE work.cleaned; --"
    ds = one_column(make_dataset, ["$1", "50%"])

    ds.apply(
        MapValuesStep(
            column="v",
            mappings=[
                ValueMapping(from_value="$1", to_value=hostile),
                ValueMapping(from_value="50%", to_value="half"),
            ],
        )
    )

    assert ds.column("v") == [hostile, "half"]


def test_map_values_rejects_duplicate_sources_after_normalizing(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["a"])

    result = ds.apply(
        MapValuesStep(
            column="v",
            match="ignore_case_and_spaces",
            mappings=[
                ValueMapping(from_value="Sales", to_value="A"),
                ValueMapping(from_value=" sales", to_value="B"),
            ],
        )
    )

    assert result.outcomes[0].status is StepStatus.BLOCKED
    assert "more than once" in (result.outcomes[0].reason or "")


def test_map_values_with_a_thousand_mappings(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["k999", "k0", "other"])
    mappings = [ValueMapping(from_value=f"k{i}", to_value=f"v{i}") for i in range(1000)]

    ds.apply(MapValuesStep(column="v", mappings=mappings))

    assert ds.column("v") == ["v999", "v0", "other"]


# --- null_placeholders ------------------------------------------------------------------------


def test_null_placeholders(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["N/A", " n/a ", "-", "Nancy", "NA"])

    result = ds.apply(NullPlaceholdersStep(columns=["v"], placeholders=["N/A", "-"]))

    assert ds.column("v") == [None, None, None, "Nancy", "NA"]
    assert result.outcomes[0].cells_changed == 3


# --- cast_number ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "options", "expected"),
    [
        (["1200", "$1,200.50", "(35)", "-4", " 7 "], {}, [1200.0, 1200.5, -35.0, -4.0, 7.0]),
        (["12%", "0.5%"], {}, [12.0, 0.5]),
        (["12%", "0.5%"], {"percent": "fraction"}, [0.12, 0.005]),
        (["1.200,50", "3,5", "€7"], {"decimal_separator": ","}, [1200.5, 3.5, 7.0]),
        (["85k", "$1.5M", "12"], {"allow_k_m_suffix": True}, [85000.0, 1500000.0, 12.0]),
        (["85k"], {}, [None]),
        (["abc", "12abc", "N/A", ""], {}, [None, None, None, None]),
    ],
)
def test_cast_number(
    make_dataset: MakeDataset,
    values: list[str],
    options: dict[str, object],
    expected: list[float | None],
) -> None:
    ds = one_column(make_dataset, values)

    ds.apply(CastNumberStep.model_validate({"column": "v", **options}))

    actual = ds.column("v")
    assert [value is None for value in actual] == [value is None for value in expected]
    assert [v for v in actual if v is not None] == pytest.approx(
        [v for v in expected if v is not None]
    )


def test_cast_number_counts_real_changes_and_unreadable_values(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["85000", "$85,000", "oops", "", "12.50"])

    result = ds.apply(CastNumberStep(column="v"))
    outcome = result.outcomes[0]

    # "85000" and "12.50" already read as those numbers, so they aren't changes.
    assert outcome.cells_changed == 2
    assert outcome.values_unreadable == 1
    assert [(c[3], c[4], c[5]) for c in ds.changes()] == [
        ("$85,000", "85000", "changed"),
        ("oops", None, "cleared"),
    ]
    assert result.columns[1].kind.value == "number"


def test_cast_number_on_a_number_column_is_blocked(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["1"])

    result = ds.apply(CastNumberStep(column="v"), CastNumberStep(column="v"))

    assert result.outcomes[1].status is StepStatus.BLOCKED
    assert "holds numbers" in (result.outcomes[1].reason or "")


# --- parse_date -------------------------------------------------------------------------------


def test_parse_date_month_first(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["4/2/2021", "12/31/2020", "not a date", ""])

    result = ds.apply(ParseDateStep(column="v", formats=["%m/%d/%Y"]))

    assert ds.column("v") == [dt.date(2021, 4, 2), dt.date(2020, 12, 31), None, None]
    assert result.outcomes[0].cells_changed == 3
    assert result.outcomes[0].values_unreadable == 1


def test_parse_date_tries_formats_in_order(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["03/04/2024", "2024-05-06", "15 Mar 2024"])

    ds.apply(ParseDateStep(column="v", formats=["%d/%m/%Y", "%Y-%m-%d", "%d %b %Y"]))

    assert ds.column("v") == [dt.date(2024, 4, 3), dt.date(2024, 5, 6), dt.date(2024, 3, 15)]


def test_parse_date_as_datetime(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["2024-03-15 09:30:00"])

    result = ds.apply(ParseDateStep(column="v", formats=["%Y-%m-%d %H:%M:%S"], output="datetime"))

    assert ds.column("v") == [dt.datetime(2024, 3, 15, 9, 30)]
    assert ds.changes()[0][4] == "2024-03-15 09:30:00"
    assert result.columns[1].kind.value == "datetime"


# --- fill_missing -----------------------------------------------------------------------------


def test_fill_missing_with_a_value(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["a", "", "  ", "b"])

    result = ds.apply(FillMissingStep(column="v", strategy="value", value="unknown"))

    assert ds.column("v") == ["a", "unknown", "unknown", "b"]
    assert [change[5] for change in ds.changes()] == ["filled", "changed"]
    assert result.outcomes[0].cells_changed == 2


@pytest.mark.parametrize(("strategy", "expected"), [("mean", 20.0), ("median", 15.0)])
def test_fill_missing_with_mean_and_median(
    make_dataset: MakeDataset, strategy: str, expected: float
) -> None:
    ds = one_column(make_dataset, ["10", "", "15", "35"])

    ds.apply(
        CastNumberStep(column="v"),
        FillMissingStep.model_validate({"column": "v", "strategy": strategy}),
    )

    assert ds.column("v") == [10.0, expected, 15.0, 35.0]


def test_fill_missing_mean_on_text_is_blocked(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["10", ""])

    result = ds.apply(FillMissingStep(column="v", strategy="mean"))

    assert result.outcomes[0].status is StepStatus.BLOCKED
    assert ds.column("v") == ["10", None]


def test_fill_missing_most_common_breaks_ties_by_value(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["b", "a", "", "b", "a"])

    ds.apply(FillMissingStep(column="v", strategy="most_common"))

    assert ds.column("v") == ["b", "a", "a", "b", "a"]


def test_fill_missing_previous_uses_file_order(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["", "x", "", "", "y", ""])

    ds.apply(FillMissingStep(column="v", strategy="previous"))

    assert ds.column("v") == [None, "x", "x", "x", "y", "y"]


def test_fill_missing_number_and_date_values_must_fit(make_dataset: MakeDataset) -> None:
    ds = make_dataset("n,d,label\n5,2024-01-01,a\n,,b\n")

    good = ds.apply(
        CastNumberStep(column="n"),
        ParseDateStep(column="d", formats=["%Y-%m-%d"]),
        FillMissingStep(column="n", strategy="value", value=0),
        FillMissingStep(column="d", strategy="value", value="2023-12-31"),
    )
    assert all(o.status is StepStatus.APPLIED for o in good.outcomes)
    assert ds.column("n") == [5.0, 0.0]
    assert ds.column("d") == [dt.date(2024, 1, 1), dt.date(2023, 12, 31)]

    bad = ds.apply(
        CastNumberStep(column="n"),
        ParseDateStep(column="d", formats=["%Y-%m-%d"]),
        FillMissingStep(column="n", strategy="value", value="zero"),
        FillMissingStep(column="d", strategy="value", value="last tuesday"),
    )
    assert [o.status for o in bad.outcomes[2:]] == [StepStatus.BLOCKED, StepStatus.BLOCKED]
    assert "fill it with a number" in (bad.outcomes[2].reason or "")
    assert "isn't a date" in (bad.outcomes[3].reason or "")
