from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_items() -> None:
    response = client.get("/items", params={"delay_ms": 0, "fail_rate": 0, "limit": 3})
    assert response.status_code == 200
    assert response.json()["count"] == 3
    assert len(response.json()["items"]) == 3
