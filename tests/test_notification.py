from datetime import datetime

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from solar_hub.db.models import Base
from solar_hub.db.repository import SolarRepository
from solar_hub.services.budget import BudgetStatus
from solar_hub.services.diagnostic import Anomaly, DiagnosticReport
from solar_hub.services.notification import AlertMessage, NotificationService


@pytest.fixture
def repo():
    """Cria um banco SQLite em memória isolado para os testes."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield SolarRepository(session)
    session.close()


def test_channel_active_detection(repo):
    """Verifica a detecção de canais ativos configurados."""
    # Sem canais
    notif_none = NotificationService(repo, system_sid="TEST_SID")
    assert not notif_none.has_active_channel

    # Apenas webhook
    notif_wh = NotificationService(repo, system_sid="TEST_SID", webhook_url="https://hooks.example.com")
    assert notif_wh.has_active_channel

    # Apenas telegram incompleto (falta chat_id)
    notif_tg_inc = NotificationService(repo, system_sid="TEST_SID", telegram_bot_token="token123")
    assert not notif_tg_inc.has_active_channel

    # Telegram completo
    notif_tg = NotificationService(
        repo, system_sid="TEST_SID", telegram_bot_token="token123", telegram_chat_id="chat999"
    )
    assert notif_tg.has_active_channel


def test_webhook_dispatch_payload(repo, monkeypatch):
    """Testa o formato do payload e o envio via Webhook."""
    recorded_requests = []

    def mock_post(url, json=None, **kwargs):
        recorded_requests.append({"url": url, "json": json})
        response = httpx.Response(status_code=200, request=httpx.Request("POST", url))
        return response

    client = httpx.Client()
    monkeypatch.setattr(client, "post", mock_post)

    service = NotificationService(
        repo,
        system_sid="TEST_SID_001",
        webhook_url="https://discord.com/api/webhooks/123/xyz",
        http_client=client,
    )

    alert = AlertMessage(
        alert_key="TEST_ALERT",
        severity="CRITICAL",
        title="Canal DC Inoperante",
        message="Canal 2 do inversor 1001 não está gerando.",
    )

    results = service.dispatch(alert)

    assert results.get("webhook") is True
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert req["url"] == "https://discord.com/api/webhooks/123/xyz"
    assert "content" in req["json"]
    assert "text" in req["json"]
    assert req["json"]["severity"] == "CRITICAL"
    assert req["json"]["system_sid"] == "TEST_SID_001"


def test_telegram_dispatch(repo, monkeypatch):
    """Testa o despacho de alertas via Telegram Bot API."""
    recorded_requests = []

    def mock_post(url, json=None, **kwargs):
        recorded_requests.append({"url": url, "json": json})
        return httpx.Response(status_code=200, request=httpx.Request("POST", url))

    client = httpx.Client()
    monkeypatch.setattr(client, "post", mock_post)

    service = NotificationService(
        repo,
        system_sid="TEST_SID_001",
        telegram_bot_token="bot123456",
        telegram_chat_id="chat_789",
        http_client=client,
    )

    alert = AlertMessage(
        alert_key="OVERHEATING",
        severity="WARNING",
        title="Temperatura Elevada",
        message="Inversor operando a 68°C.",
    )

    results = service.dispatch(alert)
    assert results.get("telegram") is True
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert "api.telegram.org/botbot123456/sendMessage" in req["url"]
    assert req["json"]["chat_id"] == "chat_789"
    assert req["json"]["parse_mode"] == "HTML"
    assert "Temperatura Elevada" in req["json"]["text"]


def test_cooldown_suppression(repo, monkeypatch):
    """Valida se alertas duplicados são suprimidos durante o cooldown configurado."""
    call_count = 0

    def mock_post(url, json=None, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(status_code=200, request=httpx.Request("POST", url))

    client = httpx.Client()
    monkeypatch.setattr(client, "post", mock_post)

    service = NotificationService(
        repo,
        system_sid="TEST_SID_001",
        webhook_url="https://hooks.example.com",
        cooldown_hours=4,
        http_client=client,
    )

    alert = AlertMessage(
        alert_key="DEAD_CHANNEL:inv1:ch1",
        severity="CRITICAL",
        title="Painel Morto",
        message="Falha de geração no canal 1",
    )

    # 1º envio: Deve despachar normalmente
    res1 = service.dispatch(alert)
    assert res1.get("webhook") is True
    assert call_count == 1

    # 2º envio imediato: Deve ser suprimido pelo cooldown
    res2 = service.dispatch(alert)
    assert res2.get("suppressed") is True
    assert call_count == 1  # Não deve ter chamado o webhook novamente!

    # 3º envio com force=True: Deve ignorar o cooldown e despachar
    res3 = service.dispatch(alert, force=True)
    assert res3.get("webhook") is True
    assert call_count == 2


def test_check_diagnostics_anomalies(repo, monkeypatch):
    """Verifica disparo de alerta quando o DiagnosticReport contém anomalias."""
    sent_alerts = []

    def mock_post(url, json=None, **kwargs):
        sent_alerts.append(json)
        return httpx.Response(status_code=200, request=httpx.Request("POST", url))

    client = httpx.Client()
    monkeypatch.setattr(client, "post", mock_post)

    service = NotificationService(
        repo,
        system_sid="TEST_SID_001",
        webhook_url="https://hooks.example.com",
        min_health_score=80,
        http_client=client,
    )

    report = DiagnosticReport(
        health_score=50,
        status="CRITICAL",
        channels_evaluated=4,
        anomalies=[
            Anomaly(
                anomaly_type="DEAD_CHANNEL",
                severity="CRITICAL",
                message="Canal 1 gerando 0 kWh.",
                inverter_uid="inv1",
                channel=1,
            )
        ],
        recommendations=["Verifique o conector MC4."],
    )

    dispatched = service.check_diagnostics(report)
    # Deve disparar 2 alertas: 1 para o LOW_HEALTH_SCORE (<80) e 1 para a anomalia DEAD_CHANNEL
    assert len(dispatched) == 2
    assert len(sent_alerts) == 2


def test_check_budget_status_alert(repo, monkeypatch):
    """Verifica disparo de alerta ao atingir limite crítico da cota mensal."""
    sent_alerts = []

    def mock_post(url, json=None, **kwargs):
        sent_alerts.append(json)
        return httpx.Response(status_code=200, request=httpx.Request("POST", url))

    client = httpx.Client()
    monkeypatch.setattr(client, "post", mock_post)

    service = NotificationService(
        repo,
        system_sid="TEST_SID_001",
        webhook_url="https://hooks.example.com",
        quota_warning_pct=85.0,
        http_client=client,
    )

    # 1. Consumo seguro (600 / 1000 = 60%) -> Não dispara
    status_ok = BudgetStatus(
        calls_this_month=600,
        monthly_limit=1000,
        remaining_month=400,
        calls_today=10,
        daily_budget_target=30,
        is_solar_window=True,
        can_request_now=True,
        reason="OK",
    )
    res_ok = service.check_budget_status(status_ok)
    assert res_ok is None
    assert len(sent_alerts) == 0

    # 2. Consumo elevado (880 / 1000 = 88%) -> Dispara alerta
    status_high = BudgetStatus(
        calls_this_month=880,
        monthly_limit=1000,
        remaining_month=120,
        calls_today=25,
        daily_budget_target=30,
        is_solar_window=True,
        can_request_now=True,
        reason="Atenção",
    )
    res_high = service.check_budget_status(status_high)
    assert res_high is not None
    assert len(sent_alerts) == 1
    assert "88.0%" in sent_alerts[0]["title"]


def test_check_midday_zero_production(repo, monkeypatch):
    """Verifica disparo de alerta quando a usina gera zero durante o meio-dia."""
    sent_alerts = []

    def mock_post(url, json=None, **kwargs):
        sent_alerts.append(json)
        return httpx.Response(status_code=200, request=httpx.Request("POST", url))

    client = httpx.Client()
    monkeypatch.setattr(client, "post", mock_post)

    service = NotificationService(
        repo,
        system_sid="TEST_SID_001",
        webhook_url="https://hooks.example.com",
        midday_check_enabled=True,
        http_client=client,
    )

    # 12:30 com 0.0 kWh -> Dispara alerta crítico
    noon_time = datetime(2026, 10, 9, 12, 30, 0)
    res = service.check_midday_production(energy_today_kwh=0.0, current_time=noon_time)
    assert res is not None
    assert len(sent_alerts) == 1
    assert "Geração Nula no Horário de Pico Solar" in sent_alerts[0]["title"]

    # 12:30 com 15.2 kWh -> Não dispara
    res_ok = service.check_midday_production(energy_today_kwh=15.2, current_time=noon_time)
    assert res_ok is None

    # 23:00 com 0.0 kWh (noite) -> Não dispara
    night_time = datetime(2026, 10, 9, 23, 0, 0)
    res_night = service.check_midday_production(energy_today_kwh=0.0, current_time=night_time)
    assert res_night is None


def test_send_test_alert(repo, monkeypatch):
    """Valida o método de teste de conectividade."""
    def mock_post(url, json=None, **kwargs):
        return httpx.Response(status_code=200, request=httpx.Request("POST", url))

    client = httpx.Client()
    monkeypatch.setattr(client, "post", mock_post)

    service = NotificationService(
        repo,
        system_sid="TEST_SID_001",
        webhook_url="https://hooks.example.com",
        http_client=client,
    )

    result = service.send_test_alert()
    assert result["success"] is True
    assert result["channels"]["webhook"] is True
