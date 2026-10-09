"""基线对比门：把当前验证摘要和一份已批准基线做比较。

第 1 节的 validate_dataset 只看当前这一份数据，这里补上"它和上一版的关系"。
输入是两份 validate_dataset 的输出（artifacts/validation.json 结构），
阈值来自 thresholds.yaml，结果用退出码表达：0 通过 / 1 warning / 2 fail。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from intent_mlops.validate import load_thresholds

DEFAULT_CURRENT_PATH = Path("artifacts/validation.json")
DEFAULT_BASELINE_PATH = Path("artifacts/validation.baseline.json")

EXIT_PASS = 0
EXIT_WARN = 1
EXIT_FAIL = 2


def class_ratios(summary: dict) -> dict:
    rows = int(summary["rows"])
    if rows <= 0:
        return {}
    return {label: count / rows for label, count in summary["labels"].items()}


def compare_to_baseline(current: dict, baseline: dict, thresholds: dict | None = None) -> dict:
    """返回 {"status": pass|warning|fail, "warnings": [...], "failures": [...], "metrics": {...}}。"""
    thresholds = thresholds if thresholds is not None else load_thresholds()
    volume = thresholds["volume"]
    drift = thresholds["drift"]

    warnings: list[str] = []
    failures: list[str] = []
    metrics: dict = {}

    # 总样本量变化：不对称阈值，缩减比增长危险。
    base_rows = int(baseline["rows"])
    new_rows = int(current["rows"])
    change_pct = (new_rows - base_rows) / base_rows * 100 if base_rows else 0.0
    metrics["rows_change_pct"] = round(change_pct, 4)
    if change_pct < -float(volume["total_rows_shrink_fail_pct"]):
        failures.append(
            f"rows shrank {abs(change_pct):.1f}% ({base_rows} -> {new_rows}), "
            f"fail threshold {volume['total_rows_shrink_fail_pct']}%"
        )
    elif change_pct > float(volume["total_rows_growth_warn_pct"]):
        warnings.append(
            f"rows grew {change_pct:.1f}% ({base_rows} -> {new_rows}), "
            f"warn threshold {volume['total_rows_growth_warn_pct']}%"
        )

    # 类别比例变化：max|p_new - p_base|。
    base_ratios = class_ratios(baseline)
    new_ratios = class_ratios(current)
    deltas = {
        label: abs(new_ratios.get(label, 0.0) - base_ratios.get(label, 0.0))
        for label in set(base_ratios) | set(new_ratios)
    }
    max_delta = max(deltas.values()) if deltas else 0.0
    metrics["max_class_ratio_delta"] = round(max_delta, 4)
    if max_delta > float(drift["class_ratio_fail"]):
        failures.append(
            f"class ratio drifted {max_delta:.3f}, fail threshold {drift['class_ratio_fail']}"
        )
    elif max_delta > float(drift["class_ratio_warn"]):
        warnings.append(
            f"class ratio drifted {max_delta:.3f}, warn threshold {drift['class_ratio_warn']}"
        )

    # 文本长度分布：验证摘要目前只落了 max_text_length，
    # 真实项目应改为 p50/p95，这里复用同一条相对变化阈值。
    base_len = int(baseline.get("max_text_length", 0))
    new_len = int(current.get("max_text_length", 0))
    if base_len:
        len_change_pct = abs(new_len - base_len) / base_len * 100
        metrics["max_text_length_change_pct"] = round(len_change_pct, 4)
        if len_change_pct > float(drift["p95_text_length_warn_pct"]):
            warnings.append(
                f"max text length changed {len_change_pct:.1f}% ({base_len} -> {new_len}), "
                f"warn threshold {drift['p95_text_length_warn_pct']}%"
            )

    status = "fail" if failures else ("warning" if warnings else "pass")
    return {"status": status, "warnings": warnings, "failures": failures, "metrics": metrics}


def main() -> None:
    current_path = Path(os.getenv("VALIDATION_PATH", str(DEFAULT_CURRENT_PATH)))
    baseline_path = Path(os.getenv("BASELINE_PATH", str(DEFAULT_BASELINE_PATH)))
    if not current_path.exists():
        raise ValueError(f"validation summary does not exist: {current_path}")
    if not baseline_path.exists():
        # 没有已批准基线时无从对比，视为通过并明确说出来，而不是假装比过了。
        print(
            json.dumps(
                {"status": "skipped", "reason": f"baseline not found: {baseline_path}"},
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(EXIT_PASS)

    current = json.loads(current_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    report = compare_to_baseline(current, baseline)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit({"pass": EXIT_PASS, "warning": EXIT_WARN, "fail": EXIT_FAIL}[report["status"]])


if __name__ == "__main__":
    main()
