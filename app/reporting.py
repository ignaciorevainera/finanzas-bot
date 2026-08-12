"""Report request contract, pure Spanish formatting, and request routing.

Defines the validated ``ReportRequest`` value object, ``format_report``
(a deterministic string formatter with stable keys per metric), and
``run_report``, which routes each metric to exactly one database function.
``parse_report_request`` arrives in a later task.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.database import (
    get_report_by_dimension,
    get_report_due_dates,
    get_report_installments,
    get_report_packages,
    get_report_person,
    get_report_recurrence,
    get_report_refunds,
    get_report_shared,
    get_report_summary,
    get_report_transfers,
)

ReportMetric = Literal[
    "summary", "category", "merchant", "payment_method", "location",
    "person", "tag", "installments", "recurrence", "due_dates",
    "transfers", "refunds", "packages", "shared",
]

METRIC_LABELS: dict[ReportMetric, str] = {
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
}

DIMENSION_METRICS = frozenset({
    "category", "merchant", "payment_method", "location", "person", "tag",
})

PERIOD_ONLY_REPORTS: dict[str, str] = {
    "installments": "get_report_installments",
    "recurrence": "get_report_recurrence",
    "due_dates": "get_report_due_dates",
    "transfers": "get_report_transfers",
    "refunds": "get_report_refunds",
    "packages": "get_report_packages",
    "shared": "get_report_shared",
}

_DIMENSION_DB_METRICS = frozenset({
    "category", "merchant", "payment_method", "location", "tag",
})


@dataclass(frozen=True)
class ReportRequest:
    """Validated report request with a half-open, timezone-aware period.

    ``start`` is inclusive and ``end`` exclusive. ``value`` carries an
    optional category, merchant, location, person, or tag filter.
    """

    metric: ReportMetric
    start: datetime
    end: datetime
    group_by: str | None = None
    value: str | None = None

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start y end deben ser timezone-aware")
        if self.end <= self.start:
            raise ValueError("end debe ser posterior a start")


async def run_report(request: ReportRequest) -> dict[str, Any]:
    """Route a report request to exactly one database function.

    Every branch returns a dict shaped for ``format_report``:
    - summary: ``income``, ``expenses``, ``shared_total``, ``net``, plus
      optional ``currency``, from the first currency group.
    - all other metrics: ``rows`` of dicts with ``label`` plus the metric
      amount field (``total`` for dimensions, ``amount`` for advanced) and
      optional per-row ``currency``.

    Dimension metrics forward ``value``; the person report filters to
    ``value`` when set and drops the reserved ``"user"`` pseudo-participant
    (the personal share, already shown as ``amount``). Metrics without a
    dispatch branch raise ``ValueError``.
    """
    if request.metric == "summary":
        rows = await get_report_summary(request.start, request.end)
        if not rows:
            return {"income": 0, "expenses": 0, "shared_total": 0, "net": 0}
        return dict(rows[0])
    if request.metric in _DIMENSION_DB_METRICS:
        rows = await get_report_by_dimension(
            request.metric, request.start, request.end, request.value
        )
        return _rows_result(rows)
    if request.metric == "person":
        rows = await get_report_person(request.start, request.end)
        if request.value is not None:
            rows = [row for row in rows if row.get("label") == request.value]
        rows = [row for row in rows if row.get("label") != "user"]
        return _rows_result(rows)
    func_name = PERIOD_ONLY_REPORTS.get(request.metric)
    if func_name is None:
        raise ValueError(f"Unsupported report metric: {request.metric}")
    return _rows_result(await globals()[func_name](request.start, request.end))


def _rows_result(rows) -> dict[str, Any]:
    return {"rows": [dict(row) for row in rows]}


def format_report(request: ReportRequest, result: dict[str, Any]) -> str:
    """Format a report result as a Spanish multi-line string.

    Stable result keys per metric:
    - summary: ``income``, ``expenses``, ``shared_total``, ``net`` (plus optional ``currency``).
    - dimension and advanced metrics: ``rows`` with ``label`` plus the metric
      amount field (``total`` for dimensions, ``amount`` for advanced) and
      optional per-row ``currency``.
    - shared: rows with ``label``, ``amount``, and ``total_amount``.
    """
    metric = request.metric
    label = METRIC_LABELS[metric]
    currency = result.get("currency")
    if metric == "summary":
        return _format_summary(result, currency)
    rows = result.get("rows") or []
    lines = [f"*{label}*"]
    if not rows:
        lines.append("No hay transacciones.")
        return "\n".join(lines)
    for row in rows:
        lines.append(_format_row_line(metric, row, currency))
    return "\n".join(lines)


def _format_summary(result: dict[str, Any], currency: str | None) -> str:
    lines = ["*Resumen*"]
    for key, label in (
        ("income", "Ingresos personales"),
        ("expenses", "Gastos personales"),
        ("shared_total", "Total compartido"),
        ("net", "Flujo neto"),
    ):
        lines.append(f"{label}: {_format_amount(result.get(key, 0), currency)}")
    return "\n".join(lines)


def _format_row_line(metric: ReportMetric, row: dict[str, Any], default_currency) -> str:
    currency = row.get("currency") or default_currency
    label = str(row.get("label") or "—")
    if metric == "shared":
        amount = _format_amount(row.get("amount", 0), currency)
        total = _format_amount(row.get("total_amount", row.get("amount", 0)), currency)
        return f"{label}: {amount} (total {total})"
    amount = _format_amount(_row_amount(metric, row), currency)
    detail = _row_detail(metric, row)
    if detail:
        return f"{label} ({detail}): {amount}"
    return f"{label}: {amount}"


def _row_amount(metric: ReportMetric, row: dict[str, Any]):
    if metric in DIMENSION_METRICS:
        return row.get("total", 0)
    return row.get("amount", 0)


def _row_detail(metric: ReportMetric, row: dict[str, Any]) -> str:
    if metric == "installments":
        number = row.get("installment_number")
        if number is not None:
            total = row.get("installment_total", "?")
            return f"cuota {number}/{total}"
    if metric == "recurrence":
        recurrence = row.get("recurrence")
        if recurrence:
            return f"cada {recurrence}"
    if metric == "due_dates":
        due_date = row.get("due_date")
        if due_date:
            return f"vence {due_date}"
    return ""


def _format_amount(value: Any, currency: str | None = None) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = f"{value}"
    if currency:
        text = f"{text} {currency}"
    return text
