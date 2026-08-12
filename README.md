# Finance Tracker Telegram Bot

Agent-oriented context and operational reference for this repository.

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture Summary](#architecture-summary)
- [Technology Stack](#technology-stack)
- [Bot Commands](#bot-commands)
- [Development Standards](#development-standards)
- [Transaction Registration Flow](#transaction-registration-flow)
- [Finance Reports](#finance-reports)
- [Database Schema (PostgreSQL 18)](#database-schema-postgresql-18)
- [Environment Variables](#environment-variables)
- [Deployment (Render)](#deployment-render)

## Project Overview

This repository contains the source code for an automated personal finance tracking bot deployed via Telegram.

The system uses Google Gemini AI (`gemini-3.5-flash` by default through the official `google-genai` SDK) to parse natural language inputs (text and voice notes via direct multimodal input) and extract structured financial transaction data.

Extracted data is stored in a serverless PostgreSQL 18 database on Neon. The application is implemented in Python with FastAPI, deployed continuously on Render, and runs with a webhook-based architecture.

## Architecture Summary

- **Structure:** Modular `app/` package layout.
- **User scope:** Single-user deployment with no authentication layer.
- **Audio pipeline:** Direct multimodal processing with Gemini (no external transcription service).
- **Interaction language:** Bot responses in Spanish; codebase strictly in English.
- **Confirmation flow:** Full summary with inline keyboard actions `Aceptar` / `Agregar más` / `Cancelar` before DB persistence.
- **AI engine:** `gemini-3.5-flash` (configurable) with `google-genai`.
- **Schema management:** Automatic table initialization on startup.
- **Monitoring:** Structured logging (`logging`) and `GET /health` endpoint.

## Technology Stack

- **Language:** Python 3.10+
- **Web framework:** FastAPI (webhook handling)
- **Telegram integration:** `python-telegram-bot` (async)
- **AI processing:** Google Gemini API (`google-genai`, model `gemini-3.5-flash`)
- **Database:** PostgreSQL 18 (Neon serverless) via `asyncpg`
- **Deployment platform:** Render (Free Web Service)

## Bot Commands

- `/start`: Initialize interaction and webhook context.
- `/help`: Show available commands and usage guidance.
- `/summary`: Generate a financial summary for the current month.
- `/report`: Generate a dimension or advanced financial report (`/report <métrica> [valor]`).
- `/recent`: List recent transactions.
- `/delete`: Remove specific transaction records.
- `/export`: Export transaction history in structured format.

## Development Standards

- **Codebase language:** All source code artifacts (variables, functions, attributes) must be in English. Database columns hold Spanish canonical values for user-facing fields (type, status, payment_method, category).
- **Security:** Hardcoded credentials are forbidden. Sensitive data must come from environment variables only.

## Transaction Registration Flow

1. **Extraction** — Gemini (`parse_transaction_from_text` / `parse_transaction_from_audio`) extracts a raw transaction from the user's message.
2. **Normalization** (`app/transaction_schema.py`) — maps values to the canonical Spanish vocabulary, capitalizes descriptions, tags, and custom categories.
3. **Defaults** (`apply_transaction_defaults`) — fills unspecified defaults: `currency=ARS`, `transaction_date=now`, `status=Completado`, `total_amount=amount`. Explicit values are never overridden.
4. **Required fields** — missing fields from `type`, `amount`, `category`, `description`, `payment_method` are asked **one at a time** until all are present.
5. **Shared distribution** — if the transaction is shared (`amount != total_amount`, participants present, or a split detected), the bot asks for the **exact per-person distribution**; amounts must sum to `total_amount`.
6. **Confirmation** — full transaction summary with inline keyboard `Aceptar` / `Agregar más` / `Cancelar`.
7. **Agregar más loop** — the user may send extra details (place, tags, cuotas, etc.). Explicit values **replace** the existing context, missing/ambiguous values **preserve** it, `notes` are appended, `tags` are unioned. The loop repeats until `Aceptar` (persist) or `Cancelar` (discard).

## Finance Reports

Financial reports aggregate stored transactions over a period. Both `/summary` and `/report` route through the shared report service (`app/reporting.py`): each request is validated as a typed `ReportRequest` and executed as a read-only query — nothing is persisted.

### Commands

- `/summary` — summary for the current month: personal income, personal expenses, shared total, and net flow.
- `/report <métrica> [valor]` — dimension or advanced report for the current month.

Examples:

- `/report category Comida`
- `/report shared`
- `/report tag Trabajo`

### Natural language reports

Question-shaped messages (containing `?` or `¿`) are interpreted by Gemini into a typed `ReportRequest` (metric plus optional filter value). Gemini returns **intent, never SQL** — the bot builds and executes its own allowlisted queries.

Examples:

- `¿Cuánto gasté en comida este mes?` — category report filtered to `Comida`.
- `¿Cuánto pago en cuotas este mes?` — installments report.

### Report dimensions

`summary`, `category`, `merchant`, `payment_method`, `location`, `person`, `tag`, `installments`, `recurrence`, `due_dates`, `transfers`, `refunds`, `packages`, `shared`.

Dimension metrics (`category`, `merchant`, `payment_method`, `location`, `person`, `tag`) accept an optional value filter (`/report category Comida`); period-only metrics (`/report shared`) accept none.

### Period semantics

Report periods are half-open `[start, end)`: `start` is inclusive, `end` is exclusive. Commands default to the current calendar month. Transactions with `status = Cancelado` are excluded from every report.

### Personal-share semantics

Personal reports aggregate `amount` (the user's personal share). Shared reports expose both `amount` and `total_amount` per row. `person` reports drop the reserved `user` pseudo-participant (the personal share, already shown as `amount`).

## Database Schema (PostgreSQL 18)

Transactions persist on a single `transactions` table managed by automatic startup migrations (`app/database.py`). Stored values use Spanish canonical vocabulary; legacy English values are migrated on startup.

```sql
CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(10) NOT NULL CHECK (type IN ('Gasto', 'Ingreso')),
    amount DECIMAL(12, 2) NOT NULL,
    total_amount DECIMAL(12, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'ARS',
    category VARCHAR(100) NOT NULL,
    description VARCHAR(255),
    merchant VARCHAR(255),
    payment_method VARCHAR(50) NOT NULL
        CHECK (payment_method IN ('Efectivo', 'Tarjeta de Débito', 'Tarjeta de Crédito', 'Transferencia', 'Otro')),
    status VARCHAR(20) NOT NULL DEFAULT 'Completado'
        CHECK (status IN ('Completado', 'Pendiente', 'Cancelado')),
    tags TEXT[],
    location VARCHAR(255),
    notes TEXT,
    transaction_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    due_date TIMESTAMP WITH TIME ZONE,
    recurrence VARCHAR(100),
    installment_number INT,
    installment_total INT,
    participants TEXT[],
    split_details JSONB,
    transfer_details JSONB,
    package_details JSONB,
    related_transaction_id UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    original_message TEXT
);
```

### Stored vocabulary (Spanish canonical values)

- **type:** `Gasto` | `Ingreso`
- **status:** `Completado` | `Pendiente` | `Cancelado` (default `Completado`)
- **payment_method:** `Efectivo` | `Tarjeta de Débito` | `Tarjeta de Crédito` | `Transferencia` | `Otro`
- **category:** 16 base Spanish categories (`Comida`, `Transporte`, `Entretenimiento`, `Salud`, `Educación`, `Ropa`, `Vivienda`, `Servicios`, `Suscripciones`, `Sueldo`, `Trabajo Independiente`, `Regalo`, `Ahorros`, `Inversión`, `Viajes`, `Otros`) plus AI-created custom categories (first letter capitalized).
- English values (`income`/`expense`, `completed`/`pending`/`cancelled`, `cash`/`credit card`/`transfer`/…) are normalized to the canonical Spanish forms on extraction and migrated on startup.

### Amount semantics

- **`amount`** — the user's personal share of the transaction.
- **`total_amount`** — the full amount. Equal to `amount` when the transaction is not shared; defaults to `amount` when omitted.
- Shared transactions store the per-person distribution in **`split_details`** (JSONB; keys are participant names plus `user` for the user's own share) and the ordered participant list in **`participants`** (TEXT[]).

### Advanced fields

- **`due_date`** — payment due date (e.g. credit-card statements, subscriptions).
- **`recurrence`** — rule for repeating transactions.
- **`installment_number`** / **`installment_total`** — current and total installments (cuotas).
- **`split_details`** / **`transfer_details`** / **`package_details`** — JSONB payloads for shared, transfer, and package transactions.
- **`related_transaction_id`** — links related records (e.g. a transfer's counterpart).

### Field roles

- **`description`** — short title / concept of the transaction.
- **`notes`** — residual free-form context appended across `Agregar más` rounds.
- **`tags`** — explicit tags plus AI-generated ones (deduplicated case-insensitively).
- `id`, `created_at`, `updated_at` are auto-managed by the database; persistence covers the 23 explicit columns above, with `original_message` retaining the raw user input.

## Environment Variables

Define the following variables in the runtime environment (Render) or local `.env` file:

- `TELEGRAM_BOT_TOKEN`: Token generated by BotFather.
- `GEMINI_API_KEY`: API key from Google AI Studio.
- `GEMINI_MODEL`: Model name (default: `gemini-3.5-flash`).
- `DATABASE_URL`: Neon PostgreSQL 18 URI with embedded username/password.
- `WEBHOOK_URL`: `https://finanzas-bot-48c4.onrender.com`
- `PYTHON_VERSION`: `3.10.0` or higher (async compatibility on Render).

## Deployment (Render)

Deployment is handled via continuous integration on Render.

### Required repository files

- `requirements.txt`: All Python dependencies.
- `.gitignore`: Must exclude local envs (`venv/`), cache files (`__pycache__/`), and secrets (`.env`).

### Render configuration

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
