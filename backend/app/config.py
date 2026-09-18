import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, get_args

_BYTES_PER_MB = 1024 * 1024

LlmProvider = Literal["none", "anthropic", "gemini"]
PROVIDERS: tuple[str, ...] = get_args(LlmProvider)
# The app is complete without any of this; a model only ever adds to it.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-5",
    "gemini": "gemini-2.5-flash",
}
# The most rows a model may ever see, whatever the setting says (CLAUDE.md:
# metadata, not data).
MAX_SAMPLE_ROWS = 20


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int = 50 * _BYTES_PER_MB
    # Each dataset keeps its source bytes and its own DuckDB database in memory,
    # so the cap bounds worst-case memory at roughly max_datasets x max_upload_bytes.
    max_datasets: int = 10
    # Queries one comparison may spend working out which steps moved which
    # answers. Questions are explained highest impact first, so a small budget
    # costs detail on the answers that matter least.
    max_attribution_queries: int = 300
    # Which model service to ask, if any. "none" keeps everything rule-based.
    llm_provider: LlmProvider = "none"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_ms: int = 8000
    llm_sample_rows: int = MAX_SAMPLE_ROWS

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key)

    @property
    def model_name(self) -> str:
        return self.llm_model or DEFAULT_MODELS.get(self.llm_provider, "")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {name} must be a whole number, got {raw!r}"
        ) from exc
    if value <= 0:
        raise ValueError(f"Environment variable {name} must be positive, got {value}")
    return value


def _env_str(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _provider() -> LlmProvider:
    name = _env_str("LLM_PROVIDER", "none").lower() or "none"
    if name not in PROVIDERS:
        raise ValueError(
            f"Environment variable LLM_PROVIDER must be one of {', '.join(PROVIDERS)}, got {name!r}"
        )
    # Checked above; the cast tells the type checker what the check proved.
    return name  # type: ignore[return-value]


def _api_key(provider: LlmProvider) -> str:
    if provider == "anthropic":
        return _env_str("ANTHROPIC_API_KEY")
    if provider == "gemini":
        return _env_str("GEMINI_API_KEY")
    return ""


@lru_cache
def get_settings() -> Settings:
    defaults = Settings()
    provider = _provider()
    return Settings(
        max_upload_bytes=_env_int("MAX_UPLOAD_MB", defaults.max_upload_bytes // _BYTES_PER_MB)
        * _BYTES_PER_MB,
        max_datasets=_env_int("MAX_DATASETS", defaults.max_datasets),
        max_attribution_queries=_env_int(
            "MAX_ATTRIBUTION_QUERIES", defaults.max_attribution_queries
        ),
        llm_provider=provider,
        llm_api_key=_api_key(provider),
        llm_model=_env_str("LLM_MODEL"),
        llm_timeout_ms=_env_int("LLM_TIMEOUT_MS", defaults.llm_timeout_ms),
        llm_sample_rows=min(_env_int("LLM_SAMPLE_ROWS", defaults.llm_sample_rows), MAX_SAMPLE_ROWS),
    )
