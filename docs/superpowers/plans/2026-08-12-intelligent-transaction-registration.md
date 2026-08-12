# Intelligent Transaction Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register complete personal-finance transactions from text or audio with Spanish normalized values, explicit missing-field questions, shared amounts, advanced context, and iterative confirmation.

**Architecture:** Introduce a pure transaction contract module for normalization, defaults, required-field validation, and context merging. Keep persistence in `app/database.py`, extraction in `app/gemini_ai.py`, and Telegram state transitions in `app/handlers.py`. Both text and audio parsers return the same normalized dictionary before handlers process it.

**Tech Stack:** Python 3.10+, `pytest`, `pytest-asyncio`, `python-telegram-bot`, Google `google-genai`, PostgreSQL 18 on Neon, `asyncpg`.

## Global Constraints

- All source code artifacts (variables, functions, DB schemas, attributes) must be in English.
- Bot responses remain in Spanish; stored human-readable values use Spanish and capitalization.
- `currency` stores ISO codes such as `ARS` without translation.
- `amount` stores the user’s personal share; `total_amount` stores the complete movement amount.
- Personal statistics use `amount`.
- Missing `type`, `amount`, `category`, `description`, or `payment_method` must trigger a question before confirmation.
- Defaults are `ARS`, current timestamp, and `Completado` for currency, date, and status.
- Ambiguous values are not inferred.
- Explicit context can replace an earlier value; ambiguous context preserves the earlier value.
- Shared expenses and shared income require exact distribution; never divide automatically.
- `Agregar más` repeats in a loop until `Aceptar` or `Cancelar`.
- Do not add new runtime dependencies.
- Every task ends with focused tests and a separate commit.

---

## File Map

- Create `app/transaction_schema.py`: canonical field names, Spanish vocabularies, defaults, normalization, missing-field detection, and context merge.
- Modify `app/gemini_ai.py`: extraction prompt and shared parser post-processing.
- Modify `app/database.py`: schema additions, Spanish constraints, idempotent startup migration, and full insert parameter mapping.
- Modify `app/handlers.py`: missing-field prompts, advanced confirmation, `Agregar más` loop, and callback state transitions.
- Create `tests/test_transaction_schema.py`: pure contract and normalization tests.
- Modify `tests/test_gemini_ai_prompt.py`: text/audio extraction contract tests.
- Modify `tests/test_database.py`: migration and insert mapping tests.
- Modify `tests/test_handlers_payment.py`: confirmation and state-flow tests.
- Modify `README.md`: final schema and registration behavior.

## Canonical Interfaces

```python
from typing import Any

TransactionData = dict[str, Any]

def normalize_transaction(data: TransactionData) -> TransactionData: ...
def apply_transaction_defaults(data: TransactionData, *, now: datetime) -> TransactionData: ...
def get_missing_transaction_fields(data: TransactionData) -> list[str]: ...
def merge_transaction_context(
    current: TransactionData,
    additions: TransactionData,
) -> TransactionData: ...
```

`normalize_transaction` returns Spanish values but does not invent missing required values. `apply_transaction_defaults` fills only currency, date, status, and `total_amount` when safe. `get_missing_transaction_fields` returns fields in this order: `type`, `amount`, `category`, `description`, `payment_method`. `merge_transaction_context` replaces only explicit non-null additions and retains previous values for null or ambiguous additions.

### Task 1: Transaction Contract And Normalization

**Files:**
- Create: `app/transaction_schema.py`
- Create: `tests/test_transaction_schema.py`

**Interfaces:**
- Consumes: raw Gemini dictionaries with English aliases or Spanish values.
- Produces: `normalize_transaction`, `apply_transaction_defaults`, `get_missing_transaction_fields`, and `merge_transaction_context` for DB and handlers.

- [ ] **Step 1: Write failing tests for canonical vocabularies and defaults**

```python
from datetime import datetime, timezone

from app.transaction_schema import (
    apply_transaction_defaults,
    get_missing_transaction_fields,
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
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `venv\Scripts\pytest.exe tests/test_transaction_schema.py -q`

Expected: FAIL because `app.transaction_schema` does not exist.

- [ ] **Step 3: Implement vocabulary constants and pure helpers**

Implement Spanish maps for `type`, the approved 16 base categories, approved payment methods, and statuses. Preserve custom categories and custom tags by capitalizing their first letter. Treat empty strings and `None` as missing. Preserve ISO currency codes. Use `datetime` values unchanged and parse ISO date strings only in the DB boundary.

```python
REQUIRED_TRANSACTION_FIELDS = (
    "type", "amount", "category", "description", "payment_method",
)

