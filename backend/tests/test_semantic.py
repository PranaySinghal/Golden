"""Column ideas: the built-in ones, and what's kept of a model's."""

from collections.abc import Callable

import pytest

from app.ai.schemas import ProposedColumn, SuggestColumnsReply
from app.config import MAX_SAMPLE_ROWS
from app.semantic.concepts import MAP_POSITION, SHARE_PRICE, STOCK_SYMBOL, concept_of
from app.semantic.engine import SAMPLE_ROWS, accepted_ideas, columns_payload, suggestions_for
from app.semantic.models import MAX_SUGGESTIONS, MIN_SUGGESTIONS, ColumnIdeas, ColumnSuggestion
from app.semantic.rules import rule_suggestions
from tests.conftest import SAMPLE_FILES, SAMPLES, SAMPLES_DIR, Dataset

MakeDataset = Callable[..., Dataset]

COMPANIES = (
    "Company,Ticker,City,Employees\n"
    "Acme Tools,ACM,Leeds,120\n"
    "Birch Foods,BRF,Lyon,45\n"
    "Cobalt Air,CBA,Oslo,300\n"
)
PLAIN = "a,b\nx,y\nz,w\n"


def names(suggestions: list[ColumnSuggestion]) -> list[str]:
    return [suggestion.name for suggestion in suggestions]


# --- built-in ideas -------------------------------------------------------------------------


def test_a_file_of_companies_gets_ideas_about_companies(make_dataset: MakeDataset) -> None:
    offered = suggestions_for(make_dataset(COMPANIES).profile, ["Company", "Ticker", "City"])

    assert names(offered.suggestions)[:4] == ["Stock price", "Industry", "Website", "Map position"]
    assert offered.suggestions[0].live_source == "A stock price service"
    assert offered.status == "off"
    assert all(suggestion.source == "rules" for suggestion in offered.suggestions)


def test_a_file_that_gives_nothing_away_still_gets_ideas(make_dataset: MakeDataset) -> None:
    offered = suggestions_for(make_dataset(PLAIN).profile, ["a", "b"])

    assert names(offered.suggestions) == ["Status", "Owner", "Notes"]


def test_a_file_that_already_has_map_positions_isnt_offered_them(
    make_dataset: MakeDataset,
) -> None:
    profile = make_dataset("City,Latitude,Longitude\nLeeds,53.8,-1.5\nLyon,45.7,4.8\n").profile

    assert "Map position" not in names(rule_suggestions(profile))


@pytest.mark.parametrize("sample", SAMPLES)
def test_every_sample_file_gets_three_to_five_ideas(sample: str, make_dataset: MakeDataset) -> None:
    filename = SAMPLE_FILES[sample]
    profile = make_dataset((SAMPLES_DIR / filename).read_bytes(), filename=filename).profile
    taken = [column.name for column in profile.columns]

    offered = suggestions_for(profile, taken).suggestions

    assert MIN_SUGGESTIONS <= len(offered) <= MAX_SUGGESTIONS
    assert not {name.casefold() for name in names(offered)} & {name.casefold() for name in taken}


def test_structurally_different_files_get_different_ideas(make_dataset: MakeDataset) -> None:
    def ideas(sample: str) -> list[str]:
        filename = SAMPLE_FILES[sample]
        data = (SAMPLES_DIR / filename).read_bytes()
        return names(rule_suggestions(make_dataset(data, filename=filename).profile))

    assert ideas("Messy_Employee_dataset") != ideas("store_orders")


def test_names_already_in_use_are_skipped_whatever_their_capitals(
    make_dataset: MakeDataset,
) -> None:
    offered = suggestions_for(make_dataset(PLAIN).profile, ["a", "b", "STATUS", "notes"])

    assert names(offered.suggestions) == ["Owner"]


# --- a model's ideas ------------------------------------------------------------------------


def reply(*columns: ProposedColumn, about: str = "") -> SuggestColumnsReply:
    return SuggestColumnsReply(about=about, columns=list(columns))


def idea(name: str, reason: str = "Helps compare the companies.", **more: str) -> ProposedColumn:
    return ProposedColumn(name=name, reason=reason, **more)


