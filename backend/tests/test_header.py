import pytest

from app.ingest.header import clean_column_names, detect_header, resolve_header
from app.ingest.models import HeaderMode


def rows(*lines: str) -> list[list[str | None]]:
    return [[cell if cell != "" else None for cell in line.split(",")] for line in lines]


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        # A label above numbers or dates is a header.
        (rows("age,joined", "25,2024-01-01", "31,2024-02-01"), True),
        # Numbers above numbers: the first row is data.
        (rows("25,2024-01-01", "31,2024-02-01", "40,2024-03-01"), False),
        # All-text columns give no signal, so assume a header.
        (rows("north,east", "south,west"), True),
        (rows("name,city", "Ann,Oslo", "Bo,Rome"), True),
        # One typed column with a label is enough, even if other columns disagree.
        (rows("id,2023,total", "A,10,5", "B,20,6"), True),
        # Known limit: a number used as the only typed column's name looks like
        # data. The "first row is a header" toggle covers this.
        (rows("id,2023", "A,10", "B,20"), False),
        # Formatted numbers count as numbers.
        ([["total"], ["$1,200.00"], ["$950.00"], ["(35.10)"]], True),
        ([["$1,200.00"], ["$950.00"], ["(35.10)"]], False),
        # A single row can only be a header (a header-only file).
        (rows("a,b"), True),
        # Blank first-row cells carry no vote.
        (rows(",age", ",25", ",31"), True),
        (rows(",5", "x,6", "y,7"), False),
        # Mostly numbers with one placeholder still counts as a number column.
        (rows("price", "10", "N/A", "12", "13", "14"), True),
    ],
)
def test_detect_header(sample: list[list[str | None]], expected: bool) -> None:
    assert detect_header(sample) is expected


def test_resolve_header_respects_the_toggle() -> None:
    numeric = rows("1,2", "3,4")
    labels = rows("a,b", "c,d")

    assert resolve_header(HeaderMode.AUTO, numeric) is False
    assert resolve_header(HeaderMode.FIRST_ROW_IS_HEADER, numeric) is True
    assert resolve_header(HeaderMode.AUTO, labels) is True
    assert resolve_header(HeaderMode.FIRST_ROW_IS_DATA, labels) is False


def test_clean_column_names() -> None:
    assert clean_column_names(["  Name ", None, "", "name", "Name_2"], 7) == [
        "Name",
        "column_2",
        "column_3",
        "name_2",
        "Name_2_2",
        "column_6",
        "column_7",
    ]


def test_clean_column_names_avoids_generated_name_collisions() -> None:
    assert clean_column_names(["column_2", None], 2) == ["column_2", "column_2_2"]


def test_row_id_name_is_reserved() -> None:
    assert clean_column_names(["_ROW_ID", "_row_id"], 2) == ["_ROW_ID_2", "_row_id_3"]
