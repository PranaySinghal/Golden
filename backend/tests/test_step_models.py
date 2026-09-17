import pytest
from pydantic import TypeAdapter, ValidationError

from app.steps.models import (
    STEP_LABELS,
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
    Recipe,
    RowIdsCondition,
    SetAsideRowsStep,
    SplitColumnStep,
    Step,
    TrimStep,
    ValueMapping,
)

STEP: TypeAdapter[Step] = TypeAdapter(Step)

EVERY_STEP: list[Step] = [
    TrimStep(columns=["a"], collapse_inner_spaces=True),
    NormalizeCaseStep(columns=["a"], case="title"),
    MapValuesStep(column="a", mappings=[ValueMapping(from_value="x", to_value=None)]),
    NullPlaceholdersStep(columns=["a"], placeholders=["N/A"]),
    CastNumberStep(column="a", decimal_separator=",", percent="fraction", allow_k_m_suffix=True),
    ParseDateStep(column="a", formats=["%d/%m/%Y", "%Y-%m-%d"], output="datetime"),
    SplitColumnStep(column="a", delimiter="-", into=["b", "c"], keep_original=False),
    DedupeStep(columns=["a"], match="ignore_case_and_spaces", keep="last", keep_row_ids=[3]),
    SetAsideRowsStep(condition=BlankCondition(column="a")),
    SetAsideRowsStep(condition=EqualsCondition(column="a", value=5.0)),
    SetAsideRowsStep(condition=OneOfCondition(column="a", values=["x", "y"])),
    SetAsideRowsStep(condition=RowIdsCondition(row_ids=[1, 2])),
    SetAsideRowsStep(condition=OutsideRangeCondition(column="a", min=0)),
    SetAsideRowsStep(condition=NotMatchingCondition(column="a", pattern="email")),
    FillMissingStep(column="a", strategy="value", value="none given"),
    FillMissingStep(column="a", strategy="previous"),
]


@pytest.mark.parametrize("step", EVERY_STEP, ids=lambda s: s.type)
def test_every_step_round_trips_through_json(step: Step) -> None:
    assert STEP.validate_json(STEP.dump_json(step)) == step


def test_every_step_type_has_a_label() -> None:
    assert {step.type for step in EVERY_STEP} == set(STEP_LABELS)


def test_step_ids_are_generated_and_unique() -> None:
    ids = {TrimStep(columns=["a"]).id for _ in range(50)}
    assert len(ids) == 50
    assert all(len(step_id) == 12 for step_id in ids)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "trim", "columns": []},
        {"type": "nope", "columns": ["a"]},
        {"type": "trim", "columns": ["a"], "surprise": True},
        {"type": "trim", "columns": ["a"], "id": "not-hex"},
        {"type": "normalize_case", "columns": ["a"], "case": "sentence"},
        {"type": "map_values", "column": "a", "mappings": []},
        {"type": "map_values", "column": "a", "mappings": [{"from_value": "", "to_value": "x"}]},
        {"type": "null_placeholders", "columns": ["a"], "placeholders": []},
        {"type": "cast_number", "column": "a", "decimal_separator": ";"},
        {"type": "parse_date", "column": "a", "formats": ["%Y%m%d"]},
        {"type": "parse_date", "column": "a", "formats": []},
        {"type": "split_column", "column": "a", "delimiter": "-", "into": ["only"]},
        {"type": "split_column", "column": "a", "delimiter": "", "into": ["b", "c"]},
        {"type": "split_column", "column": "a", "delimiter": "-", "into": ["b", "  "]},
        {"type": "dedupe", "keep": "middle"},
        {"type": "set_aside_rows", "condition": {"kind": "row_ids", "row_ids": []}},
        {"type": "set_aside_rows", "condition": {"kind": "outside_range", "column": "a"}},
        {
            "type": "set_aside_rows",
            "condition": {"kind": "outside_range", "column": "a", "min": 5, "max": 1},
        },
        {
            "type": "set_aside_rows",
            "condition": {"kind": "row_ids", "row_ids": list(range(10_001))},
        },
        {"type": "fill_missing", "column": "a", "strategy": "value"},
        {"type": "fill_missing", "column": "a", "strategy": "mean", "value": 3},
    ],
)
def test_invalid_steps_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        STEP.validate_python(payload)


def test_steps_are_immutable() -> None:
    step = TrimStep(columns=["a"])
    with pytest.raises(ValidationError):
        step.enabled = False  # type: ignore[misc]


def test_recipe_rejects_duplicate_step_ids() -> None:
    step = TrimStep(columns=["a"])
    with pytest.raises(ValidationError, match="unique"):
        Recipe(steps=[step, step])


def test_recipe_round_trips() -> None:
    recipe = Recipe(steps=EVERY_STEP)
    assert Recipe.model_validate_json(recipe.model_dump_json()) == recipe
