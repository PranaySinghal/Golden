"""Compile each Step into parameterized DuckDB SQL.

Each step turns the previous stage (a CTE named by the caller) into the next
one. Identifiers only come from the input StageSchema and are always quoted;
every value from a step's parameters is bound as a named parameter prefixed
with the step's position, so no user or AI text is ever spliced into SQL.
The regular expressions written inline below are fixed code, not input.
"""

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum

from app.db import ROW_ID_COLUMN, quote_ident
from app.profile import patterns
from app.steps.errors import StepValidationError
from app.steps.models import (
    BlankCondition,
    CastNumberStep,
    DedupeStep,
    EqualsCondition,
    FillMissingStep,
    MapValuesStep,
    NormalizeCaseStep,
    NotMatchingCondition,
    NullPlaceholdersStep,
    OneOfCondition,
    OutsideRangeCondition,
    ParseDateStep,
    RowCondition,
    RowIdsCondition,
    SetAsideRowsStep,
    SplitColumnStep,
    Step,
    TrimStep,
)
from app.steps.schema import (
    KIND_WORDS,
    StageColumn,
    StageSchema,
    ValueKind,
    blank_predicate,
    match_key,
    normalize_text,
    text_of,
    trimmed,
)

ROW_ID = quote_ident(ROW_ID_COLUMN)


@dataclass(frozen=True)
class Fragment:
    sql: str
    params: dict[str, object] = field(default_factory=dict)


class ChangeMode(StrEnum):
    # Compare the text form of the value before and after.
    TEXT = "text"
    # Text became a number: unchanged if the text was already that plain number.
    NUMBER_FROM_TEXT = "number_from_text"
    # Every filled value counts, because reading it at all is the change (dates).
    ANY_FILLED = "any_filled"
    # A new column; the "before" is the value it was made from.
    CREATED = "created"


@dataclass(frozen=True)
class ChangeSpec:
    output_column: str
    source_column: str
    source_kind: ValueKind
    output_kind: ValueKind
    mode: ChangeMode


@dataclass(frozen=True)
class CompiledStep:
    step_id: str
    kept: Fragment
    output: StageSchema
    removed: Fragment | None = None
    removal_reason: str | None = None
    changes: tuple[ChangeSpec, ...] = ()
    reads: tuple[str, ...] = ()
    creates: tuple[str, ...] = ()


class _Builder:
    """Collects bound parameters for one step, each prefixed by the step's position."""

    def __init__(self, index: int) -> None:
        self._prefix = f"p{index}_"
        self.params: dict[str, object] = {}

    def bind(self, name: str, value: object) -> str:
        key = self._prefix + name
        self.params[key] = value
        return f"${key}"


def compile_step(step: Step, schema: StageSchema, *, index: int, source: str) -> CompiledStep:
    """Compile `step` to read from the CTE `source` whose columns are `schema`."""
    b = _Builder(index)
    match step:
        case TrimStep():
            return _trim(step, schema, b, source)
        case NormalizeCaseStep():
            return _normalize_case(step, schema, b, source)
        case MapValuesStep():
            return _map_values(step, schema, b, source)
        case NullPlaceholdersStep():
            return _null_placeholders(step, schema, b, source)
        case CastNumberStep():
            return _cast_number(step, schema, b, source)
        case ParseDateStep():
            return _parse_date(step, schema, b, source)
        case SplitColumnStep():
            return _split_column(step, schema, b, source)
        case DedupeStep():
            return _dedupe(step, schema, b, source)
        case SetAsideRowsStep():
            return _set_aside_rows(step, schema, b, source)
        case FillMissingStep():
            return _fill_missing(step, schema, b, source)


# --- shared helpers ----------------------------------------------------------------


def _require(
    schema: StageSchema,
    name: str,
    step: Step,
    kinds: set[ValueKind] | None = None,
    doing: str = "used this way",
) -> StageColumn:
    column = schema.get(name)
    if column is None:
        raise StepValidationError(
            f'There\'s no column called "{name}" at this point in the recipe.', step.id
        )
    if kinds is not None and column.kind not in kinds:
        raise StepValidationError(
            f'"{name}" holds {KIND_WORDS[column.kind]}, so it can\'t be {doing}.', step.id
        )
    return column


