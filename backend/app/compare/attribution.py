"""Which steps moved an answer, found by re-running the recipe without them.

For a question whose answer changed, each step that could matter (see
influence.py) is turned off in turn and the question asked again. A step is
responsible when the answer moves without it; how far it moves is the step's
contribution. Turning a step off also blocks the steps that depended on it, so
a step gets credit for what its dependents did.

Some steps only matter together: trimming spaces and merging spellings both
fold "Active " into "Active", so removing either alone changes nothing. When no
single step explains a change, the fallback turns off every relevant step at
once, then looks for the smallest pairs that move the answer.

Work is done one variant at a time, answering every question that needs that
variant before moving on, because producing a variant's rows costs far more than
asking a question of them.

The number of questions asked is capped. Questions are explained from the
highest impact down, and when the cap won't stretch to a question's exact
answer, it falls back to the steps that could have mattered. The cap is charged
the same way whether or not an answer is already cached, so a comparison
explains the same things whatever ran before it.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations

from app.compare.diff import diff_answers
from app.compare.impact import magnitude
from app.questions.models import Answer, AnswerDiff, Question, StepContribution

# Beyond this, checking every pair costs more than it explains, so the whole
# relevant set is reported as one group.
MAX_PAIR_CHECK_STEPS = 6


class OutOfBudgetError(Exception):
    """Raised when attribution would need more questions than it's allowed."""


@dataclass
class Budget:
    """Questions attribution may still ask in this comparison."""

    remaining: int

    def spend(self, questions: int = 1) -> None:
        if questions > self.remaining:
            raise OutOfBudgetError
        self.remaining -= questions


# Answers questions from the recipe with a set of steps turned off.
AnswerWithout = Callable[[frozenset[str], Sequence[Question]], Mapping[str, Answer]]


@dataclass(frozen=True)
class Attribution:
    detail: list[StepContribution]
    method: str  # "exact" | "estimated" | "none"

    @property
    def step_ids(self) -> list[str]:
        seen: list[str] = []
        for contribution in self.detail:
            for step_id in contribution.step_ids:
                if step_id not in seen:
                    seen.append(step_id)
        return seen


NOTHING_TO_EXPLAIN = Attribution(detail=[], method="none")


def estimate(relevant: Sequence[str]) -> Attribution:
    """Without asking anything: every step that could have moved the answer."""
    if not relevant:
        return Attribution(detail=[], method="estimated")
    return Attribution(
        detail=[StepContribution(step_ids=list(relevant), together=len(relevant) > 1)],
        method="estimated",
    )


@dataclass
class _Work:
    """One question being explained, and what re-running has shown so far."""

    diff: AnswerDiff
    relevant: list[str]
    singles: dict[str, float] = field(default_factory=dict)
    pairs: list[tuple[str, str, float]] = field(default_factory=list)
    joint: float | None = None
    gave_up: bool = False

    @property
    def question(self) -> Question:
        return self.diff.question

    def record(self, answer: Answer) -> float | None:
        """How far the answer goes back without `steps`, or None if it doesn't move."""
        without = diff_answers(self.question, answer, self.diff.after)
        if not without.changed:
            return None
        return round(magnitude(without), 6)

    def attribution(self) -> Attribution:
        if self.gave_up:
            return estimate(self.relevant)
        order = {step_id: position for position, step_id in enumerate(self.relevant)}
        if self.singles:
            found = [
                StepContribution(step_ids=[step_id], contribution=moved)
                for step_id, moved in self.singles.items()
            ]
            # Biggest contribution first, recipe order breaking ties.
            found.sort(key=lambda c: (-c.contribution, order[c.step_ids[0]]))
            return Attribution(detail=found, method="exact")
        if self.pairs:
            together = [
                StepContribution(step_ids=[a, b], together=True, contribution=moved)
                for a, b, moved in self.pairs
            ]
            together.sort(key=lambda c: (-c.contribution, order[c.step_ids[0]]))
            return Attribution(detail=together, method="exact")
        if self.joint is not None:
            return Attribution(
                detail=[
                    StepContribution(
                        step_ids=list(self.relevant), together=True, contribution=self.joint
                    )
                ],
                method="exact",
            )
        # Every relevant step turned off and the answer stayed put: the change
        # came from somewhere the influence pass couldn't see. Don't blame a step.
        return estimate(self.relevant)


