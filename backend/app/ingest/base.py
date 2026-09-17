from pathlib import PurePath
from typing import Protocol

from app.errors import UnreadableFileError, UnsupportedFormatError
from app.ingest.models import IngestOptions, SourceFormat, SourceTable

_ZIP_SIGNATURE = b"PK\x03\x04"
# Old binary Office files (.xls) start with the OLE compound document signature.
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_TEXT_EXTENSIONS = {".csv", ".tsv", ".txt"}
_EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}


class FileAdapter(Protocol):
    """Turns file bytes into rows of text. Adding a format means adding an adapter."""

    format: SourceFormat

    def read(self, data: bytes, options: IngestOptions) -> SourceTable: ...


def detect_format(filename: str, data: bytes) -> SourceFormat:
    """Pick a format from the file's contents first and its name second.

    Contents win because files get renamed: an Excel workbook saved as
    "report.csv" is still a workbook.
    """
    extension = PurePath(filename).suffix.lower()

    if data.startswith(_OLE_SIGNATURE) or extension == ".xls":
        raise UnsupportedFormatError(
            "This looks like an older Excel file (.xls). Please save it as .xlsx or CSV "
            "and upload it again."
        )
    if data.startswith(_ZIP_SIGNATURE):
        if extension in _EXCEL_EXTENSIONS or extension in _TEXT_EXTENSIONS or extension == "":
            return SourceFormat.XLSX
        raise _unsupported(extension)
    if extension in _EXCEL_EXTENSIONS:
        raise UnreadableFileError(
            "This file is named like an Excel file but isn't one we can open. "
            "Try saving it again from Excel."
        )
    if extension in _TEXT_EXTENSIONS or extension == "":
        return SourceFormat.CSV
    raise _unsupported(extension)


def _unsupported(extension: str) -> UnsupportedFormatError:
    shown = extension or "this"
    return UnsupportedFormatError(
        f"We can't open {shown} files yet. Please upload a CSV or Excel (.xlsx) file."
    )
