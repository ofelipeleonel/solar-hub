import base64

import pytest
from fastapi.testclient import TestClient

from solar_hub.core.config import Settings
from solar_hub.core.security import is_safe_webhook_url
from solar_hub.interfaces.web.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_ssrf_url_validation_blocks_malicious_destinations():
    """Valida se URLs de loopback, metadados de nuvem e redes privadas são barradas."""
    # Loopback
    safe, reason = is_safe_webhook_url("http://127.0.0.1:8000/hook")
    assert safe is False
    assert "loopback" in reason.lower() or "restrito" in reason.lower()

    safe, reason = is_safe_webhook_url("http://localhost:5000")
    assert safe is False

    # Metadados de cloud instance (AWS / Hetzner / DigitalOcean / GCP)
    safe, reason = is_safe_webhook_url("http://169.254.169.254/latest/meta-data/")
    assert safe is False

    # Redes internas privadas RFC 1918 (modo padrão VPS)
    safe, reason = is_safe_webhook_url("http://10.0.0.5:8080/webhook", allow_private=False)
    assert safe is False

    safe, reason = is_safe_webhook_url("http://192.168.1.100:8123/webhook", allow_private=False)
    assert safe is False

    # Protocolos inseguros
    safe, reason = is_safe_webhook_url("file:///etc/passwd")
    assert safe is False
    assert "não permitido" in reason.lower()

    safe, reason = is_safe_webhook_url("gopher://127.0.0.1:6379")
    assert safe is False


def test_ssrf_url_validation_permits_legitimate_webhooks():
    """Valida se URLs públicas legítimas (Discord, Slack, Telegram) são autorizadas."""
    safe, reason = is_safe_webhook_url("https://discord.com/api/webhooks/12345/abcdef")
    assert safe is True

    safe, reason = is_safe_webhook_url("https://api.telegram.org/bot123/sendMessage")
    assert safe is True


