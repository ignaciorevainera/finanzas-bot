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
async def test_handle_parsed_data_questions_for_first_missing_required_field():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="gaste 500")
    context = MagicMock()
    data = {"amount": 500, "currency": "ARS", "status": "Completado"}

    await handlers.handle_parsed_data(update, context, data)

    assert handlers.pending_transactions[123]["action"] == "pick_missing"
    update.message.reply_text.assert_awaited_once()
    assert "tipo" in update.message.reply_text.await_args.args[0].lower()


def test_confirmation_shows_personal_and_total_amounts():
    from app.handlers import _build_confirm_text
    text = _build_confirm_text({
        "type": "Gasto", "amount": 30000, "total_amount": 120000,
        "currency": "ARS", "category": "Comida", "description": "Cena",
        "payment_method": "Efectivo", "participants": ["Viole"],
        "split_details": {"user": 30000, "Viole": 90000},
    })

    assert "Monto personal: $30000 ARS" in text
    assert "Monto total: $120000 ARS" in text
    assert "Viole" in text


@pytest.mark.asyncio
async def test_handle_parsed_data_questions_for_payment_method_when_null():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="gaste 5900 en jugo")
    context = MagicMock()
    data = {
        "type": "Gasto", "amount": 5900, "currency": "ARS",
        "category": "Comida", "merchant": None, "payment_method": None,
        "description": "Jugo", "transaction_date": None,
        "tags": [], "location": None, "notes": None,
    }
    await handlers.handle_parsed_data(update, context, data)
    update.message.reply_text.assert_called_once()
    assert "método de pago" in update.message.reply_text.call_args[0][0].lower()
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_missing"
    assert state["missing_fields"] == ["payment_method"]


@pytest.mark.asyncio
async def test_handle_parsed_data_asks_date_when_required_fields_known_and_date_null():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="gaste 5900 con debito")
    context = MagicMock()
    data = {
        "type": "Gasto", "amount": 5900, "currency": "ARS",
        "category": "Comida", "merchant": None, "payment_method": "Tarjeta de Débito",
        "description": "Jugo", "transaction_date": None,
        "tags": [], "location": None, "notes": None,
    }
    await handlers.handle_parsed_data(update, context, data)
    update.message.reply_text.assert_called_once()
    assert "¿De qué fecha es la transacción?" in update.message.reply_text.call_args[0][0]
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_date"


@pytest.mark.asyncio
async def test_handle_parsed_data_shows_confirm_when_required_fields_and_date_known():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="gaste 5900 con debito ayer")
    context = MagicMock()
    data = {
        "type": "Gasto", "amount": 5900, "currency": "ARS",
        "category": "Comida", "merchant": None, "payment_method": "Tarjeta de Débito",
        "description": "Jugo", "transaction_date": "2026-08-10 12:00:00",
        "tags": [], "location": None, "notes": None,
    }
    await handlers.handle_parsed_data(update, context, data)
    state = handlers.pending_transactions[123]
    assert state["action"] == "confirm"


@pytest.mark.asyncio
async def test_pick_missing_advances_through_fields_in_order_until_confirm():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "data": {"transaction_date": "2026-08-10 12:00:00"},
        "missing_fields": ["type", "amount", "category", "description", "payment_method"],
        "missing_index": 0,
    }
    answers = [
        ("gasto", "type", "Gasto"),
        ("500", "amount", 500),
        ("comida", "category", "Comida"),
        ("cena", "description", "Cena"),
        ("efectivo", "payment_method", "Efectivo"),
    ]
    for text, field, expected in answers:
        update = make_update(text=text, chat_id=123)
        context = MagicMock()
        await handlers.message_handler(update, context)
        state = handlers.pending_transactions[123]
        assert state["data"][field] == expected
    assert state["action"] == "confirm"


@pytest.mark.asyncio
async def test_pick_missing_invalid_answer_reasks_same_question():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "data": {"transaction_date": "2026-08-10 12:00:00"},
        "missing_fields": ["amount"],
        "missing_index": 0,
    }
    update = make_update(text="no me acuerdo", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_missing"
    assert state["missing_index"] == 0
    assert "monto" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_message_handler_answers_payment_method_and_advances_to_confirm():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "data": {
            "type": "Gasto", "amount": 5900, "currency": "ARS",
            "category": "Comida", "merchant": None, "payment_method": None,
            "description": "Jugo", "transaction_date": "2026-08-10 12:00:00",
            "tags": [], "location": None, "notes": None,
        },
        "missing_fields": ["payment_method"],
        "missing_index": 0,
    }
    update = make_update(text="con tarjeta de debito", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "confirm"
    assert state["data"]["payment_method"] == "Tarjeta de Débito"


@pytest.mark.asyncio
async def test_handle_parsed_data_enters_pick_split_when_participants_without_split_details():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="cena con Viole")
    context = MagicMock()
    data = {
        "type": "Gasto", "amount": 30000, "total_amount": 120000,
        "currency": "ARS", "category": "Comida", "description": "Cena",
        "payment_method": "Efectivo", "participants": ["Viole"],
        "transaction_date": "2026-08-10 12:00:00",
    }
    await handlers.handle_parsed_data(update, context, data)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_split"
    update.message.reply_text.assert_called_once()
    assert "distribución" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
