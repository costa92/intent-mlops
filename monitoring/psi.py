"""psi.py — 连续特征与离散标签的总体稳定性指数。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def psi_numeric(expected, actual, bins: int = 10, eps: float = 1e-6) -> float:
    """连续特征 PSI：用基线的分位数定义分箱，再比较两侧占比。"""
    expected = np.asarray(expected, dtype=float)
    actual = np.asarray(actual, dtype=float)
    # 非有限值先剔除：NaN 会污染分位数和直方图，Inf 会把分箱压成一格
    expected = expected[np.isfinite(expected)]
    actual = actual[np.isfinite(actual)]
    if expected.size == 0 or actual.size == 0:
        return float("nan")                 # 无法计算，不是"没漂移"

    # 关键：分箱边界只由基线决定，否则两次分箱不可比
    quantiles = np.linspace(0, 100, bins + 1)
    edges = np.unique(np.percentile(expected, quantiles))
    if len(edges) < 3:
        # 基线几乎是常数，分位数分箱失效。**不能返回 0.0** —— 那会把
        # "基线全 0、当前大量非零"这种最明显的漂移报成完全稳定。
        # 返回 NaN 让上游门禁按"数据不足"处理（hold + 调查）。
        return float("nan")
    edges[0], edges[-1] = -np.inf, np.inf

    e_cnt, _ = np.histogram(expected, bins=edges)
    a_cnt, _ = np.histogram(actual, bins=edges)
    e_pct = np.clip(e_cnt / max(e_cnt.sum(), 1), eps, None)
    a_pct = np.clip(a_cnt / max(a_cnt.sum(), 1), eps, None)
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def psi_categorical(expected, actual, eps: float = 1e-6) -> float:
    """离散分布 PSI：适用于预测标签占比这类天然分箱的数据。"""
    e = pd.Series(expected).value_counts(normalize=True)
    a = pd.Series(actual).value_counts(normalize=True)
    categories = e.index.union(a.index)
    e_pct = np.clip(e.reindex(categories, fill_value=0.0).to_numpy(), eps, None)
    a_pct = np.clip(a.reindex(categories, fill_value=0.0).to_numpy(), eps, None)
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


if __name__ == "__main__":
    rng = np.random.default_rng(42)
    base_conf = rng.beta(6, 2, 5000)     # 基线置信度分布
    print("confidence 无漂移 PSI =",
          round(psi_numeric(base_conf, rng.beta(6, 2, 5000)), 4))
    print("confidence 有漂移 PSI =",
          round(psi_numeric(base_conf, rng.beta(3, 3, 5000)), 4))

    labels = ["billing", "technical_support", "account"]
    print("label 分布 PSI =", round(psi_categorical(
        rng.choice(labels, 5000, p=[0.40, 0.35, 0.25]),
        rng.choice(labels, 5000, p=[0.65, 0.20, 0.15])), 4))
