import csv
import io
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.config import settings
from app.database import (
    get_monthly_totals,
    get_monthly_summary,
    get_recent_transactions,
    get_all_transactions,
    insert_transaction,
    delete_transaction,
)
from app.gemini_ai import (
    parse_transaction_from_text,
    parse_transaction_from_audio,
    parse_date_from_text,
)
from app.transaction_schema import (
    PAYMENT_METHOD_MAP,
    get_missing_transaction_fields,
    merge_transaction_context,
    normalize_transaction,
)

PAYMENT_METHOD_LABELS: dict[str, str] = {
    "Efectivo": "💵 Efectivo",
    "Tarjeta de Débito": "💳 Débito",
    "Tarjeta de Crédito": "💳 Crédito",
    "Transferencia": "🏦 Transferencia",
    "Otro": "Otro",
}

MISSING_FIELD_PROMPTS: dict[str, str] = {
    "type": "¿Cuál es el tipo de transacción? Responde 'gasto' o 'ingreso'.",
    "amount": "¿Cuál es el monto de la transacción?",
    "category": "¿En qué categoría clasifico esta transacción?",
    "description": "¿Cuál es el concepto o descripción de la transacción?",
    "payment_method": "¿Con qué método de pago se realizó? (Efectivo, Tarjeta de Débito, Tarjeta de Crédito, Transferencia u Otro)",
}

SPLIT_PROMPT = (
    "Este movimiento parece compartido. Indica la distribución exacta de los montos, "
    "especificando cuánto puso cada persona, incluyendo tu parte (ej: 'Viole puso 90000 y yo 30000')."
)

SPLIT_INVALID_PROMPT = (
    "Los montos no suman el total. Indica de nuevo el monto exacto de cada persona, "
    "incluyendo tu parte, de modo que sumen el total."
)

logger = logging.getLogger(__name__)

pending_transactions = {}


def _get_date_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("📅 Hoy", callback_data="date_today"),
            InlineKeyboardButton("🔙 Ayer", callback_data="date_yesterday"),
        ],
        [
            InlineKeyboardButton("🗓 Otra fecha", callback_data="date_custom"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def _get_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Aceptar", callback_data="confirm"),
                InlineKeyboardButton("➕ Agregar más", callback_data="add_context"),
                InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
            ]
        ]
    )


def check_access(update: Update) -> bool:
    if settings.allowed_chat_id:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id != settings.allowed_chat_id:
            logger.warning(f"Unauthorized access from chat_id {chat_id}")
            return False
    return True


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update):
        return
    await update.message.reply_text(
        "¡Hola! Soy tu bot de finanzas personales. Puedes registrar tus gastos o ingresos "
        "enviándome un mensaje de texto o una nota de voz. Usa /help para ver los comandos disponibles."
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update):
        return
    help_text = (
        "Comandos disponibles:\n"
        "/start - Mensaje de bienvenida\n"
        "/help - Esta ayuda\n"
        "/summary - Resumen del mes actual\n"
        "/recent - Últimas 5 transacciones\n"
        "/delete - Eliminar alguna de las últimas 5 transacciones\n"
        "/export - Exportar todas las transacciones a CSV\n\n"
        "Simplemente envíame un texto o audio con tu transacción, por ejemplo: 'Gasté 500 en comida'."
    )
    await update.message.reply_text(help_text)


async def summary_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update):
        return
    totals = await get_monthly_totals()
    summary = await get_monthly_summary()
    
    if not totals:
        await update.message.reply_text("No hay datos para este mes.")
        return

    msg = f"Resumen del mes:\nIngresos: ${totals['total_income']:.2f}\nGastos: ${totals['total_expenses']:.2f}\n\nDesglose:\n"
    for row in summary:
        msg += f"- {row['category']} ({row['type']}): ${row['total']:.2f}\n"
    
    await update.message.reply_text(msg)


async def recent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update):
        return
    transactions = await get_recent_transactions(5)
    if not transactions:
        await update.message.reply_text("No hay transacciones recientes.")
        return
    
    msg = "Últimas 5 transacciones:\n"
    for i, t in enumerate(transactions, 1):
        dt = t['transaction_date'] if ('transaction_date' in t and t['transaction_date']) else t['created_at']
        created = dt.strftime('%Y-%m-%d %H:%M') if dt else 'N/A'
        desc = f" — {t['description']}" if t['description'] else ""
        msg += f"{i}. {t['type']} de ${t['amount']} en {t['category']}{desc} ({created})\n"
    
    await update.message.reply_text(msg)


