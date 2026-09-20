"""The one call the API makes: ask a model for more, keep only what survives.

Three prompts run: one for fixes the detectors missed, two for wording. Each is
independent, so a model that writes good titles but bad fixes still helps, and a
model that can't be reached at all costs the user nothing but a quiet note.
"""

import logging
from datetime import date
from typing import Literal

import duckdb
from pydantic import BaseModel, Field

from app.ai import payload as payloads
from app.ai.client import ask, load_prompt
from app.ai.fixes import accepted_fixes
from app.ai.provider import Provider, build_provider
from app.ai.schemas import RewordIssuesReply, RewordQuestionsReply, SuggestFixesReply
from app.ai.wording import RewordedCopy, accepted_issue_copy, accepted_question_labels
from app.config import Settings
from app.detectors.models import Issue
from app.profile.models import DatasetProfile
from app.questions.models import Question

logger = logging.getLogger("tidylab.ai")

FAILED_NOTE = "Extra suggestions couldn't be fetched just now. Everything here still works."


class Enhancement(BaseModel):
    # "off" is a configuration, not a failure: the app is complete without this.
    status: Literal["off", "ready", "failed"] = "off"
    added: list[Issue] = Field(default_factory=list)
    issue_copy: dict[str, RewordedCopy] = Field(default_factory=dict)
    question_labels: dict[str, str] = Field(default_factory=dict)
    note: str | None = None


def enhance(
    conn: duckdb.DuckDBPyConnection,
    profile: DatasetProfile,
    issues: list[Issue],
    questions: list[Question],
    settings: Settings,
    provider: Provider | None = None,
    today: date | None = None,
) -> Enhancement:
    if not settings.llm_enabled:
        return Enhancement(status="off")
    service = provider or build_provider(settings)
    timeout = settings.llm_timeout_ms

    suggested = ask(
        service,
        load_prompt("suggest_fixes"),
        payloads.fixes_payload(conn, profile, issues, settings.llm_sample_rows),
        SuggestFixesReply,
        timeout,
    )
    reworded_issues = ask(
        service,
        load_prompt("reword_issues"),
        payloads.issue_wording_payload(issues),
        RewordIssuesReply,
        timeout,
    )
    reworded_questions = ask(
        service,
        load_prompt("reword_questions"),
        payloads.question_wording_payload(questions),
        RewordQuestionsReply,
        timeout,
    )

    if suggested is None and reworded_issues is None and reworded_questions is None:
        return Enhancement(status="failed", note=FAILED_NOTE)

    added = accepted_fixes(conn, profile, suggested, issues, today) if suggested else []
    copy = accepted_issue_copy(issues, reworded_issues) if reworded_issues else {}
    labels = accepted_question_labels(questions, reworded_questions) if reworded_questions else {}
    logger.info(
        "ai enhancement fixes=%d/%d wording=%d/%d labels=%d/%d",
        len(added),
        len(suggested.fixes) if suggested else 0,
        len(copy),
        len(reworded_issues.items) if reworded_issues else 0,
        len(labels),
        len(reworded_questions.items) if reworded_questions else 0,
    )
    return Enhancement(status="ready", added=added, issue_copy=copy, question_labels=labels)
