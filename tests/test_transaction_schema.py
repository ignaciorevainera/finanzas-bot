from datetime import datetime, timezone

from app.transaction_schema import (
    apply_transaction_defaults,
    get_missing_transaction_fields,
    merge_transaction_context,
    normalize_transaction,
)


def test_normalize_transaction_translates_category_and_payment_method():
    data = normalize_transaction({
        "type": "expense",
        "category": "food",
        "payment_method": "credit card",
        "description": "supermercado",
    })

    assert data["type"] == "Gasto"
    assert data["category"] == "Comida"
    assert data["payment_method"] == "Tarjeta de Crédito"
    assert data["description"] == "Supermercado"


def test_defaults_fill_only_unspecified_defaultable_fields():
    now = datetime(2026, 8, 12, 15, 30, tzinfo=timezone.utc)
    data = apply_transaction_defaults({"amount": 500}, now=now)

    assert data["currency"] == "ARS"
    assert data["transaction_date"] == now
    assert data["status"] == "Completado"
    assert data["total_amount"] == 500


def test_required_fields_are_reported_in_prompt_order():
    assert get_missing_transaction_fields({"amount": 500}) == [
        "type", "category", "description", "payment_method"
    ]


def test_merge_replaces_explicit_values_and_preserves_existing_context():
    result = merge_transaction_context(
        {"description": "Supermercado", "location": "Centro", "notes": "Con Viole"},
        {"location": "Palermo", "merchant": "Carrefour", "notes": None},
    )

    assert result == {
        "description": "Supermercado",
        "location": "Palermo",
        "merchant": "Carrefour",
        "notes": "Con Viole",
    }


def test_normalize_translates_income_and_status():
    data = normalize_transaction({
        "type": "income",
        "category": "salary",
        "payment_method": "transfer",
        "status": "completed",
    })

    assert data["type"] == "Ingreso"
    assert data["category"] == "Sueldo"
    assert data["payment_method"] == "Transferencia"
    assert data["status"] == "Completado"


def test_normalize_accepts_existing_spanish_values():
    data = normalize_transaction({"type": "Gasto", "category": "Comida"})

    assert data["type"] == "Gasto"
    assert data["category"] == "Comida"


def test_normalize_preserves_custom_category_with_capitalized_first_letter():
    data = normalize_transaction({"category": "gimnasio"})

    assert data["category"] == "Gimnasio"


def test_normalize_capitalizes_custom_tags():
    data = normalize_transaction({"tags": ["gimnasio", "openai"]})

    assert data["tags"] == ["Gimnasio", "Openai"]


def test_normalize_preserves_currency_and_missing_values():
    data = normalize_transaction({"currency": "USD", "type": None, "description": ""})

    assert data["currency"] == "USD"
    assert data["type"] is None
    assert data["description"] == ""


def test_normalize_does_not_invent_fields():
    assert normalize_transaction({}) == {}


def test_defaults_do_not_override_explicit_values():
    now = datetime(2026, 8, 12, 15, 30, tzinfo=timezone.utc)
    tx_date = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
    data = apply_transaction_defaults({
        "currency": "USD",
        "status": "Pendiente",
        "transaction_date": tx_date,
        "total_amount": 1000,
        "amount": 500,
    }, now=now)

    assert data["currency"] == "USD"
    assert data["status"] == "Pendiente"
    assert data["transaction_date"] == tx_date
    assert data["total_amount"] == 1000


def test_defaults_keep_present_datetime_and_iso_string_unchanged():
    now = datetime(2026, 8, 12, 15, 30, tzinfo=timezone.utc)
    data = apply_transaction_defaults({"transaction_date": "2026-08-10 21:00:00"}, now=now)

    assert data["transaction_date"] == "2026-08-10 21:00:00"


def test_missing_fields_treat_empty_string_as_missing():
    assert get_missing_transaction_fields({
        "type": "Gasto",
        "amount": 500,
        "category": "Comida",
        "description": "",
        "payment_method": None,
    }) == ["description", "payment_method"]


def test_merge_unions_tags_case_insensitively_in_order():
    result = merge_transaction_context(
        {"tags": ["Familia", "cena"]},
        {"tags": ["CENA", "viaje", "familia"]},
    )

    assert result["tags"] == ["Familia", "cena", "viaje"]


def test_merge_appends_notes_when_both_explicit():
    result = merge_transaction_context(
        {"notes": "Con Viole"},
        {"notes": "Invite a mama"},
    )

    assert result["notes"] == "Con Viole\nInvite a mama"


def test_merge_replaces_notes_when_current_is_missing():
    result = merge_transaction_context(
        {"notes": None},
        {"notes": "Con Viole"},
    )

    assert result["notes"] == "Con Viole"


def test_merge_ignores_empty_string_additions():
    result = merge_transaction_context(
        {"description": "Supermercado", "location": "Centro"},
        {"location": "", "merchant": "Carrefour"},
    )

    assert result["location"] == "Centro"
    assert result["merchant"] == "Carrefour"


def test_merge_preserves_explicit_time_flag_when_date_not_updated():
    result = merge_transaction_context(
        {"transaction_date": "2026-08-12 18:30:00", "transaction_date_has_explicit_time": True},
        {"location": "Palermo", "transaction_date_has_explicit_time": False},
    )

    assert result["transaction_date_has_explicit_time"] is True
    assert result["location"] == "Palermo"


def test_merge_adopts_explicit_time_flag_when_date_also_updated():
    result = merge_transaction_context(
        {"transaction_date": "2026-08-12 18:30:00", "transaction_date_has_explicit_time": True},
        {"transaction_date": "2026-08-13", "transaction_date_has_explicit_time": False},
    )

    assert result["transaction_date_has_explicit_time"] is False
    assert result["transaction_date"] == "2026-08-13"
