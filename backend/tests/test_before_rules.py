"""One test per "before" rule (app/compare/before.py)."""

from collections.abc import Callable

from app.compare.before import BeforeReading
from app.compare.evaluate import evaluate
from app.questions.models import Answer, DateGrain, Question, QuestionFilter
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]


def ask(ds: Dataset, **spec: object) -> Answer:
    question = Question.model_validate({"label": "q", "prominence": 1, **spec})
    return evaluate(ds.conn, question, BeforeReading([c.name for c in ds.profile.columns]))


def one_column(make_dataset: MakeDataset, values: list[str]) -> Dataset:
    rows = [f'{i},"{v}"' if v else f"{i}," for i, v in enumerate(values, 1)]
    return make_dataset("id,v\n" + "\n".join(rows) + "\n")


def test_b1_every_row_counts_including_repeats(make_dataset: MakeDataset) -> None:
    ds = make_dataset("a,b\nx,1\nx,1\ny,2\n")

    assert ask(ds, measure="count").value == 3


def test_b2_blanks_are_skipped_but_rows_still_count(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["a", "", "  ", "b"])

    assert ask(ds, measure="count").value == 4
    assert ask(ds, measure="count_distinct", column="v").value == 2


def test_b3_only_plain_numbers_are_numbers(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["10", " 20 ", "$30", "1,000", "12%", "85k", "N/A", "1e1"])

    total = ask(ds, measure="sum", column="v")

    assert total.value == 40
    assert (total.rows_used, total.rows_skipped) == (3, 5)


def test_b4_averages_leave_unreadable_values_out_of_the_count(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["10", "N/A", "20"])

    average = ask(ds, measure="avg", column="v")

    assert average.value == 15
    assert average.rows_skipped == 1


def test_b5_distinct_counts_ignore_case_but_not_spaces(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["Sales", "sales", "Sales "])

    assert ask(ds, measure="count_distinct", column="v").value == 2


def test_b6_groups_ignore_case_keep_spaces_and_blanks(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["Sales", "sales", "SALES", "Sales ", " Sales", "", "N/A"])

    groups = ask(ds, measure="count", group_by="v").groups

    # Equally common spellings are shown in alphabetical order, so "SALES" wins the tie.
    assert [(g.label, g.value) for g in groups] == [
        ("SALES", 3.0),
        (" Sales", 1.0),
        ("N/A", 1.0),
        ("Sales ", 1.0),
        (None, 1.0),
    ]


def test_b6_groups_show_the_most_common_spelling(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["sales", "Sales", "Sales"])

    assert ask(ds, measure="count", group_by="v").groups[0].label == "Sales"


def test_b7_only_iso_and_us_dates_are_dates(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["2024-03-15", "3/15/2024", "15/03/2024", "Mar 15, 2024"])

    trend = ask(ds, measure="count", group_by="v", grain="month")

    assert [(g.key, g.value) for g in trend.groups] == [("2024-03", 2.0)]
    assert trend.rows_skipped == 2


def test_b7_day_first_dates_are_misread_as_us_dates(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["04/03/2024"])

    trend = ask(ds, measure="count", group_by="v", grain=DateGrain.MONTH)

    assert trend.groups[0].key == "2024-04"


def test_b8_filters_ignore_case_but_not_spaces(make_dataset: MakeDataset) -> None:
    ds = make_dataset('status,n\nActive,1\nactive,2\n"Active ",3\nInactive,4\n')

    matched = ask(ds, measure="count", filter=QuestionFilter(column="status", equals="Active"))

    assert matched.value == 2


def test_b9_questions_with_nothing_readable_are_unanswerable(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["$1", "$2"])

    total = ask(ds, measure="sum", column="v")

    assert not total.answerable
    assert total.value is None
    assert total.note == 'No "v" values could be read as numbers.'


def test_unknown_column_is_unanswerable(make_dataset: MakeDataset) -> None:
    ds = one_column(make_dataset, ["1"])

    assert ask(ds, measure="sum", column="missing").note == 'There\'s no column called "missing".'