def test_a_sound_idea_is_kept_and_marked_as_a_models(make_dataset: MakeDataset) -> None:
    profile = make_dataset(COMPANIES).profile

    ideas = accepted_ideas(
        profile,
        reply(
            idea("Revenue", placeholder="To fill in", live_source="A company filings service"),
            about="A list of companies and where they are based.",
        ),
        source_text=COMPANIES,
    )

    assert ideas.status == "ready"
    assert ideas.about == "A list of companies and where they are based."
    assert ideas.suggestions == [
        ColumnSuggestion(
            name="Revenue",
            reason="Helps compare the companies.",
            placeholder="To fill in",
            source="ai",
            live_source="A company filings service",
        )
    ]


@pytest.mark.parametrize(
    "bad",
    [
        idea("company"),  # already in the file, under different capitals
        idea("_row_id"),  # ours
        idea("Revenue", reason="Acme Tools made 4,500,000 last year."),  # a figure from nowhere
        idea("Revenue 2031"),
        idea("Revenue", placeholder="99"),
        idea("Revenue", reason="Lets you **rank** the companies."),
        idea("Revenue", reason="Join on the schema to aggregate it."),
    ],
    ids=["exists", "reserved", "invented-number", "number-in-name", "number-in-placeholder",
         "markdown", "jargon"],
)  # fmt: skip
def test_an_idea_that_cant_be_trusted_is_dropped_on_its_own(
    bad: ProposedColumn, make_dataset: MakeDataset
) -> None:
    profile = make_dataset(COMPANIES).profile

    ideas = accepted_ideas(profile, reply(bad, idea("Industry")), source_text=COMPANIES)

    assert names(ideas.suggestions) == ["Industry"]


def test_a_figure_that_is_in_the_file_may_be_repeated(make_dataset: MakeDataset) -> None:
    profile = make_dataset(COMPANIES).profile

    ideas = accepted_ideas(
        profile,
        reply(idea("Size band", reason="Groups companies such as the one with 300 employees.")),
        source_text=COMPANIES,
    )

    assert names(ideas.suggestions) == ["Size band"]


def test_the_same_idea_twice_is_kept_once(make_dataset: MakeDataset) -> None:
    profile = make_dataset(COMPANIES).profile

    ideas = accepted_ideas(profile, reply(idea("Revenue"), idea("revenue")), source_text=COMPANIES)

    assert names(ideas.suggestions) == ["Revenue"]


def test_a_summary_with_an_invented_figure_is_left_out(make_dataset: MakeDataset) -> None:
    profile = make_dataset(COMPANIES).profile

    ideas = accepted_ideas(
        profile, reply(idea("Revenue"), about="A list of 9,000 companies."), source_text=COMPANIES
    )

    assert ideas.about is None
    assert names(ideas.suggestions) == ["Revenue"]


def test_a_models_ideas_come_first_and_built_in_ones_fill_the_rest(
    make_dataset: MakeDataset,
) -> None:
    profile = make_dataset(PLAIN).profile
    ideas = ColumnIdeas(
        status="ready",
        suggestions=[ColumnSuggestion(name="Revenue", reason="r", source="ai")],
    )

    offered = suggestions_for(profile, ["a", "b"], ideas)

    assert names(offered.suggestions) == ["Revenue", "Status", "Owner", "Notes"]
    assert offered.status == "ready"


def test_a_model_that_couldnt_answer_leaves_the_built_in_ideas(make_dataset: MakeDataset) -> None:
    offered = suggestions_for(make_dataset(PLAIN).profile, ["a", "b"], ColumnIdeas(status="failed"))

    assert names(offered.suggestions) == ["Status", "Owner", "Notes"]
    assert offered.status == "failed"


# --- what a model is shown ------------------------------------------------------------------


def test_a_model_sees_the_header_and_five_rows_and_no_more(make_dataset: MakeDataset) -> None:
    rows = "".join(f"Company {i},T{i},Town {i},{i}\n" for i in range(50))
    ds = make_dataset("Company,Ticker,City,Employees\n" + rows)

    payload = columns_payload(ds.conn, ds.profile)

    assert SAMPLE_ROWS == 5 <= MAX_SAMPLE_ROWS
    assert set(payload) == {"columns", "sample_rows"}
    assert [column["name"] for column in payload["columns"]] == [
        "Company",
        "Ticker",
        "City",
        "Employees",
    ]
    assert [row["Company"] for row in payload["sample_rows"]] == [f"Company {i}" for i in range(5)]
    assert "Company 40" not in str(payload)


# --- whether a model could fill a suggested column in ---------------------------------------


