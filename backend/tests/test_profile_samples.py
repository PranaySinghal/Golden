"""Golden profiles for the sample datasets.

Each sample is profiled twice: with its real headers, and with every header
replaced by col_1..col_n. Roles must come from the values, so the anonymized run
may only differ where a golden file lists an override (and every override must
be a column whose role relied on a name hint).
"""

import json
import re
from pathlib import Path
from typing import Any

import duckdb
import pytest

from app.profile.models import ColumnFlag, DatasetProfile
from app.profile.profiler import profile_table
from tests.conftest import GOLDEN_DIR, SAMPLE_FILES, SAMPLES, SAMPLES_DIR, load

# Anonymising a header means rewriting the first line, which only works on text.
CSV_SAMPLES = [name for name, file in SAMPLE_FILES.items() if file.endswith(".csv")]
JARGON = re.compile(
    r"\b(null|nan|varchar|string|dtype|regex|cardinality|semantic|schema|parse|boolean"
    r"|column type|data type|duplicate rows)\b",
    re.IGNORECASE,
)


def golden(sample: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((GOLDEN_DIR / "profile" / f"{sample}.json").read_text())
    return data


def profile_sample(sample: str, anonymize: bool = False) -> DatasetProfile:
    filename = SAMPLE_FILES[sample]
    data = (SAMPLES_DIR / filename).read_bytes()
    if anonymize:
        header, rest = data.split(b"\n", 1)
        width = len(header.split(b","))
        data = ",".join(f"col_{i + 1}" for i in range(width)).encode() + b"\n" + rest
    conn = duckdb.connect(":memory:")
    try:
        load(conn, data, filename=filename)
        return profile_table(conn)
    finally:
        conn.close()


def check_column(actual: Any, expected: dict[str, Any]) -> None:
    label = actual.name
    assert actual.semantic_role.value == expected["role"], label
    assert actual.physical_type.value == expected["physical_type"], label
    assert sorted(f.value for f in actual.flags) == sorted(expected["flags"]), label
    if "min" in expected:
        assert (actual.min_value, actual.max_value) == (expected["min"], expected["max"]), label
    patterns = {p.kind.value: p.detail for p in actual.patterns}
    for kind, detail in expected.get("patterns", {}).items():
        assert kind in patterns, f"{label}: missing {kind}"
        if detail is not None:
            assert patterns[kind] == detail, label


@pytest.mark.parametrize("sample", SAMPLES)
def test_sample_matches_golden_profile(sample: str) -> None:
    expected = golden(sample)
    profile = profile_sample(sample)

    assert profile.row_count == expected["row_count"]
    assert [c.name for c in profile.columns] == list(expected["columns"])
    for column in profile.columns:
        check_column(column, expected["columns"][column.name])


@pytest.mark.parametrize("sample", CSV_SAMPLES)
def test_roles_survive_anonymized_headers(sample: str) -> None:
    expected = golden(sample)
    named = profile_sample(sample)
    anonymous = profile_sample(sample, anonymize=True)
    overrides: dict[str, dict[str, Any]] = expected["anonymized_overrides"]

    for original, column in zip(named.columns, anonymous.columns, strict=True):
        if original.name in overrides:
            assert ColumnFlag.NAME_HINT_USED in original.flags, original.name
            check_column(column, overrides[original.name])
        else:
            check_column(column, expected["columns"][original.name])


def test_employee_acceptance_roles() -> None:
    """M1 acceptance criteria, spelled out."""
    columns = {c.name: c for c in profile_sample("Messy_Employee_dataset").columns}

    assert columns["Employee_ID"].semantic_role.value == "identifier"
    assert columns["Email"].semantic_role.value == "contact"
    assert ColumnFlag.LOW_UNIQUENESS in columns["Email"].flags
    assert columns["Email"].uniqueness < 0.1
    assert columns["Department_Region"].semantic_role.value == "category"
    assert columns["Salary"].semantic_role.value == "measure"
    assert any(p.detail == "N/A" for p in columns["Salary"].patterns)
    assert columns["Join_Date"].semantic_role.value == "date"


def test_samples_are_structurally_different() -> None:
    employee = profile_sample("Messy_Employee_dataset")
    orders = profile_sample("store_orders")

    assert not {c.name for c in employee.columns} & {c.name for c in orders.columns}
    assert employee.column_count != orders.column_count
    employee_roles = sorted(c.semantic_role.value for c in employee.columns)
    order_roles = sorted(c.semantic_role.value for c in orders.columns)
    assert employee_roles != order_roles


@pytest.mark.parametrize("sample", SAMPLES)
def test_role_notes_use_business_language(sample: str) -> None:
    for column in profile_sample(sample).columns:
        assert column.role_note.strip(), column.name
        assert not JARGON.search(column.role_note), f"{column.name}: {column.role_note}"


def test_golden_files_exist_for_every_sample() -> None:
    """Every file in data/samples is a fixture, and every fixture has a golden file."""
    on_disk = {path.name for path in Path(SAMPLES_DIR).iterdir() if path.is_file()}

    assert on_disk == set(SAMPLE_FILES.values())
    for name in SAMPLES:
        assert (GOLDEN_DIR / "profile" / f"{name}.json").exists(), name