@patch("app.handlers.parse_transaction_from_text")
async def test_message_handler_split_valid_distribution_confirms(mock_parse):
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_split",
        "data": {
            "type": "Gasto", "amount": 30000, "total_amount": 120000,
            "currency": "ARS", "category": "Comida", "description": "Cena",
            "payment_method": "Efectivo", "participants": ["Viole"],
            "transaction_date": "2026-08-10 12:00:00",
        },
    }
    mock_parse.return_value = {"split_details": {"user": 30000, "Viole": 90000}}
    update = make_update(text="Viole 90000 y yo 30000", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "confirm"
    assert state["data"]["split_details"] == {"user": 30000, "Viole": 90000}


@pytest.mark.asyncio
@patch("app.handlers.parse_transaction_from_text")
async def test_message_handler_split_invalid_sum_repeats_question(mock_parse):
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_split",
        "data": {
            "type": "Gasto", "amount": 30000, "total_amount": 120000,
            "currency": "ARS", "category": "Comida", "description": "Cena",
            "payment_method": "Efectivo", "participants": ["Viole"],
            "transaction_date": "2026-08-10 12:00:00",
        },
    }
    mock_parse.return_value = {"split_details": {"user": 30000, "Viole": 50000}}
    update = make_update(text="Viole 50000 y yo 30000", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "pick_split"
    assert "split_details" not in state["data"]
    assert "no suman" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_callback_date_today_sets_date_and_advances_to_confirm():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_date",
        "data": {
            "type": "Gasto", "amount": 5900, "currency": "ARS",
            "category": "Comida", "merchant": None, "payment_method": "Efectivo",
            "description": "Jugo", "transaction_date": None,
        },
    }
    update = make_update(callback_data="date_today", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "confirm"
    assert state["data"]["transaction_date"] is not None


@pytest.mark.asyncio
async def test_callback_date_yesterday_sets_date_and_advances_to_confirm():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_date",
        "data": {
            "type": "Gasto", "amount": 5900, "currency": "ARS",
            "category": "Comida", "merchant": None, "payment_method": "Efectivo",
            "description": "Jugo", "transaction_date": None,
        },
    }
    update = make_update(callback_data="date_yesterday", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "confirm"
    assert state["data"]["transaction_date"] is not None


@pytest.mark.asyncio
async def test_callback_date_custom_prompts_user_text_input():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_date",
        "data": {
            "type": "Gasto", "amount": 5900, "currency": "ARS",
            "category": "Comida", "merchant": None, "payment_method": "Efectivo",
            "description": "Jugo", "transaction_date": None,
        },
    }
    update = make_update(callback_data="date_custom", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "wait_custom_date"
    assert "escribe la fecha" in update.callback_query.edit_message_text.call_args[1]["text"]


@pytest.mark.asyncio
@patch("app.handlers.parse_date_from_text")
async def test_message_handler_wait_custom_date_success(mock_parse):
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "wait_custom_date",
        "data": {
            "type": "Gasto", "amount": 5900, "currency": "ARS",
            "category": "Comida", "merchant": None, "payment_method": "Efectivo",
            "description": "Jugo", "transaction_date": None,
        },
    }
    mock_parse.return_value = "2026-08-08 14:00:00"
    update = make_update(text="el sabado pasado", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "confirm"
    assert state["data"]["transaction_date"] == "2026-08-08 14:00:00"
    update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
@patch("app.handlers.parse_date_from_text")
async def test_message_handler_wait_custom_date_failure(mock_parse):
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "wait_custom_date",
        "data": {
            "type": "Gasto", "amount": 5900, "currency": "ARS",
            "category": "Comida", "merchant": None, "payment_method": "Efectivo",
            "description": "Jugo", "transaction_date": None,
        },
    }
    mock_parse.return_value = None
    update = make_update(text="invalid date input", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "wait_custom_date"
    update.message.reply_text.assert_called_once()
    assert "No pude entender la fecha" in update.message.reply_text.call_args[0][0]


def test_spanish_labels_defined():
    from app.handlers import PAYMENT_METHOD_LABELS
    assert PAYMENT_METHOD_LABELS["Efectivo"] == "💵 Efectivo"
    assert PAYMENT_METHOD_LABELS["Tarjeta de Débito"] == "💳 Débito"


def test_confirm_keyboard_includes_add_context():
    from app.handlers import _get_confirm_keyboard
    keyboard = _get_confirm_keyboard().to_dict()
    callbacks = [
        button["callback_data"]
        for row in keyboard["inline_keyboard"]
        for button in row
    ]
    assert "confirm" in callbacks
    assert "cancel" in callbacks
    assert "add_context" in callbacks


def test_build_confirm_text():
    from app.handlers import _build_confirm_text
    data = {
        "type": "Gasto",
        "amount": 1500,
        "currency": "ARS",
        "category": "Comida",
        "payment_method": "Tarjeta de Crédito",
        "transaction_date": "2026-08-10 20:00:00",
        "merchant": "Coto",
    }
    text = _build_confirm_text(data)
    assert "Tipo: Gasto" in text
    assert "Monto personal: $1500 ARS" in text
    assert "Categoría: Comida" in text
    assert "Método de pago: 💳 Crédito" in text
    assert "Fecha: 2026-08-10 20:00" in text
    assert "Comercio: Coto" in text


@pytest.mark.asyncio
async def test_summary_handler_routes_through_send_report(monkeypatch):
    from app import handlers
    send_report = AsyncMock()
    monkeypatch.setattr("app.handlers.send_report", send_report)
    update = make_update(chat_id=123)
    context = MagicMock()
    await handlers.summary_handler(update, context)
    send_report.assert_awaited_once()
    request = send_report.await_args.args[1]
    assert request.metric == "summary"


class MockRecord:
    """Mock simulating asyncpg.Record which does not have a .get() method."""
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def get(self, key, default=None):
        raise AttributeError("'Record' object has no attribute 'get'")


@pytest.mark.asyncio
@patch("app.handlers.get_recent_transactions")
async def test_recent_handler_uses_spanish_labels(mock_recent):
    from app import handlers
    from datetime import datetime
    mock_recent.return_value = [
        MockRecord({"type": "Gasto", "amount": 1200, "category": "Transporte", "description": None, "transaction_date": None, "created_at": datetime(2026, 8, 10, 15, 30)})
    ]
    update = make_update(chat_id=123)
    context = MagicMock()
    await handlers.recent_handler(update, context)
    update.message.reply_text.assert_called_once()
    sent_text = update.message.reply_text.call_args[0][0]
    assert "1. Gasto de $1200 en Transporte (2026-08-10 15:30)" in sent_text


@pytest.mark.asyncio
@patch("app.handlers.get_recent_transactions")
async def test_recent_handler_with_asyncpg_record_interface(mock_recent):
    from app import handlers
    from datetime import datetime
    mock_recent.return_value = [
        MockRecord({
            "type": "Gasto",
            "amount": 1200,
            "category": "Transporte",
            "description": "subte",
            "transaction_date": datetime(2026, 8, 10, 15, 30),
            "created_at": datetime(2026, 8, 10, 16, 0),
        })
    ]
    update = make_update(chat_id=123)
    context = MagicMock()
    await handlers.recent_handler(update, context)
    update.message.reply_text.assert_called_once()
    sent_text = update.message.reply_text.call_args[0][0]
    assert "1. Gasto de $1200 en Transporte — subte (2026-08-10 15:30)" in sent_text


@pytest.mark.asyncio
@patch("app.handlers.insert_transaction")
async def test_callback_confirm_saves_transaction(mock_insert):
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "confirm",
        "data": {
            "type": "Gasto", "amount": 5900, "currency": "ARS",
            "category": "Comida", "merchant": None, "payment_method": "Efectivo",
            "transaction_date": "2026-08-10 12:00:00",
            "tags": [], "location": None, "notes": None,
        },
    }

    async def side_effect_check_popped(data):
        assert 123 not in handlers.pending_transactions

    mock_insert.side_effect = side_effect_check_popped

    update = make_update(callback_data="confirm", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    mock_insert.assert_called_once_with({
        "type": "Gasto", "amount": 5900, "currency": "ARS",
        "category": "Comida", "merchant": None, "payment_method": "Efectivo",
        "transaction_date": "2026-08-10 12:00:00",
        "tags": [], "location": None, "notes": None,
    })
    update.callback_query.edit_message_text.assert_called_once_with(
        text="Transacción guardada exitosamente. ✅"
    )
    assert 123 not in handlers.pending_transactions


@pytest.mark.asyncio
async def test_callback_cancel_removes_pending_transaction():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "confirm",
        "data": {"type": "Gasto", "amount": 5900},
    }
    update = make_update(callback_data="cancel", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    update.callback_query.edit_message_text.assert_called_once_with(
        text="Transacción cancelada."
    )
    assert 123 not in handlers.pending_transactions


@pytest.mark.asyncio
@patch("app.handlers.insert_transaction")
async def test_callback_add_context_transitions_to_add_context_state(mock_insert):
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "confirm",
        "data": {"type": "Gasto", "amount": 5900},
    }
    update = make_update(callback_data="add_context", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "add_context"
    assert state["data"]["amount"] == 5900


@pytest.mark.asyncio
async def test_confirm_message_includes_description():
    from app.handlers import _build_confirm_text
    data = {
        "type": "Gasto", "amount": 5900, "currency": "ARS",
        "category": "Comida", "description": "jugo", "merchant": None,
        "payment_method": "Efectivo", "transaction_date": "2026-08-10 12:00:00",
        "tags": [], "location": None, "notes": None,
    }
    text = _build_confirm_text(data)
    assert "jugo" in text


@pytest.mark.asyncio
@patch("app.handlers.get_recent_transactions")
async def test_delete_handler_includes_description(mock_recent):
    from app import handlers
    mock_recent.return_value = [
        MockRecord({"id": "1", "type": "Gasto", "amount": 1200, "category": "Transporte", "description": "colectivo"}),
        MockRecord({"id": "2", "type": "Ingreso", "amount": 5000, "category": "Trabajo Independiente", "description": None}),
    ]
    update = make_update(chat_id=123)
    context = MagicMock()
    await handlers.delete_handler(update, context)
    update.message.reply_text.assert_called_once()
    sent_text = update.message.reply_text.call_args[0][0]
    assert "1. Gasto de $1200 en Transporte — colectivo" in sent_text
    assert "2. Ingreso de $5000 en Trabajo Independiente\n" in sent_text


@pytest.mark.asyncio
async def test_add_context_can_repeat_until_confirm(monkeypatch):
    from app import handlers
    handlers.pending_transactions.clear()
    chat_id = 123
    handlers.pending_transactions[chat_id] = {
        "action": "confirm",
        "data": {"description": "Supermercado", "notes": None},
    }

    update = make_update(callback_data="add_context", chat_id=chat_id)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    assert handlers.pending_transactions[chat_id]["action"] == "add_context"

    monkeypatch.setattr(
        "app.handlers.parse_transaction_from_text",
        AsyncMock(return_value={"location": "Palermo", "notes": None}),
    )
    update = make_update(text="Fue en Palermo", chat_id=chat_id)
    await handlers.message_handler(update, context)
    assert handlers.pending_transactions[chat_id]["action"] == "confirm"
    assert handlers.pending_transactions[chat_id]["data"]["location"] == "Palermo"


@pytest.mark.asyncio
async def test_cancel_discards_pending_context():
    from app import handlers
    handlers.pending_transactions.clear()
    chat_id = 123
    handlers.pending_transactions[chat_id] = {"action": "confirm", "data": {"description": "Cena"}}

    update = make_update(callback_data="cancel", chat_id=chat_id)
    context = MagicMock()
    await handlers.callback_handler(update, context)

    assert chat_id not in handlers.pending_transactions


@pytest.mark.asyncio
async def test_add_context_introducing_participants_enters_pick_split(monkeypatch):
    from app import handlers
    handlers.pending_transactions.clear()
    chat_id = 123
    handlers.pending_transactions[chat_id] = {
        "action": "add_context",
        "data": {
            "type": "Gasto", "amount": 30000, "total_amount": 30000,
            "currency": "ARS", "category": "Comida", "description": "Cena",
            "payment_method": "Efectivo", "transaction_date": "2026-08-10 12:00:00",
        },
    }
    monkeypatch.setattr(
        "app.handlers.parse_transaction_from_text",
        AsyncMock(return_value={"participants": ["Viole"]}),
    )
    update = make_update(text="Fue con Viole", chat_id=chat_id)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions[chat_id]
    assert state["action"] == "pick_split"
    assert state["data"]["participants"] == ["Viole"]
    assert "distribución" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_add_context_changing_total_revalidates_existing_split(monkeypatch):
    from app import handlers
    handlers.pending_transactions.clear()
    chat_id = 123
    handlers.pending_transactions[chat_id] = {
        "action": "add_context",
        "data": {
            "type": "Gasto", "amount": 30000, "total_amount": 120000,
            "currency": "ARS", "category": "Comida", "description": "Cena",
            "payment_method": "Efectivo", "participants": ["Viole"],
            "split_details": {"user": 30000, "Viole": 90000},
            "transaction_date": "2026-08-10 12:00:00",
        },
    }
    monkeypatch.setattr(
        "app.handlers.parse_transaction_from_text",
        AsyncMock(return_value={"total_amount": 140000}),
    )
    update = make_update(text="no, eran 140000", chat_id=chat_id)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions[chat_id]
    assert state["action"] == "pick_split"
    assert state["data"]["total_amount"] == 140000
    assert "distribución" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_add_context_unchanged_split_stays_in_confirm(monkeypatch):
    from app import handlers
    handlers.pending_transactions.clear()
    chat_id = 123
    handlers.pending_transactions[chat_id] = {
        "action": "add_context",
        "data": {
            "type": "Gasto", "amount": 30000, "total_amount": 120000,
            "currency": "ARS", "category": "Comida", "description": "Cena",
            "payment_method": "Efectivo", "participants": ["Viole"],
            "split_details": {"user": 30000, "Viole": 90000},
            "transaction_date": "2026-08-10 12:00:00",
        },
    }
    monkeypatch.setattr(
        "app.handlers.parse_transaction_from_text",
        AsyncMock(return_value={"location": "Palermo"}),
    )
    update = make_update(text="Fue en Palermo", chat_id=chat_id)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions[chat_id]
    assert state["action"] == "confirm"
    assert state["data"]["split_details"] == {"user": 30000, "Viole": 90000}
    assert state["data"]["location"] == "Palermo"


@pytest.mark.asyncio
async def test_parser_supplied_split_with_bad_sum_reenters_pick_split():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="de 120000 yo puse 30000")
    context = MagicMock()
    data = {
        "type": "Gasto", "amount": 30000, "total_amount": 120000,
        "currency": "ARS", "category": "Comida", "description": "Cena",
        "payment_method": "Efectivo", "participants": ["Viole"],
        "split_details": {"user": 30000, "Viole": 50000},
        "transaction_date": "2026-08-10 12:00:00",
    }
    await handlers.handle_parsed_data(update, context, data)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_split"
    assert "distribución" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_parser_supplied_split_with_valid_sum_goes_to_confirm():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="de 120000 yo puse 30000")
    context = MagicMock()
    data = {
        "type": "Gasto", "amount": 30000, "total_amount": 120000,
        "currency": "ARS", "category": "Comida", "description": "Cena",
        "payment_method": "Efectivo", "participants": ["Viole"],
        "split_details": {"user": 30000, "Viole": 90000},
        "transaction_date": "2026-08-10 12:00:00",
    }
    await handlers.handle_parsed_data(update, context, data)
    state = handlers.pending_transactions[123]
    assert state["action"] == "confirm"


