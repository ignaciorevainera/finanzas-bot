from datetime import datetime, timezone
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app import database


def test_schema_documentation_mentions_personal_and_total_amounts():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "total_amount" in readme
    assert "amount" in readme
    assert "Agregar más" in readme


def test_schema_documentation_describes_spanish_canonical_values():
    readme = Path("README.md").read_text(encoding="utf-8")
    for value in (
        "Gasto", "Ingreso",
        "Completado", "Pendiente", "Cancelado",
        "Efectivo", "Tarjeta de Débito", "Tarjeta de Crédito", "Transferencia", "Otro",
    ):
        assert value in readme


def test_schema_documentation_describes_advanced_columns_and_amount_semantics():
    readme = Path("README.md").read_text(encoding="utf-8")
    for field in (
        "due_date", "recurrence", "installment_number", "installment_total",
        "participants", "split_details", "transfer_details", "package_details",
        "related_transaction_id",
    ):
        assert field in readme


@pytest.mark.asyncio
async def test_init_db_runs_migrations():
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("app.database.asyncpg.create_pool", AsyncMock(return_value=mock_pool)):
        await database.init_db()

        assert mock_conn.execute.call_count == len(database.STARTUP_MIGRATIONS)
        calls = [c[0][0] for c in mock_conn.execute.call_args_list]
        assert calls == list(database.STARTUP_MIGRATIONS)
        constraint_sql = "\n".join(calls)
        assert "DROP CONSTRAINT IF EXISTS" in constraint_sql
        assert "ADD CONSTRAINT" in constraint_sql
        assert "UPDATE transactions SET total_amount = amount" in constraint_sql
        assert "ALTER COLUMN total_amount SET NOT NULL" in constraint_sql
        assert "UPDATE transactions SET type = 'Ingreso'" in constraint_sql
        assert "SET NOT NULL" in database.ALTER_TOTAL_AMOUNT_NOT_NULL_SQL
        assert "WHERE total_amount IS NULL" in database.UPDATE_TOTAL_AMOUNT_SQL
        assert "ALTER COLUMN total_amount SET NOT NULL" in database.ALTER_TOTAL_AMOUNT_NOT_NULL_SQL

    database.pool = None


def test_migrations_harden_against_legacy_rows():
    migration_sql = "\n".join(database.STARTUP_MIGRATIONS)
    assert "ADD COLUMN IF NOT EXISTS total_amount DECIMAL(12, 2);" in migration_sql
    assert "UPDATE transactions SET total_amount = amount" in migration_sql
    assert "SET NOT NULL;" in migration_sql
    assert "UPDATE transactions SET type = 'Ingreso'" in migration_sql
    assert "UPDATE transactions SET status = 'Completado'" in migration_sql
    assert "UPDATE transactions SET payment_method = 'Efectivo'" in migration_sql
    assert "DROP CONSTRAINT IF EXISTS transactions_type_check;" in migration_sql
    assert "DROP CONSTRAINT IF EXISTS transactions_status_check;" in migration_sql
    assert "DROP CONSTRAINT IF EXISTS transactions_payment_method_check;" in migration_sql


def test_legacy_checks_dropped_before_value_migration():
    names = [c for c in database.STARTUP_MIGRATIONS if c is database.DROP_LEGACY_CHECKS_SQL]
    assert names == [database.DROP_LEGACY_CHECKS_SQL]
    legacy_updates = [
        c for c in database.STARTUP_MIGRATIONS
        if c in (
            database.UPDATE_LEGACY_TYPE_VALUES_SQL,
            database.UPDATE_LEGACY_STATUS_VALUES_SQL,
            database.UPDATE_LEGACY_PAYMENT_METHOD_VALUES_SQL,
        )
    ]
    assert len(legacy_updates) == 3
    drop_idx = database.STARTUP_MIGRATIONS.index(database.DROP_LEGACY_CHECKS_SQL)
    update_idx = database.STARTUP_MIGRATIONS.index(database.UPDATE_LEGACY_TYPE_VALUES_SQL)
    assert drop_idx < update_idx
    for u in legacy_updates:
        assert database.STARTUP_MIGRATIONS.index(u) > drop_idx
    for check in (database.ALTER_TYPE_CHECK_SQL, database.ALTER_STATUS_CHECK_SQL, database.ALTER_PAYMENT_METHOD_CHECK_SQL):
        assert database.STARTUP_MIGRATIONS.index(check) > drop_idx


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
    assert args[3] == 120000
    assert args[18] == ["Viole"]

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


