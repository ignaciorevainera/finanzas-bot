"""Report request contract and pure Spanish report formatting.

Defines the validated ``ReportRequest`` value object and ``format_report``,
a deterministic string formatter with stable keys per metric. The module is
deliberately free of database and AI imports: ``run_report`` and
``parse_report_request`` arrive in later tasks.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

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
