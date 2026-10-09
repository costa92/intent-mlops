# 服务网格清单（Istio）

配套[第 12 篇](https://costalong.com/notes/mlops/gateway-service-mesh/)。**先读这句：只有一个单体推理服务的项目不需要网格**，这些清单是给"多服务互调 + 需要零信任 + 需要按权重切流"的场景准备的。

| 文件 | API | 作用 |
|---|---|---|
| `peerauthentication.yaml` | `security.istio.io/v1` | 命名空间内强制 mTLS（STRICT） |
| `authorizationpolicy.yaml` | `security.istio.io/v1` | 默认拒绝 + 只放行网关与 Prometheus |
| `destinationrule.yaml` | `networking.istio.io/v1` | 定义 `stable` / `canary` subset、连接池、熔断 |
| `virtualservice.yaml` | `networking.istio.io/v1` | 按权重切分流量、超时与重试 |

`networking.istio.io/v1` 与 `security.istio.io/v1` 自 Istio 1.22 起为稳定版本。集群若跑更早版本，把 `v1` 换成 `v1beta1`，字段结构不变。

## 前置条件

1. istiod 已安装，且命名空间已开启 sidecar 注入：

   ```bash
   kubectl label namespace intent-mlops istio-injection=enabled --overwrite
   kubectl rollout restart deployment/intent-api -n intent-mlops
   kubectl get pod -n intent-mlops -o \
     jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].name}{"\n"}{end}'
   ```

   每个 Pod 出现 `istio-proxy` 才算注入成功。

2. **subset 需要 `version` 标签**。`base/deployment.yaml` 的 Pod 只有 `app: intent-api`，`DestinationRule` 里的 `stable` / `canary` 会解析到空后端。真实用法是：给现有 Deployment 的 pod 模板加 `version: stable`，再复制一份 `intent-api-canary` Deployment 带 `version: canary`（`app: intent-api` 保持一致，两者共用同一个 Service）。

## 应用与验证

```bash
kubectl apply -f deploy/mesh/peerauthentication.yaml
kubectl apply -f deploy/mesh/authorizationpolicy.yaml
kubectl apply -f deploy/mesh/destinationrule.yaml
kubectl apply -f deploy/mesh/virtualservice.yaml

kubectl get peerauthentication,authorizationpolicy -n intent-mlops
kubectl get destinationrule,virtualservice -n intent-mlops

# 权重是否真的下发到了数据面
istioctl proxy-config route \
  deploy/intent-api -n intent-mlops --name 80 -o json \
  | jq '.[].virtualHosts[].routes[].route.weightedClusters'

# subset 是否有实际端点（空表示 version 标签没打）
istioctl proxy-config endpoint deploy/intent-api -n intent-mlops \
  --cluster 'outbound|80|canary|intent-api.intent-mlops.svc.cluster.local'
```

改放量档位就是改 `virtualservice.yaml` 里那两个 `weight`（必须和为 100），提 PR、由 GitOps 收敛：

```bash
sed -i 's/weight: 95/weight: 75/; s/weight: 5/weight: 25/' \
  deploy/mesh/virtualservice.yaml
```

## 代价

sidecar 每 Pod 额外约 50–100 MiB 内存和一跳代理延迟；控制面本身要人运维和升级；调试链路从"应用日志"变成"应用日志 + 两侧 Envoy 配置"。上之前先确认你真的需要它。
