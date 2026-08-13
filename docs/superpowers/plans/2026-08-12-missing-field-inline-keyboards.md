# Missing-Field Inline Keyboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace free-text prompts for missing closed-choice transaction fields with Telegram inline keyboards while preserving text fallback, custom categories, defaults, and existing transaction states.

**Architecture:** Keep `pending_transactions` and existing states. Add one field-aware `pick_missing` flow: callbacks and text answers both normalize to canonical Spanish values, update state, and advance to next missing field. Keep keyboard builders and Telegram-specific state logic in `app/handlers.py`; reuse vocabularies from `app/transaction_schema.py`.

**Tech Stack:** Python 3.10+, `python-telegram-bot`, `pytest`, `pytest-asyncio`.

## Global Constraints

- Submenus appear only when corresponding value is missing from parsed text/audio.
- `type`: `Gasto` / `Ingreso`.
- `category`: 16 base categories + `Otra categoría`, one keyboard in two columns.
- `payment_method`: `Efectivo`, `Tarjeta de Débito`, `Tarjeta de Crédito`, `Transferencia`, `Otro`.
- `currency` defaults to `ARS` without a question.
- `status` defaults to `Completado` without a question.
- `transaction_date` defaults to current date/time without a question.
- Text equivalents remain accepted when keyboard is displayed.
- `Otra categoría` accepts free text and capitalizes its first letter.
- Valid selection edits current prompt message instead of sending duplicate messages.
- Dates omit time unless user explicitly declared time.
- Existing `pick_split`, `pick_date`, `wait_custom_date`, `add_context`, `Aceptar`, `Cancelar`, report, text, and audio flows remain functional.
- Unknown, stale, wrong-field, or state-less callbacks never mutate transaction data.
- All source identifiers remain English; stored/user-facing values remain Spanish and capitalized.
- Do not add runtime dependencies.
- Every task ends with focused tests and a separate commit.

---

## File Map

- Modify `app/handlers.py`: keyboard builders, field-aware missing state, callbacks, text fallback, date formatting.
- Modify `app/gemini_ai.py`: transient explicit-time metadata from text/audio extraction.
- Modify `tests/test_handlers_payment.py`: keyboard, callback, text fallback, safety, date-format, and regression tests.
- Modify `tests/test_gemini_ai_prompt.py`: explicit-time metadata tests.
- Modify `README.md`: interactive missing-field behavior and text fallback.

## Interfaces

```python
def _get_missing_field_keyboard(field: str) -> InlineKeyboardMarkup | None: ...
def _get_missing_field_prompt(field: str) -> str: ...
def _resolve_missing_field_answer(field: str, value: str) -> str | None: ...
def _format_transaction_datetime(
    value: datetime | str | None,
    has_explicit_time: bool = False,
) -> str: ...
```

`_get_missing_field_keyboard` returns keyboards only for `type`, `category`, and `payment_method`. `_resolve_missing_field_answer` returns canonical Spanish value or `None`. `_format_transaction_datetime` returns `DD/MM/YYYY`, adding `HH:MM` only when `has_explicit_time=True`.

### Task 1: Keyboard Definitions And Resolvers

**Files:**
- Modify: `app/handlers.py:32-155`
- Test: `tests/test_handlers_payment.py`

**Interfaces:**
- Consumes: `TYPE_MAP`, `CATEGORY_MAP`, `PAYMENT_METHOD_MAP`, `normalize_transaction` from `app.transaction_schema`.
- Produces: keyboard builders, callback-code maps, field prompts, and `_resolve_missing_field_answer` for later tasks.

- [ ] **Step 1: Write failing keyboard/resolver tests**

```python
def test_type_keyboard_has_two_options():
    from app.handlers import _get_missing_field_keyboard
    keyboard = _get_missing_field_keyboard("type")
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert [b.text for b in buttons] == ["Gasto", "Ingreso"]
    assert [b.callback_data for b in buttons] == [
        "missing_type_expense", "missing_type_income"
    ]


def test_category_keyboard_has_seventeen_buttons_and_two_columns():
    from app.handlers import _get_missing_field_keyboard
    keyboard = _get_missing_field_keyboard("category")
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert len(buttons) == 17
    assert len(keyboard.inline_keyboard[0]) == 2
    assert buttons[-1].text == "Otra categoría"
    assert buttons[-1].callback_data == "missing_category_other"


def test_text_resolver_accepts_equivalent_values():
    from app.handlers import _resolve_missing_field_answer
    assert _resolve_missing_field_answer("type", "gasto") == "Gasto"
    assert _resolve_missing_field_answer("category", "comida") == "Comida"
    assert _resolve_missing_field_answer("payment_method", "efectivo") == "Efectivo"
    assert _resolve_missing_field_answer("payment_method", "inventado") is None
```

