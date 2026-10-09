from dataclasses import dataclass
from datetime import datetime, date, time
import logging
import threading
import time as time_module
from typing import Optional

from solar_hub.client.client import APsystemsClient
from solar_hub.core.exceptions import BudgetKeeperBlockError
from solar_hub.db.repository import SolarRepository
from solar_hub.services.budget import BudgetKeeperService

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Resultado estruturado de uma sincronização de geração."""
    success: bool
    message: str
    target_date: str
    energy_today_kwh: float
    lifetime_kwh: float
    money_saved: float
    is_finalized: bool
    timestamp: datetime


class CollectorService:
    """
    Serviço central de coleta e consolidação periódica de telemetria solar.
    Opera como Daemon contínuo ou em modo one-shot (para Cron/Task Scheduler),
    sempre subordinado às diretrizes do Budget Keeper.
    """

    def __init__(
        self,
        client: APsystemsClient,
        repository: SolarRepository,
        budget: BudgetKeeperService,
        sid: str,
        tariff_rate: float = 0.92,
        nightly_time: str = "20:00",
    ):
        self.client = client
        self.repository = repository
        self.budget = budget
        self.sid = sid
        self.tariff_rate = tariff_rate
        self.nightly_time_obj = datetime.strptime(nightly_time, "%H:%M").time()

    def sync_current(self, force: bool = False) -> SyncResult:
        """
        Executa uma leitura instantânea da usina, computa a economia financeira
        e atualiza o registro do dia atual no banco SQLite.
        """
        # 1. Verifica autorização com o Guardião de Cota
        self.budget.verify_can_request(force=force)

        today_str = date.today().isoformat()
        logger.info(f"Executando sincronização para usina {self.sid} em {today_str}...")

        # 2. Faz a chamada pontual de resumo
        summary = self.client.get_system_summary(self.sid)

        # 3. Registra auditoria da chamada no banco
        self.repository.record_api_call(
            endpoint=f"/user/api/v2/systems/summary/{self.sid}",
            method="GET",
            status_code=200,
            success=True,
            notes=f"Sync Diurno: Hoje={summary.today_kwh}kWh",
        )

        # 4. Grava agregado diário
        money_saved = round(summary.today_kwh * self.tariff_rate, 2)
        self.repository.upsert_daily_aggregate(
            system_sid=self.sid,
            target_date=today_str,
            energy_kwh=summary.today_kwh,
            money_saved=money_saved,
            is_finalized=False,
        )

        return SyncResult(
            success=True,
            message="Sincronização diurna realizada com sucesso",
            target_date=today_str,
            energy_today_kwh=summary.today_kwh,
            lifetime_kwh=summary.lifetime_kwh,
            money_saved=money_saved,
            is_finalized=False,
            timestamp=datetime.now(),
        )

    def consolidate_nightly(self, force: bool = False) -> SyncResult:
        """
        Executa o fechamento noturno definitivo do dia (ex: às 20:00).
        Congela os dados do dia no SQLite com is_finalized=True.
        """
        # Fechamento noturno pode usar force=True para garantir o fechamento mesmo fora do horário solar
        today_str = date.today().isoformat()
        logger.info(f"Executando consolidação noturna definitiva de {today_str}...")

        summary = self.client.get_system_summary(self.sid)
        self.repository.record_api_call(
            endpoint=f"/user/api/v2/systems/summary/{self.sid}",
            method="GET",
            status_code=200,
            success=True,
            notes=f"Fechamento Noturno: Total do dia={summary.today_kwh}kWh",
        )

        money_saved = round(summary.today_kwh * self.tariff_rate, 2)
        self.repository.upsert_daily_aggregate(
            system_sid=self.sid,
            target_date=today_str,
            energy_kwh=summary.today_kwh,
            money_saved=money_saved,
            is_finalized=True,
        )

        return SyncResult(
            success=True,
            message="Consolidação noturna gravada e finalizada",
            target_date=today_str,
            energy_today_kwh=summary.today_kwh,
            lifetime_kwh=summary.lifetime_kwh,
            money_saved=money_saved,
            is_finalized=True,
            timestamp=datetime.now(),
        )

    def run_daemon(
        self,
        interval_minutes: int = 30,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        """
        Loop contínuo de background (Daemon).
        - Coleta diurna no intervalo configurado (respeitando a janela solar).
        - Executa o fechamento noturno às 20:00.
        - Entra em hibernação noturna profunda durante a madrugada (0 chamadas).
        """
        logger.info(
            f"Iniciando Coletor Daemon SolarHub (Intervalo: {interval_minutes}min, "
            f"Fechamento: {self.nightly_time_obj.strftime('%H:%M')})"
        )

        last_sync_time: Optional[datetime] = None
        last_finalized_date: Optional[str] = None

        while stop_event is None or not stop_event.is_set():
            now = datetime.now()
            today_str = now.date().isoformat()
            budget_status = self.budget.get_status(now)

            # 1. Checagem de Fechamento Noturno (ex: ~20:00)
            is_nightly_window = (
                now.time().hour == self.nightly_time_obj.hour
                and now.time().minute >= self.nightly_time_obj.minute
            )

            if is_nightly_window and last_finalized_date != today_str:
                try:
                    logger.info("Horário de consolidação noturna atingido!")
                    res = self.consolidate_nightly(force=True)
                    last_finalized_date = today_str
                    logger.info(f"Dia {today_str} consolidado: {res.energy_today_kwh:.2f} kWh gerados.")
                except Exception as e:
                    logger.error(f"Erro na consolidação noturna: {e}")

            # 2. Checagem de Coleta Diurna (Janela Solar Ativa)
            elif budget_status.is_solar_window:
                should_sync = False
                if last_sync_time is None:
                    should_sync = True
                else:
                    elapsed = (now - last_sync_time).total_seconds() / 60.0
                    if elapsed >= interval_minutes:
                        should_sync = True

                if should_sync and budget_status.can_request_now:
                    try:
                        logger.info("Janela solar ativa: executando sincronização periódica...")
                        res = self.sync_current(force=False)
                        last_sync_time = now
                        logger.info(
                            f"Sync realizado: {res.energy_today_kwh:.2f} kWh hoje. "
                            f"(Próxima coleta em ~{interval_minutes}min)"
                        )
                    except BudgetKeeperBlockError as bke:
                        logger.warning(f"Coleta prevenida pelo Budget Keeper: {bke}")
                    except Exception as e:
                        logger.error(f"Erro inesperado durante a coleta diurna: {e}")

            # Pausa de 30 segundos entre checagens do loop
            if stop_event:
                if stop_event.wait(timeout=30):
                    break
            else:
                time_module.sleep(30)

        logger.info("Coletor Daemon SolarHub encerrado com sucesso.")
