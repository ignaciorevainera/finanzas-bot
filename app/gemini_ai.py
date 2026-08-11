import json
import logging
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

If the input does not describe a valid transaction, return JSON with key "error": "invalid transaction"."""


async def parse_transaction_from_text(text: str) -> dict | None:
    try:
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
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
    audio_bytes: bytes, mime_type: str
) -> dict | None:
    try:
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=[audio_part, "Extract transaction details from audio."],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
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
