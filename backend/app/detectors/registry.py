"""Run every detector and rank the issues."""

from collections.abc import Callable
from datetime import date

import duckdb

from app.detectors import (
    category_variants,
    combined_columns,
    contact_formats,
    dates,
    duplicates,
    extra_spaces,
    identifier_repeats,
    missing_values,
    numbers_as_text,
    out_of_range,
    placeholders,
)
from app.detectors.base import DetectorContext
from app.detectors.models import Issue, Tier
from app.profile.models import DatasetProfile

DETECTORS: list[Callable[[DetectorContext], list[Issue]]] = [
    placeholders.run,
    numbers_as_text.run,
    dates.run,
    extra_spaces.run,
    category_variants.run,
    combined_columns.run,
    duplicates.run,
    identifier_repeats.run,
    contact_formats.run,
    out_of_range.run,
    missing_values.run,
]

# Questions first, then things to review, then what's fixed automatically.
TIER_ORDER = {Tier.ASK: 0, Tier.LIKELY: 1, Tier.SAFE: 2}


def detect_issues(
    conn: duckdb.DuckDBPyConnection, profile: DatasetProfile, today: date | None = None
) -> list[Issue]:
    ctx = DetectorContext(conn=conn, profile=profile, today=today or date.today())
    return rank_issues([issue for detector in DETECTORS for issue in detector(ctx)], profile)


def rank_issues(issues: list[Issue], profile: DatasetProfile) -> list[Issue]:
    positions = {c.name: c.position for c in profile.columns}

    def rank(issue: Issue) -> tuple[float, int, int, str]:
        first_column = min((positions.get(c, 0) for c in issue.columns), default=-1)
        return (-issue.impact, TIER_ORDER[issue.tier], first_column, issue.id)

    return sorted(issues, key=rank)
