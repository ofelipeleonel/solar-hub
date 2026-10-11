from datetime import datetime
from unittest.mock import MagicMock

from solar_hub.services.budget import BudgetKeeperService


def test_budget_keeper_permits_when_within_quota():
    mock_repo = MagicMock()
    mock_repo.count_api_calls_this_month.return_value = 50
    mock_repo.count_api_calls_today.return_value = 5

    service = BudgetKeeperService(
        repository=mock_repo,
        monthly_limit=1000,
        window_start="06:00",
        window_end="18:00",
    )

    # Simula 10:00 da manhã (dentro da janela solar)
    dt_day = datetime(2026, 10, 9, 10, 0, 0)
    status = service.get_status(current_dt=dt_day)

    assert status.can_request_now is True
    assert status.remaining_month == 950
    assert status.calls_this_month == 50


def test_budget_keeper_blocks_at_night():
    mock_repo = MagicMock()
    mock_repo.count_api_calls_this_month.return_value = 50
    mock_repo.count_api_calls_today.return_value = 5

    service = BudgetKeeperService(
        repository=mock_repo,
        monthly_limit=1000,
        window_start="06:00",
        window_end="18:00",
    )

    # Simula 23:00 (noite)
    dt_night = datetime(2026, 10, 9, 23, 0, 0)
    status = service.get_status(current_dt=dt_night)

    assert status.is_solar_window is False
    assert status.can_request_now is False
    assert "janela solar" in status.reason.lower()


def test_budget_keeper_exhausted_monthly_limit():
    mock_repo = MagicMock()
    mock_repo.count_api_calls_this_month.return_value = 1000
    mock_repo.count_api_calls_today.return_value = 30

    service = BudgetKeeperService(
        repository=mock_repo,
        monthly_limit=1000,
        window_start="06:00",
        window_end="18:00",
    )

    dt_day = datetime(2026, 10, 9, 12, 0, 0)
    status = service.get_status(current_dt=dt_day)

    assert status.remaining_month == 0
    assert status.can_request_now is False
    assert "esgotada" in status.reason.lower()
