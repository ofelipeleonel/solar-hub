from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from solar_hub.client.models import SystemSummary
from solar_hub.core.exceptions import BudgetKeeperBlockError
from solar_hub.db.models import Base
from solar_hub.db.repository import SolarRepository
from solar_hub.services.collector import CollectorService


def test_collector_sync_current_success():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    repo = SolarRepository(session)

    mock_client = MagicMock()
    mock_client.get_system_summary.return_value = SystemSummary(
        today="18.50",
        month="150.00",
        year="2100.00",
        lifetime="63200.00",
    )

    mock_budget = MagicMock()
    mock_budget.verify_can_request.return_value = None  # Permite requisição

    service = CollectorService(
        client=mock_client,
        repository=repo,
        budget=mock_budget,
        sid="TEST_SYS_001",
    )

    result = service.sync_current(force=False)

    assert result.success is True
    assert result.energy_today_kwh == 18.50
    assert result.is_finalized is False

    # Valida persistência no repositório
    aggregates = repo.get_daily_aggregates("TEST_SYS_001")
    assert len(aggregates) == 1
    assert aggregates[0].energy_kwh == 18.50
    assert aggregates[0].is_finalized is False

    # Valida auditoria
    assert repo.count_api_calls_today() == 1


def test_collector_consolidate_nightly():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    repo = SolarRepository(session)

    mock_client = MagicMock()
    mock_client.get_system_summary.return_value = SystemSummary(
        today="24.80",
        month="160.00",
        year="2120.00",
        lifetime="63250.00",
    )
    mock_budget = MagicMock()

    service = CollectorService(
        client=mock_client,
        repository=repo,
        budget=mock_budget,
        sid="TEST_SYS_001",
    )

    result = service.consolidate_nightly(force=True)

    assert result.success is True
    assert result.energy_today_kwh == 24.80
    assert result.is_finalized is True

    aggregates = repo.get_daily_aggregates("TEST_SYS_001")
    assert len(aggregates) == 1
    assert aggregates[0].is_finalized is True


def test_collector_blocks_when_budget_keeper_denies():
    repo = MagicMock()
    mock_client = MagicMock()
    mock_budget = MagicMock()
    mock_budget.verify_can_request.side_effect = BudgetKeeperBlockError(
        reason="Fora da janela solar",
        calls_made_today=30,
        budget_limit=30,
    )

    service = CollectorService(
        client=mock_client,
        repository=repo,
        budget=mock_budget,
        sid="TEST_SYS_001",
    )

    with pytest.raises(BudgetKeeperBlockError):
        service.sync_current(force=False)


def test_collector_backfill_monthly_history_success():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    repo = SolarRepository(session)

    mock_client = MagicMock()
    # Simula resposta da APsystems para energy_level='daily', date_range='2026-10'
    mock_client.get_system_energy.return_value = {
        "energy": [15.2, 16.8, 14.0, 19.5],
        "time": ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"],
    }
    mock_budget = MagicMock()

    service = CollectorService(
        client=mock_client,
        repository=repo,
        budget=mock_budget,
        sid="TEST_SYS_001",
    )

    res = service.backfill_monthly_history("2026-10", force=True)

    assert res["success"] is True
    assert res["records_synced"] == 4
    assert res["month"] == "2026-10"

    # Confirma que os registros foram persistidos no banco
    records = repo.get_daily_aggregates_range("TEST_SYS_001", "2026-10-01", "2026-10-04")
    assert len(records) == 4
    assert records[0].date == "2026-10-01"
    assert records[0].energy_kwh == 15.2
    assert records[3].date == "2026-10-04"
    assert records[3].energy_kwh == 19.5


def test_collector_handles_quota_exceeded():
    from solar_hub.core.exceptions import QuotaExceededError

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    repo = SolarRepository(session)

    mock_client = MagicMock()
    mock_client.get_system_summary.side_effect = QuotaExceededError(
        code=2005,
        message="The access limit of the application account was exceeded",
        endpoint="/user/api/v2/systems/summary/TEST_SYS_001",
    )
    mock_budget = MagicMock()

    service = CollectorService(
        client=mock_client,
        repository=repo,
        budget=mock_budget,
        sid="TEST_SYS_001",
    )

    with pytest.raises(QuotaExceededError):
        service.sync_current(force=False)

    # Verifica se marcou a cota como esgotada no budget
    mock_budget.mark_quota_exhausted.assert_called_once()
    # Verifica se registrou a auditoria com código 2005
    calls = session.query(SolarRepository(session).record_api_call.__annotations__["return"]).all()
    assert len(calls) == 1
    assert calls[0].status_code == 2005
    assert calls[0].success is False
