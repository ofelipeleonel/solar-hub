import logging
from typing import Any, Dict, List, Optional

import httpx

from solar_hub.client.auth import build_auth_headers
from solar_hub.client.models import (
    EcuBatchEnergy,
    EcuInverters,
    InverterChannelSummary,
    InverterTelemetry,
    SystemDetails,
    SystemSummary,
)
from solar_hub.core.exceptions import (
    APsystemsAPIError,
    APsystemsAuthError,
    QuotaExceededError,
)

logger = logging.getLogger(__name__)


class APsystemsClient:
    """
    Cliente HTTP resiliente para a OpenAPI v2 da APsystems.
    Gerencia automaticamente assinaturas HMAC-SHA256, cabeçalhos de segurança
    e conversão de erros de cota e autenticação em exceções tipadas.
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        base_url: str = "https://api.apsystemsema.com:9282",
        timeout: float = 20.0
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        endpoint_path: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executa uma requisição HTTP assinada via HMAC à APsystems e valida a resposta.
        """
        # O RequestPath para o HMAC é apenas o último segmento da URL
        last_segment = endpoint_path.rstrip("/").split("/")[-1]
        headers = build_auth_headers(
            app_id=self.app_id,
            app_secret=self.app_secret,
            request_path=last_segment,
            method=method
        )
        url = f"{self.base_url}{endpoint_path}"

        logger.debug(f"Fazendo requisição {method} para {url} (segmento: {last_segment})")

        with httpx.Client(timeout=self.timeout) as client:
            try:
                response = client.request(method, url, headers=headers, params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"Erro HTTP {e.response.status_code} ao acessar {url}")
                raise APsystemsAPIError(e.response.status_code, str(e), endpoint_path) from e
            except httpx.RequestError as e:
                logger.error(f"Falha de conexão com a APsystems: {e}")
                raise APsystemsAPIError(500, f"Falha de comunicação de rede: {e}", endpoint_path) from e

        data = response.json()
        code = data.get("code")

        if code == 0:
            return data.get("data")

        # Tratamento semântico de códigos de erro documentados pela APsystems
        msg = data.get("message", "Sem mensagem detalhada")
        if code in (2005, 7001):
            logger.critical(f"Cota da API esgotada ou limite de taxa excedido! Código: {code}")
            raise QuotaExceededError(code, f"Limite de requisições excedido: {msg}", endpoint_path)
        elif code in (2000, 2001, 2002, 2003, 2004, 3000, 3001, 3002):
            logger.error(f"Falha de autenticação/autorização na APsystems: {code} - {msg}")
            raise APsystemsAuthError(code, f"Erro de autenticação: {msg}", endpoint_path)
        else:
            logger.warning(f"Erro retornado pela API APsystems: code={code}, msg={msg}")
            raise APsystemsAPIError(code, msg, endpoint_path)

    def get_system_details(self, sid: str) -> SystemDetails:
        """
        Obtém os detalhes cadastrais e status geral da usina.
        Endpoint: GET /user/api/v2/systems/details/{sid}
        """
        path = f"/user/api/v2/systems/details/{sid}"
        raw_data = self._request(path)
        return SystemDetails(**raw_data)

    def get_system_inverters(self, sid: str) -> List[EcuInverters]:
        """
        Mapeia todas as ECUs e os respectivos microinversores vinculados à usina.
        Endpoint: GET /user/api/v2/systems/inverters/{sid}
        """
        path = f"/user/api/v2/systems/inverters/{sid}"
        raw_data = self._request(path)
        if isinstance(raw_data, list):
            return [EcuInverters(**item) for item in raw_data]
        return []

    def get_system_summary(self, sid: str) -> SystemSummary:
        """
        Obtém os valores consolidados de energia (hoje, mês, ano, lifetime).
        Endpoint: GET /user/api/v2/systems/summary/{sid}
        """
        path = f"/user/api/v2/systems/summary/{sid}"
        raw_data = self._request(path)
        return SystemSummary(**raw_data)

    def get_inverter_summary(self, sid: str, uid: str) -> InverterChannelSummary:
        """
        Obtém o resumo de energia por canal DC de um microinversor específico.
        Endpoint: GET /user/api/v2/systems/{sid}/devices/inverter/summary/{uid}
        """
        path = f"/user/api/v2/systems/{sid}/devices/inverter/summary/{uid}"
        raw_data = self._request(path)
        return InverterChannelSummary(**(raw_data or {}))

    def get_inverter_telemetry(
        self,
        sid: str,
        uid: str,
        energy_level: str = "minutely",
        date_range: Optional[str] = None,
    ) -> InverterTelemetry:
        """
        Obtém telemetria elétrica fina (potência DC/AC, tensão, corrente, temperatura, frequência).
        Endpoint: GET /user/api/v2/systems/{sid}/devices/inverter/energy/{uid}
        """
        path = f"/user/api/v2/systems/{sid}/devices/inverter/energy/{uid}"
        params: Dict[str, Any] = {"energy_level": energy_level}
        if date_range:
            params["date_range"] = date_range
        raw_data = self._request(path, params=params)
        return InverterTelemetry(**(raw_data or {}))

    def get_inverter_batch_energy(
        self,
        sid: str,
        eid: str,
        date_range: Optional[str] = None,
        energy_level: str = "energy",
    ) -> EcuBatchEnergy:
        """
        Obtém telemetria em lote de TODOS os microinversores de uma ECU com apenas 1 requisição.
        Endpoint: GET /user/api/v2/systems/{sid}/devices/inverter/batch/energy/{eid}
        """
        path = f"/user/api/v2/systems/{sid}/devices/inverter/batch/energy/{eid}"
        params: Dict[str, Any] = {"energy_level": energy_level}
        if date_range:
            params["date_range"] = date_range
        raw_data = self._request(path, params=params)
        return EcuBatchEnergy(**(raw_data or {}))

    def get_system_energy(self, sid: str, energy_level: str, date_range: Optional[str] = None) -> Dict[str, Any]:
        """
        Consulta o histórico de energia agregada do sistema (hourly, daily, monthly, yearly).
        Endpoint: GET /user/api/v2/systems/energy/{sid}
        """
        path = f"/user/api/v2/systems/energy/{sid}"
        params = {"energy_level": energy_level}
        if date_range:
            params["date_range"] = date_range
        return self._request(path, params=params)
