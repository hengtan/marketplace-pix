from fastapi.testclient import TestClient

from inventory.main import app


def test_metrics_endpoint_is_exposed_with_red_series():
    client = TestClient(app)
    client.get("/openapi.json")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text
    assert 'route="/openapi.json"' in response.text
