"""Shared FastAPI dependencies: the dataset store and the settings."""

from typing import Annotated

from fastapi import Depends, Request

from app.ai.limiter import BudgetedProvider, CallBudget
from app.ai.provider import NoProvider, Provider, build_provider
from app.config import Settings
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


StoreDep = Annotated[DatasetStore, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
ProviderDep = Annotated[Provider, Depends(get_provider)]
