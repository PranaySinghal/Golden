"""The "after" reading: the cleaned table, using the types the recipe gave each column."""

from app.compare.before import spreadsheet_params, text_column
from app.compare.reading import ColumnReading, RowSource
from app.db import quote_ident, work_ref
from app.steps.apply import CLEANED_TABLE, RecipePlan, chain_sql
from app.steps.schema import StageSchema, ValueKind, text_of


def _typed_column(expr: str, kind: ValueKind) -> ColumnReading:
    if kind is ValueKind.TEXT:
        # Columns a recipe left as text are read the spreadsheet way (B3, B5, B7).
        return text_column(expr)
    as_text = text_of(expr, kind)
    return ColumnReading(
        filled=f"({expr} IS NOT NULL)",
        number=f"CAST({expr} AS DOUBLE)" if kind is ValueKind.NUMBER else "CAST(NULL AS DOUBLE)",
        date=f"CAST({expr} AS TIMESTAMP)" if kind is not ValueKind.NUMBER else "NULL",
        key=f"lower({as_text})",
        label=as_text,
    )


class AfterReading:
    """Reads a cleaned table, or a recipe's step chain without materializing it."""

    name = "after"

    def __init__(self, schema: StageSchema, source: RowSource) -> None:
        self._schema = schema
        self._source = source

    @classmethod
    def cleaned_table(cls, schema: StageSchema) -> "AfterReading":
        return cls(schema, RowSource(work_ref(CLEANED_TABLE)))

    @classmethod
    def from_plan(cls, plan: RecipePlan) -> "AfterReading":
        """Answer questions straight from a recipe's steps, leaving work.cleaned alone."""
        sql, params = chain_sql(plan)
        return cls(plan.output, RowSource(f"({sql})", params))

    def rows(self) -> RowSource:
        return self._source

    def column(self, name: str) -> ColumnReading | None:
        column = self._schema.get(name)
        if column is None:
            return None
        return _typed_column(quote_ident(name), column.kind)

    def params(self) -> dict[str, object]:
        return spreadsheet_params()