def attribute(
    diffs: Sequence[AnswerDiff],
    relevant_for: Callable[[Question], list[str]],
    answer_without: AnswerWithout,
    budget: Budget,
) -> dict[str, Attribution]:
    """Explain every changed answer. Unchanged answers are left alone."""
    found: dict[str, Attribution] = {}
    work: list[_Work] = []
    for diff in diffs:
        if not diff.changed:
            found[diff.question.id] = NOTHING_TO_EXPLAIN
            continue
        relevant = relevant_for(diff.question)
        if not relevant:
            # It changed, but no step could have done it. Don't blame one.
            found[diff.question.id] = estimate([])
            continue
        work.append(_Work(diff=diff, relevant=relevant))

    for item in _afford(work, budget):
        found[item.question.id] = estimate(item.relevant)
    planned = [item for item in work if item.question.id not in found]

    _each_step_alone(planned, answer_without, budget)
    unexplained = [item for item in planned if not item.singles and not item.gave_up]
    _only_together(unexplained, answer_without, budget)
    for item in planned:
        found[item.question.id] = item.attribution()
    return found


def _afford(work: list[_Work], budget: Budget) -> list[_Work]:
    """Drop the lowest-impact questions until the exact work fits the budget."""
    left = budget.remaining
    skipped: list[_Work] = []
    for item in sorted(work, key=lambda w: -w.diff.impact):
        if len(item.relevant) <= left:
            left -= len(item.relevant)
        else:
            skipped.append(item)
    return skipped


def _ask(
    steps: frozenset[str],
    items: Sequence[_Work],
    answer_without: AnswerWithout,
    budget: Budget,
) -> Mapping[str, Answer] | None:
    """Answer one variant for several questions, or None if the budget won't stretch."""
    if not items:
        return {}
    try:
        budget.spend(len(items))
    except OutOfBudgetError:
        return None
    return answer_without(steps, [item.question for item in items])


def _each_step_alone(work: Sequence[_Work], answer_without: AnswerWithout, budget: Budget) -> None:
    for step_id in _steps_in_order(work):
        items = [item for item in work if step_id in item.relevant and not item.gave_up]
        answers = _ask(frozenset({step_id}), items, answer_without, budget)
        if answers is None:
            for item in items:
                item.gave_up = True
            continue
        for item in items:
            moved = item.record(answers[item.question.id])
            if moved is not None:
                item.singles[step_id] = moved


def _only_together(work: Sequence[_Work], answer_without: AnswerWithout, budget: Budget) -> None:
    """Questions no single step explains: try all their steps at once, then pairs."""
    for relevant, items in _by_relevant_set(work):
        answers = _ask(frozenset(relevant), items, answer_without, budget)
        if answers is None:
            for item in items:
                item.gave_up = True
            continue
        for item in items:
            item.joint = item.record(answers[item.question.id])
        moving = [item for item in items if item.joint is not None]
        if len(relevant) > MAX_PAIR_CHECK_STEPS or not moving:
            continue
        for a, b in combinations(relevant, 2):
            pair_answers = _ask(frozenset({a, b}), moving, answer_without, budget)
            if pair_answers is None:
                # Out of budget, but the joint check already explained these.
                break
            for item in moving:
                moved = item.record(pair_answers[item.question.id])
                if moved is not None:
                    item.pairs.append((a, b, moved))


def _steps_in_order(work: Iterable[_Work]) -> list[str]:
    ordered: list[str] = []
    for item in work:
        for step_id in item.relevant:
            if step_id not in ordered:
                ordered.append(step_id)
    return ordered


def _by_relevant_set(work: Iterable[_Work]) -> list[tuple[list[str], list[_Work]]]:
    """Questions that depend on exactly the same steps share their extra checks."""
    groups: dict[tuple[str, ...], list[_Work]] = {}
    for item in work:
        groups.setdefault(tuple(item.relevant), []).append(item)
    return [(list(steps), items) for steps, items in groups.items()]
