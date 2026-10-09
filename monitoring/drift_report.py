"""drift_report.py — 每日离线漂移报告（Evidently）。

Evidently 不在 example 的依赖里（它只用于离线分析，不进推理镜像）。
运行前先装：pip install "evidently>=0.7"
"""
from __future__ import annotations

import sys
from pathlib import Path

REFERENCE = Path("data/reference_window.parquet")
CURRENT = Path("data/current_window.parquet")
OUTPUT = Path("reports/drift-report.html")


def main() -> int:
    try:
        import pandas as pd
        from evidently import Report
        from evidently.presets import DataDriftPreset, TargetDriftPreset
    except ImportError as exc:
        print(f"[drift_report] 缺少依赖：{exc.name}", file=sys.stderr)
        print('[drift_report] 请先安装：pip install "evidently>=0.7" pandas pyarrow',
              file=sys.stderr)
        return 1

    for path in (REFERENCE, CURRENT):
        if not path.exists():
            print(f"[drift_report] 缺少输入文件：{path}", file=sys.stderr)
            return 1

    # reference：训练集或上一个稳定周期的采样
    reference = pd.read_parquet(REFERENCE)
    # current：过去 24h 的推理事件（从日志/数仓回捞）
    current = pd.read_parquet(CURRENT)

    # 两份 DataFrame 至少包含：text_length / char_diversity 等特征摘要，
    # 以及 prediction（预测标签）、confidence，有标签时再加 target
    report = Report(metrics=[
        DataDriftPreset(),      # 输入特征分布漂移
        TargetDriftPreset(),    # 预测/标签分布漂移
    ])
    snapshot = report.run(reference_data=reference, current_data=current)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    snapshot.save_html(str(OUTPUT))
    print(f"[drift_report] 报告已写入 {OUTPUT}")

    result = snapshot.dict()
    print(result["metrics"][0])   # 供 CI 做门禁判断
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
