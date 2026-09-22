"""Turn a phone number into one consistent shape, without guessing at ones it can't confirm.

Uses the phonenumbers library (a port of Google's libphonenumber), so a
number's own country code decides how it's grouped and spaced, instead of a
hand-written per-country rulebook. A number the library can't parse, or whose
digit count isn't plausible for its country, is returned exactly as it was:
this only ever tidies punctuation, never the digits themselves.

Deliberately checks "possible" (a plausible digit count for its country), not
"valid" (a real, assigned area code and exchange). Sample and demo files often
use invented area codes that are the right shape but aren't real, and those
still deserve consistent punctuation; this only ever rewrites separators, so
it never claims a number is real, only that it's shaped like one.
"""

import phonenumbers

# Used only for a number with no country code of its own to go by. There's no
# way to know a bare number's country from its digits alone, so this is a
# stated convention, not something inferred per file.
DEFAULT_REGION = "US"


def format_phone_or_original(value: str | None, default_region: str) -> str | None:
    """`value` reformatted to a standard shape for its country, or unchanged.

    `default_region` (an ISO 3166-1 alpha-2 code, e.g. "US") is used only when
    `value` has no country code of its own to go by.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return value
    try:
        parsed = phonenumbers.parse(text, default_region)
    except phonenumbers.NumberParseException:
        return value
    if not phonenumbers.is_possible_number(parsed):
        return value
    style = (
        phonenumbers.PhoneNumberFormat.INTERNATIONAL
        if text.startswith("+")
        else phonenumbers.PhoneNumberFormat.NATIONAL
    )
    formatted = phonenumbers.format_number(parsed, style)
    # A number with the right digit count but no recognisable dialling
    # pattern (a placeholder like "000-000-0000", a 7-digit local number)
    # formats as a bare run of digits: punctuation removed, none put back.
    # That reads worse than the original, so leave those alone too.
    if not any(character in formatted for character in " -()"):
        return value
    return formatted