def _unique(names: list[str]) -> list[str]:
    return list(dict.fromkeys(names))


def _select_list(
    schema: StageSchema,
    replace: dict[str, str] | None = None,
    insert_after: dict[str, list[tuple[str, str]]] | None = None,
    drop: set[str] | None = None,
) -> str:
    parts = [ROW_ID]
    for column in schema.columns:
        ident = quote_ident(column.name)
        if not drop or column.name not in drop:
            expr = (replace or {}).get(column.name)
            parts.append(f"{expr} AS {ident}" if expr is not None else ident)
        for new_name, expr in (insert_after or {}).get(column.name, []):
            parts.append(f"{expr} AS {quote_ident(new_name)}")
    return ", ".join(parts)


def _with_kinds(schema: StageSchema, kinds: dict[str, ValueKind]) -> StageSchema:
    return StageSchema(
        tuple(StageColumn(c.name, kinds.get(c.name, c.kind)) for c in schema.columns)
    )


def _same_kind_changes(schema: StageSchema, names: list[str]) -> tuple[ChangeSpec, ...]:
    specs = []
    for name in names:
        column = schema.get(name)
        assert column is not None
        specs.append(ChangeSpec(name, name, column.kind, column.kind, ChangeMode.TEXT))
    return tuple(specs)


def _replace_text_columns(
    step: TrimStep | NormalizeCaseStep | NullPlaceholdersStep,
    schema: StageSchema,
    source: str,
    template: str,
    doing: str,
    params: dict[str, object],
) -> CompiledStep:
    names = _unique(step.columns)
    for name in names:
        _require(schema, name, step, {ValueKind.TEXT}, doing)
    # "{col}" in the template stands for the quoted column name.
    replace = {name: template.replace("{col}", quote_ident(name)) for name in names}
    return CompiledStep(
        step_id=step.id,
        kept=Fragment(f"SELECT {_select_list(schema, replace)} FROM {source}", params),
        output=schema,
        changes=_same_kind_changes(schema, names),
        reads=tuple(names),
    )


# --- text steps -----------------------------------------------------------------------


def _trim(step: TrimStep, schema: StageSchema, b: _Builder, source: str) -> CompiledStep:
    expr = trimmed("{col}")
    if step.collapse_inner_spaces:
        expr = f"NULLIF(regexp_replace({trimmed('{col}')}, '\\s+', ' ', 'g'), '')"
    return _replace_text_columns(step, schema, source, expr, "trimmed", b.params)


def _normalize_case(
    step: NormalizeCaseStep, schema: StageSchema, b: _Builder, source: str
) -> CompiledStep:
    match step.case:
        case "lower":
            expr = "lower({col})"
        case "upper":
            expr = "upper({col})"
        case "title":
            expr = (
                "array_to_string(list_transform(string_split(lower({col}), ' '), "
                "lambda w: upper(w[1]) || w[2:]), ' ')"
            )
    return _replace_text_columns(
        step, schema, source, expr, "changed to a different case", b.params
    )


def _null_placeholders(
    step: NullPlaceholdersStep, schema: StageSchema, b: _Builder, source: str
) -> CompiledStep:
    words = _unique([normalize_text(word) for word in step.placeholders])
    words_param = b.bind("words", words)
    expr = (
        f"CASE WHEN list_contains(CAST({words_param} AS VARCHAR[]), {match_key('{col}')}) "
        "THEN NULL ELSE {col} END"
    )
    return _replace_text_columns(
        step, schema, source, expr, "cleared of placeholder text", b.params
    )


