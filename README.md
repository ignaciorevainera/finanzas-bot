# Finance Tracker Telegram Bot - Agent Context

## Project Overview

This repository contains the source code for an automated personal finance tracking bot deployed via Telegram. The system leverages Google Gemini AI for natural language processing (handling both text and voice notes) to extract structured financial data. This data is persisted in a serverless PostgreSQL 18 database hosted on Neon. The application is built using Python and FastAPI, configured for continuous deployment on Render, operating through a Webhook architecture.

## Technology Stack

- **Language:** Python 3.10+
- **Web Framework:** FastAPI (Webhook management)
- **Telegram Integration:** `python-telegram-bot` (async implementation)
- **AI Processing:** Google Gemini API (Multimodal capabilities for text and audio)
- **Database:** PostgreSQL 18 (Neon serverless platform)
- **Deployment:** Render (Free Web Service)

## Development Standards

- **Codebase Language:** All source code, including variables, functions, database schemas (tables and columns), and attributes, must be written entirely in English.
- **Security:** Hardcoded credentials are strictly prohibited. All sensitive data (API keys, tokens, database URIs) must be accessed exclusively via environment variables.

## Database Schema (PostgreSQL 18)

The system utilizes a strict relational schema to guarantee transactional integrity.

```sql
CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(10) NOT NULL CHECK (type IN ('income', 'expense')),
    amount DECIMAL(12, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'ARS',
    category VARCHAR(100) NOT NULL,
    merchant VARCHAR(255),
    payment_method VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'completed' CHECK (status IN ('completed', 'pending', 'cancelled')),
    tags TEXT[],
    location VARCHAR(255),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    original_message TEXT
);
```

Environment Variables Configuration
The system requires the following variables defined in the execution environment (Render / .env for local testing):

TELEGRAM_BOT_TOKEN: Token provided by BotFather.

GEMINI_API_KEY: API credential from Google AI Studio.

DATABASE_URL: Standard Neon PostgreSQL 18 connection string (must incorporate username and password natively in the URI).

WEBHOOK_URL: https://finanzas-bot-48c4.onrender.com

PYTHON_VERSION: 3.10.0 (or higher) to enforce asynchronous library compatibility on Render.

Deployment Protocol
The deployment process relies on continuous integration via Render. The repository must strictly include:

requirements.txt: Specifying all required Python dependencies.

.gitignore: Configured to exclude all local environments (venv/), cache files (**pycache**/), and credentials (.env).

Render Configuration:

Build Command: pip install -r requirements.txt

Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
