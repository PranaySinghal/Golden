import pytest

from app.profile.notes import _percent


@pytest.mark.parametrize(
    ("part", "whole", "expected"),
    [
        (1020, 1020, "100%"),
        (996, 1020, "98%"),
        (999, 1000, "over 99%"),
        (1, 1000, "under 1%"),
        (0, 50, "0%"),
        (5, 0, "0%"),
    ],
)
def test_percent_never_hides_a_remainder(part: int, whole: int, expected: str) -> None:
    assert _percent(part, whole) == expected
