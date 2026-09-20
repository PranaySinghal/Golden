"""The story each fixture tells, pinned the same way its answers are."""

import json
from typing import Any

import pytest

from app.compare.engine import ComparisonEngine
from app.detectors.step_order import recipe_for
from app.story import Story, build_story
from tests.conftest import GOLDEN_DIR, SAMPLES, Dataset, open_sample


def told(ds: Dataset) -> Story | None:
    comparison = ComparisonEngine(ds.conn, ds.profile).compare(recipe_for(ds.issues()))
    return build_story(comparison.diffs)


def summary(story: Story | None) -> dict[str, Any]:
    """The sentences, and which answer each figure points at."""
    if story is None:
        return {"sentences": [], "figures": []}
    return {
        "sentences": [sentence.text for sentence in story.sentences],
        "figures": [
            part.text
            for sentence in story.sentences
            for part in sentence.parts
            if part.question_id is not None
        ],
    }


@pytest.mark.parametrize("name", SAMPLES)
def test_story_matches_golden_file(name: str) -> None:
    expected = json.loads((GOLDEN_DIR / "story" / f"{name}.json").read_text())

    assert summary(told(open_sample(name))) == expected


@pytest.mark.parametrize("name", SAMPLES)
def test_every_figure_in_a_story_points_at_an_answer(name: str) -> None:
    ds = open_sample(name)
    comparison = ComparisonEngine(ds.conn, ds.profile).compare(recipe_for(ds.issues()))
    story = build_story(comparison.diffs)
    if story is None:
        return

    asked = {diff.question.id for diff in comparison.diffs}
    for sentence in story.sentences:
        for part in sentence.parts:
            if part.question_id is not None:
                assert part.question_id in asked, part.text


@pytest.mark.parametrize("name", SAMPLES)
def test_a_story_states_no_figure_it_cannot_point_at(name: str) -> None:
    """Numbers live in linked parts; the words between them carry none."""
    story = told(open_sample(name))
    if story is None:
        return

    for sentence in story.sentences:
        for part in sentence.parts:
            if part.question_id is None:
                assert not any(character.isdigit() for character in part.text), part.text


def test_a_file_cleaning_cannot_help_has_no_story() -> None:
    """The cross-tab's numbers come out the same either way, so there's nothing to tell."""
    assert told(open_sample("sales_cross_tab")) is None
