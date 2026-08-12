# Finance Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reliable personal-finance reports available through existing commands, new report commands, and natural-language questions without allowing AI to generate SQL.

**Architecture:** Put parameterized SQL in `app/database.py` and report aggregation/formatting in a new `app/reporting.py`. Add a constrained Gemini intent parser that returns a small typed report request; handlers route both commands and natural language through the same reporting service. Personal totals use `amount`; shared reports additionally expose `total_amount`.

**Tech Stack:** Python 3.10+, `pytest`, `pytest-asyncio`, `python-telegram-bot`, Google `google-genai`, PostgreSQL 18 on Neon, `asyncpg`.

## Global Constraints

- Plan B starts only after Plan A transaction contract and schema are complete.
- All SQL is static and parameterized; Gemini never generates SQL.
- All source code artifacts (variables, functions, DB schemas, attributes) must be in English.
- Bot responses remain in Spanish; stored human-readable values use Spanish and capitalization.
- Personal statistics use `amount`.
- Shared reports show both `amount` and `total_amount`.
- Date filters use timezone-aware datetimes and explicit half-open ranges `[start, end)`.
- Unsupported report requests return a Spanish explanation; no unbounded fallback query runs.
- Do not add new runtime dependencies.
- Every task ends with focused tests and a separate commit.

---

## File Map

- Create `app/reporting.py`: report request contract, report service, and Spanish presentation helpers.
- Modify `app/gemini_ai.py`: constrained natural-language report intent parser.
- Modify `app/database.py`: parameterized report queries and DB functions.
- Modify `app/handlers.py`: report commands and natural-language routing.
- Create `tests/test_reporting.py`: pure report request and formatting tests.
- Modify `tests/test_database.py`: query parameter and result-shape tests.
- Modify `tests/test_gemini_ai_prompt.py`: report intent parser tests.
- Modify `tests/test_handlers_payment.py` or create `tests/test_handlers_reports.py`: Telegram command and natural-language route tests.
- Modify `README.md`: report commands and natural-language examples.

## Canonical Interfaces

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

ReportMetric = Literal[
    "summary", "category", "merchant", "payment_method", "location",
    "person", "tag", "installments", "recurrence", "due_dates",
    "transfers", "refunds", "packages", "shared",
]

@dataclass(frozen=True)
class ReportRequest:
    metric: ReportMetric
    start: datetime
    end: datetime
    group_by: str | None = None
    value: str | None = None

async def run_report(request: ReportRequest) -> dict[str, Any]: ...
def format_report(request: ReportRequest, result: dict[str, Any]) -> str: ...
async def parse_report_request(text: str, current_datetime: datetime | str | None = None) -> ReportRequest | None: ...
```

`start` is inclusive and `end` exclusive. `value` carries an optional category, merchant, location, person, or tag filter. `run_report` returns stable keys per metric and never returns raw DB records to handlers.

### Task 1: Report Request Contract And Formatting

**Files:**
- Create: `app/reporting.py`
- Create: `tests/test_reporting.py`

**Interfaces:**
- Consumes: validated `ReportRequest` and result dictionaries from DB functions.
- Produces: `ReportRequest`, `run_report`, and `format_report` contracts for handlers.

- [ ] **Step 1: Write failing tests for request validation and Spanish output**

```python
from datetime import datetime, timezone

from app.reporting import ReportRequest, format_report


def test_report_request_keeps_half_open_timezone_aware_period():
    request = ReportRequest(
        metric="category",
        start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        end=datetime(2026, 9, 1, tzinfo=timezone.utc),
        value="Comida",
    )

    assert request.start < request.end
    assert request.value == "Comida"


def test_format_summary_uses_personal_amount_and_shows_shared_total():
    text = format_report(
        ReportRequest("summary", datetime(2026, 8, 1, tzinfo=timezone.utc),
                      datetime(2026, 9, 1, tzinfo=timezone.utc)),
        {"income": 150000, "expenses": 30000, "shared_total": 120000, "net": 120000},
    )

    assert "Ingresos personales" in text
    assert "Gastos personales" in text
    assert "Total compartido" in text
    assert "Flujo neto" in text
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `venv\Scripts\pytest.exe tests/test_reporting.py -q`

