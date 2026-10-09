# feature_repo — Feast 参考定义（不参与本项目构建）

配套[第 16 篇：Feature Store 与训练—推理特征一致性](https://costalong.com/notes/mlops/feature-store/)第 4 节。

## 这是什么

一份**参考定义**，不是本工程的运行组件。

本系列的意图分类模型不需要 Feature Store：特征全部来自请求体里的 `text` 字段，
`TfidfVectorizer` 的词表和 IDF 已经随 `Pipeline` 一起 `joblib.dump` 进了同一个模型文件，
训练和推理共用同一份特征实现，偏斜没有容身之处。

所以：

- **`feast` 不在 `pyproject.toml` 里**，也不会被 `make train` / `pytest` / CI 触碰。
  给主工程加一个用不上的重依赖，与本系列"依赖最小"的主张直接冲突。
- 这个目录里的 `definitions.py` 和 `feature_store.yaml` 是给"当你确实需要 Feature Store 时"看的模板。
- 想看**真的能跑**的一致性演示，用不依赖 feast 的
  [`../scripts/asof_join_demo.py`](../scripts/asof_join_demo.py)。

## 文件

| 文件 | 内容 |
|---|---|
| `definitions.py` | `Entity` / `FileSource` / `FeatureView` 三件套，TTL 7 天对应 §3 的 `tolerance` |
| `feature_store.yaml` | offline store = 本地 parquet（`file`），online store = 本地 `sqlite`，无云依赖 |

## 想实际跑一遍

需要**单独**装 feast（建议用独立虚拟环境，不要装进本工程的环境）：

```bash
python -m venv .venv-feast && source .venv-feast/bin/activate
pip install 'feast[redis]'   # 只用本地 sqlite 的话 `pip install feast` 即可
```

还需要自己准备离线数据 `data/user_stats.parquet`，至少包含这几列：

| 列 | 类型 | 说明 |
|---|---|---|
| `user_id` | string | 实体键 |
| `event_time` | timestamp | 事件时间，as-of join 的时间轴 |
| `created_at` | timestamp | 到达时间，同一 `event_time` 下用于去重 |
| `open_tickets` | int64 | 特征 |
| `avg_resolution_hours` | float32 | 特征 |

然后：

```bash
cd example/feature_repo

feast apply                 # 解析 definitions.py，写入 registry.db
feast entities list         # 确认 user 实体已注册
feast feature-views list    # 确认 user_stats 已注册

# 把离线数据物化到在线存储（sqlite），日常挂定时任务增量跑
feast materialize-incremental "$(date -u +%Y-%m-%dT%H:%M:%S)"

# 首次全量物化用 materialize（指定起止时间）
feast materialize 2026-01-01T00:00:00 "$(date -u +%Y-%m-%dT%H:%M:%S)"
```

读取两条路径（正文 §4）：

```python
from feast import FeatureStore

store = FeatureStore(repo_path=".")

# 离线：内部就是 as-of join，entity_df 需含 user_id + event_timestamp
training_df = store.get_historical_features(
    entity_df=samples,
    features=["user_stats:open_tickets"],
).to_df()

# 在线：按主键点查最新值
online = store.get_online_features(
    features=["user_stats:open_tickets"],
    entity_rows=[{"user_id": "u001"}],
).to_dict()
```

## 注意

- `materialize-incremental` 的执行频率直接决定在线特征新鲜度，这是必须进 SLO 的运维指标，
  见正文「在线特征新鲜度必须进 SLO」一节。
- `data/registry.db` 和 `data/online_store.db` 是 `feast apply` / `materialize` 生成的本地状态，
  不要提交进 git。
