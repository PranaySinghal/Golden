"""The same label written different ways ("Sales", "sales ", "SALES"; "Home & Garden")."""

import re
from collections import defaultdict
from dataclasses import dataclass

from app.db import RAW_REF, quote_ident
from app.detectors import copy
from app.detectors.base import DetectorContext, IssueBuilder
from app.detectors.models import DetectorName, Issue, Tier
from app.profile.models import SemanticRole
from app.steps.models import MapValuesStep, ValueMapping
from app.steps.schema import normalize_text, trimmed

ROLES = (SemanticRole.CATEGORY, SemanticRole.TEXT)
MAX_DISTINCT = 5000
# Typos: only for longer labels, and only when one spelling clearly dominates.
TYPO_MIN_LENGTH = 6
TYPO_DOMINANCE = 5
TYPO_MAX_LABELS = 500


@dataclass(frozen=True)
class Evidence:
    column: str
    counts: list[tuple[str, int]]  # every distinct filled value as written


@dataclass(frozen=True)
class Group:
    canonical: str
    spellings: list[str]  # including the canonical one
    moved_rows: int  # rows not already written the canonical way


def gather(ctx: DetectorContext) -> list[Evidence]:
    found = []
    for column in ctx.columns_with_role(*ROLES):
        if column.distinct_count > MAX_DISTINCT or column.distinct_count < 2:
            continue
        ident = quote_ident(column.name)
        rows = ctx.query(
            f"SELECT {ident}, count(*) FROM {RAW_REF} WHERE {trimmed(ident)} IS NOT NULL "
            f"GROUP BY {ident} ORDER BY {ident}"
        )
        found.append(Evidence(column.name, [(str(value), int(n)) for value, n in rows]))
    return found


def loose_key(value: str) -> str:
    """Ignore case, spacing, "&" vs "and", and punctuation."""
    text = normalize_text(value).replace("&", " and ")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def one_edit_apart(a: str, b: str) -> bool:
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    shorter, longer = sorted((a, b), key=len)
    return any(longer[:i] + longer[i + 1 :] == shorter for i in range(len(longer)))


def _group(counts: dict[str, int], members: list[str]) -> Group:
    # Most common spelling wins; ties go to the tidier spelling, then alphabetical.
    canonical = min(members, key=lambda s: (-counts[s], s != " ".join(s.split()), s))
    return Group(canonical, sorted(members), sum(counts[m] for m in members if m != canonical))


def group_variants(counts: dict[str, int]) -> tuple[list[Group], list[Group]]:
    """Return (case/space groups, similar-spelling groups)."""
    by_exact: dict[str, list[str]] = defaultdict(list)
    for value in counts:
        by_exact[normalize_text(value)].append(value)
    exact_groups = [_group(counts, members) for members in by_exact.values() if len(members) > 1]

    # Totals per case/space-insensitive label, which the looser checks compare.
    label_counts = {key: sum(counts[m] for m in members) for key, members in by_exact.items()}
    label_display = {key: _group(counts, members).canonical for key, members in by_exact.items()}

    by_loose: dict[str, list[str]] = defaultdict(list)
    for key in label_counts:
        by_loose[loose_key(key)].append(key)
    merged: dict[str, str] = {}  # label key -> label key it joins
    for keys in by_loose.values():
        if len(keys) > 1:
            leader = min(keys, key=lambda k: (-label_counts[k], k))
            merged.update({k: leader for k in keys if k != leader})

    labels = [k for k in label_counts if k not in merged]
    if len(labels) <= TYPO_MAX_LABELS:
        for rare in labels:
            if len(rare) < TYPO_MIN_LENGTH or rare in merged:
                continue
            for common in labels:
                if (
                    common != rare
                    and common not in merged
                    and label_counts[common] >= TYPO_DOMINANCE * label_counts[rare]
                    and one_edit_apart(rare, common)
                ):
                    merged[rare] = common
                    break

    similar: dict[str, list[str]] = defaultdict(list)
    for key, leader in merged.items():
        similar[leader].append(key)
    similar_groups = [
        Group(
            canonical=label_display[leader],
            spellings=sorted([label_display[leader], *(label_display[k] for k in keys)]),
            moved_rows=sum(label_counts[k] for k in keys),
        )
        for leader, keys in similar.items()
    ]
    return exact_groups, similar_groups


def decide(evidence: list[Evidence], ctx: DetectorContext) -> list[Issue]:
    issues = []
    for item in evidence:
        counts = dict(item.counts)
        exact_groups, similar_groups = group_variants(counts)

        if exact_groups:
            b = IssueBuilder(ctx, DetectorName.CATEGORY_VARIANTS, [item.column], "case_space")
            moved = sum(g.moved_rows for g in exact_groups)
            biggest = max(exact_groups, key=lambda g: (g.moved_rows, g.canonical))
            title, explanation = copy.variants_case_space(item.column, moved, biggest.spellings[:3])
            step = b.step(
                MapValuesStep(
                    column=item.column,
                    match="ignore_case_and_spaces",
                    mappings=[
                        ValueMapping(from_value=g.canonical, to_value=g.canonical)
                        for g in exact_groups
                    ],
                )
            )
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=moved,
                    tier=Tier.SAFE,
                    steps=[step],
                    examples=[s for g in exact_groups for s in g.spellings if s != g.canonical],
                )
            )

        if similar_groups:
            b = IssueBuilder(ctx, DetectorName.CATEGORY_VARIANTS, [item.column], "similar")
            moved = sum(g.moved_rows for g in similar_groups)
            biggest = max(similar_groups, key=lambda g: (g.moved_rows, g.canonical))
            title, explanation = copy.variants_similar(item.column, moved, biggest.spellings[:3])
            step = b.step(
                MapValuesStep(
                    column=item.column,
                    match="ignore_case_and_spaces",
                    mappings=[
                        ValueMapping(from_value=spelling, to_value=g.canonical)
                        for g in similar_groups
                        for spelling in g.spellings
                        if normalize_text(spelling) != normalize_text(g.canonical)
                    ],
                )
            )
            issues.append(
                b.build(
                    title=title,
                    explanation=explanation,
                    affected_rows=moved,
                    tier=Tier.LIKELY,
                    steps=[step],
                    examples=[s for g in similar_groups for s in g.spellings],
                )
            )
    return issues


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
