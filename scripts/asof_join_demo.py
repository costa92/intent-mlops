"""as-of join 演示：泄漏写法 vs point-in-time 正确写法。

配套第 16 篇《Feature Store 与训练—推理特征一致性》§3。

只依赖 pandas，不依赖 feast，也不依赖本项目的模型代码：
    python example/scripts/asof_join_demo.py

数据是合成的：每个用户有一串按时间递增的 open_tickets 快照，
而"投诉类"样本（label=1）之后工单数会明显上涨——也就是说
"现在工单多"是"当时那次提问是投诉"的**结果**。
用最新快照打特征，等于把标签的下游产物喂给模型。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pandas as pd

SEED = 42
N_USERS = 40
T0 = datetime(2026, 1, 1)


def make_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """构造 samples（训练样本）与 user_stats（特征快照历史）。"""
    rng = random.Random(SEED)
    samples: list[dict] = []
    stats: list[dict] = []

    for i in range(N_USERS):
        user_id = f"u{i:03d}"
        # 提问时刻：第 30~90 天之间的某一刻
        prediction_time = T0 + timedelta(days=rng.randint(30, 90), hours=rng.randint(0, 23))
        label = 1 if rng.random() < 0.5 else 0  # 1=投诉，0=普通咨询

        # 提问之前：工单数在 0~2 之间小幅波动（真实可用的特征）
        base = rng.randint(0, 2)
        for d in range(1, 6):
            stats.append(
                {
                    "user_id": user_id,
                    "event_time": prediction_time - timedelta(days=d * 3, hours=rng.randint(0, 12)),
                    "open_tickets": max(0, base + rng.randint(-1, 1)),
                }
            )
        # 提问之后：投诉用户工单显著上涨，普通用户几乎不变（未来信息）
        after = base + (rng.randint(5, 9) if label == 1 else rng.randint(0, 1))
        for d in range(1, 4):
            stats.append(
                {
                    "user_id": user_id,
                    "event_time": prediction_time + timedelta(days=d * 5),
                    "open_tickets": after + d,
                }
            )

        samples.append(
            {"user_id": user_id, "prediction_time": prediction_time, "label": label}
        )

    return (
        pd.DataFrame(samples).sort_values("prediction_time").reset_index(drop=True),
        pd.DataFrame(stats).sort_values("event_time").reset_index(drop=True),
    )


def leaky_join(samples: pd.DataFrame, user_stats: pd.DataFrame) -> pd.DataFrame:
    """❌ 泄漏写法：取每个用户的最新快照，直接按 user_id merge。"""
    latest = user_stats.sort_values("event_time").groupby("user_id").tail(1)
    return samples.merge(latest, on="user_id", how="left")


def asof_join(samples: pd.DataFrame, user_stats: pd.DataFrame) -> pd.DataFrame:
    """✅ 正确写法：只取 event_time <= prediction_time 的最新一条。"""
    return pd.merge_asof(
        samples.sort_values("prediction_time"),
        user_stats.sort_values("event_time"),
        left_on="prediction_time",
        right_on="event_time",
        by="user_id",
        direction="backward",
        tolerance=pd.Timedelta("7D"),
    )


def rule_f1(frame: pd.DataFrame, threshold: int = 3) -> float:
    """一个极简"规则模型"：open_tickets >= threshold 判为投诉。返回 F1。"""
    pred = (frame["open_tickets"].fillna(0) >= threshold).astype(int)
    truth = frame["label"]
    tp = int(((pred == 1) & (truth == 1)).sum())
    fp = int(((pred == 1) & (truth == 0)).sum())
    fn = int(((pred == 0) & (truth == 1)).sum())
    return 0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn)


def main() -> None:
    samples, user_stats = make_data()
    leaky = leaky_join(samples, user_stats)
    correct = asof_join(samples, user_stats)

    future_rows = int((leaky["event_time"] > leaky["prediction_time"]).sum())
    missing = int(correct["open_tickets"].isna().sum())
    lag = (correct["prediction_time"] - correct["event_time"]).dropna()

    leaky_f1 = rule_f1(leaky)
    correct_f1 = rule_f1(correct)

    print("=== 数据规模 ===")
    print(f"样本数              : {len(samples)}")
    print(f"特征快照数          : {len(user_stats)}")
    print()
    print("=== ❌ 泄漏写法 groupby().tail(1) + merge ===")
    print(f"取到未来快照的行数  : {future_rows} / {len(leaky)} ({future_rows / len(leaky):.0%})")
    print(f"open_tickets 均值   : {leaky['open_tickets'].mean():.2f}")
    print()
    print("=== ✅ 正确写法 pd.merge_asof(direction='backward') ===")
    print(f"取到未来快照的行数  : 0 / {len(correct)} (0%)")
    print(f"open_tickets 均值   : {correct['open_tickets'].mean():.2f}")
    print(f"因 tolerance=7d 判为缺失的行数 : {missing}")
    print(
        "特征滞后时长中位数  : "
        f"{lag.median().total_seconds() / 3600:.1f} 小时（prediction_time - event_time）"
    )
    print()
    print("=== 离线指标虚高（规则模型 open_tickets>=3 判投诉）===")
    print(f"用泄漏特征的离线 F1 : {leaky_f1:.3f}")
    print(f"用正确特征的离线 F1 : {correct_f1:.3f}   ← 线上真正能拿到的水平")
    print(f"虚高幅度            : +{leaky_f1 - correct_f1:.3f}")
    print()
    print("结论：direction='backward' 这一个参数，就是这 0.x 个 F1 的全部来源。")


if __name__ == "__main__":
    main()