- [ ] **Step 2: Run tests and verify failure**

Run: `venv\Scripts\python.exe -m pytest tests/test_handlers_payment.py -k "keyboard or resolver" -q`

Expected: FAIL because builders and resolver do not exist.

- [ ] **Step 3: Implement canonical option lists and keyboards**

Derive visible values from schema maps; do not duplicate category names:

```python
TYPE_OPTIONS = (("Gasto", "missing_type_expense"), ("Ingreso", "missing_type_income"))
CATEGORY_OPTIONS = tuple(dict.fromkeys(CATEGORY_MAP.values()))
PAYMENT_METHOD_OPTIONS = tuple(PAYMENT_METHOD_MAP.values())
```

Build category rows in two columns, then put `Otra categoría` alone in final row. Use ASCII callback codes. Build payment options in two columns plus final `Otro` row. Return `None` for `amount` and `description`.

- [ ] **Step 4: Implement prompts and resolver**

Use these prompts:

```python
MISSING_FIELD_PROMPTS = {
    "type": "Selecciona tipo de transacción:",
    "amount": "¿Cuál es el monto de la transacción?",
    "category": "Selecciona una categoría:",
    "description": "¿Cuál es el concepto o descripción de la transacción?",
    "payment_method": "Selecciona el método de pago:",
}
```

`_resolve_missing_field_answer` calls `normalize_transaction` for target field. `type` and `payment_method` accept only approved canonical values. `category` accepts base or custom non-empty text. Invalid answer returns `None`.

- [ ] **Step 5: Run focused tests and commit**

Run: `venv\Scripts\python.exe -m pytest tests/test_handlers_payment.py -k "keyboard or resolver" -q`. Expected: PASS.

```bash
git add app/handlers.py tests/test_handlers_payment.py
git commit -m "feat: add missing-field inline keyboards"
```

### Task 2: Field-Aware Missing State And Callbacks

**Files:**
- Modify: `app/handlers.py:330-430,520-690`
- Test: `tests/test_handlers_payment.py`

Use existing `make_update(text=None, callback_data=None, chat_id=123)` helper from `tests/test_handlers_payment.py`; `update` and `context` in snippets mean locally constructed values, not pytest fixtures.

**Interfaces:**
- Consumes: Task 1 builders/resolver, `get_missing_transaction_fields`, `pending_transactions`.
- Produces: `pick_missing` state with `field`, `missing_fields`, `missing_index`; `missing_*` callback handling; shared advancement for callback/text paths.

- [ ] **Step 1: Write failing state tests**

```python
@pytest.mark.asyncio
async def test_missing_type_shows_keyboard(update, context):
    from app import handlers
    handlers.pending_transactions.clear()
    data = {"amount": 500, "category": "Comida", "description": "Cena",
            "payment_method": "Efectivo", "currency": "ARS",
            "status": "Completado", "transaction_date": "2026-08-12"}

    await handlers.handle_parsed_data(update, context, data)

    state = handlers.pending_transactions[123]
    assert state["action"] == "pick_missing"
    assert state["field"] == "type"
    assert update.message.reply_text.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_detected_type_skips_type_keyboard(update, context):
    from app import handlers
    handlers.pending_transactions.clear()
    data = {"type": "Gasto", "amount": 500, "description": "Cena",
            "payment_method": "Efectivo", "currency": "ARS",
            "status": "Completado", "transaction_date": "2026-08-12"}

    await handlers.handle_parsed_data(update, context, data)

    state = handlers.pending_transactions[123]
    assert state["field"] == "category"
    labels = [b.text for row in update.message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard for b in row]
    assert "Gasto" not in labels
    assert "Otra categoría" in labels
```

- [ ] **Step 2: Run tests and verify failure**

Run: `venv\Scripts\python.exe -m pytest tests/test_handlers_payment.py -k "missing_type or detected_type" -q`

Expected: FAIL because current missing state does not attach field keyboards.