DEFAULT_TRANSACTION_VALUES = {
    "currency": "ARS",
    "status": "Completado",
}
```

- [ ] **Step 4: Add shared-context merge tests**

```python
from app.transaction_schema import merge_transaction_context


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
```

- [ ] **Step 5: Implement merge semantics and run tests**

Merge only non-null additions. Merge tags as an ordered, case-insensitive union. Merge `notes` by appending a separator when both values are explicit. Replace scalar fields only when additions contain non-null values. Run: `venv\Scripts\pytest.exe tests/test_transaction_schema.py -q`. Expected: PASS.

- [ ] **Step 6: Commit contract**

```bash
git add app/transaction_schema.py tests/test_transaction_schema.py
git commit -m "feat: add transaction data contract"
```

### Task 2: Database Schema And Persistence

**Files:**
- Modify: `app/database.py`
- Modify: `tests/test_database.py`

**Interfaces:**
- Consumes: normalized `TransactionData` from `app.transaction_schema`.
- Produces: `insert_transaction(data: dict)`, schema startup migrations, and `INSERT_SQL` supporting all canonical fields.

- [ ] **Step 1: Write failing migration and insert tests**

```python
def test_create_table_contains_advanced_transaction_fields():
    for field in (
        "total_amount", "due_date", "recurrence", "installment_number",
        "installment_total", "participants", "split_details",
        "transfer_details", "package_details", "related_transaction_id",
    ):
        assert field in database.CREATE_TABLE_SQL


