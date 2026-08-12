import json
import logging
from datetime import datetime
from google import genai
from google.genai import types
from app.config import settings
from app.transaction_schema import apply_transaction_defaults, normalize_transaction

def clean_json_text(text: str) -> str:
    text = text.strip()
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace : last_brace + 1]
    return text

logger = logging.getLogger(__name__)

client = genai.Client(api_key=settings.gemini_api_key)

SYSTEM_PROMPT = """You are a financial assistant that extracts transaction details from user input in any language.
The current date and time is {current_datetime}.
Return ONLY a JSON object with the following fields:
- type: "Gasto" or "Ingreso"
- amount: number (positive float or int); the user's personal share of the movement
- total_amount: number (positive float or int); the complete amount of the movement; equal to amount unless the movement is shared
- currency: string (ISO currency code, e.g. "ARS", "USD"; default "ARS")
- category: one of ["Comida", "Transporte", "Entretenimiento", "Salud", "Educación", "Ropa", "Vivienda", "Servicios", "Suscripciones", "Sueldo", "Trabajo Independiente", "Regalo", "Ahorros", "Inversión", "Viajes", "Otros"]; preserve a custom category exactly as the user expressed it (capitalize first letter), do not force it into the list
- description: short title only (e.g. "Cena", "Supermercado", "Sueldo de agosto"); null if not mentioned
- merchant: string or null; never repeat the location here
- payment_method: one of ["Efectivo", "Tarjeta de Débito", "Tarjeta de Crédito", "Transferencia", "Otro"] only if explicitly mentioned or clearly inferable; null if not mentioned or ambiguous
- status: one of ["Completado", "Pendiente", "Cancelado"] only if explicitly mentioned; null otherwise
- tags: array of strings; include explicit tags mentioned by the user plus any additional relevant tags you generate, without duplicates
- location: string or null
- notes: string or null; residual context that does not fit description, merchant, or location
- transaction_date: ISO 8601 string ("YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS") if explicit or relative date/time is mentioned in user input (e.g. "ayer", "el lunes", "10/08"), resolved relative to current date and time; null if no date/time is mentioned
- participants: array of names of people sharing the movement; null if not shared
- split_details: object mapping each participant name plus the special key "user" to their exact amounts; required whenever the user expresses a personal share or a shared movement; never assume an equal split
- due_date: ISO 8601 string or null
- recurrence: string or null (e.g. "weekly", "monthly")
- installment_number: positive integer or null
- installment_total: positive integer or null
- transfer_details: object or null
- package_details: object or null
- related_transaction_id: string or null

Return null for any field without an explicit value. Do not generate or reference any database SQL or table names.
If the input does not describe a valid transaction, return JSON with key "error": "invalid transaction"."""

DATE_SYSTEM_PROMPT = """You are a helper that extracts a specific date and time from user input.
The current date and time is {current_datetime}.
Return ONLY a JSON object with the following fields:
- date: ISO 8601 string ("YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS") resolved relative to current date and time; null if no date/time can be inferred.

If the input does not contain a date or time expression, return JSON with key "error": "no date found"."""



def _get_formatted_datetime(current_datetime: datetime | str | None) -> str:
    if current_datetime is None:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(current_datetime, datetime):
        return current_datetime.strftime("%Y-%m-%d %H:%M:%S")
    return str(current_datetime)


def _resolve_datetime(current_datetime: datetime | str | None) -> datetime:
    if current_datetime is None:
        return datetime.now()
    if isinstance(current_datetime, datetime):
        return current_datetime
    try:
        return datetime.fromisoformat(str(current_datetime))
    except ValueError:
        return datetime.now()


def _finalize_transaction_data(
    data: dict, current_datetime: datetime | str | None
) -> dict | None:
    if not isinstance(data, dict) or "error" in data:
        return None
    data = normalize_transaction(data)
    data.setdefault("tags", [])
    return apply_transaction_defaults(data, now=_resolve_datetime(current_datetime))


async def parse_transaction_from_text(
    text: str, current_datetime: datetime | str | None = None
) -> dict | None:
    try:
        dt_str = _get_formatted_datetime(current_datetime)
        system_instruction = SYSTEM_PROMPT.format(current_datetime=dt_str)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(clean_json_text(response.text))
        result = _finalize_transaction_data(data, current_datetime)
        if result is None:
            logger.warning(
                "Failed to parse transaction from text: invalid structure",
                extra={"input_text": text, "response_data": data},
            )
            return None
        logger.info(
            "Successfully parsed transaction from text",
            extra={"parsed_data": result},
        )
        return result
    except Exception as exc:
        logger.error(
            "Error parsing transaction from text",
            extra={"input_text": text, "error": str(exc)},
            exc_info=True,
        )
        return None


async def parse_transaction_from_audio(
    audio_bytes: bytes,
    mime_type: str,
    current_datetime: datetime | str | None = None,
) -> dict | None:
    try:
        dt_str = _get_formatted_datetime(current_datetime)
        system_instruction = SYSTEM_PROMPT.format(current_datetime=dt_str)
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=[audio_part, "Extract transaction details from audio."],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(clean_json_text(response.text))
        result = _finalize_transaction_data(data, current_datetime)
        if result is None:
            logger.warning(
                "Failed to parse transaction from audio: invalid structure",
                extra={"mime_type": mime_type, "response_data": data},
            )
            return None
        logger.info(
            "Successfully parsed transaction from audio",
            extra={"mime_type": mime_type, "parsed_data": result},
        )
        return result
    except Exception as exc:
        logger.error(
            "Error parsing transaction from audio",
            extra={"mime_type": mime_type, "error": str(exc)},
            exc_info=True,
        )
        return None


async def parse_date_from_text(
    text: str, current_datetime: datetime | str | None = None
) -> str | None:
    try:
        dt_str = _get_formatted_datetime(current_datetime)
        system_instruction = DATE_SYSTEM_PROMPT.format(current_datetime=dt_str)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(clean_json_text(response.text))
        if "error" in data or not isinstance(data, dict):
            logger.warning(
                "Failed to parse date from text: invalid structure",
                extra={"input_text": text, "response_data": data},
            )
            return None
        date_val = data.get("date")
        if not date_val or not isinstance(date_val, str):
            logger.warning(
                "Failed to parse date from text: date missing or not string",
                extra={"input_text": text, "response_data": data},
            )
            return None
        logger.info(
            "Successfully parsed date from text",
            extra={"parsed_date": date_val},
        )
        return date_val
    except Exception as exc:
        logger.error(
            "Error parsing date from text",
            extra={"input_text": text, "error": str(exc)},
            exc_info=True,
        )
        return None


