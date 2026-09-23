"""Questions about a column a split replaced drop out instead of reading as broken."""

from collections.abc import Callable

from app.questions.models import Question
from app.steps.models import Recipe, SplitColumnStep
from tests.conftest import Dataset

MakeDataset = Callable[..., Dataset]

ROWS = "combo,amount\na-x,1\nb-y,2\na-y,3\nb-x,4\n"


def question(**spec: object) -> Question:
    return Question.model_validate({"label": "q", "prominence": 1, **spec})


def split(keep_original: bool) -> Recipe:
    return Recipe(
        steps=[
            SplitColumnStep(
                column="combo", delimiter="-", into=["left", "right"], keep_original=keep_original
            )
        ]
    )


def test_a_question_about_a_replaced_column_is_not_shown(make_dataset: MakeDataset) -> None:
    ds = make_dataset(ROWS)
    by_combo = question(measure="count", group_by="combo")
    total = question(measure="count")

    diffs = ds.engine(questions=[by_combo, total]).compare(split(keep_original=False)).diffs

    ids = {diff.question.id for diff in diffs}
    assert by_combo.id not in ids
    assert total.id in ids
    assert all(diff.after.answerable for diff in diffs)


def test_a_kept_column_is_still_asked_about(make_dataset: MakeDataset) -> None:
    ds = make_dataset(ROWS)
    by_combo = question(measure="count", group_by="combo")

    diffs = ds.engine(questions=[by_combo]).compare(split(keep_original=True)).diffs

    assert by_combo.id in {diff.question.id for diff in diffs}
