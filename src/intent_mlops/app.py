from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import joblib
from flask import Flask, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

DEFAULT_MODEL = Path("artifacts/intent-model.joblib")
DEFAULT_METADATA = Path("artifacts/metadata.json")
REQUESTS = Counter(
    "intent_api_requests_total", "Prediction requests", ["status", "model_version"]
)
LATENCY = Histogram(
    "intent_api_prediction_seconds", "Prediction latency", ["model_version"]
)
PREDICTIONS = Counter(
    "intent_api_predictions_total", "Predictions by label", ["label", "model_version"]
)


def create_app(model_path: Path | None = None, metadata_path: Path | None = None) -> Flask:
    app = Flask(__name__)
    selected_model = model_path or Path(os.getenv("MODEL_PATH", str(DEFAULT_MODEL)))
    selected_metadata = metadata_path or Path(
        os.getenv("MODEL_METADATA_PATH", str(DEFAULT_METADATA))
    )

    state: dict = {"model": None, "metadata": {}}
    if selected_model.exists():
        state["model"] = joblib.load(selected_model)
    if selected_metadata.exists():
        state["metadata"] = json.loads(selected_metadata.read_text(encoding="utf-8"))

    @app.get("/healthz")
    def healthz():
        return {"status": "alive"}

    @app.get("/readyz")
    def readyz():
        if state["model"] is None:
            return {"status": "not_ready"}, 503
        return {
            "status": "ready",
            "model_version": state["metadata"].get("model_version", "unknown"),
        }

    @app.get("/metrics")
    def metrics():
        return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

    @app.post("/predict")
    def predict():
        if state["model"] is None:
            REQUESTS.labels("not_ready", "unknown").inc()
            return jsonify({"error": "model is not loaded"}), 503
        payload = request.get_json(silent=True)
        # 合法 JSON 不等于 dict：["x"] / "x" / 3 都能过 get_json，
        # 直接 .get() 会抛 AttributeError 变成不计数的 500。
        if not isinstance(payload, dict):
            REQUESTS.labels("invalid", "unknown").inc()
            return jsonify({"error": "body must be a JSON object"}), 400
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            REQUESTS.labels("invalid", "unknown").inc()
            return jsonify({"error": "text must be a non-empty string"}), 400
        if len(text) > 2000:
            REQUESTS.labels("too_long", "unknown").inc()
            return jsonify({"error": "text is too long"}), 413

        started = time.perf_counter()
        probabilities = state["model"].predict_proba([text])[0]
        best = int(probabilities.argmax())
        label = str(state["model"].classes_[best])
        model_version = state["metadata"].get("model_version", "unknown")
        elapsed = time.perf_counter() - started
        REQUESTS.labels("success", model_version).inc()
        LATENCY.labels(model_version).observe(elapsed)
        PREDICTIONS.labels(label, model_version).inc()
        event = {
            "event": "prediction",
            "request_id": request.headers.get("X-Request-ID", "unknown"),
            "model_version": model_version,
            "label": str(state["model"].classes_[best]),
            "confidence": round(float(probabilities[best]), 6),
            "latency_ms": round(elapsed * 1000, 3),
        }
        logging.getLogger("intent_mlops.prediction").info(json.dumps(event))
        return jsonify(
            {
                "label": str(state["model"].classes_[best]),
                "confidence": round(float(probabilities[best]), 6),
                "model_version": model_version,
                "latency_ms": round(elapsed * 1000, 3),
            }
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        """兜底：任何未捕获异常都必须计数，否则 500 不进 SLI。

        没有它，一个 AttributeError 就能让客户端持续收到 500，而
        intent_api_requests_total 一动不动——错误率、燃烧率、请求率
        全部继续显示健康。这是"故障发生时仪表盘全绿"的典型成因。
        """
        REQUESTS.labels("error", "unknown").inc()
        app.logger.exception("unhandled error in %s", request.path)
        return jsonify({"error": "internal error"}), 500

    return app


# 注意：只保留 factory，不要在模块级再建一个 app。
# 两者并存时 gunicorn 以 "intent_mlops.app:create_app()" 启动会先执行模块级
# 那次调用、再执行 factory，每个 worker 常驻两份模型。
# 需要模块级对象的场景（如 "intent_mlops.app:app"）请改用它并删掉工厂调用。
