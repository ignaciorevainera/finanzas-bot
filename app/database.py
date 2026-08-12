from datetime import datetime
import logging
import uuid

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS transactions (
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
"""

ALTER_ADD_DESCRIPTION_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS description VARCHAR(255);
"""

ALTER_ADD_TRANSACTION_DATE_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS transaction_date TIMESTAMP WITH TIME ZONE;
"""

ALTER_ADD_TOTAL_AMOUNT_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS total_amount DECIMAL(12, 2);
"""

UPDATE_TOTAL_AMOUNT_SQL = """
UPDATE transactions SET total_amount = amount WHERE total_amount IS NULL;
"""

ALTER_TOTAL_AMOUNT_NOT_NULL_SQL = """
ALTER TABLE transactions ALTER COLUMN total_amount SET NOT NULL;
"""

DROP_LEGACY_CHECKS_SQL = """
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_type_check;
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_status_check;
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_payment_method_check;
"""

UPDATE_LEGACY_TYPE_VALUES_SQL = """
UPDATE transactions SET type = 'Ingreso' WHERE type = 'income';
UPDATE transactions SET type = 'Gasto' WHERE type = 'expense';
"""

UPDATE_LEGACY_STATUS_VALUES_SQL = """
UPDATE transactions SET status = 'Completado' WHERE status = 'completed';
UPDATE transactions SET status = 'Pendiente' WHERE status = 'pending';
UPDATE transactions SET status = 'Cancelado' WHERE status = 'cancelled';
"""

UPDATE_LEGACY_PAYMENT_METHOD_VALUES_SQL = """
UPDATE transactions SET payment_method = 'Efectivo' WHERE payment_method = 'cash';
UPDATE transactions SET payment_method = 'Tarjeta de Débito' WHERE payment_method = 'debit card';
UPDATE transactions SET payment_method = 'Tarjeta de Crédito' WHERE payment_method = 'credit card';
UPDATE transactions SET payment_method = 'Transferencia' WHERE payment_method = 'transfer';
UPDATE transactions SET payment_method = 'Otro' WHERE payment_method = 'other';
"""

ALTER_ADD_DUE_DATE_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS due_date TIMESTAMP WITH TIME ZONE;
"""

ALTER_ADD_RECURRENCE_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS recurrence VARCHAR(100);
"""

ALTER_ADD_INSTALLMENT_NUMBER_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS installment_number INT;
"""

ALTER_ADD_INSTALLMENT_TOTAL_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS installment_total INT;
"""

ALTER_ADD_PARTICIPANTS_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS participants TEXT[];
"""

ALTER_ADD_SPLIT_DETAILS_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS split_details JSONB;
"""

ALTER_ADD_TRANSFER_DETAILS_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS transfer_details JSONB;
"""

ALTER_ADD_PACKAGE_DETAILS_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS package_details JSONB;
"""

ALTER_ADD_RELATED_TRANSACTION_ID_SQL = """
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS related_transaction_id UUID;
"""

ALTER_TYPE_CHECK_SQL = """
DO $$
BEGIN
    ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_type_check;
    ALTER TABLE transactions ADD CONSTRAINT transactions_type_check
        CHECK (type IN ('Gasto', 'Ingreso')) NOT VALID;
    ALTER TABLE transactions VALIDATE CONSTRAINT transactions_type_check;
END $$;
"""

ALTER_STATUS_CHECK_SQL = """
DO $$
BEGIN
    ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_status_check;
    ALTER TABLE transactions ADD CONSTRAINT transactions_status_check
        CHECK (status IN ('Completado', 'Pendiente', 'Cancelado')) NOT VALID;
    ALTER TABLE transactions VALIDATE CONSTRAINT transactions_status_check;
END $$;
"""

ALTER_PAYMENT_METHOD_CHECK_SQL = """
DO $$
BEGIN
    ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_payment_method_check;
    ALTER TABLE transactions ADD CONSTRAINT transactions_payment_method_check
        CHECK (payment_method IN ('Efectivo', 'Tarjeta de Débito', 'Tarjeta de Crédito', 'Transferencia', 'Otro')) NOT VALID;
    ALTER TABLE transactions VALIDATE CONSTRAINT transactions_payment_method_check;
END $$;
"""

UPDATE_NULL_TRANSACTION_DATE_SQL = """
UPDATE transactions
SET transaction_date = created_at
WHERE transaction_date IS NULL;
"""

ALTER_SET_DEFAULT_TRANSACTION_DATE_SQL = """
ALTER TABLE transactions
ALTER COLUMN transaction_date SET DEFAULT CURRENT_TIMESTAMP;
"""

STARTUP_MIGRATIONS = (
    CREATE_TABLE_SQL,
    ALTER_ADD_DESCRIPTION_SQL,
    ALTER_ADD_TRANSACTION_DATE_SQL,
    ALTER_ADD_TOTAL_AMOUNT_SQL,
    UPDATE_TOTAL_AMOUNT_SQL,
    ALTER_TOTAL_AMOUNT_NOT_NULL_SQL,
    ALTER_ADD_DUE_DATE_SQL,
    ALTER_ADD_RECURRENCE_SQL,
    ALTER_ADD_INSTALLMENT_NUMBER_SQL,
    ALTER_ADD_INSTALLMENT_TOTAL_SQL,
    ALTER_ADD_PARTICIPANTS_SQL,
    ALTER_ADD_SPLIT_DETAILS_SQL,
    ALTER_ADD_TRANSFER_DETAILS_SQL,
    ALTER_ADD_PACKAGE_DETAILS_SQL,
    ALTER_ADD_RELATED_TRANSACTION_ID_SQL,
    DROP_LEGACY_CHECKS_SQL,
    UPDATE_LEGACY_TYPE_VALUES_SQL,
    UPDATE_LEGACY_STATUS_VALUES_SQL,
    UPDATE_LEGACY_PAYMENT_METHOD_VALUES_SQL,
    ALTER_TYPE_CHECK_SQL,
    ALTER_STATUS_CHECK_SQL,
    ALTER_PAYMENT_METHOD_CHECK_SQL,
    UPDATE_NULL_TRANSACTION_DATE_SQL,
    ALTER_SET_DEFAULT_TRANSACTION_DATE_SQL,
)

INSERT_SQL = """
INSERT INTO transactions
    (type, amount, total_amount, currency, category, description, merchant,
     payment_method, status, tags, location, notes, transaction_date,
     due_date, recurrence, installment_number, installment_total,
     participants, split_details, transfer_details, package_details,
     related_transaction_id, original_message)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
        COALESCE($13::TIMESTAMP WITH TIME ZONE, CURRENT_TIMESTAMP),
        $14, $15, $16, $17, $18, $19, $20, $21, $22, $23)
RETURNING *;
"""

DELETE_SQL = """
DELETE FROM transactions WHERE id = $1 RETURNING *;
"""

MONTHLY_SUMMARY_SQL = """
SELECT type, category, SUM(amount) AS total
FROM transactions
WHERE date_trunc('month', transaction_date) = date_trunc('month', CURRENT_TIMESTAMP)
  AND status = 'Completado'
GROUP BY type, category
ORDER BY type, total DESC;
"""

MONTHLY_TOTALS_SQL = """
SELECT
    COALESCE(SUM(CASE WHEN type = 'Ingreso' THEN amount ELSE 0 END), 0) AS total_income,
    COALESCE(SUM(CASE WHEN type = 'Gasto' THEN amount ELSE 0 END), 0) AS total_expenses
FROM transactions
WHERE date_trunc('month', transaction_date) = date_trunc('month', CURRENT_TIMESTAMP)
  AND status = 'Completado';
"""

RECENT_SQL = """
SELECT * FROM transactions
ORDER BY transaction_date DESC, created_at DESC
LIMIT $1;
"""

ALL_SQL = """
SELECT * FROM transactions ORDER BY transaction_date DESC, created_at DESC;
"""

_DIMENSION_GROUP_EXPR = {
    "category": "category",
    "merchant": "merchant",
    "payment_method": "payment_method",
    "location": "location",
    "tag": "unnest(tags)",
}

_DIMENSION_VALUE_FILTERS = {
    "category": "category = $3",
    "merchant": "merchant = $3",
    "payment_method": "payment_method = $3",
    "location": "location = $3",
    "tag": "$3 = ANY(tags)",
}

REPORT_DIMENSION_SQL = {}
for _dimension in _DIMENSION_GROUP_EXPR:
    _group_expr = _DIMENSION_GROUP_EXPR[_dimension]
    _value_filter = _DIMENSION_VALUE_FILTERS[_dimension]
    REPORT_DIMENSION_SQL[_dimension] = (
        f"""SELECT {_group_expr} AS label, SUM(amount) AS total, currency
FROM transactions
WHERE status <> 'Cancelado'
  AND transaction_date >= $1 AND transaction_date < $2
GROUP BY {_group_expr}, currency
ORDER BY total DESC""",
        f"""SELECT {_group_expr} AS label, SUM(amount) AS total, currency
FROM transactions
WHERE status <> 'Cancelado'
  AND transaction_date >= $1 AND transaction_date < $2
  AND {_value_filter}
GROUP BY {_group_expr}, currency
ORDER BY total DESC""",
    )
del _dimension, _group_expr, _value_filter

REPORT_SUMMARY_SQL = """
SELECT
    COALESCE(SUM(amount) FILTER (WHERE type = 'Ingreso'), 0) AS income,
    COALESCE(SUM(amount) FILTER (WHERE type = 'Gasto'), 0) AS expenses,
    COALESCE(SUM(amount) FILTER (WHERE amount < total_amount), 0) AS shared_total,
    COALESCE(SUM(amount) FILTER (WHERE type = 'Ingreso'), 0)
        - COALESCE(SUM(amount) FILTER (WHERE type = 'Gasto'), 0) AS net,
    currency
FROM transactions
WHERE status <> 'Cancelado'
  AND transaction_date >= $1 AND transaction_date < $2
GROUP BY currency
ORDER BY currency;
"""

REPORT_SHARED_SQL = """
SELECT
    currency AS label,
    SUM(amount) AS amount,
    SUM(total_amount) AS total_amount,
    currency
FROM transactions
WHERE status <> 'Cancelado'
  AND transaction_date >= $1 AND transaction_date < $2
  AND amount < total_amount
GROUP BY currency
ORDER BY total_amount DESC;
"""

REPORT_INSTALLMENTS_SQL = """
SELECT
    COALESCE(NULLIF(merchant, ''), description, category) AS label,
    installment_number,
    installment_total,
    SUM(amount) AS amount,
    currency
FROM transactions
WHERE status <> 'Cancelado'
  AND transaction_date >= $1 AND transaction_date < $2
  AND installment_number IS NOT NULL
  AND installment_total IS NOT NULL
  AND installment_total > 1
GROUP BY label, installment_number, installment_total, currency
ORDER BY label, installment_number;
"""

REPORT_RECURRENCE_SQL = """
SELECT
    COALESCE(NULLIF(merchant, ''), description, category) AS label,
    recurrence,
    SUM(amount) AS amount,
    currency
FROM transactions
WHERE status <> 'Cancelado'
  AND transaction_date >= $1 AND transaction_date < $2
  AND recurrence IS NOT NULL
GROUP BY label, recurrence, currency
ORDER BY label;
"""

REPORT_DUE_DATES_SQL = """
SELECT
    COALESCE(NULLIF(merchant, ''), description, category) AS label,
    due_date,
    SUM(amount) AS amount,
    currency
FROM transactions
WHERE status <> 'Cancelado'
  AND transaction_date >= $1 AND transaction_date < $2
  AND due_date IS NOT NULL
GROUP BY label, due_date, currency
ORDER BY due_date;
"""

REPORT_TRANSFERS_SQL = """
SELECT
    COALESCE(
        transfer_details->>'counterparty',
        transfer_details->>'bank',
        description,
        merchant,
        category
    ) AS label,
    SUM(amount) AS amount,
    currency
FROM transactions
WHERE status <> 'Cancelado'
  AND transaction_date >= $1 AND transaction_date < $2
  AND transfer_details IS NOT NULL
GROUP BY label, currency
ORDER BY amount DESC;
"""

REPORT_REFUNDS_SQL = """
SELECT
    COALESCE(NULLIF(merchant, ''), description, category) AS label,
    SUM(amount) AS amount,
    currency
FROM transactions
WHERE status <> 'Cancelado'
  AND transaction_date >= $1 AND transaction_date < $2
  AND related_transaction_id IS NOT NULL
GROUP BY label, currency
ORDER BY amount DESC;
"""

REPORT_PACKAGES_SQL = """
SELECT
    COALESCE(
        package_details->>'name',
        package_details->>'provider',
        description,
        merchant,
        category
    ) AS label,
    SUM(amount) AS amount,
    currency
FROM transactions
WHERE status <> 'Cancelado'
  AND transaction_date >= $1 AND transaction_date < $2
  AND package_details IS NOT NULL
GROUP BY label, currency
ORDER BY amount DESC;
"""

REPORT_PERSON_SQL = """
SELECT
    kv.participant AS label,
    SUM(kv.share::numeric) AS total,
    t.currency
FROM transactions t
CROSS JOIN LATERAL jsonb_each_text(t.split_details) AS kv(participant, share)
WHERE t.status <> 'Cancelado'
  AND t.transaction_date >= $1 AND t.transaction_date < $2
  AND t.split_details IS NOT NULL
  AND jsonb_typeof(t.split_details) = 'object'
GROUP BY kv.participant, t.currency
ORDER BY total DESC;
"""


async def init_db() -> None:
    global pool
    try:
        pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=1, max_size=5)
        async with pool.acquire() as conn:
            for sql in STARTUP_MIGRATIONS:
                await conn.execute(sql)
        logger.info("Database pool created and schema verified")
    except Exception as e:
        logger.error("Failed to initialize database pool: %s", e)
        raise


