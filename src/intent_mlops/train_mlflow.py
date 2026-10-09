from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path

import joblib
import mlflow

from intent_mlops.train import ARTIFACTS, DEFAULT_DATA_PATH, load_params, train

SAMPLE_TEXT = "为什么这个月重复扣款了"


def measure_p95_inference_ms(model_path: Path, rounds: int = 200) -> float:
    """单条推理延迟的 p95，单位毫秒。

    这是离线门禁用的粗测：同一进程、无 HTTP 开销、单条不批量，
    只用来挡住"新版本慢了一个数量级"这种明显退化，不能当 SLI 用
    （线上口径见第 19 篇）。
    """
    model = joblib.load(model_path)
    samples = []
    for _ in range(rounds):
        start = time.perf_counter()
        model.predict_proba([SAMPLE_TEXT])
        samples.append((time.perf_counter() - start) * 1000)
    return float(statistics.quantiles(samples, n=100)[94])


def main() -> None:
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT", "intent-classifier"))
    params = load_params()
    with mlflow.start_run() as run:
        result = train(
            Path(os.getenv("DATA_PATH", str(DEFAULT_DATA_PATH))), ARTIFACTS, params
        )
        mlflow.log_params(
            {
                "algorithm": "tfidf-logistic-regression",
                "git_sha": os.getenv("GIT_SHA", "local"),
                "dataset_sha256": result["metadata"]["dataset_sha256"],
                **params,
            }
        )
        # 只记 macro_f1 是不够的：promote.py 的离线门禁还要看类别级 recall 和
        # 推理延迟，缺一项就会被 fail-close 挡下（见第 15 篇第 2 节）。
        report = result["metrics"]["report"]
        mlflow.log_metrics(
            {
                "macro_f1": result["metrics"]["macro_f1"],
                "weighted_f1": report["weighted avg"]["f1-score"],
                **{
                    f"{label}_recall": report[label]["recall"]
                    for label in ("billing", "technical_support", "account")
                },
                "p95_inference_ms": measure_p95_inference_ms(
                    ARTIFACTS / "intent-model.joblib"
                ),
            }
        )
        mlflow.log_artifacts(str(ARTIFACTS), artifact_path="intent-model")
        print(json.dumps({"run_id": run.info.run_id}, indent=2))


if __name__ == "__main__":
    main()

