#!/usr/bin/env python3
"""Canary 放量门禁判据（第 15 篇第 7 节）。

decide() 返回三档决策：promote（继续放量）/ hold（暂停）/ rollback（回滚）。
阈值集中在下面的常量区，改数字即改标准，git log 就是审计记录。

自测：

    python deploy/canary/gate.py
"""

from __future__ import annotations

import math

# --- 阈值区：按业务错误成本调，结构不变 ---------------------------------

# 红线（触发即回滚）
ROLLBACK_ERROR_RATE = 0.02  # HTTP 5xx 率，10 min 滚动
ROLLBACK_P95_FACTOR = 1.5  # p95 延迟相对 baseline 的倍数，10 min 滚动
ROLLBACK_PSI = 0.25  # 预测分布 PSI，30 min 累积
ROLLBACK_CORRECTION_DELTA = 0.05  # 人工纠正率相对 baseline 的绝对增量，4 h
ROLLBACK_MIN_RECALL = 0.72  # 单类别 recall（technical_support），4 h

# 黄线（触发即暂停）
HOLD_ERROR_RATE = 0.005
HOLD_P95_FACTOR = 1.2
HOLD_PSI = 0.10
HOLD_LOW_CONF_DELTA = 0.03  # 低置信度（max_prob < 0.6）比例增量，30 min
HOLD_CORRECTION_DELTA = 0.02  # 人工纠正率增量，4 h（超过 ROLLBACK_ 那档才回滚）
HOLD_MIN_RECALL = 0.78  # 单类别 recall 低于此值先暂停，低于 ROLLBACK_ 才回滚
ROLLBACK_LOW_CONF_DELTA = 0.08  # 低置信度比例增量超过这个直接回滚

# 放量档位与每档最短驻留时间
STAGES = (5, 25, 50, 100)
MIN_STAGE_MINUTES = 30
# 5% 档样本量不足，跳过 4 h 业务判据；25% 及以后强制评估
BUSINESS_GATE_FROM_PCT = 25


REQUIRED_METRICS = (
    "error_rate_10m",
    "p95_ms_10m",
    "psi_30m",
    "low_conf_ratio_30m",
    "correction_rate_4h",
    "recall_technical_support_4h",
    "stage_minutes",
)


def decide(m: dict, baseline: dict, stage_pct: int) -> str:
    """返回 rollback / hold / promote。任一红线触发即回滚。

    入口先做有限性检查：Prometheus 在窗口内无样本时返回 NaN，而 NaN 的
    所有大小比较都是 False——不检查就会一路穿过全部红线和黄线走到
    promote，也就是"监控瞎了所以放量"。缺失、NaN、Inf 一律 hold。
    """
    for key in REQUIRED_METRICS:
        value = m.get(key)
        if value is None or not math.isfinite(float(value)):
            return "hold"
    for key in ("p95_ms", "correction_rate", "low_conf_ratio"):
        value = baseline.get(key)
        if value is None or not math.isfinite(float(value)):
            return "hold"

    # 系统红线：这些是"服务坏了"的直接证据，单独成立即可回滚。
    if (
        m["error_rate_10m"] >= ROLLBACK_ERROR_RATE
        or m["p95_ms_10m"] > baseline["p95_ms"] * ROLLBACK_P95_FACTOR
    ):
        return "rollback"

    # 业务判据只在样本量足够的档位评估
    business_gate = stage_pct >= BUSINESS_GATE_FROM_PCT
    business_degraded = business_gate and (
        m["correction_rate_4h"]
        > baseline["correction_rate"] + ROLLBACK_CORRECTION_DELTA
        or m["recall_technical_support_4h"] < ROLLBACK_MIN_RECALL
    )
    if business_degraded:
        return "rollback"

    # 分布类信号（PSI、低置信度比例）**不单独触发回滚**。
    # 它们只证明"变了"，不证明"变差了"——一次正常的业务活动、一次
    # 上游文案调整都能把 PSI 推过 0.25。只有当分布剧变**同时**伴随
    # 带标签的质量退化时，才有证据说新版本更差。单独出现时一律 hold，
    # 交给人去查（第 17 篇第 4 节讲了 PSI 的四条局限）。
    distribution_alarm = (
        m["psi_30m"] >= ROLLBACK_PSI
        or m["low_conf_ratio_30m"]
        > baseline["low_conf_ratio"] + ROLLBACK_LOW_CONF_DELTA
    )
    if distribution_alarm:
        return "hold"

    if (
        m["error_rate_10m"] >= HOLD_ERROR_RATE
        or m["p95_ms_10m"] > baseline["p95_ms"] * HOLD_P95_FACTOR
        or m["psi_30m"] >= HOLD_PSI
        or m["low_conf_ratio_30m"] > baseline["low_conf_ratio"] + HOLD_LOW_CONF_DELTA
    ):
        return "hold"

    # 业务判据的中间档：没坏到要回滚，但不能继续放量
    if business_gate and (
        m["correction_rate_4h"] > baseline["correction_rate"] + HOLD_CORRECTION_DELTA
        or m["recall_technical_support_4h"] < HOLD_MIN_RECALL
    ):
        return "hold"

    return "promote" if m["stage_minutes"] >= MIN_STAGE_MINUTES else "hold"


# --- 自测样例 -----------------------------------------------------------

# baseline 必须来自当前 production 的同期数据，否则正常波动会误触发
BASELINE = {"p95_ms": 40.0, "correction_rate": 0.04, "low_conf_ratio": 0.10}

_HEALTHY = {
    "error_rate_10m": 0.001,
    "p95_ms_10m": 42.0,
    "psi_30m": 0.03,
    "low_conf_ratio_30m": 0.11,
    "correction_rate_4h": 0.04,
    "recall_technical_support_4h": 0.81,
    "stage_minutes": 35,
}


def _sample(**overrides: float) -> dict:
    return {**_HEALTHY, **overrides}


def _selftest() -> None:
    cases = [
        ("健康且驻留够 30min", _sample(), 25),
        ("驻留不足 30min", _sample(stage_minutes=12), 25),
        ("延迟到 1.3x baseline", _sample(p95_ms_10m=52.0), 25),
        ("PSI 0.15 分布偏移", _sample(psi_30m=0.15), 50),
        ("5xx 率 2.5%", _sample(error_rate_10m=0.025), 5),
        ("PSI 0.4 但系统指标正常（只 hold，不回滚）", _sample(psi_30m=0.40), 5),
        ("recall 跌到 0.70 @5%（样本不足，不评估）", _sample(recall_technical_support_4h=0.70), 5),
        ("recall 跌到 0.70 @25%", _sample(recall_technical_support_4h=0.70), 25),
    ]
    for name, metrics, stage_pct in cases:
        print(f"{decide(metrics, BASELINE, stage_pct):>8}  [{stage_pct:>3}%]  {name}")


if __name__ == "__main__":
    _selftest()
