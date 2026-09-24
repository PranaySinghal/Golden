from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from tests.conftest import SAMPLES_DIR, make_xlsx

EMPLOYEE = (SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def limit_uploads(max_upload_bytes: int) -> None:
    app.state.settings = Settings(max_upload_bytes=max_upload_bytes)


def test_upload_csv_returns_a_summary(client: TestClient) -> None:
    response = client.post(
        "/api/datasets", files={"file": ("Messy_Employee_dataset.csv", EMPLOYEE, "text/csv")}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "Messy_Employee_dataset.csv"
    assert body["format"] == "csv"
    assert (body["row_count"], body["column_count"]) == (1020, 12)
    assert body["header_detected"] is True
    email = next(c for c in body["columns"] if c["name"] == "Email")
    assert email["semantic_role"] == "contact"
    assert "role_note" in email
    assert body["description"].startswith("Each row has an ID (“Employee_ID”)")

    again = client.get(f"/api/datasets/{body['id']}")
    assert again.status_code == 200
    assert again.json() == body


def test_upload_excel_with_a_chosen_sheet(client: TestClient) -> None:
    data = make_xlsx({"Notes": [["x"], ["y"]], "Data": [["email"], ["a@x.com"], ["b@x.com"]]})

    response = client.post(
        "/api/datasets", files={"file": ("book.xlsx", data)}, data={"sheet": "Data"}
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["format"], body["sheet_name"]) == ("xlsx", "Data")
    assert body["available_sheets"] == ["Notes", "Data"]


def test_reingest_with_first_row_as_data(client: TestClient) -> None:
    created = client.post(
        "/api/datasets", files={"file": ("regions.csv", b"north,east\nsouth,west\n")}
    ).json()
    assert created["row_count"] == 1

    response = client.post(
        f"/api/datasets/{created['id']}/reingest", json={"header": "data", "sheet": None}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert (body["header_mode"], body["header_detected"], body["row_count"]) == ("data", False, 2)
    assert [c["name"] for c in body["columns"]] == ["column_1", "column_2"]


def test_reingest_to_another_sheet(client: TestClient) -> None:
    data = make_xlsx({"A": [["x"], ["1"]], "B": [["y"], ["2"], ["3"]]})
    created = client.post("/api/datasets", files={"file": ("book.xlsx", data)}).json()

    body = client.post(f"/api/datasets/{created['id']}/reingest", json={"sheet": "B"}).json()

    assert (body["sheet_name"], body["row_count"]) == ("B", 2)


@pytest.mark.parametrize(
    ("filename", "data", "status", "code"),
    [
        ("empty.csv", b"", 422, "empty_file"),
        ("notes.pdf", b"%PDF-1.4", 415, "unsupported_format"),
        ("old.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 415, "unsupported_format"),
        ("book.xlsx", b"PK\x03\x04junk", 422, "unreadable_file"),
    ],
)
def test_upload_errors_are_friendly(
    client: TestClient, filename: str, data: bytes, status: int, code: str
) -> None:
    response = client.post("/api/datasets", files={"file": (filename, data)})

    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["message"]


def test_file_over_the_limit_is_rejected(client: TestClient) -> None:
    limit_uploads(100)

    response = client.post("/api/datasets", files={"file": ("big.csv", b"a\n" + b"1\n" * 200)})

    assert response.status_code == 413
    assert response.json()["code"] == "file_too_large"


def test_declared_size_over_the_limit_is_rejected_before_reading(client: TestClient) -> None:
    limit_uploads(100)

    # Over the limit plus the room kept for the envelope and any saved steps
    # sent alongside the file (api/limits.py).
    response = client.post(
        "/api/datasets",
        content=b"x" * 2_000_000,
        headers={"content-type": "multipart/form-data; boundary=zzz"},
    )

    # A malformed body would be a 400 if it were parsed; 413 means it never was.
    assert response.status_code == 413
    assert response.json()["code"] == "file_too_large"


def test_missing_sheet_on_reingest(client: TestClient) -> None:
    created = client.post(
        "/api/datasets", files={"file": ("book.xlsx", make_xlsx({"A": [["x"], ["1"]]}))}
    ).json()

    response = client.post(f"/api/datasets/{created['id']}/reingest", json={"sheet": "Nope"})

    assert response.status_code == 422
    assert response.json()["code"] == "sheet_not_found"


def test_unknown_dataset(client: TestClient) -> None:
    assert client.get("/api/datasets/nope").status_code == 404
    response = client.post("/api/datasets/nope/reingest", json={})
    assert response.status_code == 404
    assert response.json()["code"] == "dataset_not_found"


def test_upload_limits(client: TestClient) -> None:
    assert client.get("/api/upload-limits").json() == {"max_upload_bytes": 50 * 1024 * 1024}


def test_openapi_describes_the_upload_api(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert schema["info"]["title"] == "TidyLab"
    assert schema["paths"]["/api/datasets"]["post"]["operationId"] == "uploadDataset"
    assert "DatasetSummary" in schema["components"]["schemas"]
    assert "ColumnProfile" in schema["components"]["schemas"]
