import codecs

from app.errors import UnreadableFileError

_BOMS: list[tuple[bytes, str]] = [
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
]

# cp1252 comes before latin-1 because Excel on Windows exports it, and it maps
# bytes like 0x80 to characters people actually use (the euro sign, curly
# quotes). latin-1 accepts any byte, so it is the last resort that never fails.
_FALLBACKS = ["utf-8", "cp1252", "latin-1"]


def decode_text(data: bytes) -> tuple[str, str]:
    """Return the decoded text and the name of the encoding that worked."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError as exc:
                raise _unreadable() from exc

    for encoding in _FALLBACKS:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            # Null characters mean binary data or UTF-16 without a byte order mark.
            raise _unreadable()
        return text, encoding

    raise _unreadable()


def _unreadable() -> UnreadableFileError:
    return UnreadableFileError(
        "We couldn't read the text in this file. Try saving it again as CSV (UTF-8) "
        "from your spreadsheet app."
    )
