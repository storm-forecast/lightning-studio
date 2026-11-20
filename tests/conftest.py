import pytest


@pytest.fixture(autouse=True)
def no_strike_minimum(monkeypatch):
    """Most tests build alerts without a strike count; the minimum has its own tests."""
    monkeypatch.setenv('SHORTS_MIN_STRIKES', '0')