@pytest.mark.asyncio
async def test_parser_supplied_split_with_wrong_user_share_reenters_pick_split():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="de 120000 yo puse 30000")
    context = MagicMock()
    data = {
        "type": "Gasto", "amount": 30000, "total_amount": 120000,
        "currency": "ARS", "category": "Comida", "description": "Cena",
        "payment_method": "Efectivo", "participants": ["Viole"],
        "split_details": {"user": 20000, "Viole": 100000},
        "transaction_date": "2026-08-10 12:00:00",
    }
    await handlers.handle_parsed_data(update, context, data)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_split"
    assert "distribución" in update.message.reply_text.call_args[0][0].lower()


def test_amount_answer_with_worded_magnitude_is_ambiguous():
    from app.handlers import _parse_missing_field_answer
    assert _parse_missing_field_answer("amount", "2 mil pesos") is None
    assert _parse_missing_field_answer("amount", "yo puse 3000 y ella 5000") is None
    assert _parse_missing_field_answer("amount", "3000") == 3000


@pytest.mark.asyncio
async def test_pick_missing_ambiguous_amount_answer_reasks_amount():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "data": {"transaction_date": "2026-08-10 12:00:00"},
        "missing_fields": ["amount"],
        "missing_index": 0,
    }
    update = make_update(text="2 mil pesos", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_missing"
    assert state["missing_index"] == 0
    assert "amount" not in state["data"]
    assert "monto" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_pick_missing_amount_answer_sets_amount_and_total_amount():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "data": {"transaction_date": "2026-08-10 12:00:00"},
        "missing_fields": ["amount"],
        "missing_index": 0,
    }
    update = make_update(text="500", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["data"]["amount"] == 500
    assert state["data"]["total_amount"] == 500


@pytest.mark.asyncio
async def test_pick_missing_amount_answer_preserves_existing_total_amount():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "data": {"total_amount": 120000, "transaction_date": "2026-08-10 12:00:00"},
        "missing_fields": ["amount"],
        "missing_index": 0,
    }
    update = make_update(text="30000", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["data"]["amount"] == 30000
    assert state["data"]["total_amount"] == 120000


def test_split_is_valid_requires_known_total_amount():
    from app.handlers import _split_is_valid
    assert _split_is_valid(
        {"amount": 30000},
        {"user": 30000, "Viole": 90000},
    ) is False


def test_type_keyboard_has_two_options():
    from app.handlers import _get_missing_field_keyboard
    keyboard = _get_missing_field_keyboard("type")
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert [b.text for b in buttons] == ["Gasto", "Ingreso"]
    assert [b.callback_data for b in buttons] == [
        "missing_type_expense", "missing_type_income"
    ]


def test_category_keyboard_has_seventeen_buttons_and_two_columns():
    from app.handlers import _get_missing_field_keyboard
    keyboard = _get_missing_field_keyboard("category")
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert len(buttons) == 17
    assert len(keyboard.inline_keyboard[0]) == 2
    assert buttons[-1].text == "Otra categoría"
    assert buttons[-1].callback_data == "missing_category_other"


def test_payment_method_keyboard_has_five_buttons_two_columns():
    from app.handlers import _get_missing_field_keyboard
    keyboard = _get_missing_field_keyboard("payment_method")
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert [b.text for b in buttons] == [
        "Efectivo", "Tarjeta de Débito", "Tarjeta de Crédito",
        "Transferencia", "Otro",
    ]
    assert len(keyboard.inline_keyboard[0]) == 2
    assert buttons[-1].text == "Otro"


def test_text_resolver_accepts_equivalent_values():
    from app.handlers import _resolve_missing_field_answer
    assert _resolve_missing_field_answer("type", "gasto") == "Gasto"
    assert _resolve_missing_field_answer("category", "comida") == "Comida"
    assert _resolve_missing_field_answer("payment_method", "efectivo") == "Efectivo"
    assert _resolve_missing_field_answer("payment_method", "inventado") is None


def test_resolver_rejects_unknown_closed_choice_values():
    from app.handlers import _resolve_missing_field_answer
    assert _resolve_missing_field_answer("type", "inventado") is None
    assert _resolve_missing_field_answer("category", "") is None
    assert _resolve_missing_field_answer("category", "  ") is None
    assert _resolve_missing_field_answer("unknown", "gasto") is None


def test_resolver_accepts_custom_category_text():
    from app.handlers import _resolve_missing_field_answer
    assert _resolve_missing_field_answer("category", "helado") == "Helado"
    assert _resolve_missing_field_answer("category", "Trabajo") == "Trabajo"


def test_resolver_matches_canonical_values_ignoring_diacritics():
    from app.handlers import _resolve_missing_field_answer
    assert _resolve_missing_field_answer("payment_method", "tarjeta de debito") == "Tarjeta de Débito"
    assert _resolve_missing_field_answer("payment_method", "tarjeta de credito") == "Tarjeta de Crédito"
    assert _resolve_missing_field_answer("type", "gasto") == "Gasto"
    assert _resolve_missing_field_answer("category", "comida") == "Comida"
    assert _resolve_missing_field_answer("category", "educacion") == "Educación"
    assert _resolve_missing_field_answer("payment_method", "inventado") is None


def test_missing_field_keyboard_returns_none_for_free_text_fields():
    from app.handlers import _get_missing_field_keyboard
    assert _get_missing_field_keyboard("amount") is None
    assert _get_missing_field_keyboard("description") is None
    assert _get_missing_field_keyboard("unknown") is None


def test_keyboard_field_prompts():
    from app.handlers import _get_missing_field_prompt
    assert _get_missing_field_prompt("type") == "Selecciona tipo de transacción:"
    assert _get_missing_field_prompt("amount") == "¿Cuál es el monto de la transacción?"
    assert _get_missing_field_prompt("category") == "Selecciona una categoría:"
    assert _get_missing_field_prompt("payment_method") == "Selecciona el método de pago:"


@pytest.mark.asyncio
async def test_missing_type_shows_keyboard():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="gaste 500")
    context = MagicMock()
    data = {"amount": 500, "category": "Comida", "description": "Cena",
            "payment_method": "Efectivo", "currency": "ARS",
            "status": "Completado", "transaction_date": "2026-08-12"}

    await handlers.handle_parsed_data(update, context, data)

    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_missing"
    assert state["field"] == "type"
    assert state["missing_fields"] == ["type"]
    assert update.message.reply_text.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_detected_type_skips_type_keyboard():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="gaste 500")
    context = MagicMock()
    data = {"type": "Gasto", "amount": 500, "description": "Cena",
            "payment_method": "Efectivo", "currency": "ARS",
            "status": "Completado", "transaction_date": "2026-08-12"}

    await handlers.handle_parsed_data(update, context, data)

    state = handlers.pending_transactions[123]
    assert state["field"] == "category"
    labels = [
        b.text
        for row in update.message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard
        for b in row
    ]
    assert "Gasto" not in labels
    assert "Otra categoría" in labels


