# Fix Transaction Detection Gemini Quota Issue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve transaction parsing errors caused by "Quota exceeded (limit: 0)" on `gemini-2.0-flash` by making the model configurable and defaulting to `gemini-3.5-flash`.

**Architecture:** Update `Settings` configuration to load `gemini_model` from `.env` (defaulting to `gemini-3.5-flash`), then pass `settings.gemini_model` to Gemini content generation.

**Tech Stack:** Python, Google GenAI SDK, Pydantic Settings

## Global Constraints
- Do not add comments to code unless explicitly requested.
- Maintain formatting conventions.

---

### Task 1: Add configuration for Gemini Model

**Files:**
- Modify: [config.py](file:///e:/Dev/proyectos/finanzas-bot/app/config.py)

**Interfaces:**
- Produces: `settings.gemini_model` (str)

- [ ] **Step 1: Edit config.py to add `gemini_model`**
Add `gemini_model: str = "gemini-3.5-flash"` to the `Settings` class in [config.py](file:///e:/Dev/proyectos/finanzas-bot/app/config.py).

---

### Task 2: Update AI parsing functions to use configured model

**Files:**
- Modify: [gemini_ai.py](file:///e:/Dev/proyectos/finanzas-bot/app/gemini_ai.py)

**Interfaces:**
- Consumes: `settings.gemini_model`

- [ ] **Step 1: Edit gemini_ai.py to use `settings.gemini_model`**
Replace hardcoded `"gemini-2.0-flash"` in `parse_transaction_from_text` and `parse_transaction_from_audio` with `settings.gemini_model`.

---

## Verification Plan

### Manual Verification
- Run a test script using the virtual environment interpreter to ensure transaction parsing now succeeds with `gemini-3.5-flash`.
