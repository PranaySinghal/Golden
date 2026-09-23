"""The AI endpoint: off by default, additive when it works, harmless when it doesn't."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.enhance import FAILED_NOTE
from app.ai.limiter import BudgetedProvider, CallBudget
from app.ai.provider import Provider, ProviderError
from app.api.deps import get_provider
from app.config import Settings
from app.main import app
from tests.conftest import SAMPLES_DIR

EMPLOYEE = (SAMPLES_DIR / "Messy_Employee_dataset.csv").read_bytes()

SUGGESTED = {
    "fixes": [
        {
            "columns": ["Full_Name"],
            "title": '"Full_Name" holds a first and last name together',
            "explanation": "Splitting them lets you sort and group by either one.",
            "confidence": "likely",
            "steps": [
                {
                    "type": "split_column",
                    "arguments": {
                        "column": "Full_Name",
                        "delimiter": " ",
                        "into": ["Given_Name", "Family_Name"],
                    },
                }
            ],
        }
    ]
}

NAMES = "Full_Name,Team\n" + "".join(
    f"Ann Lee {i},{'Sales' if i % 2 else 'Support'}\n" for i in range(20)
)


class ScriptedProvider:
    """Answers each prompt with a canned reply, by prompt name."""

    name = "scripted"

    def __init__(self, replies: dict[str, str | Exception]) -> None:
        self.replies = replies
        self.asked: list[str] = []

    def complete(self, system: str, user: str, timeout_ms: int) -> str:
        which = next((name for name in self.replies if name in system.lower()), "")
        if not which:
            which = "fixes" if "fix" in system.lower() else "wording"
        self.asked.append(which)
        reply = self.replies.get(which, "{}")
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _rule_based_by_default() -> Iterator[None]:
    app.state.settings = Settings()
    yield
    app.state.settings = Settings()


def upload(client: TestClient, data: bytes | str, name: str = "file.csv") -> str:
    raw = data.encode() if isinstance(data, str) else data
    return str(client.post("/api/datasets", files={"file": (name, raw, "text/csv")}).json()["id"])


def use_provider(provider: Provider) -> None:
    """Stand a fake service in for the real one. No key is ever involved."""
    app.state.settings = Settings(llm_provider="anthropic", llm_api_key="test-key")
    app.dependency_overrides[get_provider] = lambda: provider


@pytest.fixture(autouse=True)
def _no_provider_by_default() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_provider, None)


def ai(client: TestClient, dataset: str) -> dict[str, Any]:
    response = client.get(f"/api/datasets/{dataset}/ai")
    assert response.status_code == 200
    return dict(response.json())


# --- with no model service ------------------------------------------------------------------


def test_without_a_service_the_endpoint_says_so_and_changes_nothing(client: TestClient) -> None:
    dataset = upload(client, EMPLOYEE, "Messy_Employee_dataset.csv")
    before = client.get(f"/api/datasets/{dataset}/issues").json()

    body = ai(client, dataset)

    assert body["status"] == "off"
    assert (body["added"], body["issue_copy"], body["note"]) == ([], {}, None)
    after = client.get(f"/api/datasets/{dataset}/issues").json()
    assert [issue["id"] for issue in after["issues"]] == [i["id"] for i in before["issues"]]


# --- when it works --------------------------------------------------------------------------


def test_a_sound_suggestion_becomes_a_card_that_can_be_accepted(client: TestClient) -> None:
    dataset = upload(client, NAMES)
    client.get(f"/api/datasets/{dataset}/issues")
    use_provider(ScriptedProvider({"fix": json.dumps(SUGGESTED)}))

    body = ai(client, dataset)

    assert body["status"] == "ready"
    [card] = body["added"]
    assert card["source"] == "ai"
    assert card["tier"] == "likely"
    assert card["affected_rows"] == 20

    # and from here it behaves like any other card
    accepted = client.post(f"/api/datasets/{dataset}/issues/{card['id']}/accept", json={})
    assert accepted.status_code == 200
    assert any(step["type"] == "split_column" for step in accepted.json()["steps"])
    preview = client.get(f"/api/datasets/{dataset}/preview", params={"issue_id": card["id"]})
    assert preview.status_code == 200


def test_a_suggestion_joins_the_list_the_review_screen_reads(client: TestClient) -> None:
    dataset = upload(client, NAMES)
    client.get(f"/api/datasets/{dataset}/issues")
    use_provider(ScriptedProvider({"fix": json.dumps(SUGGESTED)}))
    added = ai(client, dataset)["added"]

    listed = client.get(f"/api/datasets/{dataset}/issues").json()

    assert {issue["id"] for issue in listed["issues"]} >= {card["id"] for card in added}
    assert any(issue["source"] == "ai" for issue in listed["issues"])


def test_better_wording_replaces_the_template(client: TestClient) -> None:
    dataset = upload(client, EMPLOYEE, "Messy_Employee_dataset.csv")
    issues = client.get(f"/api/datasets/{dataset}/issues").json()["issues"]
    first = issues[0]
    use_provider(
        ScriptedProvider(
            {
                "rewrite messages": json.dumps(
                    {
                        "items": [
                            {
                                "id": first["id"],
                                "title": "Names are stored with spaces around them",
                                "explanation": "Those spaces split one name into two groups.",
                            }
                        ]
                    }
                )
            }
        )
    )

    body = ai(client, dataset)

    assert body["issue_copy"][first["id"]]["title"] == "Names are stored with spaces around them"


# The story prompt, as the scripted provider recognises it.
STORY = "tell a business user"
PLAIN = json.dumps({"sentences": ["Your file reads the way you meant it to."]})


def accept_everything(client: TestClient, dataset: str) -> None:
    """Take every suggestion, so the answers actually move."""
    for issue in client.get(f"/api/datasets/{dataset}/issues").json()["issues"]:
        choice = issue["ask"]["choices"][0]["id"] if issue.get("ask") else None
        client.post(
            f"/api/datasets/{dataset}/issues/{issue['id']}/accept",
            json={"choice_id": choice} if choice else {},
        )


def test_a_story_is_told_for_the_rows_as_they_stand(client: TestClient) -> None:
    """Asked for from the review screen, before anything has opened "what changed"."""
    dataset = upload(client, EMPLOYEE, "Messy_Employee_dataset.csv")
    accept_everything(client, dataset)
    provider = ScriptedProvider({STORY: PLAIN})
    use_provider(provider)

    body = ai(client, dataset)

    assert STORY in provider.asked
    assert body["story"]["source"] == "ai"
    assert [part["text"] for part in body["story"]["sentences"][0]["parts"]] == [
        "Your file reads the way you meant it to."
    ]


def test_a_story_says_which_rows_it_describes(client: TestClient) -> None:
    """So the screen can tell that its figures are the ones on the cards."""
    dataset = upload(client, EMPLOYEE, "Messy_Employee_dataset.csv")
    accept_everything(client, dataset)
    use_provider(ScriptedProvider({STORY: PLAIN}))

    told = ai(client, dataset)["story"]
    compared = client.get(f"/api/datasets/{dataset}/compare").json()

    assert told["recipe_key"] == compared["recipe_key"]
    assert compared["story"]["recipe_key"] == compared["recipe_key"]


def test_a_story_is_told_again_once_the_answers_move(client: TestClient) -> None:
    """The rest of what a model offers describes the file; this describes the answers."""
    dataset = upload(client, EMPLOYEE, "Messy_Employee_dataset.csv")
    accept_everything(client, dataset)
    provider = ScriptedProvider({STORY: PLAIN})
    use_provider(provider)
    first = ai(client, dataset)
    client.post(f"/api/datasets/{dataset}/recipe/undo")

    again = ai(client, dataset)

    assert provider.asked.count(STORY) == 2
    # and the rest was not asked for a second time
    assert provider.asked.count("fixes") == 1
    assert first["story"]["recipe_key"] != again["story"]["recipe_key"]


def test_a_file_cleaning_does_not_move_is_never_asked_about(client: TestClient) -> None:
    """Nothing moved means nothing to tell, and no reason to invite an invention."""
    dataset = upload(client, "Team,Notes\nSales,ok\nSupport,fine\nSales,ok\n")
    client.get(f"/api/datasets/{dataset}/issues")
    provider = ScriptedProvider({STORY: PLAIN})
    use_provider(provider)

    body = ai(client, dataset)

    assert client.get(f"/api/datasets/{dataset}/compare").json()["cards"] == []
    assert STORY not in provider.asked
    assert body["story"] is None


def test_the_answer_is_worked_out_once_and_kept(client: TestClient) -> None:
    dataset = upload(client, NAMES)
    client.get(f"/api/datasets/{dataset}/issues")
    provider = ScriptedProvider({"fix": json.dumps(SUGGESTED)})
    use_provider(provider)

    ai(client, dataset)
    asked = len(provider.asked)
    ai(client, dataset)

    assert len(provider.asked) == asked


# --- when it doesn't ------------------------------------------------------------------------


def test_a_service_that_cannot_be_reached_leaves_everything_working(client: TestClient) -> None:
    dataset = upload(client, NAMES)
    before = client.get(f"/api/datasets/{dataset}/issues").json()
    use_provider(
        ScriptedProvider(
            {
                "fix": ProviderError("down"),
                "rewrite": ProviderError("down"),
                "": ProviderError("down"),
            }
        )
    )

    body = ai(client, dataset)

    assert body["status"] == "failed"
    assert body["note"] == FAILED_NOTE
    assert body["added"] == []
    after = client.get(f"/api/datasets/{dataset}/issues").json()
    assert [issue["id"] for issue in after["issues"]] == [i["id"] for i in before["issues"]]


def test_a_suggestion_about_a_column_that_does_not_exist_is_quietly_dropped(
    client: TestClient,
) -> None:
    dataset = upload(client, NAMES)
    client.get(f"/api/datasets/{dataset}/issues")
    hallucinated = {
        "fixes": [
            {
                **SUGGESTED["fixes"][0],
                "columns": ["Customer_Email"],
                "steps": [{"type": "cast_number", "arguments": {"column": "Customer_Email"}}],
            }
        ]
    }
    use_provider(ScriptedProvider({"fix": json.dumps(hallucinated)}))

    body = ai(client, dataset)

    assert body["status"] == "ready"
    assert body["added"] == []


def test_an_unknown_file_is_a_clear_404(client: TestClient) -> None:
    response = client.get("/api/datasets/nope/ai")

    assert response.status_code == 404
    assert response.json()["code"] == "dataset_not_found"


# --- past the rate limit --------------------------------------------------------------------


def test_past_the_limit_the_review_still_loads_with_its_own_wording(client: TestClient) -> None:
    dataset = upload(client, NAMES)
    before = client.get(f"/api/datasets/{dataset}/issues").json()
    spent = CallBudget(1)
    spent.take()
    use_provider(BudgetedProvider(ScriptedProvider({"fix": json.dumps(SUGGESTED)}), spent))

    body = ai(client, dataset)

    assert body["status"] == "failed"
    assert body["note"] == FAILED_NOTE
    assert body["added"] == []
    after = client.get(f"/api/datasets/{dataset}/issues").json()
    assert [i["id"] for i in after["issues"]] == [i["id"] for i in before["issues"]]
