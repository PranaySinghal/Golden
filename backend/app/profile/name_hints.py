"""Generic words in column names, used only to break ties when values are ambiguous.

These are words that mean the same thing in any table ("phone", "id"), not
names from a particular dataset. A hint never overrides clear evidence from
the values.
"""

import re
from enum import StrEnum


class NameHint(StrEnum):
    PHONE = "phone"
    IDENTIFIER = "identifier"


_PHONE_WORDS = {"phone", "phones", "tel", "telephone", "mobile", "cell", "fax", "whatsapp"}
_IDENTIFIER_WORDS = {"id", "ids", "code", "ref", "reference", "key", "uuid", "guid", "sku", "no"}


def name_words(name: str) -> list[str]:
    # Split camelCase, then any run of non-letters: "EmployeeID" -> employee, id.
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return [word for word in re.split(r"[^A-Za-z]+", spaced.lower()) if word]


def name_hint(name: str) -> NameHint | None:
    words = set(name_words(name))
    # Checked first so "Phone ID" or "Phone No" still reads as a phone.
    if words & _PHONE_WORDS:
        return NameHint.PHONE
    if words & _IDENTIFIER_WORDS:
        return NameHint.IDENTIFIER
    return None