@pytest.mark.asyncio
async def test_insert_transaction_passes_advanced_fields_in_stable_order():
    mock_pool = MagicMock()
    mock_pool.fetchrow = AsyncMock(return_value={"id": "fake-uuid"})
    database.pool = mock_pool
    data = {
        "type": "Gasto", "amount": 30000, "total_amount": 120000,
        "currency": "ARS", "category": "Comida", "description": "Cena",
        "merchant": "Restaurante", "payment_method": "Efectivo",
        "status": "Completado", "tags": ["Familia"], "location": "Centro",
        "notes": "Con Viole", "transaction_date": "2026-08-12T20:00:00+00:00",
        "due_date": None, "recurrence": None, "installment_number": None,
        "installment_total": None, "participants": ["Viole"],
        "split_details": {"user": 30000, "Viole": 90000},
        "transfer_details": None, "package_details": None,
        "related_transaction_id": None,
    }

    await database.insert_transaction(data)
    args = mock_pool.fetchrow.call_args.args
    assert args[0] == database.INSERT_SQL
    assert args[2] == 120000
    assert args[18] == ["Viole"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `venv\Scripts\pytest.exe tests/test_database.py -q`

Expected: FAIL because schema and insert SQL lack new fields.

- [ ] **Step 3: Extend table definition and idempotent startup migrations**

Add `total_amount DECIMAL(12, 2) NOT NULL`, advanced nullable columns, `participants TEXT[]`, and JSONB columns. Use `amount` as personal share. For a fresh database, set `total_amount` default equal to `amount` through insert logic rather than a database expression. Replace English checks with Spanish checks for `type`, `status`, and `payment_method`; use `ALTER ... ADD COLUMN IF NOT EXISTS` for existing deployments. Keep startup SQL order deterministic.

- [ ] **Step 4: Extend insert SQL and normalize date/JSON boundaries**

Add every field to one explicit insert column list, in this parameter order: `type`, `amount`, `total_amount`, `currency`, `category`, `description`, `merchant`, `payment_method`, `status`, `tags`, `location`, `notes`, `transaction_date`, `due_date`, `recurrence`, `installment_number`, `installment_total`, `participants`, `split_details`, `transfer_details`, `package_details`, `related_transaction_id`, `original_message`. Convert ISO strings to timezone-aware `datetime`, pass arrays as Python lists, and pass JSON structures as dictionaries accepted by `asyncpg`. Use `data.get("total_amount", data["amount"])`. Preserve existing `original_message` behavior.

- [ ] **Step 5: Run focused and full database tests**

Run: `venv\Scripts\pytest.exe tests/test_database.py -q`

Expected: PASS. Then run: `venv\Scripts\pytest.exe tests/test_database.py tests/test_handlers_payment.py -q`. Expected: PASS.

- [ ] **Step 6: Commit persistence**

```bash
git add app/database.py tests/test_database.py
git commit -m "feat: persist complete transaction context"
```

### Task 3: Gemini Extraction Contract

**Files:**
- Modify: `app/gemini_ai.py`
- Modify: `tests/test_gemini_ai_prompt.py`

**Interfaces:**
- Consumes: text or audio plus optional current datetime.
- Produces: `parse_transaction_from_text(...) -> dict | None` and `parse_transaction_from_audio(...) -> dict | None` returning the same keys and Spanish canonical values.

- [ ] **Step 1: Write failing prompt and post-processing tests**

```python
@pytest.mark.asyncio
async def test_parser_returns_spanish_transaction_contract(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"type":"expense","amount":30000,"total_amount":120000,'
        '"category":"food","description":"cena","payment_method":"cash",'
        '"participants":["Viole"],"split_details":{"user":30000,"Viole":90000}}'
    ))

    result = await parse_transaction_from_text("de 120000 yo puse 30000 para cenar con Viole")

    assert result["type"] == "Gasto"
    assert result["category"] == "Comida"
    assert result["description"] == "Cena"
    assert result["payment_method"] == "Efectivo"
    assert result["amount"] == 30000
    assert result["total_amount"] == 120000


@pytest.mark.asyncio
async def test_audio_and_text_use_same_default_keys(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(return_value=make_response(
        '{"type":"income","amount":1000,"category":"salary",'
        '"description":"sueldo","payment_method":"transfer"}'
    ))

    result = await parse_transaction_from_audio(b"audio", "audio/ogg")

    assert set(("currency", "tags", "transaction_date", "status", "total_amount")) <= result.keys()
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `venv\Scripts\pytest.exe tests/test_gemini_ai_prompt.py -q`

Expected: FAIL because current prompt and post-processing return English values and omit advanced defaults.

- [ ] **Step 3: Replace extraction schema instructions**

Update `SYSTEM_PROMPT` to define canonical Spanish enums, title-only `description`, structured advanced fields, exact-share requirement, and `notes` as residual context. Tell Gemini to return `null` for absent explicit values, preserve custom categories, generate tags plus explicit tags, and return `{"error":"invalid transaction"}` for non-transactions. Do not ask Gemini to generate database SQL.

- [ ] **Step 4: Centralize parser post-processing**

Create private `_finalize_transaction_data(data: dict, current_datetime: datetime | str | None) -> dict | None` and call it from text and audio paths. It must reject error responses, call `normalize_transaction`, apply defaults with formatted datetime, and return identical key coverage for both input modes.

- [ ] **Step 5: Run all AI tests**

Run: `venv\Scripts\pytest.exe tests/test_gemini_ai_prompt.py -q`. Expected: PASS.

- [ ] **Step 6: Commit extraction**

```bash
git add app/gemini_ai.py tests/test_gemini_ai_prompt.py
git commit -m "feat: extract contextual transactions"
```

### Task 4: Missing-Field Questions And Confirmation

**Files:**
- Modify: `app/handlers.py`
- Modify: `tests/test_handlers_payment.py`

**Interfaces:**
- Consumes: finalized `TransactionData`, `get_missing_transaction_fields`, and `merge_transaction_context`.
- Produces: `handle_parsed_data`, `_build_confirm_text`, `_send_confirm_message`, and callback states `pick_missing`, `confirm`, `add_context`.

- [ ] **Step 1: Write failing handler tests for required questions and complete confirmation**

```python
@pytest.mark.asyncio
async def test_handle_parsed_data_questions_for_first_missing_required_field(update, context):
    data = {"amount": 500, "currency": "ARS", "status": "Completado"}

    await handle_parsed_data(update, context, data)

    assert pending_transactions[update.effective_chat.id]["action"] == "pick_missing"
    update.message.reply_text.assert_awaited_once()
    assert "tipo" in update.message.reply_text.await_args.args[0].lower()


def test_confirmation_shows_personal_and_total_amounts():
    text = _build_confirm_text({
        "type": "Gasto", "amount": 30000, "total_amount": 120000,
        "currency": "ARS", "category": "Comida", "description": "Cena",
        "payment_method": "Efectivo", "participants": ["Viole"],
        "split_details": {"user": 30000, "Viole": 90000},
    })

    assert "Monto personal: $30000 ARS" in text
    assert "Monto total: $120000 ARS" in text
    assert "Viole" in text
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `venv\Scripts\pytest.exe tests/test_handlers_payment.py -q`

Expected: FAIL because handler only asks for payment/date and confirmation omits advanced fields.

- [ ] **Step 3: Implement ordered missing-field prompts**

Add Spanish prompt labels and a pending state containing `missing_fields`, `missing_index`, and `data`. Add a callback or message path that stores the user’s answer in the current field, normalizes it, advances to next missing field, and confirms when list is empty. Keep existing date keyboard only for defaultable date flow; defaults should normally prevent date questions.

- [ ] **Step 4: Implement exact shared-distribution questions**

When `participants` or a shared amount is present without `split_details`, set state `pick_split` and ask for exact distribution. Parse the reply through a small structured Gemini helper or the existing transaction parser, require every participant plus user share, verify sum equals `total_amount`, and repeat question on invalid sum. Never silently equal-split.

- [ ] **Step 5: Expand confirmation text and keyboard**

Render all non-null basic and advanced fields. Add callback `add_context` beside `confirm` and `cancel`. Keep formatting Spanish and make `amount` visibly personal so user understands reporting semantics.

- [ ] **Step 6: Run focused tests**

Run: `venv\Scripts\pytest.exe tests/test_handlers_payment.py tests/test_gemini_ai_prompt.py tests/test_database.py -q`. Expected: PASS.

- [ ] **Step 7: Commit confirmation flow**

```bash
git add app/handlers.py tests/test_handlers_payment.py
git commit -m "feat: ask missing transaction details"
```

### Task 5: Iterative Add-Context Loop

**Files:**
- Modify: `app/handlers.py`
- Modify: `tests/test_handlers_payment.py`

**Interfaces:**
- Consumes: `merge_transaction_context(current, additions)` and pending `confirm` state.
- Produces: repeatable `add_context` message state ending only in `confirm` or `cancel`.

- [ ] **Step 1: Write failing loop tests**

```python
@pytest.mark.asyncio
async def test_add_context_can_repeat_until_confirm(update, context, monkeypatch):
    chat_id = update.effective_chat.id
    pending_transactions[chat_id] = {
        "action": "confirm",
        "data": {"description": "Supermercado", "notes": None},
    }
    update.callback_query.data = "add_context"
    await callback_handler(update, context)
    assert pending_transactions[chat_id]["action"] == "add_context"

    monkeypatch.setattr("app.handlers.parse_transaction_from_text", AsyncMock(
        return_value={"location": "Palermo", "notes": None}
    ))
    update.message.text = "Fue en Palermo"
    await message_handler(update, context)
    assert pending_transactions[chat_id]["action"] == "confirm"
    assert pending_transactions[chat_id]["data"]["location"] == "Palermo"


@pytest.mark.asyncio
async def test_cancel_discards_pending_context(update, context):
    chat_id = update.effective_chat.id
    pending_transactions[chat_id] = {"action": "confirm", "data": {"description": "Cena"}}
    update.callback_query.data = "cancel"

    await callback_handler(update, context)

    assert chat_id not in pending_transactions
```

- [ ] **Step 2: Run tests and verify failure**

Run: `venv\Scripts\pytest.exe tests/test_handlers_payment.py -q`. Expected: FAIL because `add_context` callback is not implemented.

- [ ] **Step 3: Implement loop state**

`add_context` callback changes state to `add_context` without deleting data. The next text message parses only additions, merges explicit values, validates shared distribution if newly introduced, changes state back to `confirm`, and sends updated confirmation. Any later `add_context` callback repeats same transition. `confirm` persists and removes state; `cancel` removes state.

- [ ] **Step 4: Test full suite and callback regressions**

Run: `venv\Scripts\pytest.exe -q`. Expected: PASS with existing payment/date/delete tests retained.

- [ ] **Step 5: Commit loop**

```bash
git add app/handlers.py tests/test_handlers_payment.py
git commit -m "feat: support iterative transaction context"
```

### Task 6: Documentation And Integration Verification

**Files:**
- Modify: `README.md`
- Modify: `tests/test_database.py`
- Modify: `tests/test_gemini_ai_prompt.py`

**Interfaces:**
- Consumes: completed transaction contract, schema, parser, and handler flow.
- Produces: documented schema and final regression evidence for Plan B.

- [ ] **Step 1: Write documentation assertions for canonical schema**

```python
def test_schema_documentation_mentions_personal_and_total_amounts():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "total_amount" in readme
    assert "amount" in readme
    assert "Agregar más" in readme
```

- [ ] **Step 2: Update README schema and behavior**

Document Spanish stored values, required fields, defaults, `amount` versus `total_amount`, JSONB fields, exact shared distribution, and the repeating `Agregar más` loop. Remove stale English-only schema claims.

- [ ] **Step 3: Run final verification**

Run: `venv\Scripts\pytest.exe -q`. Expected: PASS.

Run: `git diff --check`. Expected: no output.

Run: `git status --short`. Expected: only intended Plan A files or clean after commit.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md tests/test_database.py tests/test_gemini_ai_prompt.py
git commit -m "docs: describe contextual transaction flow"
```

## Plan A Completion Gate

Proceed to Plan B only when full test suite passes, startup migration executes on a disposable Neon branch, a sample normal transaction stores equal `amount` and `total_amount`, and a sample shared transaction stores exact personal distribution.
