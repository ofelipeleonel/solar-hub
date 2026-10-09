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