async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update):
        return
    
    chat_id = update.effective_chat.id
    transactions = await get_recent_transactions(5)
    if not transactions:
        await update.message.reply_text("No hay transacciones para eliminar.")
        return
    
    pending_transactions[chat_id] = {"action": "delete", "transactions": transactions}
    
    msg = "Responde con el número (1-5) de la transacción que deseas eliminar:\n"
    for i, t in enumerate(transactions, 1):
        desc = f" — {t['description']}" if t['description'] else ""
        msg += f"{i}. {t['type']} de ${t['amount']} en {t['category']}{desc}\n"
        
    await update.message.reply_text(msg)


async def export_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update):
        return
    
    transactions = await get_all_transactions()
    if not transactions:
        await update.message.reply_text("No hay transacciones para exportar.")
        return
    
    output = io.StringIO()
    writer = csv.writer(output)
    headers = transactions[0].keys()
    writer.writerow(headers)
    for t in transactions:
        writer.writerow([t[h] for h in headers])
            
    csv_bytes = output.getvalue().encode('utf-8')
    await update.message.reply_document(
        document=csv_bytes,
        filename="transactions.csv",
        caption="Aquí está el archivo CSV con tus transacciones."
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update):
        return
    
    chat_id = update.effective_chat.id
    text = update.message.text
    
    state = pending_transactions.get(chat_id)
    if state and state.get("action") == "delete":
        try:
            index = int(text)
            if 1 <= index <= len(state["transactions"]):
                transaction = state["transactions"][index - 1]
                t_id = str(transaction["id"])
                await delete_transaction(t_id)
                await update.message.reply_text("Transacción eliminada exitosamente.")
            else:
                await update.message.reply_text("Número fuera de rango. Operación cancelada.")
        except ValueError:
            await update.message.reply_text("Por favor, envía un número válido. Operación cancelada.")
        
        del pending_transactions[chat_id]
        return
    
    if state and state.get("action") == "wait_custom_date":
        await update.message.chat.send_action(action="typing")
        date_str = await parse_date_from_text(text)
        if date_str:
            state["data"]["transaction_date"] = date_str
            pending_transactions[chat_id] = {"action": "confirm", "data": state["data"]}
            await _send_confirm_message(update, state["data"])
        else:
            await update.message.reply_text(
                "No pude entender la fecha. Por favor, escribe la fecha (ej: 'ayer', 'el martes', '10/08') o intenta de nuevo."
            )
        return

    if state and state.get("action") == "pick_missing":
        field = state["missing_fields"][state["missing_index"]]
        value = _parse_missing_field_answer(field, text)
        if value is None:
            await update.message.reply_text(MISSING_FIELD_PROMPTS[field])
            return
        state["data"][field] = value
        if field == "amount" and state["data"].get("total_amount") in (None, ""):
            state["data"]["total_amount"] = value
        state["missing_index"] += 1
        if state["missing_index"] < len(state["missing_fields"]):
            pending_transactions[chat_id] = state
            next_field = state["missing_fields"][state["missing_index"]]
            await update.message.reply_text(MISSING_FIELD_PROMPTS[next_field])
            return
        pending_transactions[chat_id] = state
        await _advance_after_required_fields(update, chat_id, state["data"])
        return

    if state and state.get("action") == "pick_split":
        await update.message.chat.send_action(action="typing")
        parsed = await parse_transaction_from_text(text)
        split_details = parsed.get("split_details") if parsed else None
        if not _split_is_valid(state["data"], split_details):
            await update.message.reply_text(SPLIT_INVALID_PROMPT)
            return
        state["data"]["split_details"] = split_details
        if not state["data"].get("participants"):
            state["data"]["participants"] = [key for key in split_details if key != "user"]
        pending_transactions[chat_id] = state
        await _advance_after_required_fields(update, chat_id, state["data"])
        return

    if state and state.get("action") == "add_context":
        await update.message.chat.send_action(action="typing")
        additions = await parse_transaction_from_text(text)
        if not additions or "error" in additions:
            await update.message.reply_text(
                "No pude entender los detalles adicionales. Envía más detalles "
                "de la transacción (lugar, etiquetas, cuotas, etc.)."
            )
            return
        merged = merge_transaction_context(state["data"], additions)
        split_fields_changed = (
            merged.get("split_details")
            and any(
                merged.get(field) != state["data"].get(field)
                for field in ("amount", "total_amount", "participants")
            )
        )
        if _needs_split_question(merged) or split_fields_changed:
            pending_transactions[chat_id] = {"action": "pick_split", "data": merged}
            await update.message.reply_text(SPLIT_PROMPT)
            return
        pending_transactions[chat_id] = {"action": "confirm", "data": merged}
        await _send_confirm_message(update, merged)
        return
    
    await update.message.chat.send_action(action="typing")
    data = await parse_transaction_from_text(text)
    await handle_parsed_data(update, context, data)


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_access(update):
        return
    
    await update.message.chat.send_action(action="typing")
    
    file = await update.message.voice.get_file()
    audio_bytes = bytes(await file.download_as_bytearray())
    mime_type = update.message.voice.mime_type or "audio/ogg"
    
    data = await parse_transaction_from_audio(audio_bytes, mime_type)
    await handle_parsed_data(update, context, data)