async def close_db() -> None:
    global pool
    if pool:
        try:
            await pool.close()
            logger.info("Database pool closed")
        except Exception as e:
            logger.error("Error closing database pool: %s", e)
            raise
        finally:
            pool = None


def _parse_iso_datetime(value):
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning("Invalid ISO format for date '%s', falling back to None", value)
            return None
    return value


async def insert_transaction(data: dict) -> asyncpg.Record:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetchrow(
            INSERT_SQL,
            data["type"],
            data["amount"],
            data.get("total_amount", data["amount"]),
            data.get("currency", "ARS"),
            data["category"],
            data.get("description"),
            data.get("merchant"),
            data["payment_method"],
            data.get("status", "Completado"),
            data.get("tags"),
            data.get("location"),
            data.get("notes"),
            _parse_iso_datetime(data.get("transaction_date")),
            _parse_iso_datetime(data.get("due_date")),
            data.get("recurrence"),
            data.get("installment_number"),
            data.get("installment_total"),
            data.get("participants"),
            data.get("split_details"),
            data.get("transfer_details"),
            data.get("package_details"),
            data.get("related_transaction_id"),
            data.get("original_message"),
        )

    except Exception as e:
        logger.error("Error inserting transaction: %s", e)
        raise


async def delete_transaction(transaction_id: str) -> asyncpg.Record | None:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        uid = uuid.UUID(transaction_id)
    except ValueError:
        logger.warning("Invalid UUID string provided for transaction deletion: %s", transaction_id)
        return None

    try:
        return await pool.fetchrow(DELETE_SQL, uid)
    except Exception as e:
        logger.error("Error deleting transaction %s: %s", transaction_id, e)
        raise


