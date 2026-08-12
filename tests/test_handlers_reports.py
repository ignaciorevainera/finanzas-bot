import pytest
from unittest.mock import AsyncMock, MagicMock

from datetime import datetime, timezone

from app.reporting import ReportRequest


def make_update(text=None, chat_id=123):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    return update


def _request(metric="summary", value=None) -> ReportRequest:
    return ReportRequest(
        metric=metric,
        start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        end=datetime(2026, 9, 1, tzinfo=timezone.utc),
        value=value,
    )


@pytest.mark.asyncio
async def test_report_command_builds_request_and_sends(monkeypatch):
    from app import handlers
    run_report = AsyncMock(return_value={"rows": [{"label": "Comida", "total": 30000}]})
    monkeypatch.setattr("app.handlers.run_report", run_report)
    monkeypatch.setattr(
        "app.handlers.format_report", lambda request, result: "Reporte de categorías"
    )

    update = make_update(text="/report category Comida")
    await handlers.report_handler(update, MagicMock())

    update.message.reply_text.assert_awaited_once_with("Reporte de categorías")
    run_report.assert_awaited_once()
    request = run_report.await_args.args[0]
    assert request.metric == "category"
    assert request.value == "Comida"


@pytest.mark.asyncio
async def test_report_command_spanish_metric_alias(monkeypatch):
    from app import handlers
    run_report = AsyncMock(return_value={"rows": []})
    monkeypatch.setattr("app.handlers.run_report", run_report)
    monkeypatch.setattr("app.handlers.format_report", lambda request, result: "ok")

    update = make_update(text="/report etiquetas Trabajo")
    await handlers.report_handler(update, MagicMock())

    request = run_report.await_args.args[0]
    assert request.metric == "tag"
    assert request.value == "Trabajo"


@pytest.mark.asyncio
async def test_report_command_period_only_metric_has_no_value(monkeypatch):
    from app import handlers
    run_report = AsyncMock(return_value={"rows": []})
    monkeypatch.setattr("app.handlers.run_report", run_report)
    monkeypatch.setattr("app.handlers.format_report", lambda request, result: "ok")

    update = make_update(text="/report shared")
    await handlers.report_handler(update, MagicMock())

    request = run_report.await_args.args[0]
    assert request.metric == "shared"
    assert request.value is None


@pytest.mark.asyncio
async def test_report_command_unknown_syntax_shows_usage(monkeypatch):
    from app import handlers
    run_report = AsyncMock()
    monkeypatch.setattr("app.handlers.run_report", run_report)

    update = make_update(text="/report foo bar")
    await handlers.report_handler(update, MagicMock())

    update.message.reply_text.assert_awaited_once()
    assert "Uso" in update.message.reply_text.await_args.args[0]
    run_report.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_command_defaults_period_to_current_month(monkeypatch):
    from app import handlers
    run_report = AsyncMock(return_value={"rows": []})
    monkeypatch.setattr("app.handlers.run_report", run_report)
    monkeypatch.setattr("app.handlers.format_report", lambda request, result: "ok")

    update = make_update(text="/report summary")
    await handlers.report_handler(update, MagicMock())

    request = run_report.await_args.args[0]
    assert request.start.tzinfo is not None
    assert request.start.day == 1
    assert request.end > request.start
    assert request.metric == "summary"


@pytest.mark.asyncio
async def test_summary_command_routes_through_send_report(monkeypatch):
    from app import handlers
    run_report = AsyncMock(return_value={"income": 1000, "expenses": 300, "net": 700})
    monkeypatch.setattr("app.handlers.run_report", run_report)
    monkeypatch.setattr("app.handlers.format_report", lambda request, result: "Resumen del mes")

    update = make_update(text="/summary")
    await handlers.summary_handler(update, MagicMock())

    update.message.reply_text.assert_awaited_once_with("Resumen del mes")
    run_report.assert_awaited_once()
    assert run_report.await_args.args[0].metric == "summary"


@pytest.mark.asyncio
async def test_natural_language_question_routes_to_send_report(monkeypatch):
    from app import handlers
    handlers.pending_transactions.clear()
    parse_request = AsyncMock(return_value=_request("summary"))
    run_report = AsyncMock(return_value={"income": 1000, "expenses": 300, "net": 700})
    monkeypatch.setattr("app.handlers.parse_report_request", parse_request)
    monkeypatch.setattr("app.handlers.run_report", run_report)
    monkeypatch.setattr("app.handlers.format_report", lambda request, result: "Reporte listo")

    update = make_update(text="¿cuánto gasté este mes?")
    await handlers.message_handler(update, MagicMock())

    parse_request.assert_awaited_once()
    update.message.reply_text.assert_awaited_once_with("Reporte listo")


@pytest.mark.asyncio
async def test_natural_language_unsupported_question_mentions_report(monkeypatch):
    from app import handlers
    handlers.pending_transactions.clear()
    monkeypatch.setattr("app.handlers.parse_report_request", AsyncMock(return_value=None))

    update = make_update(text="¿Qué inversión debería hacer?")
    await handlers.message_handler(update, MagicMock())

    update.message.reply_text.assert_awaited_once()
    assert "reporte" in update.message.reply_text.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_non_question_message_skips_report_parsing(monkeypatch):
    from app import handlers
    handlers.pending_transactions.clear()
    parse_request = AsyncMock()
    monkeypatch.setattr("app.handlers.parse_report_request", parse_request)
    monkeypatch.setattr(
        "app.handlers.parse_transaction_from_text",
        AsyncMock(return_value={
            "type": "Gasto", "amount": 500, "total_amount": 500, "currency": "ARS",
            "category": "Comida", "description": "Cena", "payment_method": "Efectivo",
            "transaction_date": "2026-08-10 12:00:00",
        }),
    )

    update = make_update(text="gasté 500 en comida ayer")
    await handlers.message_handler(update, MagicMock())

    parse_request.assert_not_awaited()
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "confirm"


@pytest.mark.asyncio
async def test_pending_transaction_state_preserves_transaction_flow(monkeypatch):
    from app import handlers
    handlers.pending_transactions.clear()
    parse_request = AsyncMock()
    monkeypatch.setattr("app.handlers.parse_report_request", parse_request)
    monkeypatch.setattr(
        "app.handlers.parse_transaction_from_text",
        AsyncMock(return_value={"split_details": {"user": 30000, "Viole": 90000}}),
    )
    handlers.pending_transactions[123] = {
        "action": "pick_split",
        "data": {
            "type": "Gasto", "amount": 30000, "total_amount": 120000,
            "currency": "ARS", "category": "Comida", "description": "Cena",
            "payment_method": "Efectivo", "participants": ["Viole"],
            "transaction_date": "2026-08-10 12:00:00",
        },
    }

    update = make_update(text="¿cuánto pongo yo?")
    await handlers.message_handler(update, MagicMock())

    parse_request.assert_not_awaited()
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "confirm"


@pytest.mark.asyncio
async def test_send_report_guidance_on_unsupported_metric(monkeypatch):
    from app import handlers
    monkeypatch.setattr(
        "app.handlers.run_report",
        AsyncMock(side_effect=ValueError("Unsupported report metric")),
    )

    update = make_update()
    await handlers.send_report(update, _request("summary"))

    update.message.reply_text.assert_awaited_once()
    assert "reporte" in update.message.reply_text.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_send_report_generic_failure_text_on_unexpected_error(monkeypatch):
    from app import handlers
    monkeypatch.setattr(
        "app.handlers.run_report",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    update = make_update()
    await handlers.send_report(update, _request("summary"))

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    assert "error" in text.lower()