def test_api_settings_blocks_ssrf_webhook(client):
    """Garante que a API rejeita salvar webhooks apontando para endereços de loopback ou metadados."""
    payload = {"webhook_url": "http://169.254.169.254/latest/meta-data/"}
    res = client.post("/api/settings", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "rejeitada por segurança" in data["message"] or "anti-SSRF" in data["message"]


def test_api_sync_rate_limiting_cooldown(client, monkeypatch):
    """Garante que chamadas repetitivas de sincronização manual respeitam o cooldown de 30 segundos."""
    from datetime import datetime, timezone

    from solar_hub.services.collector import SyncResult

    def mock_sync(self, force=False):
        return SyncResult(
            success=True,
            energy_today_kwh=10.0,
            message="ok",
            target_date="2026-10-10",
            lifetime_kwh=50.0,
            is_finalized=False,
            timestamp=datetime.now(timezone.utc),
        )

    monkeypatch.setattr("solar_hub.services.collector.CollectorService.sync_current", mock_sync)

    import solar_hub.interfaces.web.app as app_module
    app_module.last_manual_sync_timestamp = 0.0

    try:
        # 1ª chamada: Executa
        res1 = client.post("/api/sync", json={"force": False})
        assert res1.status_code == 200
        assert res1.json()["success"] is True

        # 2ª chamada imediata: Bloqueada pelo cooldown
        res2 = client.post("/api/sync", json={"force": False})
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["success"] is False
        assert "Aguarde" in data2["message"]
    finally:
        app_module.last_manual_sync_timestamp = 0.0


def test_authentication_enforcement(monkeypatch):
    """Valida a restrição de acesso por HTTP Basic Auth e API Key quando configurados."""
    from solar_hub.core.security import get_current_settings

    # Simula configuração de produção com usuário e senha
    def mock_get_settings():
        base = Settings()
        return base.model_copy(
            update={
                "auth_username": "admin_solar",
                "auth_password": "super_secret_password_123",
                "api_key": "solar_secret_token_987",
            }
        )

    app.dependency_overrides[get_current_settings] = mock_get_settings

    try:
        protected_client = TestClient(app)

        # 1. Sem credenciais -> 401 Unauthorized
        res_anon = protected_client.get("/api/status")
        assert res_anon.status_code == 401
        assert "Basic realm" in res_anon.headers.get("www-authenticate", "")

        # 2. Credenciais inválidas -> 401 Unauthorized
        bad_auth = base64.b64encode(b"admin_solar:senha_errada").decode()
        res_bad = protected_client.get(
            "/api/status", headers={"Authorization": f"Basic {bad_auth}"}
        )
        assert res_bad.status_code == 401

        # 3. Credenciais válidas (HTTP Basic) -> 200 OK
        good_auth = base64.b64encode(b"admin_solar:super_secret_password_123").decode()
        res_ok = protected_client.get(
            "/api/status", headers={"Authorization": f"Basic {good_auth}"}
        )
        assert res_ok.status_code == 200

        # 4. Acesso via API Key no header X-API-Key -> 200 OK
        res_apikey = protected_client.get(
            "/api/status", headers={"X-API-Key": "solar_secret_token_987"}
        )
        assert res_apikey.status_code == 200

        # 5. Acesso via Bearer Token -> 200 OK
        res_bearer = protected_client.get(
            "/api/status", headers={"Authorization": "Bearer solar_secret_token_987"}
        )
        assert res_bearer.status_code == 200

    finally:
        app.dependency_overrides.clear()


def test_http_security_headers_present(client):
    """Garante que cabeçalhos de segurança HTTP contra clickjacking, MIME-sniffing e XSS estão ativos."""
    response = client.get("/")
    assert response.status_code == 200
    headers = response.headers

    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    csp = headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'self'" in csp


def test_alerts_test_and_mqtt_rate_limiting(client, monkeypatch):
    """Valida o cooldown de proteção contra rajadas em disparos manuais de teste e MQTT."""
    import solar_hub.interfaces.web.app as app_module

    app_module.last_test_alert_timestamp = 0.0
    app_module.last_mqtt_publish_timestamp = 0.0

    try:
        # Mock do envio de alerta
        def mock_test_alert(self):
            return {"success": True, "channels": {}}

        # Mock do envio MQTT
        def mock_publish(self):
            return {"success": True, "message": "published"}

        monkeypatch.setattr(
            "solar_hub.services.notification.NotificationService.send_test_alert",
            mock_test_alert,
        )
        monkeypatch.setattr(
            "solar_hub.services.mqtt.HomeAssistantMqttService.publish_all",
            mock_publish,
        )

        # 1. Alerta de Teste - 1ª chamada OK
        res1 = client.post("/api/alerts/test")
        assert res1.status_code == 200
        assert res1.json()["success"] is True

        # 2ª chamada imediata -> Cooldown
        res2 = client.post("/api/alerts/test")
        assert res2.status_code == 200
        assert res2.json()["success"] is False
        assert "Aguarde" in res2.json()["message"]

        # 2. MQTT Publish - 1ª chamada OK
        res_m1 = client.post("/api/mqtt/publish")
        assert res_m1.status_code == 200
        assert res_m1.json()["success"] is True

        # 2ª chamada imediata -> Cooldown
        res_m2 = client.post("/api/mqtt/publish")
        assert res_m2.status_code == 200
        assert res_m2.json()["success"] is False
        assert "Aguarde" in res_m2.json()["message"]

    finally:
        app_module.last_test_alert_timestamp = 0.0
        app_module.last_mqtt_publish_timestamp = 0.0


def test_telegram_token_masked_in_exception_logs(caplog):
    """Garante que falhas ou exceções ao despachar mensagens Telegram não vazam o bot token no log."""
    import logging

    from solar_hub.services.notification import AlertMessage, NotificationService

    token = "secret_bot_token_999888777"
    service = NotificationService(
        repository=None,
        system_sid="TEST_SID",
        telegram_bot_token=token,
        telegram_chat_id="12345678",
    )

    class FailingClient:
        def post(self, url, **kwargs):
            raise ConnectionError(f"Falha de rede ao conectar em {url}")

    service._http_client = FailingClient()

    alert = AlertMessage(
        alert_key="TEST_ALERT",
        severity="INFO",
        title="Teste",
        message="Mensagem de teste",
    )

    with caplog.at_level(logging.ERROR):
        result = service.send_telegram(alert)

    assert result is False
    # Garante que o token real NÃO aparece em nenhum log gerado
    assert token not in caplog.text
    # Garante que a indicação mascarada está presente
    assert "[TOKEN_MASCARADO]" in caplog.text
