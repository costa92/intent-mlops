"""Feast 特征定义（参考实现，本项目不依赖 feast）。

配套第 16 篇《Feature Store 与训练—推理特征一致性》§4。
本项目的意图分类模型不需要 Feature Store（特征已随 sklearn Pipeline 一起序列化），
这份定义只用来演示"一份定义、两条读取路径"长什么样。

跑起来需要单独 `pip install feast`，见同目录 README.md。
"""

from datetime import timedelta

from feast import Entity, FeatureView, Field, FileSource, ValueType
from feast.types import Float32, Int64

# Entity：特征挂在哪个业务主键上
user = Entity(name="user", join_keys=["user_id"], value_type=ValueType.STRING)

# Source：原始数据在哪，以及哪一列是事件时间
user_stats_source = FileSource(
    name="user_stats_source",
    path="data/user_stats.parquet",
    timestamp_field="event_time",           # point-in-time join 的时间轴
    created_timestamp_column="created_at",  # 同一事件时间下的到达顺序，用于去重
)

# FeatureView：一组共享实体、来源和 TTL 的特征
user_stats_view = FeatureView(
    name="user_stats",
    entities=[user],
    ttl=timedelta(days=7),                  # 等价于 §3 里 merge_asof 的 tolerance
    schema=[
        Field(name="open_tickets", dtype=Int64),
        Field(name="avg_resolution_hours", dtype=Float32),
    ],
    source=user_stats_source,
    online=True,                            # 允许物化到在线存储
    tags={"owner": "customer-platform", "version": "v2"},
)
