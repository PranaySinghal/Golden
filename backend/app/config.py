import os
from dataclasses import dataclass
from functools import lru_cache

_BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int = 50 * _BYTES_PER_MB
    # Each dataset keeps its source bytes and its own DuckDB database in memory,
    # so the cap bounds worst-case memory at roughly max_datasets x max_upload_bytes.
    max_datasets: int = 10


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


@lru_cache
def get_settings() -> Settings:
    defaults = Settings()
    return Settings(
        max_upload_bytes=_env_int("MAX_UPLOAD_MB", defaults.max_upload_bytes // _BYTES_PER_MB)
        * _BYTES_PER_MB,
        max_datasets=_env_int("MAX_DATASETS", defaults.max_datasets),
    )
