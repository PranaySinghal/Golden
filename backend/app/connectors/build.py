"""Turning settings into the services a server actually talks to."""

from app.ai.limiter import BudgetedProvider, CallBudget
from app.ai.provider import NoProvider, build_provider
from app.config import Settings
from app.connectors.cache import LookupCache
from app.connectors.providers.postal import NoGeocoder, PostalGeocoder, Zippopotam
from app.connectors.providers.quotes import Finnhub, NoQuotes, QuoteProvider
from app.connectors.providers.symbols import NoSymbols, Sec, SymbolLookup
from app.connectors.runner import Runtime


def build_runtime(settings: Settings, cache: LookupCache | None = None) -> Runtime:
    """Each connector is off ("none") unless it is named in the settings and has what it needs."""
    timeout = settings.connector_timeout_ms
    postal: PostalGeocoder = Zippopotam(timeout) if settings.postal_enabled else NoGeocoder()
    symbols: SymbolLookup = (
        Sec(settings.sec_user_agent, timeout) if settings.symbols_enabled else NoSymbols()
    )
    quotes: QuoteProvider = (
        Finnhub(settings.finnhub_api_key, timeout) if settings.quotes_enabled else NoQuotes()
    )
    model = build_provider(settings)
    if not isinstance(model, NoProvider):
        # Its own budget: one fill makes many calls, and must not starve the wording.
        model = BudgetedProvider(model, CallBudget(settings.ai_fill_calls_per_minute))
    return Runtime(
        postal=postal,
        symbols=symbols,
        quotes=quotes,
        cache=cache or LookupCache(settings.connector_cache_path),
        # One budget per service, shared by every request to this server.
        budgets={
            postal.name: CallBudget(settings.postal_calls_per_minute),
            quotes.name: CallBudget(settings.quote_calls_per_minute),
        },
        max_values=settings.connector_max_values_per_run,
        run_seconds=float(settings.connector_run_seconds),
        model=model,
        model_id=settings.model_name,
        fill_max_values=settings.ai_fill_max_values_per_run,
        fill_timeout_ms=settings.ai_fill_timeout_ms,
    )
