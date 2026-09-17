"""Which questions each applied step could possibly affect. Pure: no queries.

A step can only change an answer through the columns it writes, or by removing
rows. Following that forward through the recipe tells us, for any question,
the short list of steps worth re-running without. Everything outside that list
can't have moved the answer, so attribution never queries it.

The pass is deliberately generous: it asks "could this step reach that column?",
not "did it change anything?". Missing a step would mean crediting the wrong
one; including a harmless step only costs a query that finds no change.
"""

from dataclasses import dataclass

from app.questions.models import Question
from app.steps.apply import RecipePlan


@dataclass(frozen=True)
class StepInfluence:
    step_id: str
    # Columns whose final values this step had a hand in.
    columns: frozenset[str]
    # True when the step removes rows, or feeds a step that does: row counts,
    # totals and averages can then move anywhere in the table.
    every_question: bool


@dataclass(frozen=True)
class Influence:
    steps: tuple[StepInfluence, ...]  # in recipe order

    def relevant(self, question: Question) -> list[str]:
        """Ids of the steps that could have moved this question's answer."""
        wanted = question.columns
        return [
            step.step_id for step in self.steps if step.every_question or (wanted & step.columns)
        ]

    def touched_by(self, question: Question, step_ids: set[str]) -> bool:
        return bool(set(self.relevant(question)) & step_ids)

    def writes(self) -> set[str]:
        """Every column any step wrote or created."""
        return {name for step in self.steps for name in step.columns}


def influence_of(plan: RecipePlan) -> Influence:
    # For each column, the steps whose work shows up in its final values.
    behind: dict[str, set[str]] = {name: set() for name in plan.base.names()}
    everywhere: set[str] = set()
    schema = plan.base
    order: list[str] = []

    for stage in plan.stages:
        step_id = stage.compiled.step_id
        order.append(step_id)
        output = stage.compiled.output
        # A step that removes rows without naming columns (repeats across the
        # whole row, or hand-picked rows) is treated as reading everything.
        reads = stage.compiled.reads or (
            tuple(schema.names()) if stage.compiled.removed is not None else ()
        )
        inherited: set[str] = set()
        for name in reads:
            inherited |= behind.get(name, set())
        involved = inherited | {step_id}

        written = {spec.output_column for spec in stage.compiled.changes}
        written |= set(stage.compiled.creates)
        # A column the step dropped is a change to it too: questions about it
        # stop being answerable.
        written |= set(schema.names()) - set(output.names())
        for name in written:
            behind[name] = behind.get(name, set()) | involved

        if stage.compiled.removed is not None:
            everywhere |= involved
        schema = output

    return Influence(
        steps=tuple(
            StepInfluence(
                step_id=step_id,
                columns=frozenset(name for name, steps in behind.items() if step_id in steps),
                every_question=step_id in everywhere,
            )
            for step_id in order
        )
    )