def _map_values(step: MapValuesStep, schema: StageSchema, b: _Builder, source: str) -> CompiledStep:
    _require(schema, step.column, step, {ValueKind.TEXT}, "mapped to new values")
    col = quote_ident(step.column)
    key = col if step.match == "exact" else match_key(col)

    seen: set[str] = set()
    branches = []
    for position, mapping in enumerate(step.mappings):
        from_value = (
            mapping.from_value if step.match == "exact" else normalize_text(mapping.from_value)
        )
        if from_value in seen:
            raise StepValidationError(
                f'"{mapping.from_value}" is listed more than once in the mapping.', step.id
            )
        seen.add(from_value)
        when = b.bind(f"from{position}", from_value)
        then = b.bind(f"to{position}", mapping.to_value)
        branches.append(f"WHEN {when} THEN CAST({then} AS VARCHAR)")
    expr = f"CASE {key} {' '.join(branches)} ELSE {col} END"

    return CompiledStep(
        step_id=step.id,
        kept=Fragment(
            f"SELECT {_select_list(schema, {step.column: expr})} FROM {source}", b.params
        ),
        output=schema,
        changes=_same_kind_changes(schema, [step.column]),
        reads=(step.column,),
    )


# --- type steps -------------------------------------------------------------------------


def number_pattern(decimal_separator: str, allow_suffix: bool) -> str:
    """The shapes cast_number accepts, as a fixed regular expression."""
    if decimal_separator == ".":
        whole, fraction, leading = r"([0-9]{1,3}(,[0-9]{3})+|[0-9]+)", r"(\.[0-9]*)?", r"\.[0-9]+"
    else:
        whole, fraction, leading = r"([0-9]{1,3}(\.[0-9]{3})+|[0-9]+)", r"(,[0-9]*)?", r",[0-9]+"
    suffix = r"\s?[kKmM]?" if allow_suffix else ""
    return (
        rf"\(?[-+]?[$€£¥₹]?\s?[-+]?({whole}{fraction}|{leading})"
        rf"([eE][-+]?[0-9]+)?{suffix}\s?%?\)?"
    )


def _cast_number(
    step: CastNumberStep, schema: StageSchema, b: _Builder, source: str
) -> CompiledStep:
    _require(schema, step.column, step, {ValueKind.TEXT}, "turned into numbers")
    t = trimmed(quote_ident(step.column))
    pattern = b.bind("pattern", number_pattern(step.decimal_separator, step.allow_k_m_suffix))

    stripped = f"regexp_replace({t}, '[$€£¥₹\\s()%+kKmM]', '', 'g')"
    if step.decimal_separator == ",":
        digits = f"replace(replace({stripped}, '.', ''), ',', '.')"
    else:
        digits = f"replace({stripped}, ',', '')"
    sign = f"(CASE WHEN starts_with({t}, '(') AND ends_with({t}, ')') THEN -1 ELSE 1 END)"
    value = f"{sign} * TRY_CAST({digits} AS DOUBLE)"
    if step.allow_k_m_suffix:
        value += (
            f" * (CASE WHEN regexp_matches({t}, '[kK]\\s*%?\\)?$') THEN 1000 "
            f"WHEN regexp_matches({t}, '[mM]\\s*%?\\)?$') THEN 1000000 ELSE 1 END)"
        )
    if step.percent == "fraction":
        value += f" * (CASE WHEN contains({t}, '%') THEN 0.01 ELSE 1 END)"
    expr = f"CASE WHEN regexp_full_match({t}, {pattern}) THEN {value} END"

    return CompiledStep(
        step_id=step.id,
        kept=Fragment(
            f"SELECT {_select_list(schema, {step.column: expr})} FROM {source}", b.params
        ),
        output=_with_kinds(schema, {step.column: ValueKind.NUMBER}),
        changes=(
            ChangeSpec(
                step.column,
                step.column,
                ValueKind.TEXT,
                ValueKind.NUMBER,
                ChangeMode.NUMBER_FROM_TEXT,
            ),
        ),
        reads=(step.column,),
    )


def _parse_date(step: ParseDateStep, schema: StageSchema, b: _Builder, source: str) -> CompiledStep:
    _require(schema, step.column, step, {ValueKind.TEXT}, "read as dates")
    t = trimmed(quote_ident(step.column))
    attempts = [
        f"try_strptime({t}, {b.bind(f'format{position}', fmt)})"
        for position, fmt in enumerate(_unique(list(step.formats)))
    ]
    parsed = attempts[0] if len(attempts) == 1 else f"coalesce({', '.join(attempts)})"
    kind = ValueKind.DATE if step.output == "date" else ValueKind.DATETIME
    expr = f"CAST({parsed} AS DATE)" if kind is ValueKind.DATE else parsed

    return CompiledStep(
        step_id=step.id,
        kept=Fragment(
            f"SELECT {_select_list(schema, {step.column: expr})} FROM {source}", b.params
        ),
        output=_with_kinds(schema, {step.column: kind}),
        changes=(
            ChangeSpec(step.column, step.column, ValueKind.TEXT, kind, ChangeMode.ANY_FILLED),
        ),
        reads=(step.column,),
    )


