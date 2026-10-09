"""enrich_column and resolve_match: joining to looked-up answers without ever fetching."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.compare.unlocked import changed_columns
from app.steps.apply import StepStatus, answer_key, plan_recipe, volatile_columns
from app.steps.copy import columns_of, describe
from app.steps.export import build_recipe_file, recipe_file_bytes
from app.steps.models import (
    DedupeStep,
    EnrichColumnStep,
    EqualsCondition,
    Recipe,
    ResolveMatchStep,
    SetAsideRowsStep,
    SplitColumnStep,
    Step,
    TrimStep,
)
from app.steps.replay import load_recipe_file, required_columns
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]

SHOPS = "shop,zip\nNorth,90210\nSouth, 90210 \nEast,10001\nWest,\nMid,99999\n"
SNAPSHOT = "aaaaaaaaaaaa"
LATER = "bbbbbbbbbbbb"


def store(ds: Dataset, snapshot: str, rows: list[tuple[str, str | None, str | None, str]]) -> None:
    ds.conn.executemany(
        "INSERT INTO lookups.enrichments VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (snapshot, key, key, v1, v2, status, "2026-10-08T15:00:00+00:00")
            for key, v1, v2, status in rows
        ],
    )


def positions(snapshot: str | None = SNAPSHOT) -> EnrichColumnStep:
    return EnrichColumnStep(
        connector="postal_geocode",
        column="zip",
        into=["Geolocation"],
        country="US",
        snapshot=snapshot,
    )


def test_before_anything_is_looked_up_the_new_columns_are_there_and_empty(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(SHOPS)

    result = ds.apply(positions(snapshot=None))

    assert result.outcomes[0].status is StepStatus.APPLIED
    assert [c.name for c in result.columns] == ["shop", "zip", "Geolocation"]
    assert ds.column("Geolocation") == [None] * 5
    assert ds.changes() == []


def test_each_row_gets_its_values_answer(make_dataset: MakeDataset) -> None:
    ds = make_dataset(SHOPS)
    store(
        ds,
        SNAPSHOT,
        [
            ("90210", "34.0901, -118.4065", None, "found"),
            ("10001", "40.7128, -74.006", None, "found"),
            ("99999", None, None, "not_found"),
        ],
    )

    result = ds.apply(positions())

    # Spacing around a value doesn't stop it matching; a blank stays blank.
    here, there = "34.0901, -118.4065", "40.7128, -74.006"
    assert ds.column("Geolocation") == [here, here, there, None, None]
    assert [c.kind.value for c in result.columns[2:]] == ["text"]
    assert ds.row_ids() == [1, 2, 3, 4, 5]
    # Every filled cell is traced to the step, with nothing before it.
    assert result.outcomes[0].cells_changed == 3
    assert {change[3:] for change in ds.changes()} == {
        (None, here, "created"),
        (None, there, "created"),
    }


def test_another_runs_answers_are_never_used(make_dataset: MakeDataset) -> None:
    ds = make_dataset(SHOPS)
    store(ds, LATER, [("90210", "1.0, 2.0", None, "found")])

    ds.apply(positions(SNAPSHOT))

    assert ds.column("Geolocation") == [None] * 5


def test_looking_up_again_is_a_new_snapshot_and_the_old_one_still_works(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset("t\nAAPL\nMSFT\n")
    store(ds, SNAPSHOT, [("aapl", "$261.74", "2026-10-07 16:00 ET", "found")])
    store(ds, LATER, [("aapl", "$265.10", "2026-10-08 09:31 ET", "found")])

    def prices(snapshot: str) -> EnrichColumnStep:
        return EnrichColumnStep(
            connector="stock_price", column="t", into=["Price"], snapshot=snapshot
        )

    ds.apply(prices(LATER))
    result = ds.apply(prices(LATER))
    assert ds.column("Price") == ["$265.10", None]
    # When a price was true is kept beside it, never as a column of its own.
    assert [c.name for c in result.columns] == ["t", "Price"]

    ds.apply(prices(SNAPSHOT))
    assert ds.column("Price") == ["$261.74", None]


def test_a_file_with_columns_named_like_ours_still_works(make_dataset: MakeDataset) -> None:
    ds = make_dataset("key,status,snapshot,value1\n90210,open,x,y\n")
    store(ds, SNAPSHOT, [("90210", "34.0901, -118.4065", None, "found")])

    ds.apply(
        EnrichColumnStep(
            connector="postal_geocode",
            column="key",
            into=["Geolocation"],
            country="US",
            snapshot=SNAPSHOT,
        )
    )

    assert ds.column("Geolocation") == ["34.0901, -118.4065"]
    assert ds.column("status") == ["open"]


@pytest.mark.parametrize("into", [["shop"], ["SHOP"], ["_row_id"]])
def test_new_column_names_that_clash_are_refused(
    into: list[str], make_dataset: MakeDataset
) -> None:
    ds = make_dataset(SHOPS)
    step = EnrichColumnStep(connector="postal_geocode", column="zip", into=into, country="US")

    assert ds.apply(step).outcomes[0].status is StepStatus.BLOCKED


@pytest.mark.parametrize(
    "payload",
    [
        {"connector": "postal_geocode", "column": "a", "into": ["x", "y"], "country": "US"},
        {"connector": "postal_geocode", "column": "a", "into": ["x"]},
        {"connector": "stock_price", "column": "a", "into": ["x"], "country": "US"},
        {"connector": "stock_price", "column": "a", "into": ["x", "y"]},
        {"connector": "company_ticker", "column": "a", "into": ["x", "y"]},
        {"connector": "weather", "column": "a", "into": ["x"]},
        {"connector": "company_ticker", "column": "a", "into": ["x"], "snapshot": "../etc"},
    ],
)
def test_a_step_that_doesnt_fit_its_connector_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EnrichColumnStep.model_validate(payload)


def test_switched_off_is_the_same_as_never_added(make_dataset: MakeDataset) -> None:
    ds = make_dataset(SHOPS)
    trim = TrimStep(columns=["shop"])
    without = ds.apply(trim)

    off = ds.apply(trim, positions().model_copy(update={"enabled": False}))

    assert off.fingerprint == without.fingerprint


def test_it_can_follow_a_column_another_step_made(make_dataset: MakeDataset) -> None:
    ds = make_dataset("where\nNorth-90210\nEast-10001\n")
    store(ds, SNAPSHOT, [("90210", "34.0901, -118.4065", None, "found")])
    split = SplitColumnStep(column="where", delimiter="-", into=["shop", "zip"])

    result = ds.apply(split, positions())

    assert result.outcomes[1].status is StepStatus.APPLIED
    assert ds.column("Geolocation") == ["34.0901, -118.4065", None]
    # A saved recipe needs the file's own column, not the one a step made.
    assert required_columns(Recipe(steps=[split, positions()]), ds.base) == ["where"]


# --- picking between several matches --------------------------------------------------------


def test_a_pick_fills_the_rows_for_that_name_and_no_others(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Company\nAlphabet\n alphabet \nApple\n")
    store(ds, SNAPSHOT, [("apple", "AAPL", "Apple Inc.", "found")])
    tickers = EnrichColumnStep(
        connector="company_ticker", column="Company", into=["Ticker"], snapshot=SNAPSHOT
    )
    pick = ResolveMatchStep(column="Company", value="alphabet", into="Ticker", chosen="GOOGL")

    result = ds.apply(tickers, pick)

    assert ds.column("Ticker") == ["GOOGL", "GOOGL", "AAPL"]
    assert result.outcomes[1].cells_changed == 2
    assert describe(pick) == 'Use "GOOGL" in "Ticker" where "Company" is "alphabet"'
    assert columns_of(pick) == ["Company", "Ticker"]


def test_a_pick_without_its_lookup_is_blocked(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Company\nAlphabet\n")
    pick = ResolveMatchStep(column="Company", value="alphabet", into="Ticker", chosen="GOOGL")

    assert ds.apply(pick).outcomes[0].status is StepStatus.BLOCKED


def test_how_a_lookup_reads_in_the_recipe_panel() -> None:
    assert describe(positions()) == 'Look up map positions for "zip" as "Geolocation"'
    assert columns_of(positions()) == ["zip", "Geolocation"]


# --- keeping looked-up values out of the answers --------------------------------------------


def plan(ds: Dataset, *steps: Step):  # type: ignore[no-untyped-def]
    recipe = Recipe(steps=list(steps))
    return plan_recipe(recipe, ds.base), recipe


def test_looked_up_columns_are_known_and_kept_out_of_new_questions(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(SHOPS)
    split = SplitColumnStep(column="shop", delimiter="-", into=["a", "b"])

    planned, _ = plan(ds, split, positions())

    assert volatile_columns(planned) == (frozenset({"Geolocation"}), False)
    assert changed_columns(planned) == ["a", "b"]


def test_what_is_made_from_a_looked_up_column_is_kept_out_too(make_dataset: MakeDataset) -> None:
    ds = make_dataset("Company\nAlphabet\n")
    tickers = EnrichColumnStep(connector="company_ticker", column="Company", into=["Ticker"])
    prices = EnrichColumnStep(connector="stock_price", column="Ticker", into=["Price"])
    split = SplitColumnStep(column="Ticker", delimiter=".", into=["Root", "Class"])

    planned, _ = plan(ds, tickers, prices, split)

    volatile, leaks = volatile_columns(planned)
    assert volatile == {"Ticker", "Price", "Root", "Class"}
    assert not leaks
    assert changed_columns(planned) == []


def test_looking_up_again_keeps_the_answers_key(make_dataset: MakeDataset) -> None:
    ds = make_dataset(SHOPS)
    first, recipe_one = plan(ds, TrimStep(columns=["shop"]), positions(SNAPSHOT))
    second, recipe_two = plan(ds, TrimStep(columns=["shop"]), positions(LATER))

    assert answer_key(first, recipe_one) == answer_key(second, recipe_two)


def test_setting_rows_aside_by_a_looked_up_value_is_noticed(make_dataset: MakeDataset) -> None:
    ds = make_dataset(SHOPS)
    far_north = SetAsideRowsStep(condition=EqualsCondition(column="Geolocation", value="0, 0"))
    first, recipe_one = plan(ds, positions(SNAPSHOT), far_north)
    second, recipe_two = plan(ds, positions(LATER), far_north)

    assert volatile_columns(first)[1] is True
    # Which rows remain now depends on the lookup, so the key must follow it.
    assert answer_key(first, recipe_one) != answer_key(second, recipe_two)


def test_a_whole_row_repeat_check_after_a_lookup_is_noticed(make_dataset: MakeDataset) -> None:
    ds = make_dataset(SHOPS)

    planned, _ = plan(ds, positions(), DedupeStep())

    assert volatile_columns(planned)[1] is True


# --- saving and re-using --------------------------------------------------------------------


def test_a_saved_recipe_keeps_what_to_look_up_but_not_the_answers(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(SHOPS)
    saved = build_recipe_file(
        Recipe(steps=[positions()]), ds.base, "shops.csv", datetime(2026, 10, 8, tzinfo=UTC)
    )

    step = saved.recipe.steps[0]
    assert isinstance(step, EnrichColumnStep)
    assert step.snapshot is None
    assert (step.connector, step.column, step.country) == ("postal_geocode", "zip", "US")


def test_a_snapshot_written_into_a_recipe_file_by_hand_is_dropped(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(SHOPS)
    saved = build_recipe_file(Recipe(steps=[positions(None)]), ds.base, "shops.csv")
    edited = recipe_file_bytes(saved).replace(b'"snapshot": null', b'"snapshot": "aaaaaaaaaaaa"')
    assert b"aaaaaaaaaaaa" in edited

    step = load_recipe_file(edited).recipe.steps[0]

    assert isinstance(step, EnrichColumnStep)
    assert step.snapshot is None
