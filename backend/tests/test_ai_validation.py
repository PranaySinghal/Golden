"""What a model claims, and what survives checking."""

import json
import logging
from collections.abc import Callable

import pytest

from app.ai.fixes import accepted_fixes
from app.ai.payload import MAX_VALUE_CHARS, fixes_payload, issue_wording_payload
from app.ai.schemas import RewordIssuesReply, RewordQuestionsReply, SuggestFixesReply
from app.ai.wording import (
    accepted_issue_copy,
    accepted_question_labels,
    invents_numbers,
    numbers_in,
)
from app.config import MAX_SAMPLE_ROWS
from app.detectors.models import DetectorName, Issue, Tier
from app.questions.models import Question
from app.steps.models import TrimStep
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]

MESSY = "Employee_ID,Full_Name,Salary,Notes\n" + "".join(
    f"E{i:03d},Ann Lee,{50000 + i},{'Urgent | call back' if i % 2 else 'Fine | no action'}\n"
    for i in range(20)
)


def fix(**overrides: object) -> dict[str, object]:
    proposed: dict[str, object] = {
        "columns": ["Notes"],
        "title": '"Notes" holds two things in one column',
        "explanation": "Each value has a label and a message together, so neither can be "
        "counted on its own.",
        "confidence": "likely",
        "steps": [
            {
                "type": "split_column",
                "arguments": {
                    "column": "Notes",
                    "delimiter": "|",
                    "into": ["Note_Label", "Note_Message"],
                },
            }
        ],
    }
    proposed.update(overrides)
    return proposed


def reply(*fixes: dict[str, object]) -> SuggestFixesReply:
    return SuggestFixesReply.model_validate({"fixes": list(fixes)})


def accept(ds: Dataset, *fixes: dict[str, object], known: list[Issue] | None = None) -> list[Issue]:
    return accepted_fixes(ds.conn, ds.profile, reply(*fixes), known or [])


# --- proposed fixes -------------------------------------------------------------------------


def test_a_sound_fix_becomes_an_issue_like_any_other(make_dataset: MakeDataset) -> None:
    ds = make_dataset(MESSY)

    [issue] = accept(ds, fix())

    assert issue.source == "ai"
    assert issue.detector is DetectorName.AI_SUGGESTION
    assert issue.title == '"Notes" holds two things in one column'
    assert issue.steps[0].type == "split_column"
    assert (bool(issue.id), bool(issue.steps[0].id)) == (True, True)