def test_queries_filter_on_spanish_status_and_type():
    monthly_sql = database.MONTHLY_SUMMARY_SQL + database.MONTHLY_TOTALS_SQL
    for spanish_value in ("'Completado'", "'Ingreso'", "'Gasto'"):
        assert spanish_value in monthly_sql
    for english_literal in ("'completed'", "'income'", "'expense'"):
        assert english_literal not in monthly_sql


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


@pytest.mark.asyncio
async def test_get_report_summary_uses_personal_amounts_and_currency_groups():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_summary(start, end)

    sql, *params = mock_pool.fetch.call_args.args
    assert "SUM(amount)" in sql
    assert "SUM(total_amount) FILTER (WHERE amount < total_amount)" in sql
    assert "AS income" in sql
    assert "AS expenses" in sql
    assert "AS shared_total" in sql
    assert "AS net" in sql
    assert "status <> 'Cancelado'" in sql
    assert "transaction_date >= $1" in sql
    assert "transaction_date < $2" in sql
    assert "GROUP BY currency" in sql
    assert params == [start, end]


@pytest.mark.asyncio
async def test_get_report_by_dimension_covers_every_allowlisted_dimension():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    for dimension in ("category", "merchant", "payment_method", "location", "tag"):
        mock_pool.fetch.reset_mock()
        await database.get_report_by_dimension(dimension, start, end, None)
        sql, *params = mock_pool.fetch.call_args.args
        assert "SUM(amount)" in sql
        assert "AS total" in sql
        assert "status <> 'Cancelado'" in sql
        assert "transaction_date >= $1" in sql
        assert "transaction_date < $2" in sql
        assert "total_amount" not in sql
        assert params == [start, end]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_by_dimension_tag_groups_by_unnested_tags():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool

    await database.get_report_by_dimension(
        "tag",
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        None,
    )

    sql = mock_pool.fetch.call_args.args[0]
    assert "unnest(tags)" in sql
    assert "AS label" in sql

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_by_dimension_category_binds_value_filter():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_by_dimension("category", start, end, "Comida")

    sql, *params = mock_pool.fetch.call_args.args
    assert "category = $3" in sql
    assert params == [start, end, "Comida"]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_by_dimension_merchant_binds_value_filter():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_by_dimension("merchant", start, end, "Restaurante")

    sql, *params = mock_pool.fetch.call_args.args
    assert "merchant = $3" in sql
    assert params == [start, end, "Restaurante"]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_by_dimension_payment_method_binds_value_filter():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_by_dimension("payment_method", start, end, "Tarjeta de Crédito")

    sql, *params = mock_pool.fetch.call_args.args
    assert "payment_method = $3" in sql
    assert params == [start, end, "Tarjeta de Crédito"]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_by_dimension_location_binds_value_filter():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_by_dimension("location", start, end, "Centro")

    sql, *params = mock_pool.fetch.call_args.args
    assert "location = $3" in sql
    assert params == [start, end, "Centro"]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_by_dimension_tag_binds_array_filter():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_by_dimension("tag", start, end, "Familia")

    sql, *params = mock_pool.fetch.call_args.args
    assert "$3 = ANY(tags)" in sql
    assert params == [start, end, "Familia"]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_by_dimension_rejects_unknown_dimension():
    with pytest.raises(ValueError):
        await database.get_report_by_dimension(
            "not-a-dimension",
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 9, 1, tzinfo=timezone.utc),
            None,
        )


