from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import sklearn
import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from intent_mlops.validate import DEFAULT_DATA_PATH, validate_dataset

ARTIFACTS = Path("artifacts")
PARAMS_PATH = Path("params.yaml")
DEFAULT_PARAMS = {
    "test_size": 0.3,
    "random_state": 42,
    "analyzer": "char",
    "ngram_min": 2,
    "ngram_max": 4,
    "max_iter": 1000,
    "c": 1.0,
}
# 环境变量覆盖：便于第 07 篇那种一行一个 run 的对比实验。
ENV_OVERRIDES = {
    "TEST_SIZE": ("test_size", float),
    "RANDOM_STATE": ("random_state", int),
    "ANALYZER": ("analyzer", str),
    "NGRAM_MIN": ("ngram_min", int),
    "NGRAM_MAX": ("ngram_max", int),
    "MAX_ITER": ("max_iter", int),
    "C": ("c", float),
}


def load_params(params_path: Path = PARAMS_PATH) -> dict:
    """params.yaml 是唯一声明处，环境变量只做临时覆盖。"""
    params = dict(DEFAULT_PARAMS)
    if params_path.exists():
        loaded = yaml.safe_load(params_path.read_text(encoding="utf-8")) or {}
        params.update(loaded.get("train", {}))
    for env_name, (key, cast) in ENV_OVERRIDES.items():
        raw = os.getenv(env_name)
        if raw is not None:
            params[key] = cast(raw)
    return params


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def train(data_path: Path, output_dir: Path, params: dict | None = None) -> dict:
    params = params if params is not None else load_params()
    validation = validate_dataset(data_path)
    data = pd.read_csv(data_path)
    x_train, x_test, y_train, y_test = train_test_split(
        data["text"],
        data["label"],
        test_size=params["test_size"],
        random_state=params["random_state"],
        stratify=data["label"],
    )
    model = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer=params["analyzer"],
                    ngram_range=(params["ngram_min"], params["ngram_max"]),
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    C=params["c"],
                    max_iter=params["max_iter"],
                    random_state=params["random_state"],
                ),
            ),
        ]
    )
    model.fit(x_train, y_train)
    prediction = model.predict(x_test)
    macro_f1 = float(f1_score(y_test, prediction, average="macro"))

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "intent-model.joblib"
    joblib.dump(model, model_path)
    metrics = {
        "macro_f1": macro_f1,
        "report": classification_report(y_test, prediction, output_dict=True),
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metadata = {
        "model_version": os.getenv("MODEL_VERSION", "local-dev"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": sha256(data_path),
        "model_sha256": sha256(model_path),
        "sklearn_version": sklearn.__version__,
        "params": params,
        "validation": validation,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"metrics": metrics, "metadata": metadata}


def main() -> None:
    data_path = Path(os.getenv("DATA_PATH", str(DEFAULT_DATA_PATH)))
    result = train(data_path, ARTIFACTS, load_params())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

