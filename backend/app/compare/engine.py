"""One comparison engine per dataset: answers, attribution, and fast recompute.

The engine holds what's expensive to work out and cheap to keep: the questions
generated from the raw file, the "before" answers, and every answer it has
already computed. Answers are cached by what the rows look like, not by which
step objects made them, so leave-one-out variants, repeated recipes, and
switching a choice back and forth all reuse the same results.

`compare` answers every question on both sides and explains what moved.
`recompute` does the same after a user changes an ask-tier choice, but carries
over every answer the changed steps can't reach, so only the affected questions
are queried again.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import duckdb

from app.compare.after import AfterReading
from app.compare.attribution import Attribution, Budget, attribute
from app.compare.before import BeforeReading
from app.compare.cache import LruCache
from app.compare.diff import diff_answers, unlocked
from app.compare.evaluate import evaluate
from app.compare.impact import rank, score
from app.compare.influence import Influence, influence_of
from app.compare.models import Comparison
from app.compare.reading import Reading, RowSource
from app.compare.retired import still_asked
from app.compare.unlocked import MAX_UNLOCKED, candidates, changed_columns
from app.config import Settings, get_settings
from app.db import work_ref
from app.profile.models import DatasetProfile
from app.questions.generate import generate_questions
from app.questions.models import Answer, AnswerDiff, Question
from app.steps.apply import RecipePlan, answer_key, chain_sql, plan_recipe
from app.steps.identity import work_key
from app.steps.models import Recipe, Step
from app.steps.schema import base_schema

BEFORE_KEY = "before"
# The engine's own scratch tables: the recipe's rows, and one variant's rows
# while attribution asks questions of it.
CLEANED_ROWS = "compare_rows"
VARIANT_ROWS = "compare_variant"


def without_steps(recipe: Recipe, step_ids: frozenset[str]) -> Recipe:
    """The same recipe with those steps turned off. Steps that needed them block."""
    steps: list[Step] = [
        step.model_copy(update={"enabled": False}) if step.id in step_ids else step
        for step in recipe.steps
    ]
    return Recipe(steps=steps)


def applied_contents(plan: RecipePlan, recipe: Recipe) -> dict[str, str]:
    """Applied step id → what it does, ignoring its id and enabled flag."""
    running = {stage.compiled.step_id for stage in plan.stages}
    return {step.id: work_key(step) for step in recipe.steps if step.id in running}


def differing_steps(old: dict[str, str], new: dict[str, str]) -> tuple[set[str], set[str]]:
    """Step ids on each side whose work has no match on the other side.

    Two choices for the same question carry different step objects, so steps are
    matched by what they do. A step that appears in both, unchanged, is not a
    reason to recompute anything.
    """
    old_left, new_left = dict(old), dict(new)
    for step_id, content in list(old_left.items()):
        match = next((other for other, c in new_left.items() if c == content), None)
        if match is not None:
            del old_left[step_id]
            del new_left[match]
    return set(old_left), set(new_left)


@dataclass(frozen=True)
class _Variant:
    """A recipe with some steps turned off, and the key its rows answer under."""

    plan: RecipePlan
    key: str


class ComparisonEngine:
    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        profile: DatasetProfile,
        settings: Settings | None = None,
        questions: list[Question] | None = None,
    ) -> None:
        self._conn = conn
        self._profile = profile
        self._settings = settings or get_settings()
        self._base = base_schema(profile)
        self._before: Reading = BeforeReading([column.name for column in profile.columns])
        self._questions = questions if questions is not None else generate_questions(conn, profile)
        self._answers = LruCache()
        self._attributions: dict[tuple[str, str], Attribution] = {}
        # Unlocked questions found for a set of cleaned rows, keyed like answers.
        self._unlocked: dict[str, list[Question]] = {}
        self._evaluations = 0
        self._recomputed: list[str] = []

    @property
    def questions(self) -> list[Question]:
        """The questions generated from the raw file, before any cleaning."""
        return list(self._questions)

    # --- answering ---------------------------------------------------------------

    def _answer(self, question: Question, reading: Reading, key: str) -> Answer:
        cached = self._answers.get((key, question.id))
        if cached is not None:
            return cached
        result = evaluate(self._conn, question, reading)
        self._answers[(key, question.id)] = result
        self._evaluations += 1
        if question.id not in self._recomputed:
            self._recomputed.append(question.id)
        return result

    def _before_answer(self, question: Question) -> Answer:
        return self._answer(question, self._before, BEFORE_KEY)

    # --- comparing ---------------------------------------------------------------

    def compare(self, recipe: Recipe) -> Comparison:
        self._evaluations = 0
        self._recomputed = []
        return self._run(recipe)

    def recompute(self, previous: Comparison, recipe: Recipe) -> Comparison:
        """Compare again after a choice changed, reusing every answer that can't differ."""
        self._evaluations = 0
        self._recomputed = []

        old_plan = plan_recipe(previous.recipe, self._base)
        new_plan = plan_recipe(recipe, self._base)
        old_key, new_key = answer_key(old_plan, previous.recipe), answer_key(new_plan, recipe)
        if old_key == new_key:
            # The same rows: every answer is already cached under this key.
            return self._run(recipe)

        old_gone, new_added = differing_steps(
            applied_contents(old_plan, previous.recipe), applied_contents(new_plan, recipe)
        )
        old_influence, new_influence = influence_of(old_plan), influence_of(new_plan)
        unlocked_before = self._unlocked.get(old_key, [])

        def affected(question: Question) -> bool:
            return old_influence.touched_by(question, old_gone) or new_influence.touched_by(
                question, new_added
            )

        for question in [*self._questions, *unlocked_before]:
            if affected(question):
                continue
            answer = self._answers.get((old_key, question.id))
            if answer is not None:
                self._answers[(new_key, question.id)] = answer
            found = self._attributions.get((old_key, question.id))
            if found is not None:
                self._attributions[(new_key, question.id)] = found

        # The unlocked list only changes when a changed step has a hand in a
        # created or retyped column, or removes rows, which changes what those
        # columns hold. Otherwise the same questions are still the new ones, and
        # finding them again would cost a pass over the rows.
        new_columns = set(changed_columns(old_plan)) | set(changed_columns(new_plan))
        changed_steps = [
            step
            for influence, ids in ((old_influence, old_gone), (new_influence, new_added))
            for step in influence.steps
            if step.step_id in ids
        ]
        if not any(step.every_question or step.columns & new_columns for step in changed_steps):
            self._unlocked[new_key] = unlocked_before

        return self._run(recipe)

    def _run(self, recipe: Recipe) -> Comparison:
        plan = plan_recipe(recipe, self._base)
        key = answer_key(plan, recipe)
        influence = influence_of(plan)

        try:
            after = self._rows(plan, CLEANED_ROWS)
            asked = still_asked(self._questions, plan)
            questions = [*asked, *self._unlocked_questions(plan, key, after)]
            diffs = [
                score(diff_answers(q, self._before_answer(q), self._answer(q, after, key)))
                for q in questions
            ]
            diffs = self._attribute_all(rank(diffs), recipe, influence, key)
        finally:
            self._drop(CLEANED_ROWS)
            self._drop(VARIANT_ROWS)

        return Comparison(
            recipe=recipe,
            recipe_key=key,
            diffs=diffs,
            evaluations=self._evaluations,
            recomputed=list(self._recomputed),
        )

    # --- rows to read ------------------------------------------------------------

    def _rows(self, plan: RecipePlan, table: str) -> AfterReading:
        """Build a recipe's rows once so many questions can be asked of them cheaply.

        Running the chain of steps costs far more than one aggregate over its
        result, and attribution asks the same variant about many questions.
        These are the engine's own scratch tables: the cleaned table a user
        exports is built elsewhere, from the recipe they kept.
        """
        sql, params = chain_sql(plan)
        self._conn.execute(f"CREATE OR REPLACE TABLE {work_ref(table)} AS {sql}", dict(params))
        return AfterReading(plan.output, RowSource(work_ref(table)))

    def _drop(self, table: str) -> None:
        self._conn.execute(f"DROP TABLE IF EXISTS {work_ref(table)}")

    # --- unlocked questions ------------------------------------------------------

    def _unlocked_questions(self, plan: RecipePlan, key: str, after: Reading) -> list[Question]:
        known = self._unlocked.get(key)
        if known is not None:
            return known
        asked = {question.id for question in self._questions}
        found: list[Question] = []
        for question in candidates(self._conn, plan, self._profile, asked):
            if len(found) == MAX_UNLOCKED:
                break
            if unlocked(self._before_answer(question), self._answer(question, after, key)):
                found.append(question)
        self._unlocked[key] = found
        return found

    # --- attribution -------------------------------------------------------------

    def _attribute_all(
        self, diffs: list[AnswerDiff], recipe: Recipe, influence: Influence, key: str
    ) -> list[AnswerDiff]:
        variants: dict[frozenset[str], _Variant] = {}

        def answer_without(
            disabled: frozenset[str], questions: Sequence[Question]
        ) -> dict[str, Answer]:
            variant = variants.get(disabled)
            if variant is None:
                without = without_steps(recipe, disabled)
                plan = plan_recipe(without, self._base)
                variant = _Variant(plan, answer_key(plan, without))
                variants[disabled] = variant
            missing = [q for q in questions if (variant.key, q.id) not in self._answers]
            if missing:
                rows = self._rows(variant.plan, VARIANT_ROWS)
                for question in missing:
                    self._answer(question, rows, variant.key)
            return {q.id: self._answers[(variant.key, q.id)] for q in questions}

        known = {
            diff.question.id: self._attributions[(key, diff.question.id)]
            for diff in diffs
            if (key, diff.question.id) in self._attributions
        }
        found = attribute(
            [diff for diff in diffs if diff.question.id not in known],
            influence.relevant,
            answer_without,
            Budget(self._settings.max_attribution_queries),
        )
        for question_id, attribution in found.items():
            self._attributions[(key, question_id)] = attribution
        found.update(known)

        return [
            diff.model_copy(
                update={
                    "attribution": found[diff.question.id].step_ids,
                    "attribution_detail": found[diff.question.id].detail,
                    "attribution_method": found[diff.question.id].method,
                }
            )
            for diff in diffs
        ]
