# Monitoring assets

这些清单以 Kubernetes `1.34.x`、Prometheus Operator `0.90.1` 为文档基线，假设集群已安装 Operator 和实际的 Prometheus 实例。仅安装 CRD 不会自动抓取指标；Prometheus 实例的 `serviceMonitorSelector` 和 `ruleSelector` 必须能选中这些对象。

## 启用顺序

四份清单有依赖关系，**必须按顺序 apply**：

```bash
kubectl apply -f servicemonitor.yaml          # 1. 先有抓取，才有原始指标
kubectl apply -f recordingrule.yaml           # 2. 再有预聚合 SLI 序列
kubectl apply -f prometheusrule-burnrate.yaml # 3. 最后才是依赖 SLI 的燃烧率告警
kubectl apply -f prometheusrule.yaml          # 可选，固定阈值示例
```

依赖链是单向的：

| 文件 | 产出 | 依赖 |
|---|---|---|
| `servicemonitor.yaml` | 抓取 `intent_api_*` 原始指标 | Prometheus 实例的 `serviceMonitorSelector` 能选中它 |
| `recordingrule.yaml` | `intent_api:request_error_ratio:rate5m/30m/1h/6h`、`intent_api:prediction_seconds:p95_5m`、`intent_api:request:rate5m` | 原始指标已被抓取 |
| `prometheusrule-burnrate.yaml` | 快慢双窗燃烧率告警 + 延迟告警 | **只引用 recording rule 序列**，跳过第 2 步会让所有表达式为空、告警永不触发 |
| `prometheusrule.yaml` | 三条告警：错误率、p95 延迟、预测类别倾斜 | 直接查原始指标，不依赖 recording rule |
| `grafana-dashboard.json` | 请求率 / 错误率 / p95 / 错误预算余量 / 预测类别分布 | recording rule（前三个面板走预聚合序列） |

跳过第 2 步是最常见的失效方式：CRD apply 成功、`kubectl get prometheusrule` 一切正常，但告警永远是 Inactive。用 `count(intent_api:request_error_ratio:rate5m)` 确认序列真的产生了再上告警。

新建 recording rule 后需要等待至少一个 `interval`（30s）才会有第一个数据点；`rate6h` 这类长窗序列在数据积累够之前值不可信，别在刚 apply 的头几小时按它做决策。

仪表盘导入：Grafana → Dashboards → Import → Upload JSON，选一个 Prometheus 数据源即可（面板用 `${datasource}` 变量，不写死 uid）。

## 两套告警的关系

`prometheusrule.yaml` 有三条规则。前两条是固定阈值（错误率 > 2%、p95 > 150 ms，`for: 10m`）**属展示用**：它演示了 PromQL 的写法，但单一阈值紧了被日常抖动吵醒、松了漏掉慢性烧预算。

`prometheusrule-burnrate.yaml` 才是生产用法：快窗（1h ∧ 5m 燃烧率 > 14.4，`severity: critical`）立即 page，慢窗（6h ∧ 30m 燃烧率 > 6，`severity: warning`）开工单。两窗取 `and`——长窗判断"够严重"，短窗判断"还在发生"。两条规则都带 `intent_api:request:rate5m > 0.1` 的绝对量守卫，避免零流量时比率失真误报。

第三条 `IntentApiPredictionSkew`（某一类预测占比 > 60%，`severity: info`）**不属于这组取舍**：它监控的是预测分布倾斜而非服务 SLI，两套方案下都应保留，详见[第 17 篇 §6](https://costalong.com/notes/mlops/model-monitoring-drift/)。

前两条与燃烧率告警二选一即可，同时启用会产生重复告警——注意 `prometheusrule-burnrate.yaml` 里的 `IntentApiP95LatencyDegraded` 与 `prometheusrule.yaml` 的 `IntentApiHighP95Latency` 阈值同为 0.15，是最典型的一对重复。原理见[第 19 篇 2.3 节](https://costalong.com/notes/mlops/observability-slo/)。

告警阈值和 SLO 目标（示例按 99.9% / 错误预算 0.001 写死）需要根据压测基线和正式 SLO 调整。模型质量和漂移指标具有标签延迟，不应直接使用实时 HTTP 告警替代离线质量任务。

示例镜像使用一个 Gunicorn 进程加多个线程，确保进程内 Prometheus 计数一致。若生产环境要在单个 Pod 中启用多个 Gunicorn worker，需要配置 `PROMETHEUS_MULTIPROC_DIR` 和 multiprocess collector；更简单的方式是保持单进程并通过 Kubernetes 水平扩容。
