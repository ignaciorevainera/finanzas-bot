"""Pure transaction data contract: Spanish vocabulary normalization, defaults,
required-field detection, and shared-context merging.

Consumed by database persistence, Gemini extraction, and Telegram handlers.
"""

from datetime import datetime
from typing import Any

TransactionData = dict[str, Any]

REQUIRED_TRANSACTION_FIELDS = (
    "type", "amount", "category", "description", "payment_method",
)

DEFAULT_TRANSACTION_VALUES = {
    "currency": "ARS",
    "status": "Completado",
}

NOTES_MERGE_SEPARATOR = "\n"

TYPE_MAP = {
    "expense": "Gasto",
    "income": "Ingreso",
}

CATEGORY_MAP = {
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
    "freelance": "Trabajo Independiente",
    "gift": "Regalo",
    "savings": "Ahorros",
    "investment": "Inversión",
    "travel": "Viajes",
    "other": "Otros",
}

PAYMENT_METHOD_MAP = {
    "cash": "Efectivo",
    "debit card": "Tarjeta de Débito",
    "credit card": "Tarjeta de Crédito",
    "transfer": "Transferencia",
    "other": "Otro",
}

STATUS_MAP = {
    "completed": "Completado",
    "pending": "Pendiente",
    "cancelled": "Cancelado",
}


def _build_vocab_lookup(vocab_map: dict[str, str]) -> dict[str, str]:
    lookup = {key.lower(): value for key, value in vocab_map.items()}
    for value in vocab_map.values():
        lookup.setdefault(value.lower(), value)
    return lookup


_TYPE_LOOKUP = _build_vocab_lookup(TYPE_MAP)
_CATEGORY_LOOKUP = _build_vocab_lookup(CATEGORY_MAP)
_PAYMENT_METHOD_LOOKUP = _build_vocab_lookup(PAYMENT_METHOD_MAP)
_STATUS_LOOKUP = _build_vocab_lookup(STATUS_MAP)


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _capitalize_first_letter(value: str) -> str:
    return value[0].upper() + value[1:]


def _normalize_vocab(value, lookup: dict[str, str]) -> str | None:
    if _is_missing(value) or not isinstance(value, str):
        return value
    return lookup.get(value.strip().lower(), value)


def _normalize_category(value) -> str | None:
    if _is_missing(value) or not isinstance(value, str):
        return value
    canonical = _CATEGORY_LOOKUP.get(value.strip().lower())
    if canonical is not None:
        return canonical
    return _capitalize_first_letter(value.strip())


def normalize_transaction(data: TransactionData) -> TransactionData:
    """Map known English/Spanish values to canonical Spanish vocabulary."""
    result = dict(data)
    for field, lookup in (
        ("type", _TYPE_LOOKUP),
        ("status", _STATUS_LOOKUP),
        ("payment_method", _PAYMENT_METHOD_LOOKUP),
    ):
        if field in result:
            result[field] = _normalize_vocab(result[field], lookup)
    if "category" in result:
        result["category"] = _normalize_category(result["category"])
    if "description" in result and isinstance(result["description"], str) and result["description"].strip():
        result["description"] = _capitalize_first_letter(result["description"].strip())
    if "tags" in result and isinstance(result["tags"], list):
        result["tags"] = [
            _capitalize_first_letter(tag.strip())
            for tag in result["tags"]
            if isinstance(tag, str) and tag.strip()
        ]
    return result


def apply_transaction_defaults(data: TransactionData, *, now: datetime) -> TransactionData:
    """Fill only unspecified defaultable fields: currency, status, date, total."""
    result = dict(data)
    if _is_missing(result.get("currency")):
        result["currency"] = DEFAULT_TRANSACTION_VALUES["currency"]
    if _is_missing(result.get("status")):
        result["status"] = DEFAULT_TRANSACTION_VALUES["status"]
    if _is_missing(result.get("transaction_date")):
        result["transaction_date"] = now
    if _is_missing(result.get("total_amount")) and not _is_missing(result.get("amount")):
        result["total_amount"] = result["amount"]
    return result


def get_missing_transaction_fields(data: TransactionData) -> list[str]:
    """Return required fields absent from data, in canonical prompt order."""
    return [field for field in REQUIRED_TRANSACTION_FIELDS if _is_missing(data.get(field))]


def merge_transaction_context(
    current: TransactionData,
    additions: TransactionData,
) -> TransactionData:
    """Merge explicit non-null additions onto current context."""
    result = dict(current)
    for key, value in additions.items():
        if _is_missing(value):
            continue
        if key == "tags":
            result[key] = _merge_tags(current.get(key), value)
        elif key == "notes":
            result[key] = _merge_notes(current.get(key), value)
        else:
            result[key] = value
    return result


def _merge_tags(current, additions) -> list[str]:
    merged = []
    seen = set()
    for tag in list(current or []) + list(additions):
        if _is_missing(tag) or not isinstance(tag, str):
            continue
        normalized = tag.strip()
        key = normalized.lower()
        if key not in seen:
            seen.add(key)
            merged.append(normalized)
    return merged


def _merge_notes(current, addition) -> str:
    if _is_missing(current):
        return addition
    return f"{current}{NOTES_MERGE_SEPARATOR}{addition}"
