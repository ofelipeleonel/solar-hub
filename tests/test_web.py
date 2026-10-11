import pytest
from fastapi.testclient import TestClient

from solar_hub.interfaces.web.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_api_status(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "sid" in data
    assert "capacity_kwp" in data
    assert "budget" in data
    assert "remaining_month" in data["budget"]


def test_api_inverters(client):
    response = client.get("/api/inverters")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_api_history(client):
    response = client.get("/api/history")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_api_hall_of_fame(client):
    response = client.get("/api/hall-of-fame")
    assert response.status_code == 200
    data = response.json()
    assert "best_day" in data


def test_web_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "SolarHub" in response.text
    # Garante que os créditos ao ez1-monitor estão presentes no rodapé da página
    assert "ez1-monitor" in response.text


def test_api_channels(client):
    response = client.get("/api/channels")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_api_diagnostics(client):
    response = client.get("/api/diagnostics")
    assert response.status_code == 200
    data = response.json()
    assert "health_score" in data
    assert "status" in data
    assert "anomalies" in data
    assert "recommendations" in data


def test_api_alerts(client):
    response = client.get("/api/alerts")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_api_export_endpoints(client):
    # Resumo
    res_summary = client.get("/api/export/summary")
    assert res_summary.status_code == 200
    data_sum = res_summary.json()
    assert "total_days_recorded" in data_sum

    # Geração CSV
    res_gen_csv = client.get("/api/export/generation?format=csv")
    assert res_gen_csv.status_code == 200
    assert "text/csv" in res_gen_csv.headers.get("content-type", "")
    assert "system_sid,date,energy_kwh" in res_gen_csv.text

    # Geração JSON
    res_gen_json = client.get("/api/export/generation?format=json")
    assert res_gen_json.status_code == 200
    assert "application/json" in res_gen_json.headers.get("content-type", "")

    # Canais CSV
    res_chan_csv = client.get("/api/export/channels?format=csv")
    assert res_chan_csv.status_code == 200
    assert "text/csv" in res_chan_csv.headers.get("content-type", "")
    assert "inverter_uid,channel,date" in res_chan_csv.text


def test_api_metrics(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    assert "# HELP solar_today_kwh" in response.text
    assert "# TYPE solar_today_kwh gauge" in response.text
    assert "solar_today_kwh" in response.text
    assert "solar_budget_monthly_limit" in response.text


def test_api_settings_and_update(client):
    # 1. Busca configurações iniciais
    res_get = client.get("/api/settings")
    assert res_get.status_code == 200
    data = res_get.json()
    assert "telegram_bot_token" in data
    assert "alert_cooldown_hours" in data
    assert "mqtt_enabled" in data

    # 2. Atualiza configurações
    payload = {
        "telegram_bot_token": "123456789:ABCDEF1234567890",
        "telegram_chat_id": "99887766",
        "webhook_url": "https://discord.com/api/webhooks/test",
        "alert_cooldown_hours": 6,
        "alert_min_health_score": 85,
        "mqtt_enabled": True,
        "mqtt_broker": "192.168.1.50",
        "mqtt_port": 1883,
        "mqtt_username": "solar_user",
    }
    res_post = client.post("/api/settings", json=payload)
    assert res_post.status_code == 200
    assert res_post.json()["success"] is True

    # 3. Verifica se as configurações foram salvas e mascaradas
    res_get_updated = client.get("/api/settings")
    assert res_get_updated.status_code == 200
    up_data = res_get_updated.json()
    assert up_data["telegram_chat_id"] == "99887766"
    assert up_data["alert_cooldown_hours"] == 6
    assert up_data["alert_min_health_score"] == 85
    assert up_data["mqtt_enabled"] is True
    assert up_data["mqtt_broker"] == "192.168.1.50"
    assert up_data["has_telegram"] is True


def test_api_alerts_test(client):
    # Testa endpoint de teste de alertas (sem disparar se canais forem vazios/mockados)
    response = client.post("/api/alerts/test")
    assert response.status_code == 200
    data = response.json()
    assert "success" in data


def test_api_sync_endpoint(client, monkeypatch):
    from datetime import datetime, timezone

    from solar_hub.services.collector import SyncResult

    # Mock do CollectorService.sync_current e sync_channels para não bater na API externa
    def mock_sync_current(self, force=False):
        return SyncResult(
            success=True,
            energy_today_kwh=15.42,
            message="Mocked sync ok",
            target_date="2026-10-09",
            lifetime_kwh=100.0,
            is_finalized=False,
            timestamp=datetime.now(timezone.utc),
        )

    def mock_sync_channels(self, force=False):
        return 4

    monkeypatch.setattr("solar_hub.services.collector.CollectorService.sync_current", mock_sync_current)
    monkeypatch.setattr("solar_hub.services.collector.CollectorService.sync_channels", mock_sync_channels)

    res = client.post("/api/sync", json={"force": False, "sync_channels": True})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["today_kwh"] == 15.42
    assert data["channels_updated"] == 4


def test_api_mqtt_publish_endpoint(client, monkeypatch):
    # Mock do HomeAssistantMqttService.publish_all
    def mock_publish_all(self):
        return {"success": True, "message": "Sensores publicados mock"}

    monkeypatch.setattr("solar_hub.services.mqtt.HomeAssistantMqttService.publish_all", mock_publish_all)

    res = client.post("/api/mqtt/publish")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "mock" in data["message"]