async def get_monthly_summary() -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(MONTHLY_SUMMARY_SQL)
    except Exception as e:
        logger.error("Error fetching monthly summary: %s", e)
        raise


async def get_monthly_totals() -> asyncpg.Record:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetchrow(MONTHLY_TOTALS_SQL)
    except Exception as e:
        logger.error("Error fetching monthly totals: %s", e)
        raise


async def get_recent_transactions(limit: int = 10) -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(RECENT_SQL, limit)
    except Exception as e:
        logger.error("Error fetching recent transactions: %s", e)
        raise


async def get_all_transactions() -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(ALL_SQL)
    except Exception as e:
        logger.error("Error fetching all transactions: %s", e)
        raise


async def get_report_summary(start: datetime, end: datetime) -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(REPORT_SUMMARY_SQL, start, end)
    except Exception as e:
        logger.error("Error fetching report summary: %s", e)
        raise


async def get_report_by_dimension(
    dimension: str, start: datetime, end: datetime, value: str | None = None
) -> list[asyncpg.Record]:
    if dimension not in REPORT_DIMENSION_SQL:
        raise ValueError(f"Unsupported report dimension: {dimension}")
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    if value is None:
        sql, _ = REPORT_DIMENSION_SQL[dimension]
        params = [start, end]
    else:
        _, sql = REPORT_DIMENSION_SQL[dimension]
        params = [start, end, value]
    try:
        return await pool.fetch(sql, *params)
    except Exception as e:
        logger.error("Error fetching %s report: %s", dimension, e)
        raise


