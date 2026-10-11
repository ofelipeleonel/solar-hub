from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from solar_hub.client.models import EcuBatchEnergy, InverterTelemetry
from solar_hub.db.models import Base, InverterChannelTelemetryRecord
from solar_hub.db.repository import SolarRepository
from solar_hub.services.diagnostic import DiagnosticService


def test_batch_energy_parsing():
    """Valida o parsing do lote de canais da ECU (uid-canal-energia)."""
    raw_payload = {
        "energy": [
            "401000001234-1-2.45",
            "401000001234-2-2.50",
            "401000001234-3-2.40",
            "401000001234-4-2.48",
            "401000005678-1-1.10",
        ]
    }
    batch = EcuBatchEnergy(**raw_payload)
    items = batch.get_channel_items()

    assert len(items) == 5
    assert items[0].uid == "401000001234"
    assert items[0].channel == 1
    assert items[0].energy_kwh == 2.45
    assert items[4].uid == "401000005678"
    assert items[4].channel == 1
    assert items[4].energy_kwh == 1.10


def test_inverter_telemetry_snapshot():
    """Valida a extração do snapshot elétrico instantâneo mais recente."""
    raw = {
        "t": ["11:00", "11:05", "11:10"],
        "dc_p1": ["280.0", "300.0", "310.5"],
        "dc_p2": ["285.0", "302.0", "312.0"],
        "dc_v1": ["34.5", "34.8", "35.0"],
        "dc_i1": ["8.1", "8.6", "8.8"],
        "ac_p": ["560.0", "600.0", "620.0"],
        "ac_v1": ["221.0", "222.5", "220.0"],
        "ac_t": ["45.0", "48.0", "50.2"],
        "ac_f": ["60.0", "60.0", "59.9"],
    }
    telemetry = InverterTelemetry(**raw)
    snapshot = telemetry.get_latest_snapshot()

    assert snapshot["time"] == "11:10"
    assert snapshot["dc_power_w"][1] == 310.5
    assert snapshot["dc_voltage_v"][1] == 35.0
    assert snapshot["dc_current_a"][1] == 8.8
    assert snapshot["ac_power_w"] == 620.0
    assert snapshot["ac_voltage_v"] == 220.0
    assert snapshot["temperature_c"] == 50.2
    assert snapshot["frequency_hz"] == 59.9


def test_diagnostic_healthy_plant():
    """Testa uma usina perfeitamente equilibrada (100% saudável)."""
    repo = None  # evaluate_channels não depende do banco
    service = DiagnosticService(repository=repo)

    channels = [
        InverterChannelTelemetryRecord(inverter_uid="INV_1", channel=1, date="2026-10-09", energy_today_kwh=3.2),
        InverterChannelTelemetryRecord(inverter_uid="INV_1", channel=2, date="2026-10-09", energy_today_kwh=3.3),
        InverterChannelTelemetryRecord(inverter_uid="INV_2", channel=1, date="2026-10-09", energy_today_kwh=3.1),
        InverterChannelTelemetryRecord(inverter_uid="INV_2", channel=2, date="2026-10-09", energy_today_kwh=3.25),
    ]

    report = service.evaluate_channels(channels)
    assert report.health_score == 100
    assert report.status == "HEALTHY"
    assert len(report.anomalies) == 0
    assert report.channels_evaluated == 4


def test_diagnostic_dead_channel_detected():
    """Detecta canal com zero produção enquanto outros operam normalmente."""
    service = DiagnosticService(repository=None)

    channels = [
        InverterChannelTelemetryRecord(inverter_uid="INV_1", channel=1, date="2026-10-09", energy_today_kwh=3.2),
        InverterChannelTelemetryRecord(inverter_uid="INV_1", channel=2, date="2026-10-09", energy_today_kwh=0.0),  # Morto!
        InverterChannelTelemetryRecord(inverter_uid="INV_2", channel=1, date="2026-10-09", energy_today_kwh=3.1),
    ]

    report = service.evaluate_channels(channels)
    assert report.health_score < 100
    assert any(a.anomaly_type == "DEAD_CHANNEL" and a.severity == "CRITICAL" for a in report.anomalies)
    assert any("MC4" in rec or "fiação" in rec for rec in report.recommendations)


def test_diagnostic_underperforming_channel():
    """Detecta placa com sujeira severa ou sombreamento persistente (>30% desvio)."""
    service = DiagnosticService(repository=None)

    channels = [
        InverterChannelTelemetryRecord(inverter_uid="INV_1", channel=1, date="2026-10-09", energy_today_kwh=4.0),
        InverterChannelTelemetryRecord(inverter_uid="INV_1", channel=2, date="2026-10-09", energy_today_kwh=4.0),
        InverterChannelTelemetryRecord(inverter_uid="INV_2", channel=1, date="2026-10-09", energy_today_kwh=2.1),  # -47% desvio!
        InverterChannelTelemetryRecord(inverter_uid="INV_2", channel=2, date="2026-10-09", energy_today_kwh=4.1),
    ]

    report = service.evaluate_channels(channels)
    assert report.health_score < 100
    assert any(a.anomaly_type == "UNDERPERFORMING_CHANNEL" and a.channel == 1 for a in report.anomalies)


def test_diagnostic_overheating_critical():
    """Detecta microinversor operando acima de 75°C (risco de dano)."""
    service = DiagnosticService(repository=None)

    channels = [
        InverterChannelTelemetryRecord(
            inverter_uid="INV_HOT", channel=1, date="2026-10-09", energy_today_kwh=3.0, temperature_c=78.5
        ),
    ]

    report = service.evaluate_channels(channels)
    assert any(a.anomaly_type == "OVERHEATING" and a.severity == "CRITICAL" for a in report.anomalies)


def test_repository_channel_telemetry_and_anomalies():
    """Testa persistência e recuperação de canais e anomalias no SQLite."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    repo = SolarRepository(session)

    # 1. Upsert canal
    rec = repo.upsert_channel_telemetry(
        inverter_uid="INV_TEST",
        channel=1,
        date_str="2026-10-09",
        energy_today_kwh=3.55,
        power_w=320.0,
        voltage_v=34.2,
        current_a=9.3,
        temperature_c=48.0,
        frequency_hz=60.0,
    )
    assert rec.id is not None
    assert rec.energy_today_kwh == 3.55

    # 2. Consulta canais do dia
    list_day = repo.get_channel_telemetry_for_date("2026-10-09")
    assert len(list_day) == 1
    assert list_day[0].inverter_uid == "INV_TEST"

    # 3. Salva e recupera anomalias
    anomalies_data = [
        {
            "inverter_uid": "INV_TEST",
            "channel": 1,
            "anomaly_type": "UNDERPERFORMING_CHANNEL",
            "severity": "WARNING",
            "message": "Canal 1 com desvio",
            "detected_value": 1.5,
            "reference_value": 3.5,
        }
    ]
    repo.save_anomalies(system_sid="SYS_1", anomalies=anomalies_data)
    stored = repo.get_latest_anomalies(system_sid="SYS_1")
    assert len(stored) == 1
    assert stored[0].anomaly_type == "UNDERPERFORMING_CHANNEL"
    assert stored[0].severity == "WARNING"
