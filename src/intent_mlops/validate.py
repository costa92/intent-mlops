from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import yaml

EXPECTED_LABELS = {"billing", "technical_support", "account"}
DEFAULT_DATA_PATH = Path("data/intents.csv")
THRESHOLDS_PATH = Path("thresholds.yaml")
# thresholds.yaml 缺失时的内置回落值，与文件里的数值保持一致。
DEFAULT_THRESHOLDS = {
    "schema": {
        "required_columns": ["text", "label"],
        "expected_labels": sorted(EXPECTED_LABELS),
        "min_text_length": 2,
        "allow_duplicates": False,
    },
    "volume": {
        "min_samples_per_label": 5,
        "total_rows_shrink_fail_pct": 10,
        "total_rows_growth_warn_pct": 50,
    },
    "drift": {
        "class_ratio_warn": 0.05,
        "class_ratio_fail": 0.15,
        "p95_text_length_warn_pct": 30,
        "oov_rate_warn": 0.20,
    },
    "governance": {
        "owner": "platform-ml",
        "purpose": "intent-classification",
        "retention_days": 365,
    },
}


def load_thresholds(thresholds_path: Path = THRESHOLDS_PATH) -> dict:
    """thresholds.yaml 是唯一声明处，文件缺失时回落到内置默认值。"""
    thresholds = {group: dict(values) for group, values in DEFAULT_THRESHOLDS.items()}
    if thresholds_path.exists():
        loaded = yaml.safe_load(thresholds_path.read_text(encoding="utf-8")) or {}
        for group, values in loaded.items():
            thresholds.setdefault(group, {}).update(values or {})
    return thresholds


def validate_dataset(path: Path, thresholds: dict | None = None) -> dict:
    thresholds = thresholds if thresholds is not None else load_thresholds()
    schema = thresholds["schema"]
    volume = thresholds["volume"]
    required_columns = list(schema["required_columns"])
    expected_labels = set(schema["expected_labels"])

    if not path.exists():
        raise ValueError(f"dataset does not exist: {path}")

    data = pd.read_csv(path)
    if list(data.columns) != required_columns:
        raise ValueError(f"dataset columns must be exactly: {','.join(required_columns)}")
    if data.empty:
        raise ValueError("dataset must not be empty")
    if data[["text", "label"]].isna().any().any():
        raise ValueError("text and label must not contain null values")

    data["text"] = data["text"].astype(str).str.strip()
    data["label"] = data["label"].astype(str).str.strip()
    min_text_length = int(schema["min_text_length"])
    if (data["text"].str.len() < min_text_length).any():
        raise ValueError(
            f"every text value must contain at least {min_text_length} characters"
        )
    if not schema["allow_duplicates"] and data["text"].duplicated().any():
        raise ValueError("duplicate text samples are not allowed")

    labels = set(data["label"].unique())
    if labels != expected_labels:
        raise ValueError(f"expected labels {sorted(expected_labels)}, got {sorted(labels)}")

    counts = data["label"].value_counts().to_dict()
    min_per_label = int(volume["min_samples_per_label"])
    if min(counts.values()) < min_per_label:
        raise ValueError(f"each label must contain at least {min_per_label} samples")

    return {
        "rows": int(len(data)),
        "labels": {key: int(value) for key, value in sorted(counts.items())},
        "max_text_length": int(data["text"].str.len().max()),
    }


def main() -> None:
    path = Path(os.getenv("DATA_PATH", str(DEFAULT_DATA_PATH)))
    print(json.dumps(validate_dataset(path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

