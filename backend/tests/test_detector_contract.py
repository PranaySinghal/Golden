"""Rules every detector follows, checked on every sample file."""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import duckdb
import pytest

from app.detectors import (
    category_variants,
    combined_columns,
    contact_formats,
    dates,
    duplicates,
    extra_spaces,
    identifier_repeats,
    missing_values,
    numbers_as_text,
    out_of_range,
    placeholders,
)
from app.detectors.base import DetectorContext
from app.detectors.models import Issue, Tier
from app.detectors.step_order import RANK, recipe_for
from app.steps.apply import StepStatus
from app.steps.models import STEP_LABELS
from tests.conftest import (
    GOLDEN_DIR,
    REPO_ROOT,
    SAMPLE_FILES,
    SAMPLES,
    SAMPLES_DIR,
    TODAY,
    Dataset,
    load,
)

DETECTOR_MODULES = [
    placeholders,
    numbers_as_text,
    dates,
    extra_spaces,
    category_variants,
    combined_columns,
    duplicates,
    identifier_repeats,
    contact_formats,
    out_of_range,
    missing_values,
]
JARGON = re.compile(
    r"\b(null|nan|varchar|string|dtype|regex|cardinality|semantic|schema|parse|boolean|"
    r"duplicate rows|outlier|iqr|quantile|identifier|detector|column type|data type)\b",
    re.IGNORECASE,
)


def dataset(name: str, anonymize: bool = False) -> Dataset:
    filename = SAMPLE_FILES[name]
    data = (SAMPLES_DIR / filename).read_bytes()
    if anonymize:
        header, rest = data.split(b"\n", 1)
        width = len(header.split(b","))
        data = ",".join(f"col_{i + 1}" for i in range(width)).encode() + b"\n" + rest
    conn = duckdb.connect(":memory:")
    load(conn, data, filename=filename)
    return Dataset(conn)


@pytest.fixture(scope="module", params=SAMPLES)
def sample(request: pytest.FixtureRequest) -> tuple[str, Dataset, list[Issue]]:
    ds = dataset(request.param)
    return request.param, ds, ds.issues()


def summary(issues: list[Issue]) -> list[dict[str, Any]]:
    rows = []
    for issue in issues:
        recommended = [c.label for c in (issue.ask.choices if issue.ask else []) if c.recommended]
        rows.append(
            {
                "detector": issue.detector.value,
                "columns": issue.columns,
                "tier": issue.tier.value,
                "affected_rows": issue.affected_rows,
                "recommended": recommended[0] if recommended else None,
            }
        )
    return rows


def test_issues_match_golden_file(sample: tuple[str, Dataset, list[Issue]]) -> None:
    name, _, issues = sample
    expected = json.loads((GOLDEN_DIR / "issues" / f"{name}.json").read_text())

    assert summary(issues) == expected


def test_employee_acceptance_issues() -> None:
    """M3 acceptance criteria, spelled out."""
    issues = dataset("Messy_Employee_dataset").issues()
    found = {(i.detector.value, tuple(i.columns), i.tier.value): i for i in issues}

    salary = found[("placeholders", ("Salary",), "ask")]
    assert salary.affected_rows == 24
    assert found[("combined_columns", ("Department_Region",), "likely")]
    assert found[("identifier_repeats", ("Email",), "ask")]
    assert found[("contact_formats", ("Phone",), "likely")].affected_rows == 1020
    short = found[("contact_formats", ("Phone",), "ask")]
    assert "shorter than the usual 10 digits" in short.title
    assert found[("missing_values", ("Age",), "ask")].affected_rows == 211
    dates = found[("dates", ("Join_Date",), "safe")]
    assert "only make sense with the month first" in dates.explanation


def test_messier_variant_issues() -> None:
    kinds = {
        (i.detector.value, i.tier.value) for i in dataset("Messy_Employee_dataset_messier").issues()
    }

    assert ("category_variants", "safe") in kinds
    assert ("extra_spaces", "safe") in kinds
    assert ("duplicates", "safe") in kinds
    assert ("duplicates", "likely") in kinds
    assert ("dates", "likely") in kinds  # mixed date styles
    assert ("numbers_as_text", "likely") in kinds  # "$85k"


def test_issue_ids_are_stable(sample: tuple[str, Dataset, list[Issue]]) -> None:
    _, ds, issues = sample

    again = ds.issues()

    assert [i.model_dump() for i in again] == [i.model_dump() for i in issues]
    assert len({i.id for i in issues}) == len(issues)


def test_tier_shapes(sample: tuple[str, Dataset, list[Issue]]) -> None:
    _, _, issues = sample
    ids = {i.id for i in issues}
    for issue in issues:
        if issue.tier is Tier.ASK:
            assert issue.ask is not None
            assert 2 <= len(issue.ask.choices) <= 4
            assert sum(c.recommended for c in issue.ask.choices) <= 1
            assert not issue.steps
        else:
            assert issue.steps
            assert issue.ask is None
        assert set(issue.requires) <= ids
        assert 0.0 <= issue.impact <= 1.0


