# Improve Bot Transaction Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve transaction detection UX by displaying categories in Spanish, interactively asking for the payment method when missing, and capturing the concept/title of each transaction (what was bought or received).

**Architecture:** The Gemini system prompt is updated to return `payment_method: null` when ambiguous and to extract a `description` field (the item/concept of the transaction, e.g. "jugo", "almuerzo"). A new `description VARCHAR(255)` column is added to the `transactions` table via `ALTER TABLE IF NOT EXISTS`. The handler, INSERT query, and confirmation card are updated to include `description`. A static mapping dict in `handlers.py` translates English DB category strings to Spanish display labels.

**Tech Stack:** Python 3.10+, `python-telegram-bot` (async), `google-genai` SDK, `app/gemini_ai.py`, `app/handlers.py`, `app/database.py`

## Global Constraints

- Codebase language: all identifiers, variables, DB values must remain in English.
- Bot response language: Spanish only.
- No new dependencies.
- Do not add comments to code unless explicitly requested.
- DB column `payment_method` continues to store English values (`"cash"`, `"debit card"`, `"credit card"`, `"transfer"`, `"other"`).
- DB column `category` continues to store English values (`"food"`, `"transport"`, etc.).
- Follow the file and folder conventions already present in the project.

---

### Task 1: Update system prompt so payment_method defaults to null when ambiguous

**Files:**
- Modify: `app/gemini_ai.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `parse_transaction_from_text(text: str) -> dict | None` and `parse_transaction_from_audio(audio_bytes: bytes, mime_type: str) -> dict | None` — same signatures, but returned dict may now have `payment_method: None` when not inferable.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gemini_ai_prompt.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def mock_client():
    with patch("app.gemini_ai.client") as mock:
        yield mock


def make_response(json_text: str):
    resp = MagicMock()
    resp.text = json_text
    return resp


@pytest.mark.asyncio
async def test_payment_method_none_when_not_mentioned(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5900,"currency":"ARS","category":"food",'
            '"merchant":null,"payment_method":null,"tags":[],"location":null,"notes":null}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("gaste 5900 en jugo")
    assert result is not None
    assert result["payment_method"] is None


@pytest.mark.asyncio
async def test_payment_method_preserved_when_mentioned(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5900,"currency":"ARS","category":"food",'
            '"merchant":null,"payment_method":"credit card","tags":[],"location":null,"notes":null}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("gaste 5900 con tarjeta de credito")
    assert result is not None
    assert result["payment_method"] == "credit card"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd e:\Dev\proyectos\finanzas-bot
.\venv\Scripts\python.exe -m pytest tests/test_gemini_ai_prompt.py -v
```

Expected: FAIL — `result["payment_method"]` is `"cash"` because `setdefault("payment_method", "cash")` overwrites `null`.

- [ ] **Step 3: Update SYSTEM_PROMPT and remove setdefault for payment_method**

In `app/gemini_ai.py`, replace the entire `SYSTEM_PROMPT` string:

```python
SYSTEM_PROMPT = """You are a financial assistant that extracts transaction details from user input in any language.
Return ONLY a JSON object with the following fields:
- type: "expense" or "income"
- amount: number (positive float or int)
- currency: string (ISO currency code, e.g. "ARS", "USD"; default "ARS")
- category: one of ["food", "transport", "entertainment", "health", "education", "clothing", "housing", "utilities", "subscriptions", "salary", "freelance", "gift", "savings", "investment", "travel", "other"]
- merchant: string or null
- payment_method: one of ["cash", "debit card", "credit card", "transfer", "other"] if explicitly mentioned or clearly inferable; null if not mentioned or ambiguous
- tags: array of strings
- location: string or null
- notes: string or null

If the input does not describe a valid transaction, return JSON with key "error": "invalid transaction"."""
```

In `parse_transaction_from_text`, remove this line:
```python
data.setdefault("payment_method", "cash")
```

