import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from solar_hub.core.security import is_safe_webhook_url
from solar_hub.db.repository import SolarRepository
from solar_hub.services.budget import BudgetStatus
from solar_hub.services.diagnostic import DiagnosticReport

logger = logging.getLogger(__name__)


@dataclass
class AlertMessage:
    """Mensagem padronizada de alerta para despacho multicanal."""
    alert_key: str
    severity: str  # CRITICAL, WARNING, INFO
    title: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class NotificationService:
    """
    Serviço autônomo e resiliente de alertas e notificações para usinas solares.
    Suporta Webhooks genéricos (Discord, Slack, Home Assistant, n8n) e Telegram Bot,
    com controle rígido de cooldown para evitar tempestades de mensagens repetidas.
    """

    def __init__(
        self,
        repository: SolarRepository,
        system_sid: str,
        webhook_url: Optional[str] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        cooldown_hours: int = 4,
        min_health_score: int = 80,
        quota_warning_pct: float = 85.0,
        midday_check_enabled: bool = True,
        http_client: Optional[httpx.Client] = None,
        allow_private_webhooks: bool = False,
    ):
        self.repository = repository
        self.system_sid = system_sid
        self.webhook_url = webhook_url.strip() if webhook_url and webhook_url.strip() else None
        self.telegram_bot_token = telegram_bot_token.strip() if telegram_bot_token and telegram_bot_token.strip() else None
        self.telegram_chat_id = telegram_chat_id.strip() if telegram_chat_id and telegram_chat_id.strip() else None
        self.cooldown_hours = max(1, cooldown_hours)
        self.min_health_score = min_health_score
        self.quota_warning_pct = quota_warning_pct
        self.midday_check_enabled = midday_check_enabled
        self._http_client = http_client
        self.allow_private_webhooks = allow_private_webhooks

    @property
    def has_active_channel(self) -> bool:
        """Verifica se pelo menos um canal de notificação está configurado."""
        return bool(self.webhook_url or (self.telegram_bot_token and self.telegram_chat_id))

    def _get_client(self) -> httpx.Client:
        if self._http_client is not None:
            return self._http_client
        return httpx.Client(timeout=10.0)

    def send_webhook(self, alert: AlertMessage) -> bool:
        """
        Dispara payload HTTP POST para a URL configurada.
        O formato JSON é compatível simultaneamente com Discord, Slack e Webhooks REST padrão.
        """
        if not self.webhook_url:
            return False

        # Validação de segurança anti-SSRF antes do envio
        is_safe, reason = is_safe_webhook_url(
            self.webhook_url, allow_private=self.allow_private_webhooks
        )
        if not is_safe:
            logger.error(
                f"Disparo de webhook bloqueado por segurança (anti-SSRF): {reason} (URL: {self.webhook_url})"
            )
            return False

        # Ícones por severidade
        icon = "🔴" if alert.severity == "CRITICAL" else "🟡" if alert.severity == "WARNING" else "ℹ️"
        formatted_header = f"{icon} [{alert.severity}] SolarHub: {alert.title}"

        payload = {
            "title": alert.title,
            "content": f"**{formatted_header}**\n{alert.message}\n`Usina: {self.system_sid}`",
            "text": f"{formatted_header}\n{alert.message} (Usina: {self.system_sid})",
            "severity": alert.severity,
            "message": alert.message,
            "system_sid": self.system_sid,
            "timestamp": alert.timestamp.isoformat(),
            "details": alert.details,
        }

        try:
            client = self._get_client()
            response = client.post(self.webhook_url, json=payload)
            success = 200 <= response.status_code < 300
            if not success:
                logger.warning(
                    f"Falha ao enviar webhook (HTTP {response.status_code}): {response.text[:200]}"
                )
            return success
        except Exception as e:
            logger.error(f"Exceção ao disparar webhook: {e}")
            return False

    def send_telegram(self, alert: AlertMessage) -> bool:
        """
        Dispara mensagem formatada via Telegram Bot API sendMessage.
        """
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return False

        icon = "🚨" if alert.severity == "CRITICAL" else "⚠️" if alert.severity == "WARNING" else "ℹ️"
        time_str = alert.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

        text = (
            f"{icon} <b>SolarHub: {alert.title}</b>\n\n"
            f"<b>Severidade:</b> {alert.severity}\n"
            f"<b>Mensagem:</b> {alert.message}\n"
            f"<b>Usina:</b> <code>{self.system_sid}</code>\n"
            f"<b>Data/Hora:</b> <code>{time_str}</code>"
        )

        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        try:
            client = self._get_client()
            response = client.post(url, json=payload)
            success = 200 <= response.status_code < 300
            if not success:
                logger.warning(
                    f"Falha ao enviar Telegram (HTTP {response.status_code}): {response.text[:200]}"
                )
            return success
        except Exception as e:
            err_msg = str(e)
            if self.telegram_bot_token:
                err_msg = err_msg.replace(self.telegram_bot_token, "[TOKEN_MASCARADO]")
            logger.error(f"Exceção ao disparar Telegram: {err_msg}")
            return False

    def dispatch(self, alert: AlertMessage, force: bool = False) -> Dict[str, bool]:
        """
        Despacha o alerta para todos os canais configurados com proteção de cooldown.
        Retorna dicionário com o status de entrega por canal.
        """
        if not self.has_active_channel:
            logger.debug(f"Nenhum canal de alerta ativo configurado para '{alert.alert_key}'.")
            return {"configured": False}

        # 1. Verifica Cooldown
        if not force and self.repository.is_in_cooldown(
            self.system_sid, alert.alert_key, self.cooldown_hours
        ):
            logger.info(
                f"Alerta '{alert.alert_key}' suprimido por cooldown ativo ({self.cooldown_hours}h)."
            )
            return {"cooldown": True, "suppressed": True}

        results: Dict[str, bool] = {}

        # 2. Despacho Webhook
        if self.webhook_url:
            success = self.send_webhook(alert)
            results["webhook"] = success
            self.repository.record_alert_dispatch(
                system_sid=self.system_sid,
                alert_key=alert.alert_key,
                severity=alert.severity,
                title=alert.title,
                message=alert.message,
                channel="webhook",
                success=success,
                error_detail=None if success else "HTTP error or exception",
            )

        # 3. Despacho Telegram
        if self.telegram_bot_token and self.telegram_chat_id:
            success = self.send_telegram(alert)
            results["telegram"] = success
            self.repository.record_alert_dispatch(
                system_sid=self.system_sid,
                alert_key=alert.alert_key,
                severity=alert.severity,
                title=alert.title,
                message=alert.message,
                channel="telegram",
                success=success,
                error_detail=None if success else "Telegram API error",
            )

        return results

    def check_diagnostics(self, report: DiagnosticReport) -> List[Dict[str, Any]]:
        """
        Avalia o relatório de diagnóstico elétrico e despacha alertas para anomalias ou score baixo.
        """
        dispatched: List[Dict[str, Any]] = []

        # 1. Alerta de Saúde Geral Baixa
        if report.health_score < self.min_health_score and report.status != "SEM_DADOS":
            severity = "CRITICAL" if report.health_score < 60 else "WARNING"
            recommendations_summary = "; ".join(report.recommendations[:2])
            alert = AlertMessage(
                alert_key="LOW_HEALTH_SCORE",
                severity=severity,
                title=f"Índice de Saúde Operacional em {report.health_score}% ({report.status})",
                message=(
                    f"A usina fotovoltaica atingiu índice de saúde de {report.health_score}%. "
                    f"Ações recomendadas: {recommendations_summary}"
                ),
                details={"health_score": report.health_score, "status": report.status},
            )
            res = self.dispatch(alert)
            dispatched.append({"alert_key": alert.alert_key, "results": res})

        # 2. Alertas para cada anomalia individual
        for anom in report.anomalies:
            inverter_tag = anom.inverter_uid or "global"
            channel_tag = str(anom.channel) if anom.channel is not None else "all"
            key = f"ANOMALY:{anom.anomaly_type}:{inverter_tag}:{channel_tag}"

            alert = AlertMessage(
                alert_key=key,
                severity=anom.severity,
                title=f"Anomalia: {anom.anomaly_type}",
                message=anom.message,
                details={
                    "inverter_uid": anom.inverter_uid,
                    "channel": anom.channel,
                    "detected_value": anom.detected_value,
                    "reference_value": anom.reference_value,
                },
            )
            res = self.dispatch(alert)
            dispatched.append({"alert_key": key, "results": res})

        return dispatched

    def check_budget_status(self, budget_status: BudgetStatus) -> Optional[Dict[str, Any]]:
        """
        Verifica o consumo da cota mensal do Budget Keeper e dispara alerta se atingir o limiar.
        """
        if budget_status.monthly_limit <= 0:
            return None

        used_pct = (budget_status.calls_this_month / budget_status.monthly_limit) * 100.0

        if used_pct >= self.quota_warning_pct:
            bucket = int(used_pct // 5) * 5  # 85, 90, 95...
            key = f"BUDGET_QUOTA_EXCEEDED:{bucket}"
            severity = "CRITICAL" if used_pct >= 95.0 else "WARNING"
            alert = AlertMessage(
                alert_key=key,
                severity=severity,
                title=f"Consumo de Cota da API em {used_pct:.1f}% ({budget_status.calls_this_month}/{budget_status.monthly_limit})",
                message=(
                    f"A usina consumiu {budget_status.calls_this_month} de {budget_status.monthly_limit} requisições no mês "
                    f"({budget_status.remaining_month} chamadas restantes). "
                    f"O Budget Keeper continuará priorizando a integridade da cota."
                ),
                details={
                    "calls_this_month": budget_status.calls_this_month,
                    "monthly_limit": budget_status.monthly_limit,
                    "remaining_month": budget_status.remaining_month,
                },
            )
            res = self.dispatch(alert)
            return {"alert_key": key, "results": res}

        return None

    def check_midday_production(
        self, energy_today_kwh: float, current_time: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Detecta interrupção completa no meio do dia (11:30 às 14:00) quando a geração deveria estar ativa.
        """
        if not self.midday_check_enabled:
            return None

        now = current_time or datetime.now()
        is_midday = (now.hour == 11 and now.minute >= 30) or (12 <= now.hour < 14)

        if is_midday and energy_today_kwh <= 0.01:
            key = f"MIDDAY_ZERO_PRODUCTION:{now.date().isoformat()}"
            alert = AlertMessage(
                alert_key=key,
                severity="CRITICAL",
                title="Geração Nula no Horário de Pico Solar",
                message=(
                    f"A usina registrou apenas {energy_today_kwh:.2f} kWh até {now.strftime('%H:%M')}. "
                    "Possível desligamento de disjuntor CA, perda de comunicação da ECU ou falha na rede elétrica."
                ),
                details={"energy_today_kwh": energy_today_kwh, "time": now.isoformat()},
            )
            res = self.dispatch(alert)
            return {"alert_key": key, "results": res}

        return None

    def send_test_alert(self) -> Dict[str, Any]:
        """
        Dispara um alerta de teste imediato (bypassando cooldown) para validar a configuração.
        """
        alert = AlertMessage(
            alert_key="TEST_ALERT",
            severity="INFO",
            title="Teste de Conectividade do SolarHub",
            message=(
                "Parabéns! O seu canal de notificações está operando perfeitamente. "
                "Alertas elétricos e avisos de cota do SolarHub serão entregues aqui."
            ),
            details={"test": True},
        )
        results = self.dispatch(alert, force=True)
        return {
            "success": any(results.values()) if results else False,
            "channels": results,
            "has_active_channel": self.has_active_channel,
        }