def test_issues_are_ranked_by_impact(sample: tuple[str, Dataset, list[Issue]]) -> None:
    _, _, issues = sample

    impacts = [i.impact for i in issues]

    assert impacts == sorted(impacts, reverse=True)


def test_accepting_everything_gives_a_recipe_with_nothing_blocked(
    sample: tuple[str, Dataset, list[Issue]],
) -> None:
    _, ds, issues = sample
    before = ds.raw_fingerprint()

    result = ds.apply_recipe(recipe_for(issues))

    blocked = [(o.step_id, o.reason) for o in result.outcomes if o.status is StepStatus.BLOCKED]
    assert blocked == []
    assert ds.raw_fingerprint() == before


def test_every_ask_choice_runs(sample: tuple[str, Dataset, list[Issue]]) -> None:
    _, ds, issues = sample
    for issue in issues:
        if issue.ask is None:
            continue
        for choice in issue.ask.choices:
            recipe = recipe_for(issues, answers={issue.id: choice.id})
            outcomes = ds.apply_recipe(recipe, lineage=False).outcomes
            assert all(o.status is not StepStatus.BLOCKED for o in outcomes), (
                issue.title,
                choice.label,
            )


def test_required_issues_are_pulled_in(sample: tuple[str, Dataset, list[Issue]]) -> None:
    _, _, issues = sample
    for issue in issues:
        if not issue.requires:
            continue
        recipe = recipe_for(issues, accepted={issue.id})
        steps = {s.id for s in recipe.steps}
        for required in issue.requires:
            required_issue = next(i for i in issues if i.id == required)
            assert {s.id for s in required_issue.steps} <= steps


def test_recipe_steps_follow_the_standard_order(
    sample: tuple[str, Dataset, list[Issue]],
) -> None:
    _, _, issues = sample

    ranks = [RANK[s.type] for s in recipe_for(issues).steps]

    assert ranks == sorted(ranks)
    assert set(RANK) == set(STEP_LABELS)


def test_copy_uses_business_language(sample: tuple[str, Dataset, list[Issue]]) -> None:
    _, _, issues = sample
    for issue in issues:
        texts = [issue.title, issue.explanation]
        if issue.ask:
            texts += [issue.ask.prompt]
            texts += [t for c in issue.ask.choices for t in (c.label, c.description)]
        for text in texts:
            assert not JARGON.search(
                text.replace(f'"{issue.columns[0]}"' if issue.columns else "", "")
            ), text


def test_numbers_in_copy_come_from_the_evidence(
    sample: tuple[str, Dataset, list[Issue]],
) -> None:
    _, ds, issues = sample
    ctx = DetectorContext(conn=ds.conn, profile=ds.profile, today=TODAY)
    gathered = [module.gather(ctx) for module in DETECTOR_MODULES]
    evidence_text = json.dumps(
        [ds.profile.model_dump(), [i.model_dump(exclude={"title", "explanation"}) for i in issues]],
        default=str,
    ) + repr(gathered)
    known = set(re.findall(r"\d+", evidence_text))
    for issue in issues:
        for text in (issue.title, issue.explanation):
            # Quoted text is a value copied from the file, so only check the words around it.
            unquoted = re.sub(r'"[^"]*"', "", text)
            for number in re.findall(r"\d[\d,]*", unquoted):
                assert number.replace(",", "") in known, (number, text)


@pytest.mark.parametrize(
    ("name", "only_with_names"),
    [
        # Phone is recognized by its name alone (an M1 decision), so its checks need it.
        (
            "Messy_Employee_dataset",
            [("contact_formats", "ask", 92), ("contact_formats", "likely", 1020)],
        ),
        ("store_orders", []),
    ],
)
def test_detection_does_not_depend_on_column_names(
    name: str, only_with_names: list[tuple[str, str, int]]
) -> None:
    def shape(issues: list[Issue]) -> list[tuple[str, str, int]]:
        return sorted((i.detector.value, i.tier.value, i.affected_rows) for i in issues)

    named = shape(dataset(name).issues())
    anonymous = shape(dataset(name, anonymize=True).issues())

    assert [s for s in named if s not in anonymous] == only_with_names
    assert [s for s in anonymous if s not in named] == []


def test_messier_variant_script_is_reproducible(tmp_path: Path) -> None:
    output = tmp_path / "messier.csv"
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "data" / "scripts" / "make_messy_variant.py"),
            "--input",
            str(SAMPLES_DIR / "Messy_Employee_dataset.csv"),
            "--output",
            str(output),
            "--seed",
            "7",
        ],
        check=True,
        capture_output=True,
    )

    assert output.read_bytes() == (SAMPLES_DIR / "Messy_Employee_dataset_messier.csv").read_bytes()