def test_the_rows_affected_are_counted_here_not_claimed_there(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(MESSY)

    [issue] = accept(ds, fix())

    assert issue.affected_rows == 20
    assert issue.impact == 1.0


def test_a_model_never_gets_to_apply_something_unasked(make_dataset: MakeDataset) -> None:
    ds = make_dataset(MESSY)

    [issue] = accept(ds, fix(confidence="ask"))

    assert issue.tier is Tier.LIKELY


def test_a_column_that_does_not_exist_is_dropped(make_dataset: MakeDataset) -> None:
    ds = make_dataset(MESSY)

    assert accept(ds, fix(columns=["Comments"])) == []


def test_a_step_on_a_column_that_does_not_exist_is_dropped(make_dataset: MakeDataset) -> None:
    ds = make_dataset(MESSY)
    invented = fix(
        steps=[{"type": "cast_number", "arguments": {"column": "Bonus"}}], columns=["Notes"]
    )

    assert accept(ds, invented) == []


def test_a_step_type_we_do_not_have_is_dropped(make_dataset: MakeDataset) -> None:
    ds = make_dataset(MESSY)
    invented = fix(steps=[{"type": "run_sql", "arguments": {"sql": "DROP TABLE raw"}}])

    assert accept(ds, invented) == []


def test_arguments_that_do_not_fit_the_step_are_dropped(make_dataset: MakeDataset) -> None:
    ds = make_dataset(MESSY)
    wrong = fix(steps=[{"type": "split_column", "arguments": {"column": "Notes"}}])

    assert accept(ds, wrong) == []


def test_a_value_the_column_never_held_is_dropped(make_dataset: MakeDataset) -> None:
    """The model "remembers" an N/A that this file doesn't have."""
    ds = make_dataset(MESSY)
    invented = fix(
        columns=["Salary"],
        steps=[
            {
                "type": "null_placeholders",
                "arguments": {"columns": ["Salary"], "placeholders": ["N/A"]},
            }
        ],
    )

    assert accept(ds, invented) == []


def test_a_separator_the_column_never_held_is_dropped(make_dataset: MakeDataset) -> None:
    ds = make_dataset(MESSY)
    invented = fix(
        steps=[
            {
                "type": "split_column",
                "arguments": {"column": "Notes", "delimiter": ";", "into": ["A", "B"]},
            }
        ]
    )

    assert accept(ds, invented) == []


def test_a_fix_that_changes_nothing_is_not_worth_showing(make_dataset: MakeDataset) -> None:
    ds = make_dataset("id,city\n1,Paris\n2,Rome\n")
    pointless = fix(columns=["city"], steps=[{"type": "trim", "arguments": {"columns": ["city"]}}])

    assert accept(ds, pointless) == []


def test_a_fix_the_detectors_already_found_is_dropped(make_dataset: MakeDataset) -> None:
    ds = make_dataset(MESSY)
    [first] = accept(ds, fix())

    again = accept(ds, fix(title="Something else entirely"), known=[first])

    assert again == []


def test_the_number_of_fixes_is_capped() -> None:
    too_many = {"fixes": [fix() for _ in range(6)]}

    with pytest.raises(ValueError, match="fixes"):
        SuggestFixesReply.model_validate(too_many)


def test_rejections_are_logged_with_a_reason_but_no_data(
    make_dataset: MakeDataset, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="tidylab.ai")
    ds = make_dataset(MESSY)

    accept(ds, fix(columns=["Comments"]))

    assert "rejected reason=" in caplog.text
    assert "Comments" not in caplog.text


# --- what the model is allowed to see -------------------------------------------------------


def test_the_sample_never_grows_past_the_cap(make_dataset: MakeDataset) -> None:
    rows = "".join(f"E{i},Ann,{i}\n" for i in range(500))
    ds = make_dataset("id,name,n\n" + rows)

    payload = fixes_payload(ds.conn, ds.profile, [], 999)

    assert len(payload["sample_rows"]) == MAX_SAMPLE_ROWS


def test_long_values_are_cut_short(make_dataset: MakeDataset) -> None:
    ds = make_dataset("id,note\n1," + "x" * 500 + "\n")

    payload = fixes_payload(ds.conn, ds.profile, [], 5)

    assert all(
        len(str(value)) <= MAX_VALUE_CHARS
        for row in payload["sample_rows"]
        for value in row.values()
    )


def test_the_payload_carries_the_shape_of_the_file_and_nothing_private(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(MESSY)

    payload = fixes_payload(ds.conn, ds.profile, [], 5)

    assert [column["name"] for column in payload["columns"]] == [
        "Employee_ID",
        "Full_Name",
        "Salary",
        "Notes",
    ]
    assert payload["row_count"] == 20
    written = json.dumps(payload)
    assert "api_key" not in written
    assert "recipe" not in written


def test_the_same_file_always_builds_the_same_payload(make_dataset: MakeDataset) -> None:
    ds = make_dataset(MESSY)

    assert fixes_payload(ds.conn, ds.profile, [], 5) == fixes_payload(ds.conn, ds.profile, [], 5)


def test_what_is_already_known_is_sent_so_it_is_not_repeated(make_dataset: MakeDataset) -> None:
    ds = make_dataset(MESSY)
    issues = ds.issues()

    payload = fixes_payload(ds.conn, ds.profile, issues, 5)

    assert payload["already_found"] == [issue.title for issue in issues]


def test_wording_payload_carries_the_numbers_the_copy_may_use(
    make_dataset: MakeDataset,
) -> None:
    ds = make_dataset(MESSY)
    issues = ds.issues()

    payload = issue_wording_payload(issues)

    assert {item["id"] for item in payload["issues"]} == {issue.id for issue in issues}
    assert all("affected_rows" in item for item in payload["issues"])


# --- rewording ------------------------------------------------------------------------------


def an_issue(title: str, explanation: str, affected: int = 24) -> Issue:
    return Issue(
        id="i1",
        detector=DetectorName.PLACEHOLDERS,
        columns=["Salary"],
        title=title,
        explanation=explanation,
        affected_rows=affected,
        tier=Tier.LIKELY,
        impact=0.2,
        steps=[TrimStep(columns=["Salary"])],
    )


def issue_reply(**item: str) -> RewordIssuesReply:
    return RewordIssuesReply.model_validate({"items": [{"id": "i1", **item}]})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("24 values say N/A", {"24"}),
        ("1,020 rows", {"1020"}),
        ("about 2.50 each", {"2.5"}),
        ("no numbers here", set()),
    ],
)
def test_numbers_are_read_however_they_are_written(text: str, expected: set[str]) -> None:
    assert numbers_in(text) >= expected


