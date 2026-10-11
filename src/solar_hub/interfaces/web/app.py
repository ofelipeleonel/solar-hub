import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from solar_hub.client.client import APsystemsClient
from solar_hub.core.config import Settings
from solar_hub.core.security import is_safe_webhook_url, require_auth
from solar_hub.db.database import get_session_factory, init_db
from solar_hub.db.models import DailyAggregateRecord
from solar_hub.db.repository import SolarRepository
from solar_hub.services.budget import BudgetKeeperService
from solar_hub.services.collector import CollectorService
from solar_hub.services.notification import NotificationService

logger = logging.getLogger(__name__)

stop_event = threading.Event()
collector_thread: Optional[threading.Thread] = None

# Controle de taxa (Rate Limiting) para ações sob demanda (Prevenção de spam, abuso e exaustão de cota)
last_manual_sync_timestamp: float = 0.0
MANUAL_SYNC_COOLDOWN_SECONDS: float = 30.0

last_test_alert_timestamp: float = 0.0
ALERT_TEST_COOLDOWN_SECONDS: float = 15.0

last_mqtt_publish_timestamp: float = 0.0
MQTT_PUBLISH_COOLDOWN_SECONDS: float = 15.0


class SettingsUpdatePayload(BaseModel):
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    webhook_url: Optional[str] = None
    alert_cooldown_hours: Optional[int] = None
    alert_min_health_score: Optional[int] = None
    mqtt_enabled: Optional[bool] = None
    mqtt_broker: Optional[str] = None
    mqtt_port: Optional[int] = None
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None


class SyncPayload(BaseModel):
    force: bool = False
    sync_channels: bool = False



@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    init_db(settings.database_url)
    global collector_thread
    if settings.enable_daemon:
        logger.info("ENABLE_DAEMON ativado: iniciando coletor de telemetria em segundo plano...")
        session_factory = get_session_factory(settings.database_url)
        session = session_factory()
        repo = SolarRepository(session)
        client = APsystemsClient(
            app_id=settings.apsystems_app_id,
            app_secret=settings.apsystems_app_secret,
            base_url=settings.apsystems_base_url,
        )
        budget = BudgetKeeperService(
            repository=repo,
            monthly_limit=settings.monthly_budget_limit,
            reserve_calls_daily=settings.reserve_daily_calls,
            window_start=settings.solar_window_start,
            window_end=settings.solar_window_end,
        )
        notifier = NotificationService(
            repository=repo,
            system_sid=settings.apsystems_system_id,
            webhook_url=settings.alert_webhook_url,
            telegram_bot_token=settings.alert_telegram_bot_token,
            telegram_chat_id=settings.alert_telegram_chat_id,
            cooldown_hours=settings.alert_cooldown_hours,
            min_health_score=settings.alert_min_health_score,
            quota_warning_pct=settings.alert_quota_warning_pct,
            midday_check_enabled=settings.alert_midday_check,
            allow_private_webhooks=settings.allow_private_webhooks,
        )
        mqtt_service = None
        if settings.mqtt_enabled:
            from solar_hub.services.mqtt import HomeAssistantMqttService
            mqtt_service = HomeAssistantMqttService(
                repository=repo,
                budget=budget,
                system_sid=settings.apsystems_system_id,
                broker=settings.mqtt_broker,
                port=settings.mqtt_port,
                username=settings.mqtt_username,
                password=settings.mqtt_password,
                discovery_prefix=settings.mqtt_discovery_prefix,
                topic_prefix=settings.mqtt_topic_prefix,
            )
        collector = CollectorService(
            client=client,
            repository=repo,
            budget=budget,
            sid=settings.apsystems_system_id,
            nightly_time=settings.nightly_sync_time,
            notifier=notifier,
            mqtt_service=mqtt_service,
        )

        stop_event.clear()
        collector_thread = threading.Thread(
            target=collector.run_daemon,
            kwargs={"interval_minutes": 30, "stop_event": stop_event},
            daemon=True,
            name="solar-daemon-thread",
        )
        collector_thread.start()

    yield
    if settings.enable_daemon:
        logger.info("Encerrando coletor em segundo plano...")
        stop_event.set()
        if collector_thread and collector_thread.is_alive():
            collector_thread.join(timeout=5.0)


