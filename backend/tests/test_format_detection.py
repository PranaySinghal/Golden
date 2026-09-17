import pytest

from app.errors import UnreadableFileError, UnsupportedFormatError
from app.ingest.base import detect_format
from app.ingest.models import SourceFormat
from tests.conftest import make_xlsx

XLSX = make_xlsx({"S": [["a"], [1]]})
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100


@pytest.mark.parametrize("filename", ["data.csv", "DATA.CSV", "data.tsv", "data.txt", "data"])
def test_text_files_are_csv(filename: str) -> None:
    assert detect_format(filename, b"a,b\n1,2\n") is SourceFormat.CSV


@pytest.mark.parametrize("filename", ["book.xlsx", "book.XLSX", "book.xlsm", "book.csv", "book"])
def test_workbook_contents_are_excel(filename: str) -> None:
    assert detect_format(filename, XLSX) is SourceFormat.XLSX


@pytest.mark.parametrize("filename", ["old.xls", "old.csv", "old.xlsx"])
def test_old_excel_files_get_a_clear_message(filename: str) -> None:
    data = OLE if not filename.endswith(".xls") else b"anything"
    with pytest.raises(UnsupportedFormatError) as excinfo:
        detect_format(filename, data)
    assert ".xlsx or CSV" in excinfo.value.message


@pytest.mark.parametrize("filename", ["report.pdf", "image.png", "data.json", "archive.zip"])
def test_other_formats_are_unsupported(filename: str) -> None:
    data = b"PK\x03\x04..." if filename.endswith(".zip") else b"%PDF-1.4"
    with pytest.raises(UnsupportedFormatError):
        detect_format(filename, data)


def test_text_named_as_excel_is_unreadable() -> None:
    with pytest.raises(UnreadableFileError):
        detect_format("book.xlsx", b"a,b\n1,2\n")
