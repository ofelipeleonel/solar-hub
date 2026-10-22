import logging
import threading
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from solar_hub.services.mqtt import HomeAssistantMqttService
    from solar_hub.services.notification import NotificationService

from solar_hub.client.client import APsystemsClient
from solar_hub.core.exceptions import BudgetKeeperBlockError, QuotaExceededError
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
        nightly_time: str = "20:00",
        notifier: Optional["NotificationService"] = None,
        mqtt_service: Optional["HomeAssistantMqttService"] = None,
    ):
        self.client = client
        self.repository = repository
        self.budget = budget
        self.sid = sid
        self.nightly_time_obj = datetime.strptime(nightly_time, "%H:%M").time()
        self.notifier = notifier
        self.mqtt_service = mqtt_service



    def sync_current(self, force: bool = False) -> SyncResult:
        """
        Executa uma leitura instantânea da usina e atualiza o registro do dia atual no banco SQLite.
        """
        # 1. Verifica autorização com o Guardião de Cota
        self.budget.verify_can_request(force=force)

        today_str = date.today().isoformat()
        logger.info(f"Executando sincronização para usina {self.sid} em {today_str}...")

        # 2. Faz a chamada pontual de resumo
        try:
            summary = self.client.get_system_summary(self.sid)
        except QuotaExceededError as qe:
            self.budget.mark_quota_exhausted(str(qe))
            self.repository.record_api_call(
                endpoint=f"/user/api/v2/systems/summary/{self.sid}",
                method="GET",
                status_code=2005,
                success=False,
                notes="Quota Exceeded (2005)",
            )
            raise

        # 3. Registra auditoria da chamada no banco
        self.repository.record_api_call(
            endpoint=f"/user/api/v2/systems/summary/{self.sid}",
            method="GET",
            status_code=200,
            success=True,
            notes=f"Sync Diurno: Hoje={summary.today_kwh}kWh",
        )

        # 4. Grava agregado diário
        self.repository.upsert_daily_aggregate(
            system_sid=self.sid,
            target_date=today_str,
            energy_kwh=summary.today_kwh,
            is_finalized=False,
        )

        # 5. Avalia alertas (produção ao meio-dia e consumo de cota)
        if self.notifier:
            try:
                self.notifier.check_midday_production(summary.today_kwh, datetime.now())
                b_status = self.budget.get_status()
                self.notifier.check_budget_status(b_status)
            except Exception as ne:
                logger.warning(f"Erro ao avaliar alertas no sync_current: {ne}")

        # 6. Publica telemetria no Home Assistant via MQTT se habilitado
        if self.mqtt_service:
            try:
                self.mqtt_service.publish_all()
            except Exception as me:
                logger.warning(f"Erro ao publicar MQTT no sync_current: {me}")

        return SyncResult(


            success=True,
            message="Sincronização diurna realizada com sucesso",
            target_date=today_str,
            energy_today_kwh=summary.today_kwh,
            lifetime_kwh=summary.lifetime_kwh,
            is_finalized=False,
            timestamp=datetime.now(),
        )

    def consolidate_nightly(self, force: bool = False) -> SyncResult:
        """
        Executa o fechamento noturno definitivo do dia (ex: às 20:00).
        Congela os dados do dia no SQLite com is_finalized=True.
        """
        today_str = date.today().isoformat()
        logger.info(f"Executando consolidação noturna definitiva de {today_str}...")

        try:
            summary = self.client.get_system_summary(self.sid)
        except QuotaExceededError as qe:
            self.budget.mark_quota_exhausted(str(qe))
            self.repository.record_api_call(
                endpoint=f"/user/api/v2/systems/summary/{self.sid}",
                method="GET",
                status_code=2005,
                success=False,
                notes="Quota Exceeded no Fechamento Noturno (2005)",
            )
            raise

        self.repository.record_api_call(
            endpoint=f"/user/api/v2/systems/summary/{self.sid}",
            method="GET",
            status_code=200,
            success=True,
            notes=f"Fechamento Noturno: Total do dia={summary.today_kwh}kWh",
        )

        self.repository.upsert_daily_aggregate(
            system_sid=self.sid,
            target_date=today_str,
            energy_kwh=summary.today_kwh,
            is_finalized=True,
        )

        return SyncResult(
            success=True,
            message="Consolidação noturna gravada e finalizada",
            target_date=today_str,
            energy_today_kwh=summary.today_kwh,
            lifetime_kwh=summary.lifetime_kwh,
            is_finalized=True,
            timestamp=datetime.now(),
        )

    def sync_channels(self, target_date: Optional[str] = None, force: bool = False) -> int:
        """
        Sincroniza os dados de geração individual de todos os canais DC via lote da ECU.
        Consome apenas 1 requisição por ECU cadastrada.
        """
        self.budget.verify_can_request(force=force)
        today_str = target_date or date.today().isoformat()

        system = self.repository.get_system(self.sid)
        ecus = system.ecus if system else []
        total_channels_updated = 0

        for ecu in ecus:
            logger.info(f"Coletando lote de canais para ECU {ecu.eid} em {today_str}...")
            try:
                batch_data = self.client.get_inverter_batch_energy(
                    sid=self.sid,
                    eid=ecu.eid,
                    date_range=today_str,
                    energy_level="energy",
                )
            except QuotaExceededError as qe:
                self.budget.mark_quota_exhausted(str(qe))
                self.repository.record_api_call(
                    endpoint=f"/user/api/v2/systems/{self.sid}/devices/inverter/batch/energy/{ecu.eid}",
                    method="GET",
                    status_code=2005,
                    success=False,
                    notes=f"Quota Exceeded Sync Canais ECU {ecu.eid}",
                )
                raise
            self.repository.record_api_call(
                endpoint=f"/user/api/v2/systems/{self.sid}/devices/inverter/batch/energy/{ecu.eid}",
                method="GET",
                notes=f"Sync Canais ECU {ecu.eid}",
            )
            for item in batch_data.get_channel_items():
                self.repository.upsert_channel_telemetry(
                    inverter_uid=item.uid,
                    channel=item.channel,
                    date_str=today_str,
                    energy_today_kwh=item.energy_kwh,
                )
                total_channels_updated += 1

        # Avalia anomalias e dispara notificações caso configurado
        if self.notifier and total_channels_updated > 0:
            try:
                from solar_hub.services.diagnostic import DiagnosticService
                diag = DiagnosticService(self.repository)
                report = diag.diagnose_and_persist(self.sid, today_str)
                self.notifier.check_diagnostics(report)
            except Exception as ne:
                logger.warning(f"Erro ao avaliar alertas de canais no sync_channels: {ne}")

        # Publica estado atualizado dos canais no Home Assistant via MQTT
        if self.mqtt_service and total_channels_updated > 0:
            try:
                self.mqtt_service.publish_all()
            except Exception as me:
                logger.warning(f"Erro ao publicar MQTT no sync_channels: {me}")

        return total_channels_updated



    def fetch_inverter_telemetry(self, uid: str, force: bool = False):
        """
        Coleta a telemetria elétrica instantânea detalhada de um microinversor específico (V, A, W, °C, Hz).
        """
        self.budget.verify_can_request(force=force)
        today_str = date.today().isoformat()
        telemetry = self.client.get_inverter_telemetry(
            sid=self.sid,
            uid=uid,
            energy_level="minutely",
            date_range=today_str,
        )
        self.repository.record_api_call(
            endpoint=f"/user/api/v2/systems/{self.sid}/devices/inverter/energy/{uid}",
            method="GET",
            notes=f"Telemetria Fina Inversor {uid}",
        )
        snapshot = telemetry.get_latest_snapshot()
        for ch in [1, 2, 3, 4]:
            p_w = snapshot["dc_power_w"].get(ch)
            v_v = snapshot["dc_voltage_v"].get(ch)
            i_a = snapshot["dc_current_a"].get(ch)
            if any(x is not None for x in [p_w, v_v, i_a]):
                self.repository.upsert_channel_telemetry(
                    inverter_uid=uid,
                    channel=ch,
                    date_str=today_str,
                    energy_today_kwh=0.0,
                    power_w=p_w,
                    voltage_v=v_v,
                    current_a=i_a,
                    temperature_c=snapshot.get("temperature_c"),
                    frequency_hz=snapshot.get("frequency_hz"),
                )
        return telemetry

    def run_daemon(
        self,
        interval_minutes: int = 30,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        """
        Loop contínuo de background (Daemon) com resiliência estrita e proteção de cota.
        - Coleta diurna no intervalo configurado (respeitando a janela solar).
        - Executa o fechamento noturno às 20:00 (com limite seguro de tentativas).
        - Entra em hibernação profunda se a cota for esgotada na nuvem (Erro 2005) ou durante a madrugada.
        - Evita qualquer retry tempestivo de 30s em caso de erro.
        """
        logger.info(
            f"Iniciando Coletor Daemon SolarHub (Intervalo: {interval_minutes}min, "
            f"Fechamento: {self.nightly_time_obj.strftime('%H:%M')})"
        )

        last_sync_time: Optional[datetime] = None
        last_finalized_date: Optional[str] = None
        nightly_attempts: int = 0
        last_nightly_attempt_time: Optional[datetime] = None

        while stop_event is None or not stop_event.is_set():
            try:
                now = datetime.now()
                today_str = now.date().isoformat()
                budget_status = self.budget.get_status(now)

                # Se a cota mensal OpenAPI estiver esgotada na nuvem (Erro 2005), suspende coletas
                if budget_status.quota_exhausted:
                    logger.warning(
                        "Daemon SolarHub em modo de repouso: Cota OpenAPI da APsystems esgotada na nuvem (Código 2005). "
                        "Aguardando virada do mês..."
                    )
                    if stop_event:
                        if stop_event.wait(timeout=300):
                            break
                    else:
                        time_module.sleep(300)
                    continue

                # 1. Checagem de Fechamento Noturno (ex: ~20:00)
                is_nightly_window = (
                    now.time().hour == self.nightly_time_obj.hour
                    and now.time().minute >= self.nightly_time_obj.minute
                )

                if is_nightly_window and last_finalized_date != today_str:
                    # Máximo de 2 tentativas noturnas espaçadas em 10 minutos
                    can_attempt_nightly = False
                    if last_nightly_attempt_time is None:
                        can_attempt_nightly = True
                    elif (now - last_nightly_attempt_time).total_seconds() >= 600:
                        can_attempt_nightly = True

                    if can_attempt_nightly:
                        last_nightly_attempt_time = now
                        nightly_attempts += 1
                        try:
                            logger.info("Horário de consolidação noturna atingido!")
                            res = self.consolidate_nightly(force=True)
                            last_finalized_date = today_str
                            nightly_attempts = 0
                            logger.info(f"Dia {today_str} consolidado: {res.energy_today_kwh:.2f} kWh gerados.")
                        except QuotaExceededError as qe:
                            logger.critical(f"Cota da APsystems esgotada no fechamento noturno: {qe}")
                            self.budget.mark_quota_exhausted(str(qe))
                            last_finalized_date = today_str
                        except Exception as e:
                            logger.error(f"Erro na consolidação noturna (tentativa {nightly_attempts}/2): {e}")
                            if nightly_attempts >= 2:
                                logger.warning(
                                    f"Limite de tentativas noturnas atingido para {today_str}. Encerrando tentativas do dia."
                                )
                                last_finalized_date = today_str

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
                        # Atualiza last_sync_time preventivamente para impedir retry imediato em caso de erro de rede
                        last_sync_time = now
                        try:
                            logger.info("Janela solar ativa: executando sincronização periódica...")
                            res = self.sync_current(force=False)
                            logger.info(
                                f"Sync realizado: {res.energy_today_kwh:.2f} kWh hoje. "
                                f"(Próxima coleta em ~{interval_minutes}min)"
                            )
                        except BudgetKeeperBlockError as bke:
                            logger.warning(f"Coleta prevenida pelo Budget Keeper: {bke}")
                        except QuotaExceededError as qe:
                            logger.critical(f"Cota da APsystems esgotada durante a coleta diurna: {qe}")
                            self.budget.mark_quota_exhausted(str(qe))
                        except Exception as e:
                            logger.error(f"Erro inesperado durante a coleta diurna: {e}")

            except Exception as loop_err:
                logger.error(f"Erro inesperado no loop do daemon SolarHub: {loop_err}", exc_info=True)
                try:
                    self.repository.session.rollback()
                except Exception:
                    pass

            # Pausa de 30 segundos entre checagens do loop
            if stop_event:
                if stop_event.wait(timeout=30):
                    break
            else:
                time_module.sleep(30)

        logger.info("Coletor Daemon SolarHub encerrado com sucesso.")

    def backfill_monthly_history(self, year_month: str, force: bool = False) -> Dict[str, Any]:
        """
        Recupera retroativamente a série histórica diária de um mês inteiro
        utilizando APENAS 1 ÚNICA REQUISIÇÃO à OpenAPI da APsystems.
        Formato de year_month: 'YYYY-MM' (ex: '2026-10').
        """
        self.budget.verify_can_request(force=force)
        logger.info(f"Iniciando backfill histórico mensal para usina {self.sid} no mês {year_month}...")

        try:
            raw_data = self.client.get_system_energy(
                sid=self.sid,
                energy_level="daily",
                date_range=year_month,
            )
            self.repository.record_api_call(
                endpoint=f"/user/api/v2/systems/energy/{self.sid}",
                method="GET",
                status_code=200,
                success=True,
                notes=f"Backfill Histórico Mensal: {year_month}",
            )
        except QuotaExceededError as qe:
            self.budget.mark_quota_exhausted(str(qe))
            self.repository.record_api_call(
                endpoint=f"/user/api/v2/systems/energy/{self.sid}",
                method="GET",
                status_code=2005,
                success=False,
                notes="Quota Exceeded no Backfill (2005)",
            )
            raise

        records_synced = 0
        today_str = date.today().isoformat()

        # Parseamento flexível do formato retornado pela APsystems
        # Suporta dicionários {"energy": [...], "time": [...]}, lista direta [...], ou lista de objetos
        if isinstance(raw_data, dict):
            energy_list = raw_data.get("energy", [])
            time_list = raw_data.get("time", [])
        elif isinstance(raw_data, list):
            energy_list = raw_data
            time_list = []
        else:
            energy_list = []
            time_list = []

        if isinstance(energy_list, list):
            for idx, val in enumerate(energy_list):
                try:
                    energy_val = float(val) if val is not None else 0.0
                except (ValueError, TypeError):
                    continue

                if idx < len(time_list):
                    d_str = str(time_list[idx])
                    if len(d_str) <= 2:
                        day_num = int(d_str)
                        d_str = f"{year_month}-{day_num:02d}"
                else:
                    day_num = idx + 1
                    d_str = f"{year_month}-{day_num:02d}"

                # Ignora dias futuros
                if d_str > today_str:
                    continue

                is_final = d_str < today_str
                self.repository.upsert_daily_aggregate(
                    system_sid=self.sid,
                    target_date=d_str,
                    energy_kwh=energy_val,
                    is_finalized=is_final,
                )
                records_synced += 1

        return {
            "success": True,
            "month": year_month,
            "records_synced": records_synced,
            "message": f"Backfill concluído: {records_synced} dias consolidados no SQLite para o mês {year_month}.",
        }