- [ ] **Step 3: Add shared missing-field advancement**

Store state in this shape:

```python
{
    "action": "pick_missing",
    "field": "category",
    "missing_fields": ["category", "payment_method"],
    "missing_index": 0,
    "data": data,
}
```

Implement `_advance_missing_field(update, state)` to set current field, store state, and either show keyboard or ask text. When index reaches list length, set `action="confirm"` and call `_send_confirm_message`.

- [ ] **Step 4: Update `handle_parsed_data`**

Replace generic missing handling with `get_missing_transaction_fields(data)`. Initialize ordered state above. Do not ask for defaults. Preserve split validation and confirmation after required fields complete.

- [ ] **Step 5: Implement callbacks and edit-message progression**

Parse only callback codes beginning `missing_`. Accept callback only when state action is `pick_missing`, callback field equals `state["field"]`, and option is valid for that field. Update canonical value, increment `missing_index`, then use `query.edit_message_text` with next prompt and keyboard. `missing_category_other` sets `action="pick_custom_category"` and asks for text.

Unknown callback, wrong field, stale state, or absent state edits a short Spanish message without changing `data`.

- [ ] **Step 6: Run callback tests and commit**

Run: `venv\Scripts\python.exe -m pytest tests/test_handlers_payment.py -q`. Expected: PASS.

```bash
git add app/handlers.py tests/test_handlers_payment.py
git commit -m "feat: advance missing fields with callbacks"
```

### Task 3: Text Fallback, Explicit-Time Metadata, And Date Formatting

**Files:**
- Modify: `app/handlers.py:330-430,600-690`
- Modify: `app/gemini_ai.py:20-150`
- Test: `tests/test_handlers_payment.py`
- Test: `tests/test_gemini_ai_prompt.py`

Use existing `make_update` helper for handler tests and the existing mocked Gemini client fixture for parser tests.

**Interfaces:**
- Consumes: field-aware state and `_resolve_missing_field_answer`.
- Produces: text fallback for closed-choice fields, `pick_custom_category` handling, transient `transaction_date_has_explicit_time` metadata, and `_format_transaction_datetime` used by `_build_confirm_text`.

- [ ] **Step 1: Write failing fallback/date tests**

```python
@pytest.mark.asyncio
async def test_text_equivalent_advances_missing_field(update, context):
    from app import handlers
    handlers.pending_transactions[123] = {
        "action": "pick_missing", "field": "payment_method",
        "missing_fields": ["payment_method"], "missing_index": 0,
        "data": {"type": "Gasto", "amount": 500, "category": "Comida",
                 "description": "Cena"},
    }
    update.message.text = "tarjeta de debito"

    await handlers.message_handler(update, context)

    assert handlers.pending_transactions[123]["action"] == "confirm"
    assert handlers.pending_transactions[123]["data"]["payment_method"] == "Tarjeta de Débito"


def test_confirm_date_omits_time_when_not_declared():
    from app.handlers import _build_confirm_text
    text = _build_confirm_text({"type": "Gasto", "amount": 500,
                                "total_amount": 500, "currency": "ARS",
                                "category": "Comida", "description": "Cena",
                                "payment_method": "Efectivo",
                                "transaction_date": "2026-08-12"})
    assert "Fecha: 12/08/2026" in text
    assert "00:00" not in text


def test_confirm_date_includes_explicit_time():
    from app.handlers import _build_confirm_text
    text = _build_confirm_text({"type": "Gasto", "amount": 500,
                                "total_amount": 500, "currency": "ARS",
                                "category": "Comida", "description": "Cena",
                                "payment_method": "Efectivo",
                                "transaction_date": "2026-08-12T18:30:00+00:00"})
    assert "Fecha: 12/08/2026 18:30" in text
```

- [ ] **Step 2: Run tests and verify failure**

Run: `venv\Scripts\python.exe -m pytest tests/test_handlers_payment.py -k "text_equivalent or confirm_date" -q`

Expected: FAIL because text state handling and date formatting are incomplete.

- [ ] **Step 3: Add explicit-time metadata to text/audio parser**

Extend transaction extraction JSON contract with `transaction_date_has_explicit_time: boolean`. Prompt rules: `true` only when input explicitly declares a clock time; `false` for date-only expressions, relative dates without time, and no date. `_finalize_transaction_data` defaults missing metadata to `False`. Add tests for `"ayer"` returning `false` and `"ayer a las 18:30"` returning `true`. Preserve metadata through normalization and defaults.