async def handle_parsed_data(update: Update, context: ContextTypes.DEFAULT_TYPE, data: dict | None):
    if not data or "error" in data:
        await update.message.reply_text("No pude entender la transacción. Por favor, intenta de nuevo.")
        return

    chat_id = update.effective_chat.id

    missing_fields = get_missing_transaction_fields(data)
    if missing_fields:
        pending_transactions[chat_id] = {
            "action": "pick_missing",
            "data": data,
            "missing_fields": missing_fields,
            "missing_index": 0,
        }
        await update.message.reply_text(MISSING_FIELD_PROMPTS[missing_fields[0]])
        return

    await _advance_after_required_fields(update, chat_id, data)


async def _advance_after_required_fields(update: Update, chat_id: int, data: dict):
    if _needs_split_question(data):
        pending_transactions[chat_id] = {"action": "pick_split", "data": data}
        await update.message.reply_text(SPLIT_PROMPT)
        return

    if data.get("transaction_date") is None:
        pending_transactions[chat_id] = {"action": "pick_date", "data": data}
        await update.message.reply_text(
            "¿De qué fecha es la transacción?",
            reply_markup=_get_date_keyboard(),
        )
        return

    pending_transactions[chat_id] = {"action": "confirm", "data": data}
    await _send_confirm_message(update, data)


def _parse_missing_field_answer(field: str, text: str) -> str | float | None:
    value = text.strip()
    if not value:
        return None
    if field == "amount":
        matches = re.findall(r"\d+(?:[.,]\d+)?", value)
        if len(matches) != 1:
            return None
        if _amount_answer_is_ambiguous(value):
            return None
        try:
            num = float(matches[0].replace(",", "."))
        except ValueError:
            return None
        return int(num) if num.is_integer() else num
    if field in ("type", "payment_method"):
        canonical_values = (
            ("Gasto", "Ingreso")
            if field == "type"
            else tuple(PAYMENT_METHOD_MAP.values())
        )
        return _match_canonical_vocab(value, field, canonical_values)
    return normalize_transaction({field: value}).get(field)


_AMBIGUOUS_AMOUNT_WORDS = frozenset(
    {"mil", "miles", "millon", "millones", "y", "mas", "aprox", "cerca", "alrededor"}
)


def _amount_answer_is_ambiguous(value: str) -> bool:
    words = set(re.findall(r"[a-z]+", _strip_diacritics(value).lower()))
    return bool(words & _AMBIGUOUS_AMOUNT_WORDS)


def _match_canonical_vocab(value: str, field: str, canonical_values: tuple[str, ...]) -> str | None:
    normalized = normalize_transaction({field: value}).get(field)
    if normalized in canonical_values:
        return normalized
    stripped = _strip_diacritics(value).lower()
    if len(stripped) < 3:
        return None
    for canonical in canonical_values:
        canonical_stripped = _strip_diacritics(canonical).lower()
        if canonical_stripped in stripped or stripped in canonical_stripped:
            return canonical
    return None