app = FastAPI(
    title="SolarHub Web Dashboard",
    description="Interface Web local, autônoma e leve para monitoramento solar APsystems. Inspirada pelo projeto open-source ez1-monitor.",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(require_auth)],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response


# Configuração segura de CORS
_init_settings = Settings()
_cors_raw = _init_settings.cors_origins.strip()
if _cors_raw == "*" or not _cors_raw:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    _origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

STATIC_DIR = Path(__file__).parent / "static"


def get_repo_and_settings():
    settings = Settings()
    session_factory = get_session_factory(settings.database_url)
    session = session_factory()
    repo = SolarRepository(session)
    budget = BudgetKeeperService(
        repository=repo,
        monthly_limit=settings.monthly_budget_limit,
        reserve_calls_daily=settings.reserve_daily_calls,
        window_start=settings.solar_window_start,
        window_end=settings.solar_window_end,
    )
    return settings, session, repo, budget


@app.get("/api/status")
def get_status() -> Dict[str, Any]:
    """Retorna o status geral da usina, telemetria de hoje e governança de cota."""
    settings, session, repo, budget = get_repo_and_settings()
    try:
        system = repo.get_system(settings.apsystems_system_id)
        budget_status = budget.get_status()

        # Pega o agregado de hoje no banco local
        today_agg = repo.get_daily_aggregates(settings.apsystems_system_id, limit=1)
        today_kwh = today_agg[0].energy_kwh if today_agg else 0.0
        # Total de inversores e canais no banco local
        total_inverters = len(repo.get_inverters())

        return {
            "sid": settings.apsystems_system_id,
            "system_name": system.name if system else f"Usina {settings.apsystems_system_id[-6:]}",
            "capacity_kwp": system.capacity_kwp if system else 0.0,
            "status_light": system.status_light if system else 1,
            "today_kwh": today_kwh,
            "total_inverters": total_inverters,
            "budget": {
                "calls_this_month": budget_status.calls_this_month,
                "monthly_limit": budget_status.monthly_limit,
                "remaining_month": budget_status.remaining_month,
                "calls_today": budget_status.calls_today,
                "daily_budget_target": budget_status.daily_budget_target,
                "is_solar_window": budget_status.is_solar_window,
                "reason": budget_status.reason,
            }
        }
    finally:
        session.close()


@app.get("/api/history")
def get_history(limit: int = 30) -> List[Dict[str, Any]]:
    """Retorna a série histórica de dias para renderização gráfica no Chart.js."""
    settings, session, repo, _ = get_repo_and_settings()
    try:
        records = repo.get_daily_aggregates(settings.apsystems_system_id, limit=limit)
        # Ordena de forma cronológica (mais antigo primeiro) para o gráfico
        ordered = sorted(records, key=lambda r: r.date)
        return [
            {
                "date": r.date,
                "energy_kwh": r.energy_kwh,
                "is_finalized": r.is_finalized,
            }
            for r in ordered
        ]
    finally:
        session.close()


@app.get("/api/inverters")
def get_inverters() -> List[Dict[str, Any]]:
    """Retorna a lista de microinversores cadastrados e sua topologia."""
    settings, session, repo, _ = get_repo_and_settings()
    try:
        invs = repo.get_inverters()
        return [
            {
                "uid": inv.uid,
                "ecu_eid": inv.ecu_eid,
                "model": inv.model,
                "channels_count": inv.channels_count,
                "alias": inv.alias or f"Microinversor {inv.uid[-4:]}",
            }
            for inv in invs
        ]
    finally:
        session.close()