In `parse_transaction_from_audio`, remove this line:
```python
data.setdefault("payment_method", "cash")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.\venv\Scripts\python.exe -m pytest tests/test_gemini_ai_prompt.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/gemini_ai.py tests/test_gemini_ai_prompt.py
git commit -m "feat(gemini): return null payment_method when not inferable from input"
```

---

### Task 2: Add Spanish display maps and interactive payment method picker

**Files:**
- Modify: `app/handlers.py`

**Interfaces:**
- Consumes: parsed dict from Task 1 where `payment_method` may be `None`.
- Produces:
  - `CATEGORY_LABELS: dict[str, str]` — maps English DB category → Spanish display string.
  - `PAYMENT_METHOD_LABELS: dict[str, str]` — maps English DB payment_method → Spanish display string.
  - `handle_parsed_data(update, context, data)` — sends inline keyboard when `payment_method` is `None`; otherwise shows confirm/cancel card directly.
  - `pending_transactions` now supports `"action": "pick_payment"` state with key `"data"` (parsed dict, `payment_method` still `None`).
  - `callback_handler` handles `callback_data` values `"pm_cash"`, `"pm_debit card"`, `"pm_credit card"`, `"pm_transfer"`, `"pm_other"` to fill `payment_method` and advance to confirm state.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_handlers_payment.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


def make_update(text=None, callback_data=None, chat_id=123):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    if callback_data is not None:
        update.callback_query = MagicMock()
        update.callback_query.data = callback_data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_handle_parsed_data_asks_payment_method_when_null():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="gaste 5900 en jugo")
    context = MagicMock()
    data = {
        "type": "expense", "amount": 5900, "currency": "ARS",
        "category": "food", "merchant": None, "payment_method": None,
        "tags": [], "location": None, "notes": None,
    }
    await handlers.handle_parsed_data(update, context, data)
    update.message.reply_text.assert_called_once()
    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_payment"


@pytest.mark.asyncio
async def test_handle_parsed_data_shows_confirm_when_payment_known():
    from app import handlers
    handlers.pending_transactions.clear()
    update = make_update(text="gaste 5900 con debito")
    context = MagicMock()
    data = {
        "type": "expense", "amount": 5900, "currency": "ARS",
        "category": "food", "merchant": None, "payment_method": "debit card",
        "tags": [], "location": None, "notes": None,
    }
    await handlers.handle_parsed_data(update, context, data)
    state = handlers.pending_transactions[123]
    assert state["action"] == "confirm"


@pytest.mark.asyncio
async def test_callback_sets_payment_method_and_advances_to_confirm():
    from app import handlers
    handlers.pending_transactions.clear()
    handlers.pending_transactions[123] = {
        "action": "pick_payment",
        "data": {
            "type": "expense", "amount": 5900, "currency": "ARS",
            "category": "food", "merchant": None, "payment_method": None,
            "tags": [], "location": None, "notes": None,
        },
    }
    update = make_update(callback_data="pm_cash", chat_id=123)
    context = MagicMock()
    await handlers.callback_handler(update, context)
    state = handlers.pending_transactions.get(123)
    assert state is not None
    assert state["action"] == "confirm"
    assert state["data"]["payment_method"] == "cash"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.\venv\Scripts\python.exe -m pytest tests/test_handlers_payment.py -v
```

Expected: FAIL — no `pick_payment` action, no `pm_*` callback handling, no `CATEGORY_LABELS`.

- [ ] **Step 3: Add CATEGORY_LABELS and PAYMENT_METHOD_LABELS**

In `app/handlers.py`, after the imports and before `logger = logging.getLogger(__name__)`, add:

```python
CATEGORY_LABELS: dict[str, str] = {
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
    "freelance": "Freelance",
    "gift": "Regalo",
    "savings": "Ahorros",
    "investment": "Inversión",
    "travel": "Viajes",
    "other": "Otro",
}

