"""Spaces before or after values (and doubled spaces inside labels)."""

from dataclasses import dataclass

from app.db import RAW_REF, quote_ident
from app.detectors import copy
from app.detectors.base import DetectorContext, IssueBuilder
from app.detectors.models import DetectorName, Issue, Tier
from app.profile.models import SemanticRole
from app.steps.models import TrimStep

# Numbers and dates are trimmed when they're read, so only text-like columns count.
ROLES = (SemanticRole.CATEGORY, SemanticRole.TEXT, SemanticRole.IDENTIFIER, SemanticRole.CONTACT)
EDGE_SPACES = r"^\s+.*|.*\s+$"
INNER_SPACES = r".*\S\s{2,}\S.*"


@dataclass(frozen=True)
class Evidence:
    edge_columns: list[str]
    inner_columns: list[str]  # category columns with doubled spaces inside
    rows: int
    examples: list[str]


def gather(ctx: DetectorContext) -> Evidence:
    columns = ctx.columns_with_role(*ROLES)
    edge, inner, conditions = [], [], []
    examples: list[str] = []
    for column in columns:
        ident = quote_ident(column.name)
        check_inner = column.semantic_role is SemanticRole.CATEGORY
        row = ctx.query(
            f"SELECT count_if(regexp_full_match({ident}, $edge)), "
            f"count_if(regexp_full_match({ident}, $inner)), "
            f"min({ident}) FILTER (WHERE regexp_full_match({ident}, $edge)) FROM {RAW_REF}",
            {"edge": EDGE_SPACES, "inner": INNER_SPACES},
        )[0]
        if row[0]:
            edge.append(column.name)
            examples.append(str(row[2]))
            conditions.append(f"regexp_full_match({ident}, $edge)")
        if check_inner and row[1]:
            inner.append(column.name)
            conditions.append(f"regexp_full_match({ident}, $inner)")
    rows = 0
    if conditions:
        params = {"edge": EDGE_SPACES}
        if inner:
            params["inner"] = INNER_SPACES
        sql = f"SELECT count(*) FROM {RAW_REF} WHERE {' OR '.join(conditions)}"
        rows = int(ctx.query(sql, params)[0][0])
    return Evidence(edge, inner, rows, examples)


def decide(evidence: Evidence, ctx: DetectorContext) -> list[Issue]:
    columns = list(dict.fromkeys(evidence.edge_columns + evidence.inner_columns))
    if not columns:
        return []
    b = IssueBuilder(ctx, DetectorName.EXTRA_SPACES, columns, "spaces")
    steps = []
    edge_only = [c for c in columns if c not in evidence.inner_columns]
    if edge_only:
        steps.append(b.step(TrimStep(columns=edge_only)))
    if evidence.inner_columns:
        steps.append(b.step(TrimStep(columns=evidence.inner_columns, collapse_inner_spaces=True)))
    title, explanation = copy.extra_spaces(evidence.rows, columns)
    return [
        b.build(
            title=title,
            explanation=explanation,
            affected_rows=evidence.rows,
            tier=Tier.SAFE,
            steps=steps,
            examples=evidence.examples,
        )
    ]


def run(ctx: DetectorContext) -> list[Issue]:
    return decide(gather(ctx), ctx)
