import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from app.config import settings
from app.database import init_db, close_db
from app.handlers import (
    start_handler,
    help_handler,
    summary_handler,
    recent_handler,
    delete_handler,
    export_handler,
    message_handler,
    voice_handler,
    callback_handler,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .updater(None)
        .build()
    )

    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("summary", summary_handler))
    application.add_handler(CommandHandler("recent", recent_handler))
    application.add_handler(CommandHandler("delete", delete_handler))
    application.add_handler(CommandHandler("export", export_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.VOICE, voice_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    await application.initialize()
    await application.start()
    
    webhook_url = f"{settings.webhook_url}/webhook"
    await application.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES)

    app.state.telegram_app = application

    yield

    await application.stop()
    await application.shutdown()
    await close_db()


app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    application = app.state.telegram_app
    update = Update.de_json(data=payload, bot=application.bot)
    await application.process_update(update)
    return {"status": "processed"}
