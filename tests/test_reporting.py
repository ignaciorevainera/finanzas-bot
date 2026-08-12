from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.reporting import ReportRequest, format_report, run_report


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


def test_empty_report_explains_no_transactions():
    request = ReportRequest(
        "merchant",
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    assert "No hay transacciones" in format_report(request, {"rows": []})


@pytest.mark.asyncio
async def test_run_report_dispatches_category_request(monkeypatch):
    raw = [{"label": "Comida", "total": 30000, "currency": "ARS"}]
    expected = {"rows": raw}
    mocked = AsyncMock(return_value=raw)
    monkeypatch.setattr("app.reporting.get_report_by_dimension", mocked)
    request = ReportRequest(
        "category",
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    result = await run_report(request)

    assert result == expected
    mocked.assert_awaited_once_with("category", request.start, request.end, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metric", "db_func", "period_only"),
    [
        ("summary", "get_report_summary", True),
        ("category", "get_report_by_dimension", False),
        ("merchant", "get_report_by_dimension", False),
        ("payment_method", "get_report_by_dimension", False),
        ("location", "get_report_by_dimension", False),
        ("tag", "get_report_by_dimension", False),
        ("installments", "get_report_installments", True),
        ("recurrence", "get_report_recurrence", True),
        ("due_dates", "get_report_due_dates", True),
        ("transfers", "get_report_transfers", True),
        ("refunds", "get_report_refunds", True),
        ("packages", "get_report_packages", True),
        ("shared", "get_report_shared", True),
    ],
)
async def test_run_report_dispatches_every_metric_to_its_db_function(
    monkeypatch, metric, db_func, period_only
):
    if metric == "summary":
        raw = [
            {"income": 100, "expenses": 40, "shared_total": 10, "net": 60, "currency": "ARS"}
        ]
        expected = raw[0]
    else:
        raw = [{"label": "x", "total": 1, "currency": "ARS"}]
        expected = {"rows": raw}
    mocked = AsyncMock(return_value=raw)
    monkeypatch.setattr(f"app.reporting.{db_func}", mocked)
    request = _request(metric)

    result = await run_report(request)

    assert result == expected
    if period_only:
        mocked.assert_awaited_once_with(request.start, request.end)
    else:
        mocked.assert_awaited_once_with(metric, request.start, request.end, None)


@pytest.mark.asyncio
async def test_run_report_summary_empty_returns_zeroed_dict(monkeypatch):
    mocked = AsyncMock(return_value=[])
    monkeypatch.setattr("app.reporting.get_report_summary", mocked)

    result = await run_report(_request("summary"))

    assert result == {"income": 0, "expenses": 0, "shared_total": 0, "net": 0}


@pytest.mark.asyncio
async def test_run_report_passes_dimension_filter_value_through(monkeypatch):
    mocked = AsyncMock(return_value=[])
    monkeypatch.setattr("app.reporting.get_report_by_dimension", mocked)
    request = _request("tag", value="Sueldo")

    result = await run_report(request)

    assert result == {"rows": []}
    mocked.assert_awaited_once_with("tag", request.start, request.end, "Sueldo")


@pytest.mark.asyncio
async def test_run_report_person_filters_reserved_user_row(monkeypatch):
    mocked = AsyncMock(
        return_value=[
            {"label": "user", "total": 5000, "currency": "ARS"},
            {"label": "María", "total": 3000, "currency": "ARS"},
            {"label": "user", "total": 2000, "currency": "USD"},
        ]
    )
    monkeypatch.setattr("app.reporting.get_report_person", mocked)
    request = _request("person")

    result = await run_report(request)

    assert result == {"rows": [{"label": "María", "total": 3000, "currency": "ARS"}]}
    mocked.assert_awaited_once_with(request.start, request.end)


@pytest.mark.asyncio
async def test_run_report_person_returns_empty_when_only_user_rows(monkeypatch):
    mocked = AsyncMock(return_value=[{"label": "user", "total": 5000, "currency": "ARS"}])
    monkeypatch.setattr("app.reporting.get_report_person", mocked)

    result = await run_report(_request("person"))

    assert result == {"rows": []}


@pytest.mark.asyncio
async def test_run_report_person_value_filter_keeps_only_matching_person(monkeypatch):
    mocked = AsyncMock(
        return_value=[
            {"label": "user", "total": 5000, "currency": "ARS"},
            {"label": "María", "total": 3000, "currency": "ARS"},
            {"label": "José", "total": 4000, "currency": "ARS"},
        ]
    )
    monkeypatch.setattr("app.reporting.get_report_person", mocked)
    request = _request("person", value="José")

    result = await run_report(request)

    assert result == {"rows": [{"label": "José", "total": 4000, "currency": "ARS"}]}
    mocked.assert_awaited_once_with(request.start, request.end)


@pytest.mark.asyncio
async def test_run_report_person_value_filter_returns_empty_when_no_match(monkeypatch):
    mocked = AsyncMock(
        return_value=[
            {"label": "user", "total": 5000, "currency": "ARS"},
            {"label": "María", "total": 3000, "currency": "ARS"},
        ]
    )
    monkeypatch.setattr("app.reporting.get_report_person", mocked)

    result = await run_report(_request("person", value="Nadie"))

    assert result == {"rows": []}


@pytest.mark.asyncio
async def test_run_report_raises_value_error_for_unroutable_metric(monkeypatch):
    mock_summary = AsyncMock(return_value={"income": 0})
    monkeypatch.setattr("app.reporting.get_report_summary", mock_summary)
    request = ReportRequest(
        "bogus",
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError):
        await run_report(request)

    mock_summary.assert_not_awaited()
