import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, get_args

_BYTES_PER_MB = 1024 * 1024

LlmProvider = Literal["none", "anthropic", "gemini"]
PROVIDERS: tuple[str, ...] = get_args(LlmProvider)
# Outside services that can fill in new columns. Each is off unless named here.
PostalGeocoderName = Literal["none", "zippopotam"]
SymbolLookupName = Literal["none", "sec"]
QuoteProviderName = Literal["none", "finnhub"]
# The app is complete without any of this; a model only ever adds to it.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-5-5",
    "gemini": "gemini-2.5-flash",
}
# The most rows a model may ever see, whatever the setting says (CLAUDE.md:
# metadata, not data).
MAX_SAMPLE_ROWS = 20
# A saved recipe is text: at most MAX_STEPS steps, each carrying a bounded list
# of values, so a real one is a few kilobytes. Kept tight because an upload may
# carry one, and every byte allowed here is a byte the size guard has to let
# through before it can read anything. Not a setting — it bounds a format, not
# a user's file.
MAX_RECIPE_BYTES = 1024 * 1024


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
    # Claude's column ideas take about eight seconds on a wide file; leave room.
    llm_timeout_ms: int = 20000
    llm_sample_rows: int = MAX_SAMPLE_ROWS
    # Model calls allowed per minute across the whole server. Past it, the
    # rule-based wording is used, as it is when no service is configured.
    llm_max_calls_per_minute: int = 20
    # A built frontend to serve alongside the API (the one-container deploy).
    # Empty in development, where Vite serves the page.
    static_dir: str = ""
    # --- connectors: every one is "none" unless turned on -------------------------
    postal_geocoder: PostalGeocoderName = "none"
    symbol_lookup: SymbolLookupName = "none"
    quote_provider: QuoteProviderName = "none"
    finnhub_api_key: str = ""
    # The companies list is public but asks each caller to name itself and a contact.
    sec_user_agent: str = ""
    connector_timeout_ms: int = 5000
    # Different values one lookup run may ask a service about. The rest wait
    # for the next run; answers already cached don't count.
    connector_max_values_per_run: int = 100
    # How long one run may take before the remaining values are left for later.
    connector_run_seconds: int = 25
    postal_calls_per_minute: int = 60
    quote_calls_per_minute: int = 50
    # --- AI fill: a model filling in a new column's values ------------------------
    # Different values one fill may send. The rest wait for "fill in the rest".
    ai_fill_max_values_per_run: int = 400
    ai_fill_calls_per_minute: int = 60
    # Longer than for wording: one call carries dozens of values.
    ai_fill_timeout_ms: int = 20000
    # A file to keep looked-up answers in across restarts. Empty keeps them in memory.
    connector_cache_path: str = ""

    @property
    def postal_enabled(self) -> bool:
        return self.postal_geocoder != "none"

    @property
    def symbols_enabled(self) -> bool:
        return self.symbol_lookup != "none" and bool(self.sec_user_agent)

    @property
    def quotes_enabled(self) -> bool:
        return self.quote_provider != "none" and bool(self.finnhub_api_key)

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


def _choice[Name: str](env: str, allowed: tuple[Name, ...]) -> Name:
    name = _env_str(env, "none").lower() or "none"
    for option in allowed:
        if option == name:
            return option
    raise ValueError(
        f"Environment variable {env} must be one of {', '.join(allowed)}, got {name!r}"
    )


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
        llm_max_calls_per_minute=_env_int(
            "LLM_MAX_CALLS_PER_MINUTE", defaults.llm_max_calls_per_minute
        ),
        static_dir=_env_str("STATIC_DIR"),
        postal_geocoder=_choice("POSTAL_GEOCODER", get_args(PostalGeocoderName)),
        symbol_lookup=_choice("SYMBOL_LOOKUP", get_args(SymbolLookupName)),
        quote_provider=_choice("QUOTE_PROVIDER", get_args(QuoteProviderName)),
        finnhub_api_key=_env_str("FINNHUB_API_KEY"),
        sec_user_agent=_env_str("SEC_USER_AGENT"),
        connector_timeout_ms=_env_int("CONNECTOR_TIMEOUT_MS", defaults.connector_timeout_ms),
        connector_max_values_per_run=_env_int(
            "CONNECTOR_MAX_VALUES_PER_RUN", defaults.connector_max_values_per_run
        ),
        connector_run_seconds=_env_int("CONNECTOR_RUN_SECONDS", defaults.connector_run_seconds),
        postal_calls_per_minute=_env_int(
            "POSTAL_CALLS_PER_MINUTE", defaults.postal_calls_per_minute
        ),
        quote_calls_per_minute=_env_int("QUOTE_CALLS_PER_MINUTE", defaults.quote_calls_per_minute),
        ai_fill_max_values_per_run=_env_int(
            "AI_FILL_MAX_VALUES_PER_RUN", defaults.ai_fill_max_values_per_run
        ),
        ai_fill_calls_per_minute=_env_int(
            "AI_FILL_CALLS_PER_MINUTE", defaults.ai_fill_calls_per_minute
        ),
        ai_fill_timeout_ms=_env_int("AI_FILL_TIMEOUT_MS", defaults.ai_fill_timeout_ms),
        connector_cache_path=_env_str("CONNECTOR_CACHE_PATH"),
    )