@app.get("/api/hall-of-fame")
def get_hall_of_fame() -> Dict[str, Any]:
    """Retorna os recordes históricos (inspirado na funcionalidade Hall of Fame do ez1-monitor)."""
    settings, session, repo, _ = get_repo_and_settings()
    try:
        # Busca o melhor dia histórico registrado no banco
        stmt = (
            select(DailyAggregateRecord)
            .where(DailyAggregateRecord.system_sid == settings.apsystems_system_id)
            .order_by(DailyAggregateRecord.energy_kwh.desc())
            .limit(1)
        )
        best_day = session.execute(stmt).scalar_one_or_none()

        return {
            "best_day": {
                "date": best_day.date if best_day else "-",
                "energy_kwh": best_day.energy_kwh if best_day else 0.0,
            } if best_day else None
        }
    finally:
        session.close()


@app.get("/api/channels")
def get_channels(target_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retorna a telemetria individual de todos os canais DC registrados no SQLite."""
    from datetime import date
    settings, session, repo, _ = get_repo_and_settings()
    try:
        day_str = target_date or date.today().isoformat()
        records = repo.get_channel_telemetry_for_date(day_str)
        return [
            {
                "inverter_uid": r.inverter_uid,
                "channel": r.channel,
                "date": r.date,
                "energy_today_kwh": r.energy_today_kwh,
                "power_w": r.power_w,
                "voltage_v": r.voltage_v,
                "current_a": r.current_a,
                "temperature_c": r.temperature_c,
                "frequency_hz": r.frequency_hz,
            }
            for r in records
        ]
    finally:
        session.close()


@app.get("/api/diagnostics")
def get_diagnostics(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Retorna o relatório de saúde elétrica e anomalias calculadas pelo DiagnosticService."""
    from datetime import date

    from solar_hub.services.diagnostic import DiagnosticService

    settings, session, repo, _ = get_repo_and_settings()
    try:
        day_str = target_date or date.today().isoformat()
        diag_service = DiagnosticService(repository=repo)
        report = diag_service.diagnose_and_persist(settings.apsystems_system_id, day_str)

        return {
            "health_score": report.health_score,
            "status": report.status,
            "channels_evaluated": report.channels_evaluated,
            "average_channel_kwh": report.average_channel_kwh,
            "anomalies": [
                {
                    "type": a.anomaly_type,
                    "severity": a.severity,
                    "message": a.message,
                    "inverter_uid": a.inverter_uid,
                    "channel": a.channel,
                    "detected_value": a.detected_value,
                    "reference_value": a.reference_value,
                }
                for a in report.anomalies
            ],
            "channel_details": [
                {
                    "inverter_uid": cd.inverter_uid,
                    "channel": cd.channel,
                    "energy_today_kwh": cd.energy_today_kwh,
                    "power_w": cd.power_w,
                    "voltage_v": cd.voltage_v,
                    "current_a": cd.current_a,
                    "temperature_c": cd.temperature_c,
                    "deviation_pct": cd.deviation_pct,
                    "status": cd.status,
                }
                for cd in report.channel_details
            ],
            "recommendations": report.recommendations,
        }
    finally:
        session.close()


@app.get("/api/alerts")
def get_alerts(limit: int = 20) -> List[Dict[str, Any]]:
    """Retorna os registros de alertas e notificações disparadas."""
    settings, session, repo, _ = get_repo_and_settings()
    try:
        records = repo.get_recent_alerts(settings.apsystems_system_id, limit=limit)
        return [
            {
                "id": r.id,
                "alert_key": r.alert_key,
                "severity": r.severity,
                "title": r.title,
                "message": r.message,
                "channel": r.channel,
                "dispatched_at": r.dispatched_at.isoformat() if r.dispatched_at else None,
                "success": r.success,
                "error_detail": r.error_detail,
            }
            for r in records
        ]
    finally:
        session.close()


def get_effective_services(repo: SolarRepository, settings: Settings):
    from solar_hub.services.mqtt import HomeAssistantMqttService

    telegram_token = repo.get_setting("alert_telegram_bot_token", settings.alert_telegram_bot_token)
    telegram_chat = repo.get_setting("alert_telegram_chat_id", settings.alert_telegram_chat_id)
    webhook_url = repo.get_setting("alert_webhook_url", settings.alert_webhook_url)
    cooldown = int(repo.get_setting("alert_cooldown_hours", str(settings.alert_cooldown_hours)))
    min_health = int(repo.get_setting("alert_min_health_score", str(settings.alert_min_health_score)))

    notifier = NotificationService(
        repository=repo,
        system_sid=settings.apsystems_system_id,
        webhook_url=webhook_url,
        telegram_bot_token=telegram_token,
        telegram_chat_id=telegram_chat,
        cooldown_hours=cooldown,
        min_health_score=min_health,
        quota_warning_pct=settings.alert_quota_warning_pct,
        midday_check_enabled=settings.alert_midday_check,
        allow_private_webhooks=settings.allow_private_webhooks,
    )

    mqtt_enabled_str = repo.get_setting("mqtt_enabled", "true" if settings.mqtt_enabled else "false")
    mqtt_enabled = mqtt_enabled_str.lower() in ("true", "1", "yes")
    mqtt_broker = repo.get_setting("mqtt_broker", settings.mqtt_broker)
    mqtt_port = int(repo.get_setting("mqtt_port", str(settings.mqtt_port)))
    mqtt_user = repo.get_setting("mqtt_username", settings.mqtt_username)
    mqtt_pass = repo.get_setting("mqtt_password", settings.mqtt_password)

    mqtt_service = HomeAssistantMqttService(
        repository=repo,
        budget=BudgetKeeperService(repo, settings.monthly_budget_limit),
        system_sid=settings.apsystems_system_id,
        broker=mqtt_broker,
        port=mqtt_port,
        username=mqtt_user,
        password=mqtt_pass,
        discovery_prefix=settings.mqtt_discovery_prefix,
        topic_prefix=settings.mqtt_topic_prefix,
    )

    return notifier, mqtt_service, mqtt_enabled


@app.get("/api/settings")
def get_settings() -> Dict[str, Any]:
    """Retorna as configurações atuais ativas no SolarHub."""
    settings, session, repo, _ = get_repo_and_settings()
    try:
        notifier, _, mqtt_enabled = get_effective_services(repo, settings)
        tg_token = repo.get_setting("alert_telegram_bot_token", settings.alert_telegram_bot_token)
        masked_token = f"{tg_token[:6]}...{tg_token[-4:]}" if tg_token and len(tg_token) > 10 else ("Configurado" if tg_token else "")
        return {
            "telegram_bot_token": masked_token,
            "telegram_chat_id": repo.get_setting("alert_telegram_chat_id", settings.alert_telegram_chat_id) or "",
            "webhook_url": repo.get_setting("alert_webhook_url", settings.alert_webhook_url) or "",
            "alert_cooldown_hours": int(repo.get_setting("alert_cooldown_hours", str(settings.alert_cooldown_hours))),
            "alert_min_health_score": int(repo.get_setting("alert_min_health_score", str(settings.alert_min_health_score))),
            "has_telegram": bool(notifier.telegram_bot_token and notifier.telegram_chat_id),
            "has_webhook": bool(notifier.webhook_url),
            "mqtt_enabled": mqtt_enabled,
            "mqtt_broker": repo.get_setting("mqtt_broker", settings.mqtt_broker) or "localhost",
            "mqtt_port": int(repo.get_setting("mqtt_port", str(settings.mqtt_port))),
            "mqtt_username": repo.get_setting("mqtt_username", settings.mqtt_username) or "",
        }
    finally:
        session.close()


@app.post("/api/settings")
def update_settings(payload: SettingsUpdatePayload) -> Dict[str, Any]:
    """Atualiza configurações de alertas e integrações persistindo no banco SQLite."""
    settings, session, repo, _ = get_repo_and_settings()
    try:
        if payload.telegram_bot_token is not None and payload.telegram_bot_token != "Configurado":
            repo.set_setting("alert_telegram_bot_token", payload.telegram_bot_token.strip())
        if payload.telegram_chat_id is not None:
            repo.set_setting("alert_telegram_chat_id", payload.telegram_chat_id.strip())
        if payload.webhook_url is not None:
            clean_url = payload.webhook_url.strip()
            if clean_url:
                is_safe, reason = is_safe_webhook_url(
                    clean_url, allow_private=settings.allow_private_webhooks
                )
                if not is_safe:
                    return {
                        "success": False,
                        "message": f"URL de webhook rejeitada por segurança (anti-SSRF): {reason}",
                    }
                repo.set_setting("alert_webhook_url", clean_url)
            else:
                repo.set_setting("alert_webhook_url", "")
        if payload.alert_cooldown_hours is not None:
            repo.set_setting("alert_cooldown_hours", str(payload.alert_cooldown_hours))
        if payload.alert_min_health_score is not None:
            repo.set_setting("alert_min_health_score", str(payload.alert_min_health_score))
        if payload.mqtt_enabled is not None:
            repo.set_setting("mqtt_enabled", "true" if payload.mqtt_enabled else "false")
        if payload.mqtt_broker is not None:
            repo.set_setting("mqtt_broker", payload.mqtt_broker.strip())
        if payload.mqtt_port is not None:
            repo.set_setting("mqtt_port", str(payload.mqtt_port))
        if payload.mqtt_username is not None:
            repo.set_setting("mqtt_username", payload.mqtt_username.strip())
        if payload.mqtt_password is not None:
            repo.set_setting("mqtt_password", payload.mqtt_password)

        return {"success": True, "message": "Configurações salvas com sucesso!"}
    finally:
        session.close()


@app.post("/api/alerts/test")
def trigger_test_alert() -> Dict[str, Any]:
    """Dispara um alerta de teste para validar os canais configurados."""
    global last_test_alert_timestamp
    now = time.time()
    if now - last_test_alert_timestamp < ALERT_TEST_COOLDOWN_SECONDS:
        remaining = int(ALERT_TEST_COOLDOWN_SECONDS - (now - last_test_alert_timestamp))
        return {
            "success": False,
            "message": f"Aguarde {remaining}s antes de enviar outro alerta de teste (rate limit).",
        }
    last_test_alert_timestamp = now

    settings, session, repo, _ = get_repo_and_settings()
    try:
        notifier, _, _ = get_effective_services(repo, settings)
        return notifier.send_test_alert()
    finally:
        session.close()


@app.post("/api/mqtt/publish")
def trigger_mqtt_publish() -> Dict[str, Any]:
    """Publica os sensores e o estado no Home Assistant via MQTT."""
    global last_mqtt_publish_timestamp
    now = time.time()
    if now - last_mqtt_publish_timestamp < MQTT_PUBLISH_COOLDOWN_SECONDS:
        remaining = int(MQTT_PUBLISH_COOLDOWN_SECONDS - (now - last_mqtt_publish_timestamp))
        return {
            "success": False,
            "message": f"Aguarde {remaining}s antes de publicar no MQTT novamente (rate limit).",
        }
    last_mqtt_publish_timestamp = now

    settings, session, repo, _ = get_repo_and_settings()
    try:
        _, mqtt_service, _ = get_effective_services(repo, settings)
        return mqtt_service.publish_all()
    finally:
        session.close()


@app.post("/api/sync")
def trigger_sync(payload: Optional[SyncPayload] = None) -> Dict[str, Any]:
    """Executa sincronização sob demanda com a usina solar respeitando o Budget Keeper."""
    global last_manual_sync_timestamp
    now = time.time()
    if now - last_manual_sync_timestamp < MANUAL_SYNC_COOLDOWN_SECONDS:
        remaining = int(MANUAL_SYNC_COOLDOWN_SECONDS - (now - last_manual_sync_timestamp))
        return {
            "success": False,
            "message": f"Aguarde {remaining}s antes de solicitar nova sincronização manual (proteção de cota).",
            "today_kwh": 0.0,
            "channels_updated": 0,
        }
    last_manual_sync_timestamp = now

    # Desativa força via chamada de API pública para proteger a integridade da cota
    force = False
    sync_channels = payload.sync_channels if payload else False

    settings, session, repo, budget = get_repo_and_settings()
    try:
        client = APsystemsClient(
            app_id=settings.apsystems_app_id,
            app_secret=settings.apsystems_app_secret,
            base_url=settings.apsystems_base_url,
        )
        notifier, mqtt_service, _ = get_effective_services(repo, settings)
        collector = CollectorService(
            client=client,
            repository=repo,
            budget=budget,
            sid=settings.apsystems_system_id,
            notifier=notifier,
            mqtt_service=mqtt_service,
        )

        res = collector.sync_current(force=force)
        channels_updated = 0
        if sync_channels:
            channels_updated = collector.sync_channels(force=force)

        return {
            "success": res.success,
            "message": res.message,
            "today_kwh": res.energy_today_kwh,
            "channels_updated": channels_updated,
        }
    finally:
        session.close()



@app.get("/api/export/summary")
def get_export_summary() -> Dict[str, Any]:
    """Retorna o resumo estatístico das tabelas exportáveis no banco local."""
    from solar_hub.services.export import ExportService

    settings, session, repo, _ = get_repo_and_settings()
    try:
        service = ExportService(repository=repo, system_sid=settings.apsystems_system_id)
        return service.export_summary()
    finally:
        session.close()


@app.get("/api/export/generation")
def export_generation(
    format: str = "csv",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """Exporta o histórico de geração diária em CSV ou JSON (zero consumo de cota)."""
    from solar_hub.services.export import ExportService

    settings, session, repo, _ = get_repo_and_settings()
    try:
        service = ExportService(repository=repo, system_sid=settings.apsystems_system_id)
        fmt = format.lower().strip()
        content = service.export_generation(
            export_format=fmt,
            start_date=start_date,
            end_date=end_date,
        )

        media_type = "application/json" if fmt == "json" else "text/csv; charset=utf-8"
        filename = f"generation_{settings.apsystems_system_id[-6:]}.{fmt}"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return Response(content=content, media_type=media_type, headers=headers)
    finally:
        session.close()


@app.get("/api/export/channels")
def export_channels(
    format: str = "csv",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    inverter_uid: Optional[str] = None,
):
    """Exporta a telemetria detalhada de canais DC em CSV ou JSON (zero consumo de cota)."""
    from solar_hub.services.export import ExportService

    settings, session, repo, _ = get_repo_and_settings()
    try:
        service = ExportService(repository=repo, system_sid=settings.apsystems_system_id)
        fmt = format.lower().strip()
        content = service.export_channels(
            export_format=fmt,
            start_date=start_date,
            end_date=end_date,
            inverter_uid=inverter_uid,
        )

        media_type = "application/json" if fmt == "json" else "text/csv; charset=utf-8"
        filename = f"channels_{settings.apsystems_system_id[-6:]}.{fmt}"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return Response(content=content, media_type=media_type, headers=headers)
    finally:
        session.close()


@app.get("/metrics")
def get_metrics():
    """Endpoint Prometheus para coleta e scraping de métricas operacionais."""
    from solar_hub.services.metrics import PrometheusMetricsService

    settings, session, repo, budget = get_repo_and_settings()
    try:
        service = PrometheusMetricsService(
            repository=repo, budget=budget, system_sid=settings.apsystems_system_id
        )
        content = service.generate_metrics()
        return Response(content=content, media_type="text/plain; version=0.0.4; charset=utf-8")
    finally:
        session.close()


# Monta os arquivos estáticos



if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(STATIC_DIR / "index.html")
