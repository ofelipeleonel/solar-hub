from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from solar_hub.db.models import Base
from solar_hub.db.repository import SolarRepository
from solar_hub.services.budget import BudgetKeeperService
from solar_hub.services.metrics import PrometheusMetricsService


@pytest.fixture
def metrics_env():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    repo = SolarRepository(session)

    # Cria usina e telemetria
    today_str = date.today().isoformat()
    repo.upsert_system("SYSTEM_ABC", capacity_kwp=4.5)
    repo.upsert_daily_aggregate("SYSTEM_ABC", today_str, energy_kwh=16.85, is_finalized=False)
    repo.upsert_channel_telemetry(
        inverter_uid="INV_01",
        channel=1,
        date_str=today_str,
        energy_today_kwh=4.20,
        power_w=315.0,
        voltage_v=34.8,
        current_a=9.05,
        temperature_c=49.2,
        frequency_hz=60.0,
    )

    budget = BudgetKeeperService(
        repository=repo,
        monthly_limit=1000,
        reserve_calls_daily=4,
    )

    yield repo, budget
    session.close()


def test_prometheus_metrics_format(metrics_env):
    repo, budget = metrics_env
    service = PrometheusMetricsService(repository=repo, budget=budget, system_sid="SYSTEM_ABC")
    text = service.generate_metrics()

    # Validações estruturais do Prometheus Exposition 0.0.4
    assert "# HELP solar_today_kwh" in text
    assert "# TYPE solar_today_kwh gauge" in text
    assert 'solar_today_kwh{system_id="SYSTEM_ABC"} 16.850' in text

    assert "# HELP solar_capacity_kwp" in text
    assert 'solar_capacity_kwp{system_id="SYSTEM_ABC"} 4.50' in text

    assert "# HELP solar_health_score" in text
    assert 'solar_health_score{system_id="SYSTEM_ABC"} 100' in text

    assert "# HELP solar_budget_calls_this_month" in text
    assert 'solar_budget_monthly_limit{system_id="SYSTEM_ABC"} 1000' in text

    # Telemetria de canal
    assert 'solar_channel_energy_today_kwh{system_id="SYSTEM_ABC",inverter_uid="INV_01",channel="1"} 4.200' in text
    assert 'solar_channel_power_watts{system_id="SYSTEM_ABC",inverter_uid="INV_01",channel="1"} 315.0' in text
    assert 'solar_channel_voltage_volts{system_id="SYSTEM_ABC",inverter_uid="INV_01",channel="1"} 34.8' in text
    assert 'solar_inverter_temperature_celsius{system_id="SYSTEM_ABC",inverter_uid="INV_01"} 49.2' in text
