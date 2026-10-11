import json
from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from solar_hub.db.models import Base
from solar_hub.db.repository import SolarRepository
from solar_hub.services.budget import BudgetKeeperService
from solar_hub.services.mqtt import HomeAssistantMqttService


@pytest.fixture
def mqtt_env():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    repo = SolarRepository(session)

    today_str = date.today().isoformat()
    repo.upsert_system("SYSTEM_XYZ", capacity_kwp=6.2, name="Usina da Fazenda")
    repo.upsert_daily_aggregate("SYSTEM_XYZ", today_str, energy_kwh=28.40, is_finalized=False)
    repo.upsert_channel_telemetry(
        inverter_uid="401000009999",
        channel=1,
        date_str=today_str,
        energy_today_kwh=7.10,
        power_w=340.0,
        voltage_v=35.0,
        current_a=9.71,
        temperature_c=52.0,
        frequency_hz=60.0,
    )

    budget = BudgetKeeperService(repository=repo, monthly_limit=1000)
    service = HomeAssistantMqttService(
        repository=repo,
        budget=budget,
        system_sid="SYSTEM_XYZ",
        broker="mqtt.local",
        discovery_prefix="homeassistant",
        topic_prefix="solarhub",
    )

    yield service
    session.close()


def test_discovery_configs_generation(mqtt_env):
    service = mqtt_env
    configs = service.generate_discovery_configs()

    assert len(configs) >= 4  # today_kwh, health_score, budget_remaining, budget_calls, plus channel sensors

    # Procura config de energia do dia
    energy_cfg = next(c for c in configs if "today_kwh" in c["topic"])
    assert energy_cfg["topic"] == "homeassistant/sensor/solarhub_SYSTEM_XYZ/today_kwh/config"
    payload = energy_cfg["payload"]
    assert payload["device_class"] == "energy"
    assert payload["state_class"] == "total_increasing"
    assert payload["unit_of_measurement"] == "kWh"
    assert payload["device"]["name"] == "Usina da Fazenda"
    assert payload["device"]["identifiers"] == ["solarhub_SYSTEM_XYZ"]

    # Procura sensor de canal
    ch_power_cfg = next(c for c in configs if "ch1_power" in c["topic"])
    assert ch_power_cfg["payload"]["device_class"] == "power"
    assert ch_power_cfg["payload"]["unit_of_measurement"] == "W"


def test_build_state_payload(mqtt_env):
    service = mqtt_env
    state = service.build_state_payload()

    assert state["today_kwh"] == 28.4
    assert state["health_score"] == 100
    assert state["budget_remaining"] == 1000
    assert state["inv_9999_ch1_energy"] == 7.1
    assert state["inv_9999_ch1_power"] == 340.0
    assert state["inv_9999_temp"] == 52.0


def test_publish_all_with_mock_client(mqtt_env):
    service = mqtt_env
    mock_client = MagicMock()

    result = service.publish_all(client=mock_client)
    assert result["success"] is True
    assert result["sensors_discovered"] > 0
    assert result["state_topic"] == "solarhub/SYSTEM_XYZ/state"

    # Verifica se publicou availability "online"
    mock_client.publish.assert_any_call(
        "solarhub/SYSTEM_XYZ/availability", payload="online", qos=1, retain=True
    )

    # Verifica se publicou no state topic
    published_state = None
    for call in mock_client.publish.call_args_list:
        args, kwargs = call
        if args[0] == "solarhub/SYSTEM_XYZ/state":
            published_state = json.loads(kwargs["payload"])
            break

    assert published_state is not None
    assert published_state["today_kwh"] == 28.4
