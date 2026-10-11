import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from solar_hub.db.models import Base
from solar_hub.db.repository import SolarRepository
from solar_hub.services.export import ExportService


@pytest.fixture
def repo_with_data():
    """Cria um banco SQLite em memória com dados simulados para exportação."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    repo = SolarRepository(session)

    # Popula dados de geração diária
    repo.upsert_daily_aggregate("SID_123", "2026-10-01", 22.450, is_finalized=True)
    repo.upsert_daily_aggregate("SID_123", "2026-10-02", 25.120, is_finalized=True)
    repo.upsert_daily_aggregate("SID_123", "2026-10-03", 18.800, is_finalized=False)

    # Popula dados de telemetria por canal
    repo.upsert_channel_telemetry(
        inverter_uid="INV_01",
        channel=1,
        date_str="2026-10-02",
        energy_today_kwh=6.25,
        power_w=320.0,
        voltage_v=34.5,
        current_a=9.2,
        temperature_c=48.5,
        frequency_hz=60.0,
    )
    repo.upsert_channel_telemetry(
        inverter_uid="INV_01",
        channel=2,
        date_str="2026-10-02",
        energy_today_kwh=6.30,
        power_w=322.0,
        voltage_v=34.6,
        current_a=9.3,
        temperature_c=48.5,
        frequency_hz=60.0,
    )

    yield repo
    session.close()


def test_export_generation_csv(repo_with_data):
    """Testa a exportação da geração diária no formato CSV."""
    service = ExportService(repo_with_data, system_sid="SID_123")
    csv_content = service.export_generation(export_format="csv")

    lines = csv_content.strip().split("\n")
    assert len(lines) == 4  # 1 cabeçalho + 3 dias
    assert "system_sid,date,energy_kwh,peak_power_w,is_finalized,updated_at" in lines[0]
    assert "SID_123,2026-10-01,22.450" in lines[1]
    assert "SID_123,2026-10-02,25.120" in lines[2]
    assert "SID_123,2026-10-03,18.800" in lines[3]


def test_export_generation_json(repo_with_data):
    """Testa a exportação da geração diária no formato JSON com filtro de período."""
    service = ExportService(repo_with_data, system_sid="SID_123")
    json_str = service.export_generation(
        export_format="json",
        start_date="2026-10-02",
        end_date="2026-10-03",
    )

    data = json.loads(json_str)
    assert len(data) == 2
    assert data[0]["date"] == "2026-10-02"
    assert data[0]["energy_kwh"] == 25.120
    assert data[1]["date"] == "2026-10-03"


def test_export_channels_csv_and_file(repo_with_data, tmp_path):
    """Testa a exportação de canais em CSV gravando diretamente em disco."""
    service = ExportService(repo_with_data, system_sid="SID_123")
    out_file = tmp_path / "subfolder" / "channels.csv"

    csv_content = service.export_channels(export_format="csv", output_file=out_file)

    assert out_file.exists()
    saved_text = out_file.read_text(encoding="utf-8")
    assert saved_text == csv_content

    lines = csv_content.strip().split("\n")
    assert len(lines) == 3  # Cabeçalho + 2 canais
    assert "inverter_uid,channel,date,energy_today_kwh,power_w" in lines[0]
    assert "INV_01,1,2026-10-02,6.250,320.0,34.5,9.20,48.5,60.0" in lines[1]
    assert "INV_01,2,2026-10-02,6.300,322.0,34.6,9.30,48.5,60.0" in lines[2]


def test_export_channels_json(repo_with_data):
    """Testa a exportação de canais em JSON com filtro de microinversor."""
    service = ExportService(repo_with_data, system_sid="SID_123")
    json_str = service.export_channels(
        export_format="json",
        inverter_uid="INV_01",
    )

    data = json.loads(json_str)
    assert len(data) == 2
    assert data[0]["inverter_uid"] == "INV_01"
    assert data[0]["channel"] == 1
    assert data[0]["power_w"] == 320.0


def test_export_summary(repo_with_data):
    """Testa a geração de resumo estatístico do banco."""
    service = ExportService(repo_with_data, system_sid="SID_123")
    summary = service.export_summary()

    assert summary["system_sid"] == "SID_123"
    assert summary["total_days_recorded"] == 3
    assert summary["total_energy_kwh"] == round(22.450 + 25.120 + 18.800, 2)
    assert summary["channel_records_count"] == 2
    assert summary["date_range"]["start"] == "2026-10-01"
    assert summary["date_range"]["end"] == "2026-10-03"


def test_invalid_format_raises_error(repo_with_data):
    """Garante que formatos desconhecidos geram ValueError explicativo."""
    service = ExportService(repo_with_data, system_sid="SID_123")
    with pytest.raises(ValueError, match="Formato não suportado"):
        service.export_generation(export_format="xml")