def _strip_diacritics(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def _needs_split_question(data: dict) -> bool:
    if data.get("split_details"):
        return not _split_is_valid(data, data["split_details"])
    if data.get("participants"):
        return True
    amount = data.get("amount")
    total_amount = data.get("total_amount")
    if amount is not None and total_amount is not None:
        try:
            return abs(float(amount) - float(total_amount)) > 1e-6
        except (TypeError, ValueError):
            return False
    return False


def _split_is_valid(data: dict, split_details) -> bool:
    if not isinstance(split_details, dict) or not split_details:
        return False
    required_keys = set(data.get("participants") or []) | {"user"}
    if not required_keys <= set(split_details):
        return False
    total_amount = data.get("total_amount")
    if total_amount is None:
        return False
    try:
        if abs(sum(float(value) for value in split_details.values()) - float(total_amount)) > 1e-6:
            return False
    except (TypeError, ValueError):
        return False
    amount = data.get("amount")
    if amount is None:
        return True
    try:
        if abs(float(split_details["user"]) - float(amount)) > 1e-6:
            return False
    except (TypeError, ValueError, KeyError):
        return False
    return True


def _format_amount(value, currency: str) -> str:
    return f"${value} {currency}"


def _format_datetime(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value
    return str(value)


def _build_confirm_text(data: dict) -> str:
    currency = data.get("currency", "ARS")
    lines = ["Transacción detectada:"]
    if data.get("type"):
        lines.append(f"Tipo: {data['type']}")
    lines.append(f"Monto personal: {_format_amount(data.get('amount'), currency)}")
    if data.get("total_amount") is not None:
        lines.append(f"Monto total: {_format_amount(data['total_amount'], currency)}")
    if data.get("category"):
        lines.append(f"Categoría: {data['category']}")
    if data.get("description"):
        lines.append(f"Concepto: {data['description']}")
    if data.get("merchant"):
        lines.append(f"Comercio: {data['merchant']}")
    payment = data.get("payment_method")
    if payment:
        lines.append(f"Método de pago: {PAYMENT_METHOD_LABELS.get(payment, payment)}")
    date_str = _format_datetime(data.get("transaction_date"))
    if date_str:
        lines.append(f"Fecha: {date_str}")
    if data.get("status"):
        lines.append(f"Estado: {data['status']}")
    if data.get("participants"):
        lines.append(f"Participantes: {', '.join(data['participants'])}")
    if data.get("split_details"):
        distribution = ", ".join(
            f"{'Yo' if key == 'user' else key}: {_format_amount(amount, currency)}"
            for key, amount in data["split_details"].items()
        )
        lines.append(f"Distribución: {distribution}")
    installment_number = data.get("installment_number")
    installment_total = data.get("installment_total")
    if installment_number or installment_total:
        lines.append(f"Cuotas: {installment_number}/{installment_total}")
    if data.get("recurrence"):
        lines.append(f"Recurrencia: {data['recurrence']}")
    due_date_str = _format_datetime(data.get("due_date"))
    if due_date_str:
        lines.append(f"Vencimiento: {due_date_str}")
    if data.get("location"):
        lines.append(f"Ubicación: {data['location']}")
    if data.get("tags"):
        lines.append(f"Etiquetas: {', '.join(data['tags'])}")
    if data.get("notes"):
        lines.append(f"Notas: {data['notes']}")
    return "\n".join(lines)


async def _send_confirm_message(update: Update, data: dict):
    await update.message.reply_text(
        _build_confirm_text(data),
        reply_markup=_get_confirm_keyboard(),
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not check_access(update):
        return

    chat_id = update.effective_chat.id
    state = pending_transactions.get(chat_id)

    if not state:
        await query.edit_message_text(text="No hay transacción pendiente.")
        return

    if state.get("action") == "pick_date" and query.data.startswith("date_"):
        if query.data == "date_today":
            state["data"]["transaction_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pending_transactions[chat_id] = {"action": "confirm", "data": state["data"]}
            await query.edit_message_text(
                text=_build_confirm_text(state["data"]),
                reply_markup=_get_confirm_keyboard(),
            )
        elif query.data == "date_yesterday":
            yesterday = datetime.now() - timedelta(days=1)
            state["data"]["transaction_date"] = yesterday.strftime("%Y-%m-%d %H:%M:%S")
            pending_transactions[chat_id] = {"action": "confirm", "data": state["data"]}
            await query.edit_message_text(
                text=_build_confirm_text(state["data"]),
                reply_markup=_get_confirm_keyboard(),
            )
        elif query.data == "date_custom":
            pending_transactions[chat_id] = {"action": "wait_custom_date", "data": state["data"]}
            await query.edit_message_text(
                text="Por favor, escribe la fecha de la transacción (ej. 'ayer', 'el martes pasado', '10/08'):"
            )
        return

    if state.get("action") == "confirm" and query.data == "add_context":
        pending_transactions[chat_id] = {"action": "add_context", "data": state["data"]}
        await query.edit_message_text(
            text="Envía más detalles de la transacción (lugar, etiquetas, cuotas, etc.)."
        )
        return

    if state.get("action") != "confirm":
        await query.edit_message_text(text="No hay transacción pendiente para confirmar.")
        return

    if query.data == "confirm":
        data = pending_transactions.pop(chat_id)["data"]
        await insert_transaction(data)
        await query.edit_message_text(text="Transacción guardada exitosamente. ✅")
    elif query.data == "cancel":
        pending_transactions.pop(chat_id, None)
        await query.edit_message_text(text="Transacción cancelada.")

