"""Shared FastAPI dependencies: the dataset store and the settings."""

from typing import Annotated

from fastapi import Depends, Request

from app.ai.limiter import BudgetedProvider, CallBudget
from app.ai.provider import NoProvider, Provider, build_provider
from app.config import Settings
from app.connectors.build import build_runtime
from app.connectors.runner import Runtime
from app.store import DatasetStore


def get_store(request: Request) -> DatasetStore:
    store: DatasetStore = request.app.state.store
    return store


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_provider(request: Request) -> Provider:
    """The model service, if one is configured. Injected so a test can stand in for it."""
    settings: Settings = request.app.state.settings
    provider = build_provider(settings)
    if isinstance(provider, NoProvider):
        return provider
    budget: CallBudget = request.app.state.llm_budget
    return BudgetedProvider(provider, budget)


def get_connectors(request: Request) -> Runtime:
    """The outside services, built on first use and kept for the life of the server.

    Built lazily and rebuilt if the settings object changes, so the lookup cache
    file is only opened by a server that actually uses connectors.
    """
    settings: Settings = request.app.state.settings
    held: tuple[Settings, Runtime] | None = getattr(request.app.state, "connectors", None)
    if held is None or held[0] is not settings:
        held = (settings, build_runtime(settings))
        request.app.state.connectors = held
    return held[1]


StoreDep = Annotated[DatasetStore, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
ProviderDep = Annotated[Provider, Depends(get_provider)]
ConnectorsDep = Annotated[Runtime, Depends(get_connectors)]
