"""Questions about a column the recipe itself took away.

A split that replaces its column leaves the file's questions about that column
with nothing to read. "Couldn't be answered" would count as the biggest change a
step can make, when the question was simply replaced: the new columns' own
questions arrive as unlocked ones.
"""

from app.questions.models import Question
from app.steps.apply import RecipePlan


def asks_removed_column(question: Question, plan: RecipePlan) -> bool:
    return any(
        plan.base.get(name) is not None and plan.output.get(name) is None
        for name in question.columns
    )


def still_asked(questions: list[Question], plan: RecipePlan) -> list[Question]:
    return [question for question in questions if not asks_removed_column(question, plan)]
