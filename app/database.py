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
    type VARCHAR(10) NOT NULL CHECK (type IN ('income', 'expense')),
    amount DECIMAL(12, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'ARS',
    category VARCHAR(100) NOT NULL,
    description VARCHAR(255),
    merchant VARCHAR(255),
    payment_method VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'completed'
        CHECK (status IN ('completed', 'pending', 'cancelled')),
    tags TEXT[],
    location VARCHAR(255),
    notes TEXT,
    transaction_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
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

UPDATE_NULL_TRANSACTION_DATE_SQL = """
UPDATE transactions
SET transaction_date = created_at
WHERE transaction_date IS NULL;
"""

ALTER_SET_DEFAULT_TRANSACTION_DATE_SQL = """
ALTER TABLE transactions
ALTER COLUMN transaction_date SET DEFAULT CURRENT_TIMESTAMP;
"""

INSERT_SQL = """
INSERT INTO transactions
    (type, amount, currency, category, description, merchant, payment_method,
     status, tags, location, notes, original_message, transaction_date)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, COALESCE($13::TIMESTAMP WITH TIME ZONE, CURRENT_TIMESTAMP))
RETURNING *;
"""

DELETE_SQL = """
DELETE FROM transactions WHERE id = $1 RETURNING *;
"""

MONTHLY_SUMMARY_SQL = """
SELECT type, category, SUM(amount) AS total
FROM transactions
WHERE date_trunc('month', transaction_date) = date_trunc('month', CURRENT_TIMESTAMP)
  AND status = 'completed'
GROUP BY type, category
ORDER BY type, total DESC;
"""

MONTHLY_TOTALS_SQL = """
SELECT
    COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) AS total_income,
    COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0) AS total_expenses
FROM transactions
WHERE date_trunc('month', transaction_date) = date_trunc('month', CURRENT_TIMESTAMP)
  AND status = 'completed';
"""

RECENT_SQL = """
SELECT * FROM transactions
ORDER BY transaction_date DESC, created_at DESC
LIMIT $1;
"""

ALL_SQL = """
SELECT * FROM transactions ORDER BY transaction_date DESC, created_at DESC;
"""


async def init_db() -> None:
    global pool
    try:
        pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=1, max_size=5)
        async with pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
            await conn.execute(ALTER_ADD_DESCRIPTION_SQL)
            await conn.execute(ALTER_ADD_TRANSACTION_DATE_SQL)
            await conn.execute(UPDATE_NULL_TRANSACTION_DATE_SQL)
            await conn.execute(ALTER_SET_DEFAULT_TRANSACTION_DATE_SQL)
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


async def insert_transaction(data: dict) -> asyncpg.Record:
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")
    try:
        tx_date = data.get("transaction_date")
        if isinstance(tx_date, str):
            try:
                tx_date = datetime.fromisoformat(tx_date)
            except ValueError:
                logger.warning(
                    "Invalid ISO format for transaction_date '%s', falling back to None",
                    tx_date,
                )
                tx_date = None


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
            tx_date,
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

