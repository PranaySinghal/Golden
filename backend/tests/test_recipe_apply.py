"""Recipe-level behavior: disabling, blocked steps, caching, raw immutability, SQL safety."""

import re
from collections.abc import Callable

import duckdb
import pytest

from app.steps.apply import StepStatus, apply_recipe, plan_recipe
from app.steps.compile import compile_step
from app.steps.models import (
    CastNumberStep,
    DedupeStep,
    EqualsCondition,
    FillMissingStep,
    MapValuesStep,
    NormalizeCaseStep,
    NullPlaceholdersStep,
    OneOfCondition,
    ParseDateStep,
    Recipe,
    SetAsideRowsStep,
    SplitColumnStep,
    Step,
    TrimStep,
    ValueMapping,
)
from app.steps.schema import StageSchema
from tests.conftest import SAMPLES_DIR, Dataset

MakeDataset = Callable[..., Dataset]
EMPLOYEE = (SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes()


def employee_steps() -> list[Step]:
    return [
        NullPlaceholdersStep(columns=["Salary"], placeholders=["N/A"]),
        CastNumberStep(column="Salary"),
        SplitColumnStep(column="Department_Region", delimiter="-", into=["Department", "Region"]),
        TrimStep(columns=["Region"]),
        ParseDateStep(column="Join_Date", formats=["%m/%d/%Y"]),
        DedupeStep(columns=["Email"], match="ignore_case_and_spaces"),
        FillMissingStep(column="Age", strategy="most_common"),
        SetAsideRowsStep(condition=EqualsCondition(column="Status", value="Pending")),
        NormalizeCaseStep(columns=["Performance_Score"], case="upper"),
        MapValuesStep(
            column="Remote_Work",
            mappings=[
                ValueMapping(from_value="TRUE", to_value="Yes"),
                ValueMapping(from_value="FALSE", to_value="No"),
            ],
        ),
    ]


def snapshot(ds: Dataset) -> tuple[object, ...]:
    return (ds.cleaned(), ds.set_aside(), ds.changes())


@pytest.mark.parametrize("position", range(len(employee_steps())))
def test_disabling_a_step_equals_never_adding_it(make_dataset: MakeDataset, position: int) -> None:
    steps = employee_steps()
    ds = make_dataset(EMPLOYEE)

    disabled = list(steps)
    disabled[position] = steps[position].model_copy(update={"enabled": False})
    with_disabled = ds.apply_recipe(Recipe(steps=disabled))
    disabled_state = snapshot(ds)

    without = ds.apply_recipe(Recipe(steps=[s for i, s in enumerate(steps) if i != position]))

    assert snapshot(ds) == disabled_state
    assert with_disabled.fingerprint == without.fingerprint
    assert with_disabled.row_count == without.row_count


def test_step_that_needs_a_disabled_step_is_blocked_and_the_rest_runs(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(EMPLOYEE)
    split = SplitColumnStep(
        column="Department_Region", delimiter="-", into=["Department", "Region"], enabled=False
    )
    uses_split = SetAsideRowsStep(condition=EqualsCondition(column="Region", value="Texas"))
    independent = TrimStep(columns=["Email"])

    result = ds.apply(split, uses_split, independent)

    assert [o.status for o in result.outcomes] == [
        StepStatus.DISABLED,
        StepStatus.BLOCKED,
        StepStatus.APPLIED,
    ]
    reason = result.outcomes[1].reason or ""
    assert reason.startswith("It depends on an earlier step that's turned off")
    assert 'no column called "Region"' in reason
    assert result.row_count == 1020


def test_step_broken_on_its_own_is_blocked_without_blaming_other_steps(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(EMPLOYEE)

    result = ds.apply(TrimStep(columns=["Nope"]), TrimStep(columns=["Email"]))

    assert result.outcomes[0].status is StepStatus.BLOCKED
    assert (
        result.outcomes[0].reason == 'There\'s no column called "Nope" at this point in the recipe.'
    )
    assert result.outcomes[1].status is StepStatus.APPLIED


def test_step_order_matters(make_dataset: MakeDataset) -> None:
    ds = make_dataset('v\n" Sales "\n')
    mapping = MapValuesStep(
        column="v", mappings=[ValueMapping(from_value="Sales", to_value="Revenue")]
    )
    trim = TrimStep(columns=["v"])

    ds.apply(mapping, trim)
    assert ds.column("v") == ["Sales"]

    ds.apply(trim, mapping)
    assert ds.column("v") == ["Revenue"]


def test_empty_recipe_copies_raw_as_cleaned(make_dataset: MakeDataset) -> None:
    ds = make_dataset("a,b\n1,x\n2,y\n")

    result = ds.apply()

    assert ds.cleaned() == [(1, "1", "x"), (2, "2", "y")]
    assert (result.set_aside_count, ds.changes()) == (0, [])


def test_unchanged_recipe_reuses_the_previous_result(make_dataset: MakeDataset) -> None:
    ds = make_dataset(EMPLOYEE)
    recipe = Recipe(steps=employee_steps())

    first = apply_recipe(ds.conn, recipe, ds.base)
    ds.conn.execute("DROP TABLE work.cleaned")  # would break if anything re-ran
    again = apply_recipe(ds.conn, recipe, ds.base, previous=first)

    assert again is first


def test_changed_recipe_rebuilds(make_dataset: MakeDataset) -> None:
    ds = make_dataset(EMPLOYEE)
    steps = employee_steps()
    first = apply_recipe(ds.conn, Recipe(steps=steps), ds.base)

    toggled = [steps[0].model_copy(update={"enabled": False}), *steps[1:]]
    second = apply_recipe(ds.conn, Recipe(steps=toggled), ds.base, previous=first)

    assert second is not first
    assert second.fingerprint != first.fingerprint


def test_lineage_is_rebuilt_when_asked_after_a_run_without_it(make_dataset: MakeDataset) -> None:
    ds = make_dataset(EMPLOYEE)
    recipe = Recipe(steps=employee_steps())

    quick = apply_recipe(ds.conn, recipe, ds.base, lineage=False)
    assert quick.outcomes[0].cells_changed is None
    full = apply_recipe(ds.conn, recipe, ds.base, lineage=True, previous=quick)

    assert full is not quick
    assert full.outcomes[0].cells_changed == 24


# --- the raw table is never changed -----------------------------------------------------------


def test_raw_table_is_unchanged_by_every_step_type(make_dataset: MakeDataset) -> None:
    ds = make_dataset(EMPLOYEE)
    before = ds.raw_fingerprint()

    for step in employee_steps():
        ds.apply(step)
    ds.apply_recipe(Recipe(steps=employee_steps()))
    ds.apply_recipe(Recipe(steps=employee_steps()), lineage=False)

    assert ds.raw_fingerprint() == before


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE source.raw SET Salary = '0'",
        "DELETE FROM source.raw",
        "INSERT INTO source.raw (_row_id) VALUES (99999)",
        "DROP TABLE source.raw",
        "ALTER TABLE source.raw ADD COLUMN extra VARCHAR",
        "CREATE TABLE source.sneaky (x INTEGER)",
    ],
)
def test_database_refuses_writes_to_raw(make_dataset: MakeDataset, statement: str) -> None:
    ds = make_dataset(EMPLOYEE)
    before = ds.raw_fingerprint()

    with pytest.raises(duckdb.Error, match="read-only"):
        ds.conn.execute(statement)

    assert ds.raw_fingerprint() == before


# --- SQL safety -------------------------------------------------------------------------------


def test_compiled_sql_never_contains_user_values() -> None:
    schema = StageSchema.all_text(["name", "code"])
    markers = ["xyzzy-marker-1", "xyzzy-marker-2", "xyzzy-marker-3"]
    steps: list[Step] = [
        MapValuesStep(
            column="name",
            mappings=[ValueMapping(from_value=markers[0], to_value=markers[1])],
        ),
        NullPlaceholdersStep(columns=["name"], placeholders=[markers[2]]),
        SplitColumnStep(column="code", delimiter="|;'", into=["left", "right"]),
        SetAsideRowsStep(condition=OneOfCondition(column="name", values=markers)),
        FillMissingStep(column="name", strategy="value", value=markers[0]),
    ]
    for index, step in enumerate(steps):
        compiled = compile_step(step, schema, index=index, source="s0")
        sql = compiled.kept.sql + (compiled.removed.sql if compiled.removed else "")
        for marker in [*markers, "|;'"]:
            assert marker not in sql
        # Every parameter the SQL mentions is bound, and nothing extra is bound.
        referenced = set(re.findall(r"\$(p\d+_\w+)", compiled.kept.sql))
        assert referenced == set(compiled.kept.params)


def test_plan_is_pure_and_needs_no_database() -> None:
    schema = StageSchema.all_text(["Salary"])

    plan = plan_recipe(Recipe(steps=[CastNumberStep(column="Salary")]), schema)

    assert [c.kind.value for c in plan.output.columns] == ["number"]
