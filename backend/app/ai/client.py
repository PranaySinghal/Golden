"""Asking a model a versioned prompt, and getting a parsed answer or nothing.

Every call is bounded in time, tried at most twice, and logged by name, version
and outcome — never by content. What comes back is parsed into a Pydantic model;
anything that doesn't fit is rejected whole and the caller keeps its templates.
"""

import json
import logging
import re
import time
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.ai.provider import Provider, ProviderError

logger = logging.getLogger("tidylab.ai")

PROMPTS_DIR = Path(__file__).parent / "prompts"
ATTEMPTS = 2
# A model sometimes wraps its JSON in a sentence or a code fence.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class PromptFile(BaseModel):
    """A prompt as it lives on disk: a name, a version, and the instructions."""

    name: str
    version: str
    system: str

    @property
    def id(self) -> str:
        return f"{self.name}.{self.version}"


def load_prompt(name: str, version: str = "v1") -> PromptFile:
    path = PROMPTS_DIR / f"{name}.{version}.md"
    return PromptFile(name=name, version=version, system=path.read_text().strip())


def extract_json(text: str) -> str:
    """The JSON object in a reply, whether or not the model wrapped it in prose."""
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1)
    found = _OBJECT.search(text)
    return found.group(0) if found else text.strip()


def ask[Reply: BaseModel](
    provider: Provider,
    prompt: PromptFile,
    payload: dict[str, object],
    reply_model: type[Reply],
    timeout_ms: int,
) -> Reply | None:
    """Ask once (twice if the service stumbles). None means "use the templates"."""
    user = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    started = time.perf_counter()
    outcome = "error"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            text = provider.complete(prompt.system, user, timeout_ms)
        except ProviderError as error:
            outcome = "unreachable"
            if attempt == ATTEMPTS:
                _log(prompt, provider, started, outcome, detail=str(error))
                return None
            continue
        try:
            parsed = reply_model.model_validate_json(extract_json(text))
        except ValidationError as error:
            # A reply we can't trust isn't worth a second try: the model already
            # had the schema, and the templates are a perfectly good answer.
            _log(prompt, provider, started, "invalid", detail=f"{len(error.errors())} problems")
            return None
        _log(prompt, provider, started, "ok")
        return parsed
    return None


def _log(
    prompt: PromptFile, provider: Provider, started: float, outcome: str, detail: str = ""
) -> None:
    """What happened, never what was said: no payload, no reply, no key."""
    logger.info(
        "ai prompt=%s provider=%s outcome=%s ms=%d%s",
        prompt.id,
        provider.name,
        outcome,
        int((time.perf_counter() - started) * 1000),
        f" detail={detail}" if detail else "",
    )
