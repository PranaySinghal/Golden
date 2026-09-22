"""format_phone_or_original: tidy punctuation, never invent digits or a shape."""

from app.steps.phone import format_phone_or_original


def test_a_us_number_with_dashes_gets_parens_and_a_space() -> None:
    assert format_phone_or_original("415-555-0100", "US") == "(415) 555-0100"


def test_a_us_number_already_in_that_shape_is_unchanged() -> None:
    assert format_phone_or_original("(415) 555-0100", "US") == "(415) 555-0100"


def test_a_number_with_a_country_code_is_formatted_internationally() -> None:
    assert format_phone_or_original("+442079460958", "GB") == "+44 20 7946 0958"


def test_a_shape_with_no_real_area_code_is_still_reformatted() -> None:
    # "627" isn't an assigned NANP area code, but the shape is unambiguous, and
    # demo/sample files are full of invented-but-plausible numbers like this.
    assert format_phone_or_original("627-743-6636", "US") == "(627) 743-6636"


def test_a_bare_number_is_read_against_the_default_region() -> None:
    # No "+", so this is read as a GB number, which it doesn't dial like — GB's
    # formatter can't find a real pattern to group it by, and a bare run of
    # digits would read worse than the input, so it's left alone.
    assert format_phone_or_original("415-555-0100", "GB") == "415-555-0100"


def test_a_number_with_no_recognisable_dialling_pattern_is_unchanged() -> None:
    # Ten digits is a plausible length, but nothing groups an all-zero
    # placeholder into a real-looking number; stripping its dashes without
    # putting anything back would make it harder to read, not easier.
    assert format_phone_or_original("000-000-0000", "US") == "000-000-0000"


def test_unparseable_text_is_returned_unchanged() -> None:
    assert format_phone_or_original("call me maybe", "US") == "call me maybe"


def test_a_number_thats_too_short_to_be_one_is_unchanged() -> None:
    assert format_phone_or_original("415-555", "US") == "415-555"


def test_blank_and_none_pass_through() -> None:
    assert format_phone_or_original("", "US") == ""
    assert format_phone_or_original("   ", "US") == "   "
    assert format_phone_or_original(None, "US") is None


def test_reformatting_is_idempotent() -> None:
    once = format_phone_or_original("415-555-0100", "US")
    twice = format_phone_or_original(once, "US")
    assert once == twice
