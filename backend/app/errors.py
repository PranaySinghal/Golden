"""Typed errors. Each carries a stable code and a message safe to show a business user."""


class AppError(Exception):
    code: str = "app_error"
    http_status: int = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EmptyFileError(AppError):
    code = "empty_file"

    def __init__(self) -> None:
        super().__init__("This file is empty. Please choose a file that has some data in it.")


class FileTooLargeError(AppError):
    code = "file_too_large"
    http_status = 413

    def __init__(self, size_bytes: int, limit_bytes: int) -> None:
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"This file is {_format_mb(size_bytes)}, which is over the "
            f"{_format_mb(limit_bytes)} limit. Try a smaller file or split it up."
        )


class UnsupportedFormatError(AppError):
    code = "unsupported_format"
    http_status = 415


class UnreadableFileError(AppError):
    code = "unreadable_file"
    http_status = 422


class SheetNotFoundError(AppError):
    code = "sheet_not_found"
    http_status = 422

    def __init__(self, sheet: str, available: list[str]) -> None:
        self.sheet = sheet
        self.available = available
        names = ", ".join(f'"{name}"' for name in available) or "none"
        super().__init__(f'There is no sheet called "{sheet}" in this file. Sheets found: {names}.')


class DatasetNotFoundError(AppError):
    code = "dataset_not_found"
    http_status = 404

    def __init__(self, dataset_id: str) -> None:
        self.dataset_id = dataset_id
        super().__init__("We couldn't find that file. It may have expired; please upload it again.")


def _format_mb(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    if mb < 1:
        return f"{max(size_bytes // 1024, 1)} KB"
    return f"{mb:.0f} MB" if mb >= 10 else f"{mb:.1f} MB"
