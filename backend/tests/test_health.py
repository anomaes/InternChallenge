from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_api_ok_even_without_erp():
    res = TestClient(app).get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "erp" in body