@pytest.mark.asyncio
async def test_callback_type_selection_sets_value_and_advances():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "type",
        "missing_fields": ["type", "category"],
        "missing_index": 0,
        "data": {"amount": 500, "transaction_date": "2026-08-12"},
    }
    update = make_update(callback_data="missing_type_expense", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_missing"
    assert state["data"]["type"] == "Gasto"
    assert state["missing_index"] == 1
    assert state["field"] == "category"
    update.callback_query.edit_message_text.assert_awaited_once()
    assert (
        update.callback_query.edit_message_text.await_args.kwargs["reply_markup"]
        is not None
    )


@pytest.mark.asyncio
async def test_callback_last_field_advances_to_confirm():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "payment_method",
        "missing_fields": ["payment_method"],
        "missing_index": 0,
        "data": {"type": "Gasto", "amount": 500, "category": "Comida",
                 "description": "Cena", "transaction_date": "2026-08-12"},
    }
    update = make_update(callback_data="missing_payment_cash", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "confirm"
    assert state["data"]["payment_method"] == "Efectivo"


@pytest.mark.asyncio
async def test_callback_category_maps_base_value():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "category",
        "missing_fields": ["category"],
        "missing_index": 0,
        "data": {"type": "Gasto", "amount": 500, "description": "Cena",
                 "payment_method": "Efectivo", "transaction_date": "2026-08-12"},
    }
    update = make_update(callback_data="missing_cat_food", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "confirm"
    assert state["data"]["category"] == "Comida"


@pytest.mark.asyncio
async def test_callback_base_category_otros_maps_to_otros():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "category",
        "missing_fields": ["category"],
        "missing_index": 0,
        "data": {"type": "Gasto", "amount": 500, "description": "Cena",
                 "payment_method": "Efectivo", "transaction_date": "2026-08-12"},
    }
    update = make_update(callback_data="missing_cat_other", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "confirm"
    assert state["data"]["category"] == "Otros"


@pytest.mark.asyncio
async def test_callback_custom_category_enters_pick_custom_category():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "category",
        "missing_fields": ["category", "payment_method"],
        "missing_index": 0,
        "data": {"type": "Gasto", "amount": 500, "description": "Cena",
                 "payment_method": "Efectivo", "transaction_date": "2026-08-12"},
    }
    update = make_update(callback_data="missing_category_other", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_custom_category"
    assert state["data"]["type"] == "Gasto"
    assert "categoría" in update.callback_query.edit_message_text.call_args[1]["text"].lower()


@pytest.mark.asyncio
async def test_callback_unknown_option_does_not_mutate_data():
    from app import handlers
    handlers.pending_transactions.clear()
    state_data = {"amount": 500, "transaction_date": "2026-08-12"}
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "type",
        "missing_fields": ["type", "category"],
        "missing_index": 0,
        "data": state_data,
    }
    update = make_update(callback_data="missing_type_invented", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_missing"
    assert state["missing_index"] == 0
    assert state["data"] == state_data
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_callback_wrong_field_does_not_mutate_data():
    from app import handlers
    handlers.pending_transactions.clear()
    state_data = {"amount": 500, "transaction_date": "2026-08-12"}
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "type",
        "missing_fields": ["type", "category"],
        "missing_index": 0,
        "data": state_data,
    }
    update = make_update(callback_data="missing_cat_food", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_missing"
    assert state["missing_index"] == 0
    assert state["data"] == state_data
    assert "category" not in state["data"]


@pytest.mark.asyncio
async def test_callback_stale_state_does_not_mutate():
    from app import handlers
    handlers.pending_transactions.clear()
    data = {"amount": 500}
    handlers.pending_transactions[123] = {"action": "confirm", "data": data}
    update = make_update(callback_data="missing_type_expense", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "confirm"
    assert state["data"] == data
    update.callback_query.edit_message_text.assert_awaited_once()
    assert (
        "ya no está en ese paso"
        in update.callback_query.edit_message_text.await_args.kwargs["text"]
    )


@pytest.mark.asyncio
async def test_callback_stale_in_pick_split_edits_message_without_mutation():
    from app import handlers
    handlers.pending_transactions.clear()
    data = {"type": "Gasto", "amount": 30000, "total_amount": 120000,
            "participants": ["Viole"]}
    handlers.pending_transactions[123] = {"action": "pick_split", "data": data}
    update = make_update(callback_data="missing_type_expense", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_split"
    assert state["data"] == data
    update.callback_query.edit_message_text.assert_awaited_once()
    assert (
        "ya no está en ese paso"
        in update.callback_query.edit_message_text.await_args.kwargs["text"]
    )


@pytest.mark.asyncio
async def test_callback_stale_in_pick_date_edits_message_without_mutation():
    from app import handlers
    handlers.pending_transactions.clear()
    data = {"amount": 500}
    handlers.pending_transactions[123] = {"action": "pick_date", "data": data}
    update = make_update(callback_data="missing_type_expense", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_date"
    assert state["data"] == data
    update.callback_query.edit_message_text.assert_awaited_once()
    assert (
        "ya no está en ese paso"
        in update.callback_query.edit_message_text.await_args.kwargs["text"]
    )


@pytest.mark.asyncio
async def test_callback_absent_state_edits_without_mutating():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(callback_data="missing_type_expense", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    assert 123 not in handlers.pending_transactions
    update.callback_query.edit_message_text.assert_awaited_once_with(
        text="No hay transacción pendiente."
    )


@pytest.mark.asyncio
async def test_text_fallback_advances_missing_field():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "payment_method",
        "missing_fields": ["payment_method"],
        "missing_index": 0,
        "data": {"type": "Gasto", "amount": 500, "category": "Comida",
                 "description": "Cena", "transaction_date": "2026-08-12"},
    }
    update = make_update(text="tarjeta de debito", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "confirm"
    assert state["data"]["payment_method"] == "Tarjeta de Débito"


@pytest.mark.asyncio
async def test_text_invalid_answer_reprompts_with_keyboard():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "type",
        "missing_fields": ["type"],
        "missing_index": 0,
        "data": {"amount": 500, "transaction_date": "2026-08-12"},
    }
    update = make_update(text="inventado", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_missing"
    assert state["missing_index"] == 0
    assert "type" not in state["data"]
    assert update.message.reply_text.call_args[1]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_callback_last_field_with_split_enters_pick_split():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "payment_method",
        "missing_fields": ["payment_method"],
        "missing_index": 0,
        "data": {
            "type": "Gasto", "amount": 30000, "total_amount": 120000,
            "currency": "ARS", "category": "Comida", "description": "Cena",
            "payment_method": None, "participants": ["Viole"],
            "transaction_date": "2026-08-12",
        },
    }
    update = make_update(callback_data="missing_payment_cash", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_split"
    assert state["data"]["payment_method"] == "Efectivo"
    update.callback_query.edit_message_text.assert_awaited_once()
    assert (
        "distribución"
        in update.callback_query.edit_message_text.await_args.kwargs["text"].lower()
    )


@pytest.mark.asyncio
async def test_callback_last_field_no_split_date_present_confirms_via_edit():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "payment_method",
        "missing_fields": ["payment_method"],
        "missing_index": 0,
        "data": {"type": "Gasto", "amount": 500, "category": "Comida",
                 "description": "Cena", "transaction_date": "2026-08-12"},
    }
    update = make_update(callback_data="missing_payment_cash", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "confirm"
    assert state["data"]["payment_method"] == "Efectivo"
    update.callback_query.edit_message_text.assert_awaited_once()
    assert (
        "Transacción detectada:"
        in update.callback_query.edit_message_text.await_args.kwargs["text"]
    )


@pytest.mark.asyncio
async def test_callback_last_field_date_null_enters_pick_date():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "payment_method",
        "missing_fields": ["payment_method"],
        "missing_index": 0,
        "data": {"type": "Gasto", "amount": 500, "category": "Comida",
                 "description": "Cena", "transaction_date": None},
    }
    update = make_update(callback_data="missing_payment_cash", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_date"
    edit_kwargs = update.callback_query.edit_message_text.await_args.kwargs
    assert "¿De qué fecha es la transacción?" in edit_kwargs["text"]
    assert edit_kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_text_completed_missing_fields_split_still_triggers_via_reply():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_missing",
        "field": "payment_method",
        "missing_fields": ["payment_method"],
        "missing_index": 0,
        "data": {
            "type": "Gasto", "amount": 30000, "total_amount": 120000,
            "currency": "ARS", "category": "Comida", "description": "Cena",
            "payment_method": None, "participants": ["Viole"],
            "transaction_date": "2026-08-12",
        },
    }
    update = make_update(text="efectivo", chat_id=123)
    context = MagicMock()
    await handlers.message_handler(update, context)
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_split"
    assert state["data"]["payment_method"] == "Efectivo"
    assert "distribución" in update.message.reply_text.call_args[0][0].lower()
