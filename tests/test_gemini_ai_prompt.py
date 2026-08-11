import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def mock_client():
    with patch("app.gemini_ai.client") as mock:
        yield mock


def make_response(json_text: str):
    resp = MagicMock()
    resp.text = json_text
    return resp


@pytest.mark.asyncio
async def test_payment_method_none_when_not_mentioned(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5900,"currency":"ARS","category":"food",'
            '"merchant":null,"payment_method":null,"tags":[],"location":null,"notes":null}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("gaste 5900 en jugo")
    assert result is not None
    assert result["payment_method"] is None


@pytest.mark.asyncio
async def test_payment_method_preserved_when_mentioned(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5900,"currency":"ARS","category":"food",'
            '"merchant":null,"payment_method":"credit card","tags":[],"location":null,"notes":null}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("gaste 5900 con tarjeta de credito")
    assert result is not None
    assert result["payment_method"] == "credit card"


@pytest.mark.asyncio
async def test_description_extracted_from_text(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5900,"currency":"ARS","category":"food",'
            '"description":"jugo","merchant":null,"payment_method":null,"tags":[],"location":null,"notes":null}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("gaste 5900 en jugo")
    assert result is not None
    assert result.get("description") == "jugo"


@pytest.mark.asyncio
async def test_description_is_none_when_not_present(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5900,"currency":"ARS","category":"food",'
            '"description":null,"merchant":null,"payment_method":null,"tags":[],"location":null,"notes":null}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("gaste plata")
    assert result is not None
    assert result.get("description") is None