- [ ] **Step 4: Implement text fallback in `message_handler`**

When state action is `pick_missing`, resolve `state["field"]` with `_resolve_missing_field_answer`. Invalid answer replies with same prompt and keyboard, preserving state. Valid answer updates data, increments index, and sends next prompt using `reply_text` for the message-driven path. `amount` and `description` keep existing free-text parsing. `pick_custom_category` accepts non-empty text, normalizes category, then resumes missing sequence.

- [ ] **Step 5: Use one date formatter in confirmation**

Track explicit time as transient parser/handler metadata named `transaction_date_has_explicit_time`. Set it to `True` only when the original text/audio extraction contains an explicit clock time; set it to `False` for current-date defaults, `Hoy`, `Ayer`, and date-only custom input. Do not add this metadata to `INSERT_SQL`; `insert_transaction` already ignores unknown dictionary keys. Preserve it while `Agregar más` merges context.

Implement `_format_transaction_datetime`:

```python
def _format_transaction_datetime(value, has_explicit_time=False):
    if not value:
        return ""
    if not has_explicit_time:
        if isinstance(value, datetime):
            return value.strftime("%d/%m/%Y")
        return datetime.fromisoformat(value).strftime("%d/%m/%Y")
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    parsed = datetime.fromisoformat(value)
    return parsed.strftime("%d/%m/%Y %H:%M")
```

Use helper from `_build_confirm_text` with `data.get("transaction_date_has_explicit_time", False)`; preserve date picker behavior and only include time when user input contained time. Add tests proving a default `datetime(2026, 8, 12, 18, 30)` still displays `12/08/2026`, while the same value with the flag set displays `12/08/2026 18:30`.

- [ ] **Step 6: Test invalid/stale callbacks and run focused suite**

Add tests that invalid text preserves `pick_missing`, `missing_category_other` accepts custom category, unknown callback does not mutate data, and existing `pick_split`/`add_context` callbacks still work.

Run: `venv\Scripts\python.exe -m pytest tests/test_handlers_payment.py -q`. Expected: PASS.

- [ ] **Step 7: Commit fallback and dates**

```bash
git add app/handlers.py app/gemini_ai.py tests/test_handlers_payment.py tests/test_gemini_ai_prompt.py
git commit -m "feat: support text fallback for missing fields"
```

### Task 4: Documentation And Full Regression Verification

**Files:**
- Modify: `README.md`
- Modify: `tests/test_handlers_payment.py`
- Modify: `tests/test_gemini_ai_prompt.py`

**Interfaces:**
- Consumes: completed keyboard/resolver/state/date behavior.
- Produces: documented interaction contract and final regression evidence.

- [ ] **Step 1: Write documentation assertion**

```python
from pathlib import Path


def test_readme_documents_missing_field_keyboards():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "teclado" in readme.lower()
    assert "Otra categoría" in readme
    assert "Agregar más" in readme
```

- [ ] **Step 2: Update README interaction documentation**

Document that closed-choice missing fields show inline keyboards, detected fields skip questions, text equivalents remain valid, `Otra categoría` accepts custom text, and date confirmation omits time unless explicitly declared. Keep schema, reports, environment, and deployment sections intact.

- [ ] **Step 3: Add text/audio bypass regression tests**

Mock parser output with complete `type`, `category`, and `payment_method` for both text/audio handler paths. Assert no missing-field keyboard is shown and confirmation is reached directly.

- [ ] **Step 4: Run full verification**

Run: `venv\Scripts\python.exe -m pytest -q`. Expected: all tests pass; only existing google-genai deprecation warning may remain.

Run: `git diff --check`. Expected: no output.

Run: `git status --short`. Expected: clean after commit.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md tests/test_handlers_payment.py tests/test_gemini_ai_prompt.py
git commit -m "docs: describe missing-field keyboards"
```

## Self-Review Checklist

- Every spec requirement maps to Task 1, 2, 3, or 4.
- No placeholder instructions remain.
- Callback names match keyboard builders and callback parser exactly.
- `missing_index`, `field`, and `missing_fields` use same names in every task.
- Date display behavior matches both string and `datetime` inputs.
- Full regression suite covers report, split, add-context, confirm, cancel, text, and audio flows.
