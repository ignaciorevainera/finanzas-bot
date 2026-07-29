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
from app.gemini_ai import parse_transaction_from_text, parse_transaction_from_audio

logger = logging.getLogger(__name__)

pending_transactions = {}


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
        created = t['created_at'].strftime('%Y-%m-%d %H:%M') if t['created_at'] else 'N/A'
        msg += f"{i}. {t['type']} de ${t['amount']} en {t['category']} ({created})\n"
    
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
        msg += f"{i}. {t['type']} de ${t['amount']} en {t['category']}\n"
        
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
    pending_transactions[chat_id] = {"action": "confirm", "data": data}
    
    msg = (
        f"Transacción detectada:\n"
        f"Tipo: {data.get('type')}\n"
        f"Monto: ${data.get('amount')} {data.get('currency', 'ARS')}\n"
        f"Categoría: {data.get('category')}\n"
        f"Método de pago: {data.get('payment_method')}\n"
    )
    if data.get("merchant"):
        msg += f"Comercio: {data.get('merchant')}\n"
        
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirmar", callback_data="confirm"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(msg, reply_markup=reply_markup)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not check_access(update):
        return
        
    chat_id = update.effective_chat.id
    state = pending_transactions.get(chat_id)
    
    if not state or state.get("action") != "confirm":
        await query.edit_message_text(text="No hay transacción pendiente para confirmar.")
        return
        
    if query.data == "confirm":
        data = state["data"]
        await insert_transaction(data)
        await query.edit_message_text(text="Transacción guardada exitosamente.")
    elif query.data == "cancel":
        await query.edit_message_text(text="Transacción cancelada.")
        
    if chat_id in pending_transactions:
        del pending_transactions[chat_id]
