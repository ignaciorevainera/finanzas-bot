import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_update(text=None, callback_data=None, chat_id=123):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    if callback_data is not None:
        update.callback_query = MagicMock()
        update.callback_query.data = callback_data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_handle_parsed_data_asks_payment_method_when_null():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="gaste 5900 en jugo")
    context = MagicMock()
    data = {
        "type": "expense", "amount": 5900, "currency": "ARS",
        "category": "food", "merchant": None, "payment_method": None,
        "tags": [], "location": None, "notes": None,
    }
    await handlers.handle_parsed_data(update, context, data)
    update.message.reply_text.assert_called_once()
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_payment"


@pytest.mark.asyncio
async def test_handle_parsed_data_shows_confirm_when_payment_known():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="gaste 5900 con debito")
    context = MagicMock()
    data = {
        "type": "expense", "amount": 5900, "currency": "ARS",
        "category": "food", "merchant": None, "payment_method": "debit card",
        "tags": [], "location": None, "notes": None,
    }
    await handlers.handle_parsed_data(update, context, data)
    state = handlers.pending_transactions[123]
    assert state["action"] == "confirm"


@pytest.mark.asyncio
async def test_callback_sets_payment_method_and_advances_to_confirm():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_payment",
        "data": {
            "type": "expense", "amount": 5900, "currency": "ARS",
            "category": "food", "merchant": None, "payment_method": None,
            "tags": [], "location": None, "notes": None,
        },
    }
    update = make_update(callback_data="pm_cash", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "confirm"
    assert state["data"]["payment_method"] == "cash"


def test_spanish_labels_defined():
    from app.handlers import CATEGORY_LABELS, PAYMENT_METHOD_LABELS
    assert CATEGORY_LABELS["food"] == "Comida"
    assert CATEGORY_LABELS["transport"] == "Transporte"
    assert PAYMENT_METHOD_LABELS["cash"] == "💵 Efectivo"
    assert PAYMENT_METHOD_LABELS["debit card"] == "💳 Débito"


def test_build_confirm_text():
    from app.handlers import _build_confirm_text
    data = {
        "type": "expense",
        "amount": 1500,
        "currency": "ARS",
        "category": "food",
        "payment_method": "credit card",
        "merchant": "Coto",
    }
    text = _build_confirm_text(data)
    assert "Tipo: Gasto" in text
    assert "Monto: $1500 ARS" in text
    assert "Categoría: Comida" in text
    assert "Método de pago: 💳 Crédito" in text
    assert "Comercio: Coto" in text


@pytest.mark.asyncio
@patch("app.handlers.get_monthly_totals")
@patch("app.handlers.get_monthly_summary")
async def test_summary_handler_uses_spanish_labels(mock_summary, mock_totals):
    from app import handlers
    mock_totals.return_value = {"total_income": 10000.0, "total_expenses": 5000.0}
    mock_summary.return_value = [
        {"category": "food", "type": "expense", "total": 5000.0}
    ]
    update = make_update(chat_id=123)
    context = MagicMock()
    await handlers.summary_handler(update, context)
    update.message.reply_text.assert_called_once()
    sent_text = update.message.reply_text.call_args[0][0]
    assert "Comida (Gasto): $5000.00" in sent_text


@pytest.mark.asyncio
@patch("app.handlers.get_recent_transactions")
async def test_recent_handler_uses_spanish_labels(mock_recent):
    from app import handlers
    from datetime import datetime
    mock_recent.return_value = [
        {"type": "expense", "amount": 1200, "category": "transport", "created_at": datetime(2026, 8, 10, 15, 30)}
    ]
    update = make_update(chat_id=123)
    context = MagicMock()
    await handlers.recent_handler(update, context)
    update.message.reply_text.assert_called_once()
    sent_text = update.message.reply_text.call_args[0][0]
    assert "1. Gasto de $1200 en Transporte (2026-08-10 15:30)" in sent_text


@pytest.mark.asyncio
@patch("app.handlers.insert_transaction")
async def test_callback_confirm_saves_transaction(mock_insert):
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "confirm",
        "data": {
            "type": "expense", "amount": 5900, "currency": "ARS",
            "category": "food", "merchant": None, "payment_method": "cash",
            "tags": [], "location": None, "notes": None,
        },
    }
    update = make_update(callback_data="confirm", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    mock_insert.assert_called_once_with({
        "type": "expense", "amount": 5900, "currency": "ARS",
        "category": "food", "merchant": None, "payment_method": "cash",
        "tags": [], "location": None, "notes": None,
    })
    update.callback_query.edit_message_text.assert_called_once_with(
        text="Transacción guardada exitosamente. ✅"
    )
    assert 123 not in handlers.pending_transactions