@pytest.mark.asyncio
async def test_get_report_installments_filters_installment_rows():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_installments(start, end)

    sql, *params = mock_pool.fetch.call_args.args
    assert "installment_number" in sql
    assert "installment_total" in sql
    assert "SUM(amount) AS amount" in sql
    assert "status <> 'Cancelado'" in sql
    assert "transaction_date >= $1" in sql
    assert "transaction_date < $2" in sql
    assert params == [start, end]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_recurrence_filters_recurring_rows():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_recurrence(start, end)

    sql, *params = mock_pool.fetch.call_args.args
    assert "recurrence" in sql
    assert "SUM(amount) AS amount" in sql
    assert "status <> 'Cancelado'" in sql
    assert "transaction_date >= $1" in sql
    assert "transaction_date < $2" in sql
    assert params == [start, end]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_due_dates_filters_rows_with_due_date():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_due_dates(start, end)

    sql, *params = mock_pool.fetch.call_args.args
    assert "due_date" in sql
    assert "SUM(amount) AS amount" in sql
    assert "status <> 'Cancelado'" in sql
    assert "transaction_date >= $1" in sql
    assert "transaction_date < $2" in sql
    assert params == [start, end]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_transfers_uses_jsonb_operator():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_transfers(start, end)

    sql, *params = mock_pool.fetch.call_args.args
    assert "transfer_details->>" in sql
    assert "transfer_details IS NOT NULL" in sql
    assert "SUM(amount) AS amount" in sql
    assert "status <> 'Cancelado'" in sql
    assert "transaction_date >= $1" in sql
    assert "transaction_date < $2" in sql
    assert params == [start, end]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_refunds_filters_related_transactions():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_refunds(start, end)

    sql, *params = mock_pool.fetch.call_args.args
    assert "related_transaction_id IS NOT NULL" in sql
    assert "SUM(amount) AS amount" in sql
    assert "status <> 'Cancelado'" in sql
    assert "transaction_date >= $1" in sql
    assert "transaction_date < $2" in sql
    assert params == [start, end]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_packages_uses_jsonb_operator():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_packages(start, end)

    sql, *params = mock_pool.fetch.call_args.args
    assert "package_details->>" in sql
    assert "package_details IS NOT NULL" in sql
    assert "SUM(amount) AS amount" in sql
    assert "status <> 'Cancelado'" in sql
    assert "transaction_date >= $1" in sql
    assert "transaction_date < $2" in sql
    assert params == [start, end]

    database.pool = None


@pytest.mark.asyncio
async def test_get_report_person_uses_split_details_jsonb():
    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(return_value=[])
    database.pool = mock_pool
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, tzinfo=timezone.utc)

    await database.get_report_person(start, end)

    sql, *params = mock_pool.fetch.call_args.args
    assert "jsonb_each_text" in sql
    assert "split_details IS NOT NULL" in sql
    assert "SUM(" in sql
    assert "AS total" in sql
    assert "AS label" in sql
    assert "status <> 'Cancelado'" in sql
    assert "transaction_date >= $1" in sql
    assert "transaction_date < $2" in sql
    assert params == [start, end]

    database.pool = None


def test_dimension_allowlist_matches_expected_dimensions():
    assert set(database.REPORT_DIMENSION_SQL) == {
        "category", "merchant", "payment_method", "location", "tag",
    }


def _all_report_sql():
    dimension_variants = [
        variant
        for pair in database.REPORT_DIMENSION_SQL.values()
        for variant in pair
    ]
    return dimension_variants + [
        database.REPORT_SUMMARY_SQL,
        database.REPORT_SHARED_SQL,
        database.REPORT_INSTALLMENTS_SQL,
        database.REPORT_RECURRENCE_SQL,
        database.REPORT_DUE_DATES_SQL,
        database.REPORT_TRANSFERS_SQL,
        database.REPORT_REFUNDS_SQL,
        database.REPORT_PACKAGES_SQL,
        database.REPORT_PERSON_SQL,
    ]


def test_all_report_queries_filter_cancelled_and_use_half_open_bounds():
    for sql in _all_report_sql():
        assert "status <> 'Cancelado'" in sql
        assert "transaction_date >= $1" in sql
        assert "transaction_date < $2" in sql
        assert "SUM(" in sql


def test_report_queries_bind_values_not_interpolate_them():
    for sql in _all_report_sql():
        assert "2026" not in sql
        assert "Comida" not in sql
    filtered_variants = [
        pair[1]
        for pair in database.REPORT_DIMENSION_SQL.values()
    ]
    for sql in filtered_variants:
        assert "$3" in sql
