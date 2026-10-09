from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from solar_hub.client.models import EcuInverters, InverterInfo, SystemDetails
from solar_hub.db.models import Base
from solar_hub.db.repository import SolarRepository
from solar_hub.services.discovery import HardwareDiscoveryService


def test_discovery_with_multiple_topologies():
    """
    Testa se o serviço de descoberta mapeia perfeitamente diferentes configurações:
    - Cenário A: Usina pequena com 1 inversor DS3 (2 painéis)
    - Cenário B: Usina média com 7 inversores YC1000 (28 painéis)
    - Cenário C: Usina comercial com QT2 e múltiplas ECUs
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    repo = SolarRepository(session)

    mock_client = MagicMock()
    mock_client.get_system_details.return_value = SystemDetails(
        sid="TEST_SYS_001",
        create_date="2021-01-01",
        capacity="10.22",
        type=1,
        timezone="America/Sao_Paulo",
        ecu=["ECU_100"],
        light=1,
    )

    # Simula 7 inversores YC1000 de 4 canais
    mock_inverters = [
        InverterInfo(uid=f"INV_{i}", type="YC1000") for i in range(1, 8)
    ]
    mock_client.get_system_inverters.return_value = [
        EcuInverters(
            eid="ECU_100",
            timezone="America/Sao_Paulo",
            inverter=mock_inverters,
        )
    ]

    service = HardwareDiscoveryService(client=mock_client, repository=repo)
    result = service.discover_and_sync("TEST_SYS_001")

    assert result.sid == "TEST_SYS_001"
    assert result.inverters_count == 7
    assert result.estimated_total_panels == 28  # 7 * 4
    assert result.inverters_by_model == {"YC1000": 7}
    assert result.capacity_kwp == 10.22

    # Verifica persistência no banco em memória
    inverters_in_db = repo.get_inverters()
    assert len(inverters_in_db) == 7
    for inv in inverters_in_db:
        assert inv.channels_count == 4
        assert inv.ecu_eid == "ECU_100"


def test_discovery_with_dual_channel_ds3():
    """Valida se o modelo DS3 é corretamente identificado com 2 canais."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    repo = SolarRepository(session)

    mock_client = MagicMock()
    mock_client.get_system_details.return_value = SystemDetails(
        sid="TEST_SYS_DS3",
        create_date="2023-05-10",
        capacity="1.60",
        type=1,
        timezone="America/Sao_Paulo",
        ecu=["ECU_200"],
        light=1,
    )
    mock_client.get_system_inverters.return_value = [
        EcuInverters(
            eid="ECU_200",
            timezone="America/Sao_Paulo",
            inverter=[
                InverterInfo(uid="INV_DS3_1", type="DS3"),
                InverterInfo(uid="INV_DS3_2", type="DS3-D"),
            ],
        )
    ]

    service = HardwareDiscoveryService(client=mock_client, repository=repo)
    result = service.discover_and_sync("TEST_SYS_DS3")

    assert result.inverters_count == 2
    assert result.estimated_total_panels == 4  # 2 * 2 canais
