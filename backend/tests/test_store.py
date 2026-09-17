"""The dataset flow the upload endpoint (M6) will wrap: file bytes in, a stored,
profiled dataset out, plus re-reading with different options."""

import threading

import pytest

from app.config import Settings
from app.errors import (
    DatasetNotFoundError,
    EmptyFileError,
    FileTooLargeError,
    SheetNotFoundError,
    UnsupportedFormatError,
)
from app.ingest.models import HeaderMode, IngestOptions, SourceFormat
from app.profile.models import SemanticRole
from app.store import DatasetStore
from tests.conftest import SAMPLES_DIR, make_xlsx

EMPLOYEE = (SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes()
ORDERS = (SAMPLES_DIR / "store_orders.csv").read_bytes()


@pytest.fixture
def store() -> DatasetStore:
    return DatasetStore(Settings(max_datasets=3))


def raw_count(store: DatasetStore, dataset_id: str) -> int:
    row = store.get(dataset_id).conn.execute("SELECT count(*) FROM raw").fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.parametrize(
    ("filename", "data", "rows", "columns"),
    [
        ("Messy_Employee_dataset.csv", EMPLOYEE, 1020, 12),
        ("store_orders.csv", ORDERS, 64, 11),
    ],
)
def test_create_ingests_and_profiles(
    store: DatasetStore, filename: str, data: bytes, rows: int, columns: int
) -> None:
    session = store.create(filename, data)

    assert len(session.id) == 32
    assert session.filename == filename
    assert session.ingest.row_count == rows
    assert session.profile.row_count == rows
    assert session.profile.column_count == columns
    assert [c.name for c in session.profile.columns] == session.ingest.columns
    assert raw_count(store, session.id) == rows
    assert store.get(session.id) is session


def test_datasets_are_isolated(store: DatasetStore) -> None:
    employees = store.create("employees.csv", EMPLOYEE)
    orders = store.create("orders.csv", ORDERS)

    assert employees.id != orders.id
    assert raw_count(store, employees.id) == 1020
    assert raw_count(store, orders.id) == 64


def test_excel_upload_flow_with_chosen_sheet(store: DatasetStore) -> None:
    data = make_xlsx(
        {"Notes": [["text"], ["hello"]], "Data": [["email"], ["a@x.com"], ["b@x.com"]]}
    )

    session = store.create("book.xlsx", data, IngestOptions(sheet="Data"))

    assert session.ingest.format is SourceFormat.XLSX
    assert session.ingest.available_sheets == ["Notes", "Data"]
    assert session.profile.columns[0].semantic_role is SemanticRole.CONTACT


def test_reingest_with_first_row_is_data_keeps_the_id(store: DatasetStore) -> None:
    session = store.create("regions.csv", b"north,east\nsouth,west\n")
    assert session.ingest.header_detected is True
    old_conn = session.conn

    updated = store.reingest(session.id, IngestOptions(header=HeaderMode.FIRST_ROW_IS_DATA))

    assert updated.id == session.id
    assert updated.ingest.header_detected is False
    assert updated.ingest.columns == ["column_1", "column_2"]
    assert updated.profile.row_count == 2
    assert store.get(session.id) is updated
    assert raw_count(store, session.id) == 2
    with pytest.raises(Exception, match="closed"):
        old_conn.execute("SELECT 1")


def test_failed_reingest_leaves_the_dataset_untouched(store: DatasetStore) -> None:
    data = make_xlsx({"Only": [["a"], ["1"]]})
    session = store.create("book.xlsx", data)

    with pytest.raises(SheetNotFoundError):
        store.reingest(session.id, IngestOptions(sheet="Missing"))

    assert store.get(session.id) is session
    assert raw_count(store, session.id) == 1


@pytest.mark.parametrize(
    ("filename", "data", "error"),
    [
        ("empty.csv", b"", EmptyFileError),
        ("notes.pdf", b"%PDF-1.4", UnsupportedFormatError),
        ("big.csv", b"a\n" + b"1\n" * 600, FileTooLargeError),
    ],
)
def test_rejected_uploads_are_not_stored(
    filename: str, data: bytes, error: type[Exception]
) -> None:
    store = DatasetStore(Settings(max_upload_bytes=1000))

    with pytest.raises(error):
        store.create(filename, data)

    assert len(store) == 0


def test_errors_carry_user_friendly_messages() -> None:
    store = DatasetStore(Settings(max_upload_bytes=10))

    with pytest.raises(FileTooLargeError) as excinfo:
        store.create("big.csv", b"a,b\n1,2\n3,4\n")

    assert excinfo.value.code == "file_too_large"
    assert excinfo.value.http_status == 413
    assert "limit" in excinfo.value.message


def test_unknown_dataset(store: DatasetStore) -> None:
    with pytest.raises(DatasetNotFoundError) as excinfo:
        store.get("nope")
    assert excinfo.value.http_status == 404

    with pytest.raises(DatasetNotFoundError):
        store.reingest("nope", IngestOptions())
    with pytest.raises(DatasetNotFoundError):
        store.delete("nope")


def test_delete_closes_the_dataset(store: DatasetStore) -> None:
    session = store.create("a.csv", b"x\n1\n")

    store.delete(session.id)

    assert len(store) == 0
    with pytest.raises(DatasetNotFoundError):
        store.get(session.id)
    with pytest.raises(Exception, match="closed"):
        session.conn.execute("SELECT 1")


def test_oldest_dataset_is_evicted_past_the_limit(store: DatasetStore) -> None:
    ids = [store.create(f"f{i}.csv", f"x\n{i}\n".encode()).id for i in range(4)]

    assert len(store) == 3
    with pytest.raises(DatasetNotFoundError):
        store.get(ids[0])
    for dataset_id in ids[1:]:
        assert store.get(dataset_id).id == dataset_id


def test_concurrent_creates(store: DatasetStore) -> None:
    big_store = DatasetStore(Settings(max_datasets=50))
    errors: list[BaseException] = []

    def upload(index: int) -> None:
        try:
            big_store.create(f"f{index}.csv", ORDERS)
        except BaseException as exc:  # collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=upload, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(big_store) == 8
