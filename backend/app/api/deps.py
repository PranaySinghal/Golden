"""Shared FastAPI dependencies: the dataset store and the settings."""

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings
from app.store import DatasetStore


def get_store(request: Request) -> DatasetStore:
    store: DatasetStore = request.app.state.store
    return store


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


StoreDep = Annotated[DatasetStore, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
