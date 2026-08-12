from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_registration_flow_documentation_describes_defaults_and_required_fields():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "currency" in readme
    assert "ARS" in readme
    assert "status" in readme
    assert "Completado" in readme
    for field in ("type", "amount", "category", "description", "payment_method"):
        assert field in readme


def test_registration_flow_documentation_describes_split_and_add_context_loop():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "Agregar más" in readme
    assert "Aceptar" in readme
    assert "Cancelar" in readme


@pytest.fixture(autouse=True)
def mock_client():
    with patch("app.gemini_ai.client") as mock:
        yield mock


def make_response(json_text: str):
    resp = MagicMock()
    resp.text = json_text
    return resp


@pytest.mark.asyncio
async def test_parser_returns_spanish_transaction_contract(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"type":"expense","amount":30000,"total_amount":120000,'
        '"category":"food","description":"cena","payment_method":"cash",'
        '"participants":["Viole"],"split_details":{"user":30000,"Viole":90000}}'
    ))

    from app.gemini_ai import parse_transaction_from_text

    result = await parse_transaction_from_text("de 120000 yo puse 30000 para cenar con Viole")

    assert result["type"] == "Gasto"
    assert result["category"] == "Comida"
    assert result["description"] == "Cena"
    assert result["payment_method"] == "Efectivo"
    assert result["amount"] == 30000
    assert result["total_amount"] == 120000


@pytest.mark.asyncio
async def test_audio_and_text_use_same_default_keys(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"type":"income","amount":1000,"category":"salary",'
        '"description":"sueldo","payment_method":"transfer"}'
    ))

    from app.gemini_ai import parse_transaction_from_audio

    result = await parse_transaction_from_audio(b"audio", "audio/ogg")

    assert set(("currency", "tags", "transaction_date", "status", "total_amount")) <= result.keys()


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
    assert result["payment_method"] == "Tarjeta de Crédito"


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
    assert result.get("description") == "Jugo"


@pytest.mark.asyncio
async def test_description_capitalization_lowercase(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5900,"currency":"ARS","category":"food",'
            '"description":"jugo de naranja","merchant":null,"payment_method":null,"tags":[],"location":null,"notes":null}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("gaste 5900 en jugo de naranja")
    assert result is not None
    assert result.get("description") == "Jugo de naranja"


@pytest.mark.asyncio
async def test_description_capitalization_preserves_internal_uppercase(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5000,"currency":"ARS","category":"other",'
            '"description":"subscripcion a OpenAI","merchant":null,"payment_method":null,"tags":[],"location":null,"notes":null}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("openai 5000")
    assert result is not None
    assert result.get("description") == "Subscripcion a OpenAI"



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
async def test_transaction_date_defaults_to_current_datetime_when_omitted(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5000,"currency":"ARS","category":"food",'
            '"description":"cena"}'
        )
    )
    from datetime import datetime
    from app.gemini_ai import parse_transaction_from_text
    test_dt = datetime(2026, 8, 11, 12, 0, 0)
    result = await parse_transaction_from_text("gaste 5000 en cena", current_datetime=test_dt)
    assert result is not None
    assert result.get("transaction_date") == test_dt


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
async def test_parse_report_request_extracts_category_and_month(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"metric":"category","start":"2026-08-01T00:00:00+00:00",'
        '"end":"2026-09-01T00:00:00+00:00","value":"Comida"}'
    ))

    from app.gemini_ai import parse_report_request

    result = await parse_report_request("¿Cuánto gasté en comida este mes?",
                                       current_datetime="2026-08-12 12:00:00")

    assert result.metric == "category"
    assert result.value == "Comida"
    assert result.start.isoformat() == "2026-08-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_parse_report_request_returns_none_for_non_report(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"error":"unsupported report"}'
    ))

    from app.gemini_ai import parse_report_request

    assert await parse_report_request("¿Qué debería comprar?", current_datetime="2026-08-12 12:00:00") is None


@pytest.mark.asyncio
async def test_parse_report_request_rejects_inverted_period(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"metric":"summary","start":"2026-09-01T00:00:00+00:00",'
        '"end":"2026-08-01T00:00:00+00:00"}'
    ))

    from app.gemini_ai import parse_report_request

    assert await parse_report_request("reporte", current_datetime="2026-08-12 12:00:00") is None


@pytest.mark.asyncio
async def test_parse_report_request_rejects_naive_datetime(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"metric":"summary","start":"2026-08-01T00:00:00",'
        '"end":"2026-09-01T00:00:00"}'
    ))

    from app.gemini_ai import parse_report_request

    assert await parse_report_request("reporte", current_datetime="2026-08-12 12:00:00") is None


@pytest.mark.asyncio
async def test_parse_report_request_rejects_missing_dates(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"metric":"summary"}'
    ))

    from app.gemini_ai import parse_report_request

    assert await parse_report_request("reporte", current_datetime="2026-08-12 12:00:00") is None


@pytest.mark.asyncio
async def test_parse_report_request_rejects_unknown_metric(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"metric":"cashflow","start":"2026-08-01T00:00:00+00:00",'
        '"end":"2026-09-01T00:00:00+00:00"}'
    ))

    from app.gemini_ai import parse_report_request

    assert await parse_report_request("reporte", current_datetime="2026-08-12 12:00:00") is None


@pytest.mark.asyncio
async def test_parse_report_request_normalizes_value_to_canonical_spanish(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"metric":"category","start":"2026-08-01T00:00:00+00:00",'
        '"end":"2026-09-01T00:00:00+00:00","value":"comida"}'
    ))

    from app.gemini_ai import parse_report_request

    result = await parse_report_request("¿Cuánto gasté en comida?", current_datetime="2026-08-12 12:00:00")

    assert result is not None
    assert result.value == "Comida"


@pytest.mark.asyncio
async def test_parse_report_request_normalizes_payment_method_value(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"metric":"payment_method","start":"2026-08-01T00:00:00+00:00",'
        '"end":"2026-09-01T00:00:00+00:00","value":"efectivo"}'
    ))

    from app.gemini_ai import parse_report_request

    result = await parse_report_request("¿Cuánto gasté en efectivo?", current_datetime="2026-08-12 12:00:00")

    assert result is not None
    assert result.value == "Efectivo"


@pytest.mark.asyncio
async def test_parse_report_request_includes_current_datetime(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"metric":"summary","start":"2026-08-01T00:00:00+00:00",'
        '"end":"2026-09-01T00:00:00+00:00"}'
    ))

    from app.gemini_ai import parse_report_request

    test_dt = "2026-08-12 12:00:00"
    await parse_report_request("reporte del mes", current_datetime=test_dt)

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



