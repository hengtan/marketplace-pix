from fastapi.testclient import TestClient

from gateway.main import app


def test_metrics_endpoint_is_exposed():
    client = TestClient(app)
    client.get("/health")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "http_request_duration_seconds" in response.text
    assert 'route="/health"' in response.text