Expected: FAIL because `app.reporting` does not exist.

- [ ] **Step 3: Implement immutable request and stable result formatting**

Define `ReportMetric`, `ReportRequest`, Spanish metric labels, currency formatting, and one formatter branch per metric. Reject naive datetimes with `ValueError`; reject `end <= start`. Format amounts using stored currency and avoid assuming every result is ARS.

- [ ] **Step 4: Add tests for every supported metric label**

```python
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
        text = format_report(
            ReportRequest(metric, datetime(2026, 8, 1, tzinfo=timezone.utc),
                          datetime(2026, 9, 1, tzinfo=timezone.utc)),
            {"rows": []},
        )
        assert label in text
```

- [ ] **Step 5: Run tests and commit contract**

Run: `venv\Scripts\pytest.exe tests/test_reporting.py -q`. Expected: PASS.

```bash
git add app/reporting.py tests/test_reporting.py
git commit -m "feat: add report request contract"
```

### Task 2: Parameterized Database Reports

**Files:**
- Modify: `app/database.py`
- Modify: `tests/test_database.py`

**Interfaces:**
- Consumes: `start: datetime`, `end: datetime`, optional `value: str`.
- Produces: async DB functions `get_report_summary`, `get_report_by_dimension`, `get_report_shared`, and advanced report functions used by `run_report`.

- [ ] **Step 1: Write failing tests for SQL parameters and personal-share semantics**

```python
@pytest.mark.asyncio
async def test_get_report_by_dimension_uses_amount_and_date_range():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_by_dimension("category", start, end, None)

    sql, *params = mock_pool.fetch.call_args.args
    assert "SUM(amount)" in sql
    assert "transaction_date >= $1" in sql
    assert params == [start, end]


@pytest.mark.asyncio
async def test_get_report_shared_returns_personal_and_total_amounts():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    await database.get_report_shared(
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    sql = mock_pool.fetch.call_args.args[0]
    assert "SUM(amount)" in sql
    assert "SUM(total_amount)" in sql
    assert "amount < total_amount" in sql
```

- [ ] **Step 2: Run tests and verify failure**

Run: `venv\Scripts\pytest.exe tests/test_database.py -q`. Expected: FAIL because report functions do not exist.

- [ ] **Step 3: Implement fixed dimension query map**

Use a private allowlisted mapping from dimensions to SQL expressions: category, merchant, payment_method, location, and tags. Never interpolate user input as SQL identifiers. Build optional value filters only from fixed branches and pass values as parameters. Every query filters `status <> 'Cancelado'` and uses half-open date bounds.

- [ ] **Step 4: Implement summary and shared queries**

Summary must return personal income, personal expenses, and net. Shared query returns rows or totals containing both `SUM(amount)` and `SUM(total_amount)` where `amount < total_amount`. Preserve currency grouping; never add ARS and USD together.

- [ ] **Step 5: Implement advanced report queries**

Add parameterized queries for installment rows, recurring rows, due dates, transfer JSONB fields, related refunds, package JSONB fields, and participant/split JSONB data. Use PostgreSQL JSONB operators only in static SQL. Return plain dict-like records with stable aliases consumed by `app.reporting`.

- [ ] **Step 6: Run database tests and commit**

Run: `venv\Scripts\pytest.exe tests/test_database.py -q`. Expected: PASS.

```bash
git add app/database.py tests/test_database.py
git commit -m "feat: add parameterized finance reports"
```

### Task 3: Report Service

**Files:**
- Modify: `app/reporting.py`
- Modify: `tests/test_reporting.py`

**Interfaces:**
- Consumes: `ReportRequest` and DB functions from Task 2.
- Produces: `async def run_report(request: ReportRequest) -> dict[str, Any]` with one dispatch branch per `ReportMetric`.

- [ ] **Step 1: Write failing dispatch tests**

```python
@pytest.mark.asyncio
async def test_run_report_dispatches_category_request(monkeypatch):
    expected = {"rows": [{"label": "Comida", "total": 30000}]}
    mocked = AsyncMock(return_value=expected)
    monkeypatch.setattr("app.reporting.get_report_by_dimension", mocked)
    request = ReportRequest(
        "category",
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    result = await run_report(request)

    assert result == expected
    mocked.assert_awaited_once_with("category", request.start, request.end, None)
```

