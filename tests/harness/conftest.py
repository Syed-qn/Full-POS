"""Fixtures for the eval-harness test suite.

The ``restaurant`` fixture mirrors the one in ``tests/conversation/conftest.py``
so the harness tests can use it without depending on the conversation package.
"""
import pytest

from app.identity.models import Restaurant


@pytest.fixture
async def restaurant(db_session) -> Restaurant:
    """Seed a minimal restaurant row required for conversation FK."""
    row = Restaurant(
        name="Test Restaurant",
        phone="+97141234567",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(row)
    await db_session.flush()
    return row
