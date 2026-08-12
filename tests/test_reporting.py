from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from app.reporting import ReportRequest, format_report


def _request(metric: str, value: str | None = None) -> ReportRequest:
    return ReportRequest(
        metric=metric,
        start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        end=datetime(2026, 9, 1, tzinfo=timezone.utc),
        value=value,
    )


def test_report_request_keeps_half_open_timezone_aware_period():
    request = ReportRequest(
        metric="category",
        start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        end=datetime(2026, 9, 1, tzinfo=timezone.utc),
        value="Comida",
    )

    assert request.start < request.end
    assert request.value == "Comida"


def test_report_request_defaults_group_by_and_value_to_none():
    request = _request("summary")

    assert request.group_by is None
    assert request.value is None


def test_report_request_is_immutable():
    request = _request("summary")

    with pytest.raises(FrozenInstanceError):
        request.metric = "category"


def test_report_request_rejects_naive_datetimes():
    aware = datetime(2026, 9, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        ReportRequest("summary", datetime(2026, 8, 1), aware)
    with pytest.raises(ValueError):
        ReportRequest("summary", aware, datetime(2026, 9, 1))


def test_report_request_rejects_empty_period():
    moment = datetime(2026, 8, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        ReportRequest("summary", moment, moment)


def test_report_request_rejects_inverted_period():
    with pytest.raises(ValueError):
        ReportRequest(
            "summary",
            start=datetime(2026, 9, 1, tzinfo=timezone.utc),
            end=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )


def test_format_summary_uses_personal_amount_and_shows_shared_total():
    text = format_report(
        _request("summary"),
        {"income": 150000, "expenses": 30000, "shared_total": 120000, "net": 120000},
    )

    assert "Ingresos personales" in text
    assert "Gastos personales" in text
    assert "Total compartido" in text
    assert "Flujo neto" in text


def test_format_summary_uses_stored_currency_when_provided():
    text = format_report(
        _request("summary"),
        {"currency": "USD", "income": 1000, "expenses": 300, "shared_total": 0, "net": 700},
    )

    assert "USD" in text
    assert "ARS" not in text


def test_format_report_has_specific_labels_for_advanced_metrics():
    for metric, label in {
        "installments": "Cuotas",
        "recurrence": "Recurrentes",
        "due_dates": "Vencimientos",
        "transfers": "Transferencias",
        "refunds": "Reembolsos",
        "packages": "Paquetes",
        "shared": "Compartidos",
    }.items():
        text = format_report(_request(metric), {"rows": []})
        assert label in text


def test_format_report_covers_every_metric_with_spanish_label():
    for metric, label in {
        "summary": "Resumen",
        "category": "Categorías",
        "merchant": "Comercios",
        "payment_method": "Medios de Pago",
        "location": "Ubicaciones",
        "person": "Personas",
        "tag": "Etiquetas",
        "installments": "Cuotas",
        "recurrence": "Recurrentes",
        "due_dates": "Vencimientos",
        "transfers": "Transferencias",
        "refunds": "Reembolsos",
        "packages": "Paquetes",
        "shared": "Compartidos",
    }.items():
        text = format_report(_request(metric), {"rows": []})
        assert label in text


def test_format_empty_result_explains_no_transactions():
    text = format_report(_request("merchant"), {"rows": []})

    assert "No hay transacciones" in text


def test_format_category_rows_show_label_amount_and_currency():
    text = format_report(
        _request("category"),
        {"currency": "ARS", "rows": [{"label": "Comida", "total": 30000}]},
    )

    assert "Comida" in text
    assert "30000 ARS" in text


def test_format_uses_stored_currency_not_ars():
    text = format_report(
        _request("category"),
        {"currency": "USD", "rows": [{"label": "Comida", "total": 120.5}]},
    )

    assert "USD" in text
    assert "ARS" not in text
    assert "120.5" in text


def test_format_shared_rows_show_personal_and_total_amounts():
    text = format_report(
        _request("shared"),
        {
            "currency": "ARS",
            "rows": [{"label": "Cena con amigos", "amount": 5000, "total_amount": 15000}],
        },
    )

    assert "Cena con amigos" in text
    assert "5000" in text
    assert "15000" in text
