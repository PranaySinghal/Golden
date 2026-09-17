import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    get_settings.cache_clear()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
    monkeypatch.delenv("MAX_DATASETS", raising=False)

    assert get_settings() == Settings(max_upload_bytes=50 * 1024 * 1024, max_datasets=10)


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", "5")
    monkeypatch.setenv("MAX_DATASETS", "2")

    assert get_settings() == Settings(max_upload_bytes=5 * 1024 * 1024, max_datasets=2)


@pytest.mark.parametrize("value", ["abc", "0", "-3"])
def test_invalid_environment_values_fail_loudly(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_MB", value)

    with pytest.raises(ValueError, match="MAX_UPLOAD_MB"):
        get_settings()