PAYMENT_METHOD_LABELS: dict[str, str] = {
    "cash": "💵 Efectivo",
    "debit card": "💳 Débito",
    "credit card": "💳 Crédito",
    "transfer": "🏦 Transferencia",
    "other": "Otro",
}
```

- [ ] **Step 4: Replace handle_parsed_data**

Replace the entire `handle_parsed_data` function (lines 176-202 in current `app/handlers.py`) with:

```python
async def handle_parsed_data(update: Update, context: ContextTypes.DEFAULT_TYPE, data: dict | None):
    if not data or "error" in data:
        await update.message.reply_text("No pude entender la transacción. Por favor, intenta de nuevo.")
        return

    chat_id = update.effective_chat.id

    if data.get("payment_method") is None:
        pending_transactions[chat_id] = {"action": "pick_payment", "data": data}
        keyboard = [
            [
                InlineKeyboardButton(PAYMENT_METHOD_LABELS["cash"], callback_data="pm_cash"),
                InlineKeyboardButton(PAYMENT_METHOD_LABELS["debit card"], callback_data="pm_debit card"),
            ],
            [
                InlineKeyboardButton(PAYMENT_METHOD_LABELS["credit card"], callback_data="pm_credit card"),
                InlineKeyboardButton(PAYMENT_METHOD_LABELS["transfer"], callback_data="pm_transfer"),
            ],
            [
                InlineKeyboardButton(PAYMENT_METHOD_LABELS["other"], callback_data="pm_other"),
            ],
        ]
        await update.message.reply_text(
            "¿Con qué método de pago fue la transacción?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    pending_transactions[chat_id] = {"action": "confirm", "data": data}
    await _send_confirm_message(update, data)


def _build_confirm_text(data: dict) -> str:
    category_label = CATEGORY_LABELS.get(data.get("category", ""), data.get("category", ""))
    payment_label = PAYMENT_METHOD_LABELS.get(data.get("payment_method", ""), data.get("payment_method", ""))
    type_label = "Gasto" if data.get("type") == "expense" else "Ingreso"
    msg = (
        f"Transacción detectada:\n"
        f"Tipo: {type_label}\n"
        f"Monto: ${data.get('amount')} {data.get('currency', 'ARS')}\n"
        f"Categoría: {category_label}\n"
        f"Método de pago: {payment_label}\n"
    )
    if data.get("merchant"):
        msg += f"Comercio: {data.get('merchant')}\n"
    return msg


async def _send_confirm_message(update: Update, data: dict):
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirmar", callback_data="confirm"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ]
    ]
    await update.message.reply_text(
        _build_confirm_text(data),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
```

- [ ] **Step 5: Replace callback_handler**

Replace the entire `callback_handler` function (lines 205-227 in current `app/handlers.py`) with:

```python
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not check_access(update):
        return

    chat_id = update.effective_chat.id
    state = pending_transactions.get(chat_id)

    if not state:
        await query.edit_message_text(text="No hay transacción pendiente.")
        return

    if state.get("action") == "pick_payment" and query.data.startswith("pm_"):
        payment_method = query.data[len("pm_"):]
        state["data"]["payment_method"] = payment_method
        pending_transactions[chat_id] = {"action": "confirm", "data": state["data"]}
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirmar", callback_data="confirm"),
                InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
            ]
        ]
        await query.edit_message_text(
            text=_build_confirm_text(state["data"]),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if state.get("action") != "confirm":
        await query.edit_message_text(text="No hay transacción pendiente para confirmar.")
        return

    if query.data == "confirm":
        await insert_transaction(state["data"])
        await query.edit_message_text(text="Transacción guardada exitosamente. ✅")
    elif query.data == "cancel":
        await query.edit_message_text(text="Transacción cancelada.")

    if chat_id in pending_transactions:
        del pending_transactions[chat_id]
```

- [ ] **Step 6: Update recent_handler, delete_handler, summary_handler to use Spanish labels**

In `recent_handler`, replace the inner loop body:
```python
# before
msg += f"{i}. {t['type']} de ${t['amount']} en {t['category']} ({created})\n"
# after
type_label = "Gasto" if t["type"] == "expense" else "Ingreso"
category_label = CATEGORY_LABELS.get(t["category"], t["category"])
msg += f"{i}. {type_label} de ${t['amount']} en {category_label} ({created})\n"
```

In `delete_handler`, replace the inner loop body:
```python
# before
msg += f"{i}. {t['type']} de ${t['amount']} en {t['category']}\n"
# after
type_label = "Gasto" if t["type"] == "expense" else "Ingreso"
category_label = CATEGORY_LABELS.get(t["category"], t["category"])
msg += f"{i}. {type_label} de ${t['amount']} en {category_label}\n"
```

In `summary_handler`, replace the inner loop body:
```python
# before
msg += f"- {row['category']} ({row['type']}): ${row['total']:.2f}\n"
# after
type_label = "Gasto" if row["type"] == "expense" else "Ingreso"
category_label = CATEGORY_LABELS.get(row["category"], row["category"])
msg += f"- {category_label} ({type_label}): ${row['total']:.2f}\n"
```

- [ ] **Step 7: Run all tests to verify they pass**

```bash
.\venv\Scripts\python.exe -m pytest tests/test_handlers_payment.py tests/test_gemini_ai_prompt.py -v
```

Expected: PASS all tests.

- [ ] **Step 8: Commit**

```bash
git add app/handlers.py tests/test_handlers_payment.py
git commit -m "feat(handlers): add Spanish labels and interactive payment method picker"
```

---

### Task 3: Add description field for transaction concept/title

**Files:**
- Modify: `app/database.py`
- Modify: `app/gemini_ai.py`
- Modify: `app/handlers.py`

**Interfaces:**
- Consumes: `SYSTEM_PROMPT` from Task 1 (already updated); `handle_parsed_data` and `_build_confirm_text` from Task 2.
- Produces:
  - `description: str | None` field in the parsed dict returned by `parse_transaction_from_text` / `parse_transaction_from_audio`.
  - `transactions` table gains a `description VARCHAR(255)` column, nullable.
  - `INSERT_SQL` gains `description` as parameter `$12`.
  - Confirmation card and `/recent` list include the description when present.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_gemini_ai_prompt.py`:

```python
@pytest.mark.asyncio
async def test_description_extracted_from_text(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5900,"currency":"ARS","category":"food",'
            '"description":"jugo","merchant":null,"payment_method":null,"tags":[],"location":null,"notes":null}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("gaste 5900 en jugo")
    assert result is not None
    assert result.get("description") == "jugo"


@pytest.mark.asyncio
async def test_description_is_none_when_not_present(mock_client):
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=make_response(
            '{"type":"expense","amount":5900,"currency":"ARS","category":"food",'
            '"description":null,"merchant":null,"payment_method":null,"tags":[],"location":null,"notes":null}'
        )
    )
    from app.gemini_ai import parse_transaction_from_text
    result = await parse_transaction_from_text("gaste plata")
    assert result is not None
    assert result.get("description") is None
```

Add to `tests/test_handlers_payment.py`:

```python
@pytest.mark.asyncio
async def test_confirm_message_includes_description():
    from app.handlers import _build_confirm_text
    data = {
        "type": "expense", "amount": 5900, "currency": "ARS",
        "category": "food", "description": "jugo", "merchant": None,
        "payment_method": "cash", "tags": [], "location": None, "notes": None,
    }
    text = _build_confirm_text(data)
    assert "jugo" in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.\venv\Scripts\python.exe -m pytest tests/test_gemini_ai_prompt.py tests/test_handlers_payment.py -v
```

Expected: FAIL — `description` key absent from parsed dict, `_build_confirm_text` doesn't include it.

- [ ] **Step 3: Add description to SYSTEM_PROMPT in app/gemini_ai.py**

In `SYSTEM_PROMPT` (already updated in Task 1), add `description` between `category` and `merchant`:

```python
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
```

- [ ] **Step 4: Add ALTER TABLE migration and update INSERT_SQL in app/database.py**

Add this constant after `CREATE_TABLE_SQL`:

```python
ALTER_ADD_DESCRIPTION_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS description VARCHAR(255);
"""
```

In `init_db`, after `await conn.execute(CREATE_TABLE_SQL)`, add:

```python
await conn.execute(ALTER_ADD_DESCRIPTION_SQL)
```

Replace `INSERT_SQL` with:

```python
INSERT_SQL = """
INSERT INTO transactions
    (type, amount, currency, category, description, merchant, payment_method,
     status, tags, location, notes, original_message)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
RETURNING *;
"""
```

In `insert_transaction`, update the `pool.fetchrow` call to pass `description` as `$5` and shift the rest:

```python
return await pool.fetchrow(
    INSERT_SQL,
    data["type"],
    data["amount"],
    data.get("currency", "ARS"),
    data["category"],
    data.get("description"),
    data.get("merchant"),
    data["payment_method"],
    data.get("status", "completed"),
    data.get("tags"),
    data.get("location"),
    data.get("notes"),
    data.get("original_message"),
)
```

- [ ] **Step 5: Update _build_confirm_text in app/handlers.py to show description**

Replace the `_build_confirm_text` function:

```python
def _build_confirm_text(data: dict) -> str:
    category_label = CATEGORY_LABELS.get(data.get("category", ""), data.get("category", ""))
    payment_label = PAYMENT_METHOD_LABELS.get(data.get("payment_method", ""), data.get("payment_method", ""))
    type_label = "Gasto" if data.get("type") == "expense" else "Ingreso"
    msg = (
        f"Transacción detectada:\n"
        f"Tipo: {type_label}\n"
        f"Monto: ${data.get('amount')} {data.get('currency', 'ARS')}\n"
        f"Categoría: {category_label}\n"
        f"Método de pago: {payment_label}\n"
    )
    if data.get("description"):
        msg += f"Concepto: {data.get('description')}\n"
    if data.get("merchant"):
        msg += f"Comercio: {data.get('merchant')}\n"
    return msg
```

Also update the `recent_handler` loop body to show description when available:

```python
type_label = "Gasto" if t["type"] == "expense" else "Ingreso"
category_label = CATEGORY_LABELS.get(t["category"], t["category"])
desc = f" — {t['description']}" if t.get("description") else ""
msg += f"{i}. {type_label} de ${t['amount']} en {category_label}{desc} ({created})\n"
```

- [ ] **Step 6: Run all tests to verify they pass**

```bash
.\venv\Scripts\python.exe -m pytest tests/test_gemini_ai_prompt.py tests/test_handlers_payment.py -v
```

Expected: PASS all tests.

- [ ] **Step 7: Commit**

```bash
git add app/database.py app/gemini_ai.py app/handlers.py tests/test_gemini_ai_prompt.py tests/test_handlers_payment.py
git commit -m "feat(transactions): add description field for transaction concept/title"
```

---

## Verification Plan

### Automated Tests

```bash
.\venv\Scripts\python.exe -m pytest tests/test_gemini_ai_prompt.py tests/test_handlers_payment.py -v
```

Expected: todos los tests PASS.

### Manual Verification

- Enviar `"gasté 5900 en jugo"` → bot pregunta método de pago con 5 botones; al elegir, la tarjeta de confirmación muestra *Concepto: jugo*.
- Enviar `"gasté 5900 en nafta con tarjeta de débito"` → bot muestra directamente la tarjeta de confirmación con *Transporte*, *Débito* y *Concepto: nafta*, sin preguntar.
- Ejecutar `/recent` → cada línea muestra el concepto cuando disponible (ej. `Gasto de $5900 en Comida — jugo`).
- Ejecutar `/summary` → categorías y tipos en español.
- Verificar en la DB de Neon que la columna `description` existe y contiene valores correctos.