# --- shape steps ----------------------------------------------------------------------------


def _split_column(
    step: SplitColumnStep, schema: StageSchema, b: _Builder, source: str
) -> CompiledStep:
    _require(schema, step.column, step, {ValueKind.TEXT}, "split")
    remaining = StageSchema(
        tuple(c for c in schema.columns if step.keep_original or c.name != step.column)
    )
    seen: set[str] = set()
    for name in step.into:
        folded = name.casefold()
        if folded == ROW_ID_COLUMN.casefold():
            raise StepValidationError(f'"{name}" is a reserved column name.', step.id)
        if folded in seen:
            raise StepValidationError(f'The new column "{name}" is named twice.', step.id)
        if remaining.name_taken(name):
            raise StepValidationError(
                f'There\'s already a column called "{name}". Pick a different name.', step.id
            )
        seen.add(folded)

    col = quote_ident(step.column)
    delimiter = b.bind("delimiter", step.delimiter)
    parts = f"string_split({col}, {delimiter})"
    last = len(step.into)
    new_columns = []
    for position, name in enumerate(step.into, start=1):
        if position < last:
            part = f"{parts}[{position}]"
        else:
            # The last column keeps the rest, so no text is lost when there are extra parts.
            part = f"array_to_string({parts}[{position}:], {delimiter})"
        expr = trimmed(part) if step.trim_parts else f"NULLIF({part}, '')"
        new_columns.append((name, expr))

    drop = set() if step.keep_original else {step.column}
    select = _select_list(schema, insert_after={step.column: new_columns}, drop=drop)

    output_columns: list[StageColumn] = []
    for column in schema.columns:
        if column.name not in drop:
            output_columns.append(column)
        if column.name == step.column:
            output_columns.extend(StageColumn(name, ValueKind.TEXT) for name in step.into)

    return CompiledStep(
        step_id=step.id,
        kept=Fragment(f"SELECT {select} FROM {source}", b.params),
        output=StageSchema(tuple(output_columns)),
        changes=tuple(
            ChangeSpec(name, step.column, ValueKind.TEXT, ValueKind.TEXT, ChangeMode.CREATED)
            for name in step.into
        ),
        reads=(step.column,),
        creates=tuple(step.into),
    )


# --- row steps ---------------------------------------------------------------------------------


def _keep_list(b: _Builder, row_ids: list[int]) -> str:
    return f"list_contains(CAST({b.bind('keep', row_ids)} AS BIGINT[]), {ROW_ID})"


def _dedupe(step: DedupeStep, schema: StageSchema, b: _Builder, source: str) -> CompiledStep:
    names = schema.names() if step.columns is None else _unique(step.columns)
    keys = []
    for name in names:
        column = _require(schema, name, step)
        ident = quote_ident(name)
        use_key = step.match == "ignore_case_and_spaces" and column.kind is ValueKind.TEXT
        keys.append(match_key(ident) if use_key else ident)
    if not keys:
        raise StepValidationError("There are no columns to compare for repeats.", step.id)

    order = "ASC" if step.keep == "first" else "DESC"
    rank = f"row_number() OVER (PARTITION BY {', '.join(keys)} ORDER BY {ROW_ID} {order})"
    keep = _keep_list(b, step.keep_row_ids)

    earlier = "an earlier" if step.keep == "first" else "a later"
    if step.columns is None:
        reason = f"Same values as {earlier} row."
    else:
        listed = ", ".join(f'"{name}"' for name in names)
        reason = f"Same {listed} as {earlier} row."

    return CompiledStep(
        step_id=step.id,
        kept=Fragment(
            f"SELECT {_select_list(schema)} FROM {source} QUALIFY {rank} = 1 OR {keep}",
            dict(b.params),
        ),
        output=schema,
        removed=Fragment(
            f"SELECT {ROW_ID} FROM {source} QUALIFY {rank} > 1 AND NOT {keep}",
            dict(b.params),
        ),
        removal_reason=reason,
        reads=() if step.columns is None else tuple(names),
    )


