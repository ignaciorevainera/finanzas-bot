import json
import logging
from datetime import datetime
from google import genai
from google.genai import types
from app.config import settings

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
- type: "expense" or "income"
- amount: number (positive float or int)
- currency: string (ISO currency code, e.g. "ARS", "USD"; default "ARS")
- category: one of ["food", "transport", "entertainment", "health", "education", "clothing", "housing", "utilities", "subscriptions", "salary", "freelance", "gift", "savings", "investment", "travel", "other"]
- description: short string describing what was bought or received (e.g. "jugo", "almuerzo", "sueldo de agosto"); null if not mentioned
- merchant: string or null
- payment_method: one of ["cash", "debit card", "credit card", "transfer", "other"] if explicitly mentioned or clearly inferable; null if not mentioned or ambiguous
- tags: array of strings
- location: string or null
- notes: string or null
- transaction_date: ISO 8601 string ("YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS") if explicit or relative date/time is mentioned in user input (e.g. "ayer", "el lunes", "10/08"), resolved relative to current date and time; null if no date/time is mentioned

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
        if "error" in data or not isinstance(data, dict):
            logger.warning(
                "Failed to parse transaction from text: invalid structure",
                extra={"input_text": text, "response_data": data},
            )
            return None
        data.setdefault("currency", "ARS")
        data.setdefault("tags", [])
        data.setdefault("transaction_date", None)
        logger.info(
            "Successfully parsed transaction from text",
            extra={"parsed_data": data},
        )
        return data
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
        if "error" in data or not isinstance(data, dict):
            logger.warning(
                "Failed to parse transaction from audio: invalid structure",
                extra={"mime_type": mime_type, "response_data": data},
            )
            return None
        data.setdefault("currency", "ARS")
        data.setdefault("tags", [])
        data.setdefault("transaction_date", None)
        logger.info(
            "Successfully parsed transaction from audio",
            extra={"mime_type": mime_type, "parsed_data": data},
        )
        return data
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


