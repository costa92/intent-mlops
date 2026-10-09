from pathlib import Path

from intent_mlops.app import create_app
from intent_mlops.train import train


def make_client(tmp_path):
    train(Path("data/intents.csv"), tmp_path)
    app = create_app(tmp_path / "intent-model.joblib", tmp_path / "metadata.json")
    app.config.update(TESTING=True)
    return app.test_client()


def test_health_and_readiness(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert b"intent_api_requests_total" in metrics.data


def test_prediction_contract(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/predict", json={"text": "我无法登录"})
    body = response.get_json()
    assert response.status_code == 200
    assert body["label"] in {"billing", "technical_support", "account"}
    assert 0 <= body["confidence"] <= 1
    assert body["latency_ms"] >= 0


def test_prediction_label_metric(tmp_path):
    client = make_client(tmp_path)
    label = client.post("/predict", json={"text": "我无法登录"}).get_json()["label"]
    metrics = client.get("/metrics").data.decode("utf-8")
    assert "intent_api_predictions_total" in metrics
    counted = [
        line
        for line in metrics.splitlines()
        if line.startswith("intent_api_predictions_total{")
        and f'label="{label}"' in line
    ]
    assert counted and float(counted[0].rsplit(" ", 1)[1]) >= 1.0


def test_invalid_prediction_input(tmp_path):
    client = make_client(tmp_path)
    assert client.post("/predict", json={}).status_code == 400
