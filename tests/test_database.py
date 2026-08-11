from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app import database


@pytest.mark.asyncio
async def test_init_db_runs_migrations():
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("app.database.asyncpg.create_pool", AsyncMock(return_value=mock_pool)):
        await database.init_db()

        assert mock_conn.execute.call_count == 5
        calls = [c[0][0] for c in mock_conn.execute.call_args_list]
        assert database.CREATE_TABLE_SQL in calls
        assert database.ALTER_ADD_DESCRIPTION_SQL in calls
        assert database.ALTER_ADD_TRANSACTION_DATE_SQL in calls
        assert database.UPDATE_NULL_TRANSACTION_DATE_SQL in calls
        assert database.ALTER_SET_DEFAULT_TRANSACTION_DATE_SQL in calls

    database.pool = None


@pytest.mark.asyncio
async def test_insert_transaction_with_transaction_date():
    mock_pool = MagicMock()
    mock_pool.fetchrow = AsyncMock(return_value={"id": "fake-uuid"})
    database.pool = mock_pool

    tx_date = datetime(2026, 8, 10, 15, 30, tzinfo=timezone.utc)
    data = {
        "type": "expense",
        "amount": 1500.0,
        "currency": "ARS",
        "category": "food",
        "description": "almuerzo",
        "merchant": "Restaurante",
        "payment_method": "cash",
        "status": "completed",
        "tags": ["food"],
        "location": "Centro",
        "notes": "con amigos",
        "original_message": "gaste 1500",
        "transaction_date": tx_date,
    }

    res = await database.insert_transaction(data)
    assert res == {"id": "fake-uuid"}
    mock_pool.fetchrow.assert_called_once()
    args = mock_pool.fetchrow.call_args[0]
    assert args[0] == database.INSERT_SQL
    assert args[13] == tx_date

    database.pool = None


@pytest.mark.asyncio
async def test_insert_transaction_with_iso_string_date():
    mock_pool = MagicMock()
    mock_pool.fetchrow = AsyncMock(return_value={"id": "fake-uuid"})
    database.pool = mock_pool

    data = {
        "type": "expense",
        "amount": 1500.0,
        "category": "food",
        "payment_method": "cash",
        "transaction_date": "2026-08-10T15:30:00+00:00",
    }

    await database.insert_transaction(data)
    mock_pool.fetchrow.assert_called_once()
    args = mock_pool.fetchrow.call_args[0]
    expected_dt = datetime(2026, 8, 10, 15, 30, tzinfo=timezone.utc)
    assert args[13] == expected_dt

    database.pool = None


@pytest.mark.asyncio
async def test_insert_transaction_with_invalid_iso_string_date_fallback():
    mock_pool = MagicMock()
    mock_pool.fetchrow = AsyncMock(return_value={"id": "fake-uuid"})
    database.pool = mock_pool

    data = {
        "type": "expense",
        "amount": 1500.0,
        "category": "food",
        "payment_method": "cash",
        "transaction_date": "not-a-valid-date",
    }

    await database.insert_transaction(data)
    mock_pool.fetchrow.assert_called_once()
    args = mock_pool.fetchrow.call_args[0]
    assert args[13] is None

    database.pool = None



@pytest.mark.asyncio
async def test_queries_use_transaction_date():
    assert "transaction_date" in database.CREATE_TABLE_SQL
    assert "transaction_date" in database.ALTER_ADD_TRANSACTION_DATE_SQL
    assert "transaction_date" in database.INSERT_SQL
    assert "transaction_date" in database.MONTHLY_SUMMARY_SQL
    assert "transaction_date" in database.MONTHLY_TOTALS_SQL
    assert "transaction_date" in database.RECENT_SQL
    assert "transaction_date" in database.ALL_SQL
