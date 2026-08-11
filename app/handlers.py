from datetime import datetime, timedelta
import csv
import io
import logging
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

CATEGORY_LABELS: dict[str, str] = {
    "food": "Comida",
    "transport": "Transporte",
    "entertainment": "Entretenimiento",
    "health": "Salud",
    "education": "Educación",
    "clothing": "Ropa",
    "housing": "Vivienda",
    "utilities": "Servicios",
    "subscriptions": "Suscripciones",
    "salary": "Sueldo",
    "freelance": "Freelance",
    "gift": "Regalo",
    "savings": "Ahorros",
    "investment": "Inversión",
    "travel": "Viajes",
    "other": "Otro",
}

PAYMENT_METHOD_LABELS: dict[str, str] = {
    "cash": "💵 Efectivo",
    "debit card": "💳 Débito",
    "credit card": "💳 Crédito",
    "transfer": "🏦 Transferencia",
    "other": "Otro",
}

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
                InlineKeyboardButton("✅ Confirmar", callback_data="confirm"),
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
        type_label = "Gasto" if row["type"] == "expense" else "Ingreso"
        category_label = CATEGORY_LABELS.get(row["category"], row["category"])
        msg += f"- {category_label} ({type_label}): ${row['total']:.2f}\n"
    
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
        type_label = "Gasto" if t["type"] == "expense" else "Ingreso"
        category_label = CATEGORY_LABELS.get(t["category"], t["category"])
        desc = f" — {t['description']}" if t['description'] else ""
        msg += f"{i}. {type_label} de ${t['amount']} en {category_label}{desc} ({created})\n"
    
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
        type_label = "Gasto" if t["type"] == "expense" else "Ingreso"
        category_label = CATEGORY_LABELS.get(t["category"], t["category"])
        desc = f" — {t['description']}" if t['description'] else ""
        msg += f"{i}. {type_label} de ${t['amount']} en {category_label}{desc}\n"
        
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

    if data.get("payment_method") is None:
        pending_transactions[chat_id] = {"action": "pick_payment", "data": data}
        keyboard = [
            [
                InlineKeyboardButton(PAYMENT_METHOD_LABELS["cash"], callback_data="pm_cash"),
                InlineKeyboardButton(PAYMENT_METHOD_LABELS["debit card"], callback_data="pm_debit card"),
            ],
            [
                InlineKeyboardButton(PAYMENT_METHOD_LABELS["credit card"], callback_data="pm_credit card"),
                InlineKeyboardButton(PAYMENT_METHOD_LABELS["transfer"], callback_data="pm_transfer"),
            ],
            [
                InlineKeyboardButton(PAYMENT_METHOD_LABELS["other"], callback_data="pm_other"),
            ],
        ]
        await update.message.reply_text(
            "¿Con qué método de pago fue la transacción?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
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


def _build_confirm_text(data: dict) -> str:
    category_label = CATEGORY_LABELS.get(data.get("category", ""), data.get("category", ""))
    payment_label = PAYMENT_METHOD_LABELS.get(data.get("payment_method", ""), data.get("payment_method", ""))
    type_label = "Gasto" if data.get("type") == "expense" else "Ingreso"
    
    tx_date_str = ""
    if data.get("transaction_date"):
        dt_val = data["transaction_date"]
        if isinstance(dt_val, datetime):
            tx_date_str = dt_val.strftime("%Y-%m-%d %H:%M")
        elif isinstance(dt_val, str):
            try:
                parsed_dt = datetime.fromisoformat(dt_val)
                tx_date_str = parsed_dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                tx_date_str = dt_val

    msg = (
        f"Transacción detectada:\n"
        f"Tipo: {type_label}\n"
        f"Monto: ${data.get('amount')} {data.get('currency', 'ARS')}\n"
        f"Categoría: {category_label}\n"
        f"Método de pago: {payment_label}\n"
    )
    if tx_date_str:
        msg += f"Fecha: {tx_date_str}\n"
    if data.get("description"):
        msg += f"Concepto: {data.get('description')}\n"
    if data.get("merchant"):
        msg += f"Comercio: {data.get('merchant')}\n"
    return msg


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

    if state.get("action") == "pick_payment" and query.data.startswith("pm_"):
        payment_method = query.data[len("pm_"):]
        state["data"]["payment_method"] = payment_method
        if state["data"].get("transaction_date") is None:
            pending_transactions[chat_id] = {"action": "pick_date", "data": state["data"]}
            await query.edit_message_text(
                text="¿De qué fecha es la transacción?",
                reply_markup=_get_date_keyboard(),
            )
        else:
            pending_transactions[chat_id] = {"action": "confirm", "data": state["data"]}
            await query.edit_message_text(
                text=_build_confirm_text(state["data"]),
                reply_markup=_get_confirm_keyboard(),
            )
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

