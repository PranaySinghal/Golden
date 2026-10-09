"""A model filling in a new column, one answer per different value.

This is the one place in the app where a model supplies cell values rather
than wording (an owner-approved exception to "AI proposes, code executes"; see
docs/decisions.md). So everything it says is treated as a claim:

- It may answer "not sure", and is told a blank beats a guess.
- A label must come from the closed list the column was created with.
- Numbers and amounts are refused outright. Those stay with the engine.
- Each answer is short, single-line text; a web address must look like one.
- An answer that fails a check leaves the cell empty with the reason
  "not sure". It is never repaired.

Values are sent in batches, a few at a time in parallel, and remembered so the
same question isn't paid for twice.
"""

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.ai.client import ask, load_prompt
from app.ai.schemas import FillReply
from app.ai.wording import MARKDOWN
from app.connectors import freshness
from app.connectors.models import LookupResult, Status
from app.connectors.runner import Runtime

BATCH_SIZE = 40
PARALLEL_CALLS = 4
MAX_ANSWER_CHARS = 120
# Bumped with ANSWER rules below, so answers accepted under old rules are re-asked.
CACHE_AS = "ai_fill:v1"
# A bare number, with or without a currency sign, a percent or a "k"/"million".
_NUMBER = re.compile(
    r"[\s$€£¥₹~≈]*[-+]?\d[\d.,\s]*(%|[kmb]n?|thousand|million|billion|trillion)?\s*", re.I
)
_WEBSITE = re.compile(r"(https?://)?([a-z0-9-]+\.)+[a-z]{2,}(/\S*)?", re.I)

# Ways of saying "I don't know" that aren't a value.
_NON_ANSWERS = {"unknown", "n/a", "na", "none", "null", "not sure", "unsure", "not available"}


@dataclass(frozen=True)
class FillSpec:
    """What the new column is, as the step that creates it describes it."""

    name: str
    instruction: str
    kind: str  # "label" | "text" | "website"
    based_on: str
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class FillItem:
    key: str
    shown: str
    context: dict[str, str] = field(default_factory=dict)


def accept_answer(spec: FillSpec, answer: str | None) -> str | None:
    """The answer as it may go in a cell, or None when it may not."""
    raw = (answer or "").strip()
    if "\n" in raw:
        return None
    text = " ".join(raw.split())
    if not text or len(text) > MAX_ANSWER_CHARS:
        return None
    if any(mark in text for mark in MARKDOWN) or text.lower() in _NON_ANSWERS:
        return None
    if _NUMBER.fullmatch(text):
        return None
    if spec.kind == "label":
        allowed = {choice.casefold(): choice for choice in spec.choices}
        return allowed.get(text.casefold())
    if spec.kind == "website":
        return text.lower() if _WEBSITE.fullmatch(text) else None
    return text


def _cache_key(spec: FillSpec, item: FillItem, runtime: Runtime, prompt_id: str) -> str:
    asked = [
        runtime.model_id,
        prompt_id,
        spec.name,
        spec.instruction,
        spec.kind,
        list(spec.choices),
        item.key,
        sorted(item.context.items()),
    ]
    return hashlib.sha256(json.dumps(asked, ensure_ascii=False).encode()).hexdigest()


def fill_values(
    spec: FillSpec, items: list[FillItem], runtime: Runtime, limit: int | None = None
) -> dict[str, LookupResult]:
    """An answer or a reason for every item. `items` come most common first."""
    prompt = load_prompt("fill_column")
    results: dict[str, LookupResult] = {}
    to_ask: list[FillItem] = []
    cap = runtime.fill_max_values if limit is None else limit
    now = runtime.now()

    for item in items:
        held = runtime.cache.get(CACHE_AS, _cache_key(spec, item, runtime, prompt.id))
        if held is not None:
            results[item.key] = held
        elif len(to_ask) < cap:
            to_ask.append(item)
        else:
            results[item.key] = LookupResult(Status.PENDING)

    batches = [to_ask[start : start + BATCH_SIZE] for start in range(0, len(to_ask), BATCH_SIZE)]

    def run(batch: list[FillItem]) -> dict[str, LookupResult]:
        return _ask_batch(spec, batch, runtime, prompt.id, freshness.stamp(now))

    if batches:
        with ThreadPoolExecutor(max_workers=PARALLEL_CALLS) as pool:
            for answered in pool.map(run, batches):
                results.update(answered)
    return results


def _ask_batch(
    spec: FillSpec, batch: list[FillItem], runtime: Runtime, prompt_id: str, fetched_at: str
) -> dict[str, LookupResult]:
    payload: dict[str, object] = {
        "column": spec.name,
        "meaning": spec.instruction,
        "based_on": spec.based_on,
        "allowed_answers": list(spec.choices) or None,
        "rows": [
            {
                "id": number,
                "value": item.shown,
                **({"context": item.context} if item.context else {}),
            }
            for number, item in enumerate(batch, start=1)
        ],
    }
    reply = ask(
        runtime.model, load_prompt("fill_column"), payload, FillReply, runtime.fill_timeout_ms
    )
    if reply is None:
        # Unreachable, over its limit, or an answer we couldn't read. Not a
        # reason to guess, and not remembered: the next run asks again.
        return {item.key: LookupResult(Status.UNAVAILABLE) for item in batch}

    said = {answer.id: answer.answer for answer in reply.answers}
    results: dict[str, LookupResult] = {}
    for number, item in enumerate(batch, start=1):
        accepted = accept_answer(spec, said.get(number))
        result = (
            LookupResult(Status.FOUND, accepted, fetched_at=fetched_at)
            if accepted is not None
            else LookupResult(Status.NOT_SURE, fetched_at=fetched_at)
        )
        runtime.cache.put(CACHE_AS, _cache_key(spec, item, runtime, prompt_id), result)
        results[item.key] = result
    return results