def _set_aside_rows(
    step: SetAsideRowsStep, schema: StageSchema, b: _Builder, source: str
) -> CompiledStep:
    predicate, reason, reads = _condition(step.condition, step, schema, b)
    matched = f"coalesce({predicate}, false)"
    keep = _keep_list(b, step.keep_row_ids)
    return CompiledStep(
        step_id=step.id,
        kept=Fragment(
            f"SELECT {_select_list(schema)} FROM {source} WHERE NOT {matched} OR {keep}",
            b.params,
        ),
        output=schema,
        removed=Fragment(
            f"SELECT {ROW_ID} FROM {source} WHERE {matched} AND NOT {keep}", dict(b.params)
        ),
        removal_reason=reason,
        reads=reads,
    )


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


_NOT_MATCHING_PATTERNS = {
    "email": patterns.EMAIL,
    "phone": f"({patterns.PHONE_FORMATTED})|({patterns.PHONE_DIGITS_ONLY})",
    "number": patterns.LENIENT_NUMBER,
    "date": f"({patterns.DATE_YEAR_FIRST})|({patterns.DATE_NUMERIC})|({patterns.DATE_TEXT})",
}
_NOT_MATCHING_WORDS = {
    "email": "an email address",
    "phone": "a phone number",
    "number": "a number",
    "date": "a date",
}


def _condition(
    condition: RowCondition, step: Step, schema: StageSchema, b: _Builder
) -> tuple[str, str, tuple[str, ...]]:
    """Return (SQL predicate, plain-language reason, columns read)."""
    match condition:
        case RowIdsCondition():
            ids = b.bind("row_ids", condition.row_ids)
            return f"list_contains(CAST({ids} AS BIGINT[]), {ROW_ID})", "Picked by hand.", ()

        case BlankCondition():
            column = _require(schema, condition.column, step)
            predicate = blank_predicate(quote_ident(column.name), column.kind)
            return predicate, f'"{column.name}" is blank.', (column.name,)

        case EqualsCondition() | OneOfCondition():
            column = _require(schema, condition.column, step)
            values = (
                [condition.value] if isinstance(condition, EqualsCondition) else condition.values
            )
            left, bound_values, sql_type = _comparable(column, values, condition.match, step)
            if isinstance(condition, EqualsCondition):
                right = b.bind("value", bound_values[0])
                predicate = f"{left} = CAST({right} AS {sql_type})"
                reason = f'"{column.name}" is "{_display(condition.value)}".'
            else:
                right = b.bind("values", bound_values)
                predicate = f"list_contains(CAST({right} AS {sql_type}[]), {left})"
                reason = f'"{column.name}" is one of the listed values.'
            return predicate, reason, (column.name,)

        case OutsideRangeCondition():
            column = _require(
                schema, condition.column, step, {ValueKind.NUMBER}, "compared to a range"
            )
            ident = quote_ident(column.name)
            checks = []
            if condition.min is not None:
                checks.append(f"{ident} < {b.bind('min', condition.min)}")
            if condition.max is not None:
                checks.append(f"{ident} > {b.bind('max', condition.max)}")
            if condition.min is not None and condition.max is not None:
                reason = (
                    f'"{column.name}" is outside {_format_number(condition.min)} '
                    f"to {_format_number(condition.max)}."
                )
            elif condition.min is not None:
                reason = f'"{column.name}" is below {_format_number(condition.min)}.'
            else:
                assert condition.max is not None
                reason = f'"{column.name}" is above {_format_number(condition.max)}.'
            return f"({' OR '.join(checks)})", reason, (column.name,)

        case NotMatchingCondition():
            column = _require(
                schema, condition.column, step, {ValueKind.TEXT}, "checked against a format"
            )
            ident = quote_ident(column.name)
            pattern = b.bind("pattern", _NOT_MATCHING_PATTERNS[condition.pattern])
            predicate = (
                f"(NOT {blank_predicate(ident, ValueKind.TEXT)} "
                f"AND NOT regexp_full_match({trimmed(ident)}, {pattern}))"
            )
            words = _NOT_MATCHING_WORDS[condition.pattern]
            return predicate, f'"{column.name}" doesn\'t look like {words}.', (column.name,)