async def get_report_shared(start: datetime, end: datetime) -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(REPORT_SHARED_SQL, start, end)
    except Exception as e:
        logger.error("Error fetching shared report: %s", e)
        raise


async def get_report_installments(start: datetime, end: datetime) -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(REPORT_INSTALLMENTS_SQL, start, end)
    except Exception as e:
        logger.error("Error fetching installments report: %s", e)
        raise


async def get_report_recurrence(start: datetime, end: datetime) -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(REPORT_RECURRENCE_SQL, start, end)
    except Exception as e:
        logger.error("Error fetching recurrence report: %s", e)
        raise


async def get_report_due_dates(start: datetime, end: datetime) -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(REPORT_DUE_DATES_SQL, start, end)
    except Exception as e:
        logger.error("Error fetching due dates report: %s", e)
        raise


async def get_report_transfers(start: datetime, end: datetime) -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(REPORT_TRANSFERS_SQL, start, end)
    except Exception as e:
        logger.error("Error fetching transfers report: %s", e)
        raise


async def get_report_refunds(start: datetime, end: datetime) -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(REPORT_REFUNDS_SQL, start, end)
    except Exception as e:
        logger.error("Error fetching refunds report: %s", e)
        raise


async def get_report_packages(start: datetime, end: datetime) -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(REPORT_PACKAGES_SQL, start, end)
    except Exception as e:
        logger.error("Error fetching packages report: %s", e)
        raise


async def get_report_person(start: datetime, end: datetime) -> list[asyncpg.Record]:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        return await pool.fetch(REPORT_PERSON_SQL, start, end)
    except Exception as e:
        logger.error("Error fetching person report: %s", e)
        raise