- [ ] **Step 2: Run test and verify failure**

Run: `venv\Scripts\pytest.exe tests/test_reporting.py::test_run_report_dispatches_category_request -q`. Expected: FAIL because `run_report` lacks dispatch.

- [ ] **Step 3: Implement explicit metric dispatch**

Map each `ReportMetric` to one known DB function. Keep request period and filter unchanged. Raise `ValueError` for impossible metrics instead of silently running summary. Do not duplicate SQL in service.

- [ ] **Step 4: Add empty and multi-currency formatting tests**

```python
def test_empty_report_explains_no_transactions():
    request = ReportRequest("merchant", datetime(2026, 8, 1, tzinfo=timezone.utc),
                            datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert "No hay transacciones" in format_report(request, {"rows": []})
```

- [ ] **Step 5: Run service tests and commit**

Run: `venv\Scripts\pytest.exe tests/test_reporting.py -q`. Expected: PASS.

```bash
git add app/reporting.py tests/test_reporting.py
git commit -m "feat: route finance report requests"
```

### Task 4: Natural-Language Report Intent

**Files:**
- Modify: `app/gemini_ai.py`
- Modify: `tests/test_gemini_ai_prompt.py`

**Interfaces:**
- Consumes: Spanish user report question and current datetime.
- Produces: `parse_report_request(...) -> ReportRequest | None` with allowed metric, explicit date range, optional filter, or `None` for unsupported requests.

- [ ] **Step 1: Write failing intent tests**

```python
@pytest.mark.asyncio
async def test_parse_report_request_extracts_category_and_month(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"metric":"category","start":"2026-08-01T00:00:00+00:00",'
        '"end":"2026-09-01T00:00:00+00:00","value":"Comida"}'
    ))

    result = await parse_report_request("¿Cuánto gasté en comida este mes?",
                                       current_datetime="2026-08-12 12:00:00")

    assert result.metric == "category"
    assert result.value == "Comida"
    assert result.start.isoformat() == "2026-08-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_parse_report_request_returns_none_for_non_report(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"error":"unsupported report"}'
    ))

    assert await parse_report_request("¿Qué debería comprar?", current_datetime="2026-08-12 12:00:00") is None
```

- [ ] **Step 2: Run tests and verify failure**

Run: `venv\Scripts\pytest.exe tests/test_gemini_ai_prompt.py -q`. Expected: FAIL because parser does not exist.

- [ ] **Step 3: Add constrained report prompt**

Define only approved metric literals, ISO start/end timestamps, optional `group_by` and `value`, and an error response for non-report questions. Instruct model to interpret Spanish date phrases relative to injected current datetime. Do not expose SQL, table names, or database implementation details in prompt.

- [ ] **Step 4: Implement parser validation**

Parse JSON through existing `clean_json_text`, reject unknown metrics, missing dates, naive datetimes, inverted periods, and error objects. Normalize category/payment/person/tag filter capitalization using the transaction schema helper. Return `ReportRequest` only after validation.

- [ ] **Step 5: Run AI tests and commit**

Run: `venv\Scripts\pytest.exe tests/test_gemini_ai_prompt.py -q`. Expected: PASS.

```bash
git add app/gemini_ai.py tests/test_gemini_ai_prompt.py
git commit -m "feat: parse natural language report intents"
```

### Task 5: Telegram Commands And Natural-Language Routing

**Files:**
- Create: `tests/test_handlers_reports.py`
- Modify: `app/handlers.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: `ReportRequest`, `parse_report_request`, `run_report`, and `format_report`.
- Produces: `/summary`, `/report`, and natural-language report routing through one `send_report` helper.

- [ ] **Step 1: Write failing route tests**

```python
@pytest.mark.asyncio
async def test_report_command_uses_same_service_as_natural_language(update, context, monkeypatch):
    result = {"income": 1000, "expenses": 300, "net": 700}
    monkeypatch.setattr("app.handlers.run_report", AsyncMock(return_value=result))
    monkeypatch.setattr("app.handlers.format_report", lambda request, data: "Reporte listo")

    await report_handler(update, context)

    update.message.reply_text.assert_awaited_once_with("Reporte listo")


