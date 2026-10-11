import logging
from dataclasses import dataclass, field
from typing import Dict, List

from solar_hub.client.client import APsystemsClient
from solar_hub.db.repository import SolarRepository

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryResult:
    """Sumário do auto-mapeamento de hardware da usina solar."""
    sid: str
    capacity_kwp: float
    status_light: int
    timezone: str
    create_date: str
    ecus_count: int
    inverters_count: int
    estimated_total_panels: int
    inverters_by_model: Dict[str, int] = field(default_factory=dict)
    ecu_ids: List[str] = field(default_factory=list)


class HardwareDiscoveryService:
    """
    Serviço autônomo de descoberta de topologia.
    Examina a usina via OpenAPI da APsystems e adapta automaticamente o banco de dados local
    para qualquer configuração de hardware (múltiplas ECUs, modelos DS3, QS1, QT2, YC1000, etc.).
    """

    def __init__(self, client: APsystemsClient, repository: SolarRepository):
        self.client = client
        self.repository = repository

    def discover_and_sync(self, sid: str) -> DiscoveryResult:
        """
        Executa 2 requisições pontuais à APsystems, descobre toda a infraestrutura física
        e persiste as tabelas relacionais locais.
        """
        logger.info(f"Iniciando descoberta automática de hardware para a usina {sid}...")

        # 1. Consulta detalhes cadastrais da usina
        details = self.client.get_system_details(sid)
        self.repository.record_api_call(
            endpoint=f"/user/api/v2/systems/details/{sid}",
            method="GET",
            status_code=200,
            success=True,
            notes="Auto-Discovery: Detalhes da Usina"
        )

        self.repository.upsert_system(
            sid=details.sid,
            capacity_kwp=details.capacity_kwp,
            system_type=details.type,
            timezone=details.timezone,
            create_date=details.create_date,
            status_light=details.light,
        )


        # 2. Consulta lista de ECUs e microinversores
        ecu_list = self.client.get_system_inverters(sid)
        self.repository.record_api_call(
            endpoint=f"/user/api/v2/systems/inverters/{sid}",
            method="GET",
            status_code=200,
            success=True,
            notes="Auto-Discovery: Inversores e ECUs"
        )

        total_inverters = 0
        total_panels = 0
        model_counts: Dict[str, int] = {}
        ecu_ids: List[str] = []

        for ecu_data in ecu_list:
            ecu_ids.append(ecu_data.eid)
            self.repository.upsert_ecu(
                eid=ecu_data.eid,
                system_sid=details.sid,
                timezone=ecu_data.timezone,
                model=ecu_data.model,
            )

            for inv in ecu_data.inverter:
                total_inverters += 1
                channels = inv.estimated_channels_count
                total_panels += channels
                model_counts[inv.type] = model_counts.get(inv.type, 0) + 1

                self.repository.upsert_inverter(
                    uid=inv.uid,
                    ecu_eid=ecu_data.eid,
                    model=inv.type,
                    channels_count=channels,
                )

        logger.info(
            f"Descoberta concluída: {len(ecu_list)} ECU(s), {total_inverters} microinversores, "
            f"{total_panels} painéis estimados."
        )

        return DiscoveryResult(
            sid=details.sid,
            capacity_kwp=details.capacity_kwp,
            status_light=details.light,
            timezone=details.timezone,
            create_date=details.create_date,
            ecus_count=len(ecu_list),
            inverters_count=total_inverters,
            estimated_total_panels=total_panels,
            inverters_by_model=model_counts,
            ecu_ids=ecu_ids,
        )
