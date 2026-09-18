"""Upload a file and read back what we learned about it. No business logic here."""

from typing import Annotated, BinaryIO

from fastapi import APIRouter, File, Form, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import SettingsDep, StoreDep
from app.errors import FileTooLargeError
from app.ingest.models import HeaderMode, IngestOptions, SourceFormat
from app.profile.models import ColumnProfile
from app.store import DatasetSession

router = APIRouter(prefix="/api", tags=["datasets"])

_CHUNK_BYTES = 1024 * 1024


class UploadLimits(BaseModel):
    max_upload_bytes: int


class DatasetSummary(BaseModel):
    id: str
    filename: str
    format: SourceFormat
    sheet_name: str | None
    available_sheets: list[str]
    header_mode: HeaderMode
    header_detected: bool
    row_count: int
    column_count: int
    empty_rows_skipped: int
    columns: list[ColumnProfile]


class ReingestRequest(BaseModel):
    sheet: str | None = Field(default=None, description="Excel sheet; None means the first one.")
    header: HeaderMode = HeaderMode.AUTO


@router.get("/upload-limits", response_model=UploadLimits, operation_id="getUploadLimits")
def get_upload_limits(settings: SettingsDep) -> UploadLimits:
    return UploadLimits(max_upload_bytes=settings.max_upload_bytes)


@router.post(
    "/datasets",
    response_model=DatasetSummary,
    status_code=status.HTTP_201_CREATED,
    operation_id="uploadDataset",
)
def upload_dataset(
    store: StoreDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="A CSV or Excel (.xlsx) file.")],
    sheet: Annotated[str | None, Form()] = None,
    header: Annotated[HeaderMode, Form()] = HeaderMode.AUTO,
) -> DatasetSummary:
    # Oversized requests that declare their size are turned away by
    # UploadSizeMiddleware before the body is read; this catches the rest.
    data = _read_within_limit(file.file, settings.max_upload_bytes)
    session = store.create(
        file.filename or "upload", data, IngestOptions(sheet=sheet, header=header)
    )
    return _summary(session)


@router.get("/datasets/{dataset_id}", response_model=DatasetSummary, operation_id="getDataset")
def get_dataset(dataset_id: str, store: StoreDep) -> DatasetSummary:
    return _summary(store.get(dataset_id))


@router.post(
    "/datasets/{dataset_id}/reingest",
    response_model=DatasetSummary,
    operation_id="reingestDataset",
)
def reingest_dataset(dataset_id: str, body: ReingestRequest, store: StoreDep) -> DatasetSummary:
    session = store.reingest(dataset_id, IngestOptions(sheet=body.sheet, header=body.header))
    return _summary(session)


def _read_within_limit(stream: BinaryIO, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := stream.read(_CHUNK_BYTES):
        size += len(chunk)
        if size > limit:
            raise FileTooLargeError(size, limit)
        chunks.append(chunk)
    return b"".join(chunks)


def _summary(session: DatasetSession) -> DatasetSummary:
    ingest = session.ingest
    return DatasetSummary(
        id=session.id,
        filename=session.filename,
        format=ingest.format,
        sheet_name=ingest.sheet_name,
        available_sheets=ingest.available_sheets,
        header_mode=ingest.header_mode,
        header_detected=ingest.header_detected,
        row_count=session.profile.row_count,
        column_count=session.profile.column_count,
        empty_rows_skipped=ingest.empty_rows_skipped,
        columns=session.profile.columns,
    )