def fill_of(make_dataset: MakeDataset, **plan: object) -> object:
    profile = make_dataset(COMPANIES).profile
    proposed = ProposedColumn(name="Industry", reason="Helps compare the companies.", **plan)  # type: ignore[arg-type]
    [kept] = accepted_ideas(profile, reply(proposed), source_text=COMPANIES).suggestions
    return kept.fill


def test_a_label_column_carries_its_labels_and_the_column_it_reads(
    make_dataset: MakeDataset,
) -> None:
    fill = fill_of(
        make_dataset,
        kind="label",
        based_on="Company",
        choices=["Technology", "Retail", "retail", "", "Finance"],
    )

    assert fill is not None
    assert (fill.based_on, fill.kind) == ("Company", "label")  # type: ignore[attr-defined]
    # One spelling each, and no empty label.
    assert fill.choices == ["Technology", "Retail", "Finance"]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "plan",
    [
        {"kind": "none", "based_on": "Company"},
        {"kind": "label", "based_on": "Nope", "choices": ["A", "B"]},
        {"kind": "label", "based_on": "company", "choices": ["A", "B"]},  # not spelled the same
        {"kind": "label", "based_on": "Company", "choices": ["Only one"]},
        {"kind": "label", "based_on": "Company", "choices": ["**A**", "B"]},
        {"kind": "text", "based_on": ""},
        # A size band worked out from a number is arithmetic, not a model's call.
        {"kind": "label", "based_on": "Employees", "choices": ["Small", "Large"]},
    ],
    ids=[
        "not-fillable",
        "no-such-column",
        "wrong-spelling",
        "one-label",
        "markup",
        "no-column",
        "from-a-number",
    ],
)
def test_a_plan_that_doesnt_hold_together_leaves_a_plain_suggestion(
    plan: dict[str, object], make_dataset: MakeDataset
) -> None:
    assert fill_of(make_dataset, **plan) is None


def test_text_and_website_columns_need_no_labels(make_dataset: MakeDataset) -> None:
    site = fill_of(make_dataset, kind="website", based_on="Company")

    assert site is not None
    assert (site.kind, site.choices) == ("website", [])  # type: ignore[attr-defined]


def test_built_in_ideas_are_never_filled_in_by_a_model(make_dataset: MakeDataset) -> None:
    offered = suggestions_for(make_dataset(COMPANIES).profile, ["Company"]).suggestions

    assert all(suggestion.fill is None for suggestion in offered)


# --- ideas that would repeat what a connector already looked up -----------------------------


@pytest.mark.parametrize(
    ("name", "concept"),
    [
        ("Map position", MAP_POSITION),
        ("Geolocation", MAP_POSITION),
        ("Latitude and longitude", MAP_POSITION),
        ("Lat/Long", MAP_POSITION),
        ("Store coordinates", MAP_POSITION),
        ("Share price", SHARE_PRICE),
        ("Stock price", SHARE_PRICE),
        ("Latest stock quote", SHARE_PRICE),
        ("Ticker", STOCK_SYMBOL),
        ("Stock symbol", STOCK_SYMBOL),
        # Near misses that are their own thing.
        ("Unit price", None),
        ("Stock on hand", None),
        ("Location", None),
        ("Position in company", None),
        ("Market share", None),
        ("Symbol", None),
    ],
)
def test_a_column_name_is_recognised_as_something_a_connector_adds(
    name: str, concept: str | None
) -> None:
    assert concept_of(name) == concept


def test_an_idea_for_something_already_looked_up_is_not_offered(
    make_dataset: MakeDataset,
) -> None:
    profile = make_dataset(COMPANIES).profile
    ideas = ColumnIdeas(
        status="ready",
        suggestions=[
            ColumnSuggestion(name="Share price", reason="r", source="ai"),
            ColumnSuggestion(name="Headquarters coordinates", reason="r", source="ai"),
            ColumnSuggestion(name="Revenue", reason="r", source="ai"),
        ],
    )

    before = names(suggestions_for(profile, ["Company"], ideas).suggestions)
    after = names(
        suggestions_for(
            profile, ["Company"], ideas, covered={MAP_POSITION, SHARE_PRICE}
        ).suggestions
    )

    assert {"Share price", "Headquarters coordinates"} <= set(before)
    # One idea is offered once, whoever worded it: the model's stands for the built-in one.
    assert not {"Stock price", "Map position"} & set(before)
    # Once looked up, neither wording comes back.
    assert not {"Share price", "Headquarters coordinates", "Stock price", "Map position"} & set(
        after
    )
    assert "Revenue" in after