def _display(value: str | float) -> str:
    return value if isinstance(value, str) else _format_number(value)


def _comparable(
    column: StageColumn, values: list[str | float], match: str, step: Step
) -> tuple[str, list[object], str]:
    """The column expression, the values to bind, and their SQL type."""
    ident = quote_ident(column.name)
    if column.kind is ValueKind.NUMBER:
        if any(isinstance(value, str) for value in values):
            raise StepValidationError(
                f'"{column.name}" holds numbers, so compare it to numbers.', step.id
            )
        return ident, [float(value) for value in values], "DOUBLE"
    texts = [_display(value) for value in values]
    if column.kind is not ValueKind.TEXT:
        return text_of(ident, column.kind), list(texts), "VARCHAR"
    if match == "ignore_case_and_spaces":
        return match_key(ident), [normalize_text(text) for text in texts], "VARCHAR"
    return ident, list(texts), "VARCHAR"


def _fill_missing(
    step: FillMissingStep, schema: StageSchema, b: _Builder, source: str
) -> CompiledStep:
    column = _require(schema, step.column, step)
    ident = quote_ident(column.name)
    blank = blank_predicate(ident, column.kind)

    match step.strategy:
        case "value":
            assert step.value is not None
            fill = _fill_value(column, step.value, step, b)
        case "mean" | "median":
            _require(
                schema, column.name, step, {ValueKind.NUMBER}, f"filled with the {step.strategy}"
            )
            aggregate = "avg" if step.strategy == "mean" else "median"
            fill = f"(SELECT {aggregate}({ident}) FROM {source})"
        case "most_common":
            fill = (
                f"(SELECT {ident} FROM {source} WHERE NOT {blank} "
                f"GROUP BY {ident} ORDER BY count(*) DESC, {ident} LIMIT 1)"
            )
        case "previous":
            fill = (
                f"last_value(CASE WHEN {blank} THEN NULL ELSE {ident} END IGNORE NULLS) "
                f"OVER (ORDER BY {ROW_ID} ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)"
            )
    expr = f"CASE WHEN {blank} THEN {fill} ELSE {ident} END"

    return CompiledStep(
        step_id=step.id,
        kept=Fragment(
            f"SELECT {_select_list(schema, {column.name: expr})} FROM {source}", b.params
        ),
        output=schema,
        changes=_same_kind_changes(schema, [column.name]),
        reads=(column.name,),
    )


def _fill_value(column: StageColumn, value: str | float, step: Step, b: _Builder) -> str:
    match column.kind:
        case ValueKind.TEXT:
            return f"CAST({b.bind('value', _display(value))} AS VARCHAR)"
        case ValueKind.NUMBER:
            if isinstance(value, str):
                raise StepValidationError(
                    f'"{column.name}" holds numbers, so fill it with a number.', step.id
                )
            return f"CAST({b.bind('value', float(value))} AS DOUBLE)"
        case ValueKind.DATE | ValueKind.DATETIME:
            parse = (
                dt.date.fromisoformat
                if column.kind is ValueKind.DATE
                else dt.datetime.fromisoformat
            )
            example = "2024-03-15" if column.kind is ValueKind.DATE else "2024-03-15 09:30:00"
            if not isinstance(value, str):
                raise StepValidationError(
                    f'"{column.name}" holds dates, so fill it with a date like {example}.', step.id
                )
            try:
                parse(value)
            except ValueError as exc:
                raise StepValidationError(
                    f'"{value}" isn\'t a date we can read. Use a date like {example}.', step.id
                ) from exc
            sql_type = "DATE" if column.kind is ValueKind.DATE else "TIMESTAMP"
            return f"CAST({b.bind('value', value)} AS {sql_type})"