@pytest.mark.asyncio
async def test_natural_language_report_rejects_unsupported_intent(update, context, monkeypatch):
    monkeypatch.setattr("app.handlers.parse_report_request", AsyncMock(return_value=None))
    update.message.text = "¿Qué inversión debería hacer?"

    await message_handler(update, context)

    assert "reporte" in update.message.reply_text.await_args.args[0].lower()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `venv\Scripts\pytest.exe tests/test_handlers_reports.py -q`. Expected: FAIL because report handler and routing do not exist.

- [ ] **Step 3: Implement command parsing**

Add `/report` with metric aliases and optional period syntax, plus `/summary` routing to `ReportRequest("summary", current_month_start, next_month_start)`. Use a small parser for fixed command forms; reject unknown syntax with Spanish usage text. Register command handlers in `main.py` using existing application patterns.

- [ ] **Step 4: Implement shared report sender**

Create `async def send_report(update, request) -> None` that calls `run_report`, formats result, and replies. Both `/report` and natural-language messages call it. Catch only expected `ValueError`/unsupported intent errors and return user-facing Spanish guidance; log unexpected errors and return generic failure text.

- [ ] **Step 5: Route natural-language questions without breaking pending transactions**

When chat has pending transaction state, preserve current transaction flow. Otherwise call `parse_report_request` for messages that appear to ask for financial analysis; send a report when parser returns a request. Keep invalid transaction handling unchanged for messages that are neither report requests nor valid transactions.

- [ ] **Step 6: Run handler tests and commit**

Run: `venv\Scripts\pytest.exe tests/test_handlers_reports.py tests/test_handlers_payment.py -q`. Expected: PASS.

```bash
git add app/handlers.py main.py tests/test_handlers_reports.py
git commit -m "feat: expose finance reports in Telegram"
```

### Task 6: README And End-To-End Verification

**Files:**
- Modify: `README.md`
- Modify: `tests/test_reporting.py`
- Modify: `tests/test_handlers_reports.py`

**Interfaces:**
- Consumes: completed DB queries, report service, intent parser, and Telegram routes.
- Produces: documented commands/examples and final regression evidence.

- [ ] **Step 1: Write report documentation assertions**

```python
def test_readme_documents_command_and_natural_language_reports():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "/report" in readme
    assert "¿Cuánto gasté en comida este mes?" in readme
    assert "amount" in readme
    assert "total_amount" in readme
```

- [ ] **Step 2: Update README**

Document `/summary`, `/report`, supported report dimensions, natural-language examples, half-open date behavior, personal-share semantics, and the rule that AI returns intent rather than SQL.

- [ ] **Step 3: Add integration-shaped service test**

```python
@pytest.mark.asyncio
async def test_category_report_formats_database_rows(monkeypatch):
    monkeypatch.setattr("app.reporting.get_report_by_dimension", AsyncMock(
        return_value={"rows": [{"label": "Comida", "total": 30000, "currency": "ARS"}]}
    ))
    request = ReportRequest("category", datetime(2026, 8, 1, tzinfo=timezone.utc),
                            datetime(2026, 9, 1, tzinfo=timezone.utc))

    text = format_report(request, await run_report(request))

    assert "Comida" in text
    assert "30000" in text
```

- [ ] **Step 4: Run complete verification**

Run: `venv\Scripts\pytest.exe -q`. Expected: PASS.

Run: `git diff --check`. Expected: no output.

Run: `git status --short`. Expected: clean after commit.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md tests/test_reporting.py tests/test_handlers_reports.py
git commit -m "docs: describe finance reports"
```

## Plan B Completion Gate

Verify report queries on a disposable Neon branch with normal, shared, installment, recurring, transfer, refund, and package fixtures. Confirm personal reports sum `amount`, shared reports expose `total_amount`, natural-language requests produce only allowlisted `ReportRequest` values, and unsupported requests execute no SQL.
