from collections.abc import Callable

import pytest

from app.steps.lineage import CellNotFoundError, cell_history, set_aside_rows, step_changes
from app.steps.models import (
    CastNumberStep,
    DedupeStep,
    NullPlaceholdersStep,
    SplitColumnStep,
    TrimStep,
)
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]

FILE = 'id,amount,region\n1," $1,200 ",North-East\n2,N/A,South-West\n3,50,North-East\n'


def cleaned(make_dataset: MakeDataset) -> Dataset:
    ds = make_dataset(FILE)
    ds.apply(
        TrimStep(columns=["amount"]),
        NullPlaceholdersStep(columns=["amount"], placeholders=["N/A"]),
        CastNumberStep(column="amount"),
        SplitColumnStep(column="region", delimiter="-", into=["area", "side"]),
        DedupeStep(columns=["region"]),
    )
    return ds


def test_cell_changed_by_several_steps(make_dataset: MakeDataset) -> None:
    ds = cleaned(make_dataset)
    assert ds.result is not None
    trim, _, cast, _, _ = ds.result.outcomes

    history = cell_history(ds.conn, ds.result, 1, "amount")

    assert history.original == " $1,200 "
    assert history.in_original_file
    assert [(c.step_id, c.before, c.after, c.kind) for c in history.changes] == [
        (trim.step_id, " $1,200 ", "$1,200", "changed"),
        (cast.step_id, "$1,200", "1200", "changed"),
    ]
    assert history.current == "1200"
    assert history.set_aside is None


def test_cell_cleared_by_a_placeholder_step(make_dataset: MakeDataset) -> None:
    ds = cleaned(make_dataset)
    assert ds.result is not None

    history = cell_history(ds.conn, ds.result, 2, "amount")

    assert [(c.before, c.after, c.kind) for c in history.changes] == [("N/A", None, "cleared")]
    assert history.current is None


def test_untouched_cell(make_dataset: MakeDataset) -> None:
    ds = cleaned(make_dataset)
    assert ds.result is not None

    history = cell_history(ds.conn, ds.result, 2, "id")

    assert (history.original, history.changes, history.current) == ("2", [], "2")


def test_cell_in_a_created_column(make_dataset: MakeDataset) -> None:
    ds = cleaned(make_dataset)
    assert ds.result is not None

    history = cell_history(ds.conn, ds.result, 2, "side")

    assert history.in_original_file is False
    assert history.original is None
    assert [(c.before, c.after, c.kind) for c in history.changes] == [
        ("South-West", "West", "created")
    ]
    assert history.current == "West"


def test_cell_in_a_set_aside_row(make_dataset: MakeDataset) -> None:
    ds = cleaned(make_dataset)
    assert ds.result is not None
    dedupe = ds.result.outcomes[4]

    history = cell_history(ds.conn, ds.result, 3, "amount")

    assert history.set_aside is not None
    assert history.set_aside.step_id == dedupe.step_id
    assert history.set_aside.reason == 'Same "region" as an earlier row.'
    assert history.current is None
    # Changes made before the row was set aside are still traceable.
    assert history.original == "50"


def test_unknown_cells(make_dataset: MakeDataset) -> None:
    ds = cleaned(make_dataset)
    assert ds.result is not None

    with pytest.raises(CellNotFoundError):
        cell_history(ds.conn, ds.result, 99, "amount")
    with pytest.raises(CellNotFoundError):
        cell_history(ds.conn, ds.result, 1, "nope")


def test_cell_history_needs_lineage(make_dataset: MakeDataset) -> None:
    ds = make_dataset(FILE)
    result = ds.apply(TrimStep(columns=["amount"]), lineage=False)

    with pytest.raises(ValueError, match="lineage"):
        cell_history(ds.conn, result, 1, "amount")


def test_change_log_holds_only_changed_cells(make_dataset: MakeDataset) -> None:
    ds = make_dataset("a,b\nx,1\ny,2\n")

    ds.apply(TrimStep(columns=["a", "b"]))

    assert ds.conn.execute("SELECT count(*) FROM work.changes").fetchone() == (0,)


def test_step_counts_match_the_change_log(make_dataset: MakeDataset) -> None:
    ds = cleaned(make_dataset)
    assert ds.result is not None

    for outcome in ds.result.outcomes:
        logged = ds.conn.execute(
            "SELECT count(*) FROM work.changes WHERE step_id = $s", {"s": outcome.step_id}
        ).fetchone()
        assert logged == (outcome.cells_changed,)


def test_step_changes_sample(make_dataset: MakeDataset) -> None:
    ds = cleaned(make_dataset)
    assert ds.result is not None
    split = ds.result.outcomes[3]

    sample = step_changes(ds.conn, split.step_id, limit=3)

    assert [(c.row_id, c.column, c.after) for c in sample] == [
        (1, "area", "North"),
        (1, "side", "East"),
        (2, "area", "South"),
    ]


def test_set_aside_rows_show_values_as_uploaded(make_dataset: MakeDataset) -> None:
    ds = cleaned(make_dataset)

    rows = set_aside_rows(ds.conn)

    assert len(rows) == 1
    assert rows[0].row_id == 3
    assert rows[0].values == {"id": "3", "amount": "50", "region": "North-East"}
