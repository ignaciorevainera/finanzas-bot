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


@pytest.mark.asyncio
async def test_transaction_date_extracted_when_mentioned(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5000,"currency":"ARS","category":"food",'
            '"description":"cena","transaction_date":"2026-08-10 21:00:00"}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("gaste 5000 en cena ayer")
    assert result is not None
    assert result.get("transaction_date") == "2026-08-10 21:00:00"


@pytest.mark.asyncio
async def test_transaction_date_default_none_when_omitted(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5000,"currency":"ARS","category":"food",'
            '"description":"cena"}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("gaste 5000 en cena")
    assert result is not None
    assert result.get("transaction_date") is None


@pytest.mark.asyncio
async def test_system_prompt_includes_current_datetime(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5000,"currency":"ARS","category":"food"}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    test_dt = "2026-08-11 12:00:00"
    await parse_transaction_from_text("gaste 5000", current_datetime=test_dt)
    
    call_args = mock_client.aio.models.generate_content.call_args
    assert call_args is not None
    config = call_args.kwargs.get("config")
    assert config is not None
    assert f"The current date and time is {test_dt}." in config.system_instruction


@pytest.mark.asyncio
async def test_parse_date_from_text_success(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response('{"date": "2026-08-10 14:00:00"}')
    )
    from app.gemini_ai import parse_date_from_text
    result = await parse_date_from_text("ayer")
    assert result == "2026-08-10 14:00:00"


@pytest.mark.asyncio
async def test_parse_date_from_text_error_returns_none(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response('{"error": "no date found"}')
    )
    from app.gemini_ai import parse_date_from_text
    result = await parse_date_from_text("hola")
    assert result is None


@pytest.mark.asyncio
async def test_parse_date_from_text_includes_current_datetime(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response('{"date": "2026-08-10"}')
    )
    from app.gemini_ai import parse_date_from_text
    test_dt = "2026-08-11 12:00:00"
    await parse_date_from_text("ayer", current_datetime=test_dt)

    call_args = mock_client.aio.models.generate_content.call_args
    assert call_args is not None
    config = call_args.kwargs.get("config")
    assert config is not None
    assert f"The current date and time is {test_dt}." in config.system_instruction



