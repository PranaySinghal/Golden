import csv
import io
from collections import Counter
from collections.abc import Iterator

from app.errors import UnreadableFileError
from app.ingest.decode import decode_text
from app.ingest.models import IngestOptions, SourceFormat, SourceTable

_CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]
_SNIFF_CHARS = 64_000
_SNIFF_ROWS = 50
# The csv module's default per-field cap (131 KB) rejects legitimate long text
# cells; the upload size limit already bounds memory.
_FIELD_SIZE_LIMIT = 2**31 - 1


class CsvAdapter:
    format = SourceFormat.CSV

    def read(self, data: bytes, options: IngestOptions) -> SourceTable:
        text, encoding = decode_text(data)
        delimiter = sniff_delimiter(text[:_SNIFF_CHARS])
        return SourceTable(rows=_read_rows(text, delimiter), encoding=encoding, delimiter=delimiter)


def sniff_delimiter(sample: str) -> str:
    """Pick the separator that splits the most rows into the same number of fields.

    csv.Sniffer is avoided because it guesses letters as delimiters on
    single-column files and raises on many real exports.
    """
    if "\n" in sample:
        # The sample may end mid-row; drop the partial last line.
        sample = sample[: sample.rfind("\n")]

    best, best_score = ",", 0.0
    for delimiter in _CANDIDATE_DELIMITERS:
        widths: list[int] = []
        try:
            reader = csv.reader(io.StringIO(sample, newline=""), delimiter=delimiter)
            for row in reader:
                if row:
                    widths.append(len(row))
                if len(widths) >= _SNIFF_ROWS:
                    break
        except csv.Error:
            continue
        if not widths:
            continue
        width, count = Counter(widths).most_common(1)[0]
        if width < 2:
            continue
        # Consistency matters most; more fields breaks ties between consistent choices.
        score = count / len(widths) + width / 10_000
        if score > best_score:
            best, best_score = delimiter, score
    return best


def _read_rows(text: str, delimiter: str) -> Iterator[list[str | None]]:
    csv.field_size_limit(_FIELD_SIZE_LIMIT)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        for row in reader:
            yield [value if value != "" else None for value in row]
    except csv.Error as exc:
        raise UnreadableFileError(
            f"We couldn't read row {reader.line_num} of this file. It may have an unclosed "
            "quote. Try opening and re-saving it in your spreadsheet app."
        ) from exc
