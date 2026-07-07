import pytest

from app.payments.credentials import clear_credentials, get_credentials_status, set_credentials


@pytest.mark.anyio
async def test_set_and_status_never_leaks_secret(db_session, restaurant):
    await set_credentials(db_session, restaurant=restaurant, provider="stripe", secret_key="sk_test_abc123")
    await db_session.commit()

    status = get_credentials_status(restaurant)
    assert status["provider"] == "stripe"
    assert status["configured"] is True
    assert "secret_key" not in status
    assert "sk_test_abc123" not in str(status)


@pytest.mark.anyio
async def test_clear_credentials_reverts_to_unconfigured(db_session, restaurant):
    await set_credentials(db_session, restaurant=restaurant, provider="stripe", secret_key="sk_test_xyz")
    await db_session.commit()

    await clear_credentials(db_session, restaurant=restaurant)
    await db_session.commit()

    status = get_credentials_status(restaurant)
    assert status["provider"] == "mock"
    assert status["configured"] is False


@pytest.mark.anyio
async def test_default_status_is_unconfigured(db_session, restaurant):
    status = get_credentials_status(restaurant)
    assert status["provider"] == "mock"
    assert status["configured"] is False