def test_the_same_number_written_differently_is_the_same_number() -> None:
    assert not invents_numbers("1020 rows", "1,020 rows")
    assert not invents_numbers("2.50 each", "2.5 each")


def test_a_number_that_was_not_there_is_an_invention() -> None:
    assert invents_numbers("24 values say N/A", "24 values, about 12% of the column")


def test_a_clean_rewrite_replaces_the_template() -> None:
    issue = an_issue('24 "Salary" values say "N/A"', "Spreadsheets leave these out of averages.")

    accepted = accepted_issue_copy(
        [issue],
        issue_reply(
            title='24 salaries say "N/A" instead of a number',
            explanation="Your average pay is worked out from the other rows.",
        ),
    )

    assert accepted["i1"].title == '24 salaries say "N/A" instead of a number'


def test_a_rewrite_that_invents_a_number_is_refused() -> None:
    issue = an_issue('24 "Salary" values say "N/A"', "Spreadsheets leave these out.")

    accepted = accepted_issue_copy(
        [issue],
        issue_reply(
            title="Roughly 3% of salaries are missing",
            explanation="Spreadsheets leave these out.",
        ),
    )

    assert accepted == {}


def test_a_rewrite_may_use_a_number_it_was_given() -> None:
    issue = an_issue("Some salaries are missing", "They are left out.", affected=24)

    accepted = accepted_issue_copy(
        [issue],
        issue_reply(title="24 salaries are missing", explanation="They are left out."),
    )

    assert accepted["i1"].title == "24 salaries are missing"


def test_a_rewrite_that_reaches_for_jargon_is_refused() -> None:
    issue = an_issue("Some salaries are missing", "They are left out.")

    accepted = accepted_issue_copy(
        [issue],
        issue_reply(title="Null values in Salary", explanation="They are left out."),
    )

    assert accepted == {}


def test_a_rewrite_dressed_up_as_markdown_is_refused() -> None:
    issue = an_issue("Some salaries are missing", "They are left out.")

    accepted = accepted_issue_copy(
        [issue],
        issue_reply(title="**Missing salaries**", explanation="They are left out."),
    )

    assert accepted == {}


def test_one_bad_rewrite_does_not_lose_the_good_ones() -> None:
    good = an_issue("Some salaries are missing", "They are left out.")
    other = an_issue("Some phones are short", "They may be wrong.").model_copy(update={"id": "i2"})

    accepted = accepted_issue_copy(
        [good, other],
        RewordIssuesReply.model_validate(
            {
                "items": [
                    {"id": "i1", "title": "12% of the salaries are missing", "explanation": "x."},
                    {"id": "i2", "title": "Some phone numbers look too short", "explanation": "y."},
                ]
            }
        ),
    )

    assert set(accepted) == {"i2"}


def test_a_rewrite_for_something_we_did_not_ask_about_is_ignored() -> None:
    issue = an_issue("Some salaries are missing", "They are left out.")

    accepted = accepted_issue_copy(
        [issue],
        RewordIssuesReply.model_validate(
            {"items": [{"id": "unknown", "title": "Anything", "explanation": "At all."}]}
        ),
    )

    assert accepted == {}


def test_a_question_label_is_reworded_within_the_same_rules() -> None:
    question = Question(
        measure="count",
        group_by="Department",
        label='How many rows are there for each "Department"?',
        prominence=0.6,
    )

    accepted = accepted_question_labels(
        [question],
        RewordQuestionsReply.model_validate(
            {"items": [{"id": question.id, "label": 'How many people are in each "Department"?'}]}
        ),
    )

    assert accepted[question.id] == 'How many people are in each "Department"?'


def test_a_question_label_that_invents_a_number_is_refused() -> None:
    question = Question(measure="count", label="How many rows are there?", prominence=1.0)

    accepted = accepted_question_labels(
        [question],
        RewordQuestionsReply.model_validate(
            {"items": [{"id": question.id, "label": "How many of the 1,020 rows are there?"}]}
        ),
    )

    assert accepted == {}
