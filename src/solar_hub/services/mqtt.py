import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt

from solar_hub.db.repository import SolarRepository
from solar_hub.services.budget import BudgetKeeperService
from solar_hub.services.diagnostic import DiagnosticService

logger = logging.getLogger(__name__)


class HomeAssistantMqttService:
    """
    Serviço de publicação MQTT com suporte ao Home Assistant MQTT Discovery.
    Publica automaticamente entidades padronizadas de energia, potência, temperatura
    e status de governança de cota diretamente no broker MQTT.
    """

    def __init__(
        self,
        repository: SolarRepository,
        budget: BudgetKeeperService,
        system_sid: str,
        broker: str = "localhost",
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        discovery_prefix: str = "homeassistant",
        topic_prefix: str = "solarhub",
    ):
        self.repository = repository
        self.budget = budget
        self.system_sid = system_sid
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.discovery_prefix = discovery_prefix.rstrip("/")
        self.topic_prefix = topic_prefix.rstrip("/")

    @property
    def state_topic(self) -> str:
        return f"{self.topic_prefix}/{self.system_sid}/state"

    @property
    def availability_topic(self) -> str:
        return f"{self.topic_prefix}/{self.system_sid}/availability"

    def _get_device_dict(self) -> Dict[str, Any]:
        system = self.repository.get_system(self.system_sid)
        plant_name = system.name if system and system.name else f"Usina Solar ({self.system_sid[-6:]})"
        return {
            "identifiers": [f"solarhub_{self.system_sid}"],
            "name": plant_name,
            "manufacturer": "APsystems / SolarHub",
            "model": "SolarHub OpenAPI Monitor",
            "sw_version": "0.1.0",
        }

    def generate_discovery_configs(self) -> List[Dict[str, Any]]:
        """
        Gera as mensagens de configuração MQTT Discovery para o Home Assistant.
        """
        configs: List[Dict[str, Any]] = []
        device = self._get_device_dict()
        node_id = f"solarhub_{self.system_sid}"

        # 1. Energia Gerada Hoje (kWh)
        configs.append({
            "topic": f"{self.discovery_prefix}/sensor/{node_id}/today_kwh/config",
            "payload": {
                "name": "Energia Solar Hoje",
                "unique_id": f"{node_id}_today_kwh",
                "state_topic": self.state_topic,
                "value_template": "{{ value_json.today_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "total_increasing",
                "availability_topic": self.availability_topic,
                "device": device,
            },
        })

        # 2. Índice de Saúde Operacional (%)
        configs.append({
            "topic": f"{self.discovery_prefix}/sensor/{node_id}/health_score/config",
            "payload": {
                "name": "Índice de Saúde Operacional",
                "unique_id": f"{node_id}_health_score",
                "state_topic": self.state_topic,
                "value_template": "{{ value_json.health_score }}",
                "unit_of_measurement": "%",
                "icon": "mdi:solar-power-variant",
                "state_class": "measurement",
                "availability_topic": self.availability_topic,
                "device": device,
            },
        })

        # 3. Cota da API Restante (reqs)
        configs.append({
            "topic": f"{self.discovery_prefix}/sensor/{node_id}/budget_remaining/config",
            "payload": {
                "name": "Cota OpenAPI Restante",
                "unique_id": f"{node_id}_budget_remaining",
                "state_topic": self.state_topic,
                "value_template": "{{ value_json.budget_remaining }}",
                "unit_of_measurement": "req",
                "icon": "mdi:counter",
                "state_class": "measurement",
                "availability_topic": self.availability_topic,
                "device": device,
            },
        })

        # 4. Chamadas Consumidas no Mês (reqs)
        configs.append({
            "topic": f"{self.discovery_prefix}/sensor/{node_id}/budget_calls_this_month/config",
            "payload": {
                "name": "Chamadas OpenAPI no Mês",
                "unique_id": f"{node_id}_budget_calls_this_month",
                "state_topic": self.state_topic,
                "value_template": "{{ value_json.budget_calls_this_month }}",
                "unit_of_measurement": "req",
                "icon": "mdi:chart-arc",
                "state_class": "measurement",
                "availability_topic": self.availability_topic,
                "device": device,
            },
        })

        # 5. Sensores granulares por canal DC e microinversor
        today_str = date.today().isoformat()
        channels = self.repository.get_channel_telemetry_for_date(today_str)
        seen_inverters = set()

        for ch in channels:
            ch_key = f"inv_{ch.inverter_uid[-4:]}_ch{ch.channel}"

            # Energia do canal (kWh)
            configs.append({
                "topic": f"{self.discovery_prefix}/sensor/{node_id}/{ch_key}_energy/config",
                "payload": {
                    "name": f"Inversor {ch.inverter_uid[-4:]} Canal {ch.channel} Energia",
                    "unique_id": f"{node_id}_{ch_key}_energy",
                    "state_topic": self.state_topic,
                    "value_template": f"{{{{ value_json.{ch_key}_energy }}}}",
                    "unit_of_measurement": "kWh",
                    "device_class": "energy",
                    "state_class": "total_increasing",
                    "availability_topic": self.availability_topic,
                    "device": device,
                },
            })

            # Potência instantânea do canal (W)
            if ch.power_w is not None:
                configs.append({
                    "topic": f"{self.discovery_prefix}/sensor/{node_id}/{ch_key}_power/config",
                    "payload": {
                        "name": f"Inversor {ch.inverter_uid[-4:]} Canal {ch.channel} Potência",
                        "unique_id": f"{node_id}_{ch_key}_power",
                        "state_topic": self.state_topic,
                        "value_template": f"{{{{ value_json.{ch_key}_power }}}}",
                        "unit_of_measurement": "W",
                        "device_class": "power",
                        "state_class": "measurement",
                        "availability_topic": self.availability_topic,
                        "device": device,
                    },
                })

            # Temperatura do inversor (°C)
            if ch.inverter_uid not in seen_inverters and ch.temperature_c is not None:
                seen_inverters.add(ch.inverter_uid)
                inv_key = f"inv_{ch.inverter_uid[-4:]}"
                configs.append({
                    "topic": f"{self.discovery_prefix}/sensor/{node_id}/{inv_key}_temp/config",
                    "payload": {
                        "name": f"Inversor {ch.inverter_uid[-4:]} Temperatura",
                        "unique_id": f"{node_id}_{inv_key}_temp",
                        "state_topic": self.state_topic,
                        "value_template": f"{{{{ value_json.{inv_key}_temp }}}}",
                        "unit_of_measurement": "°C",
                        "device_class": "temperature",
                        "state_class": "measurement",
                        "availability_topic": self.availability_topic,
                        "device": device,
                    },
                })

        return configs

    def build_state_payload(self) -> Dict[str, Any]:
        """
        Monta o dicionário JSON de estado com telemetrias atuais.
        """
        today_str = date.today().isoformat()
        today_agg = self.repository.get_daily_aggregates(self.system_sid, limit=1)
        today_kwh = today_agg[0].energy_kwh if today_agg and today_agg[0].date == today_str else 0.0

        budget_status = self.budget.get_status()

        channels = self.repository.get_channel_telemetry_for_date(today_str)
        if channels:
            diag_service = DiagnosticService(self.repository)
            report = diag_service.evaluate_channels(channels)
            health_score = report.health_score
            anomalies_count = len(report.anomalies)
        else:
            health_score = 100
            anomalies_count = 0

        payload: Dict[str, Any] = {
            "today_kwh": round(today_kwh, 3),
            "health_score": health_score,
            "anomalies_count": anomalies_count,
            "budget_remaining": budget_status.remaining_month,
            "budget_calls_this_month": budget_status.calls_this_month,
            "budget_calls_today": budget_status.calls_today,
            "is_solar_window": budget_status.is_solar_window,
        }

        seen_inverters = set()
        for ch in channels:
            ch_key = f"inv_{ch.inverter_uid[-4:]}_ch{ch.channel}"
            payload[f"{ch_key}_energy"] = round(ch.energy_today_kwh, 3)
            if ch.power_w is not None:
                payload[f"{ch_key}_power"] = round(ch.power_w, 1)

            if ch.inverter_uid not in seen_inverters and ch.temperature_c is not None:
                seen_inverters.add(ch.inverter_uid)
                inv_key = f"inv_{ch.inverter_uid[-4:]}"
                payload[f"{inv_key}_temp"] = round(ch.temperature_c, 1)

        return payload

    def publish_all(self, client: Optional[mqtt.Client] = None) -> Dict[str, Any]:
        """
        Conecta ao broker MQTT, envia os tópicos de auto-descoberta e publica o estado atual.
        """
        owns_client = client is None
        if client is None:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"solarhub_{self.system_sid}")
            if self.username and self.password:
                client.username_pw_set(self.username, self.password)

            client.will_set(self.availability_topic, payload="offline", qos=1, retain=True)
            try:
                client.connect(self.broker, self.port, keepalive=60)
            except Exception as e:
                logger.error(f"Falha ao conectar ao broker MQTT ({self.broker}:{self.port}): {e}")
                return {"success": False, "error": str(e)}

        published_configs = 0
        try:
            # 1. Marca usina como online
            client.publish(self.availability_topic, payload="online", qos=1, retain=True)

            # 2. Publica as mensagens de auto-descoberta
            discovery_configs = self.generate_discovery_configs()
            for item in discovery_configs:
                payload_str = json.dumps(item["payload"])
                client.publish(item["topic"], payload=payload_str, qos=1, retain=True)
                published_configs += 1

            # 3. Publica o estado JSON atual
            state = self.build_state_payload()
            client.publish(self.state_topic, payload=json.dumps(state), qos=1, retain=True)

            logger.info(
                f"Publicação MQTT concluída: {published_configs} sensores descobertos e estado publicado em {self.state_topic}."
            )
            return {
                "success": True,
                "sensors_discovered": published_configs,
                "state_topic": self.state_topic,
                "payload": state,
            }
        finally:
            if owns_client:
                try:
                    client.disconnect()
                except Exception:
                    pass
