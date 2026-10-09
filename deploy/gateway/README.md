# 入口网关补强清单（Traefik v3）

配套[第 12 篇](https://costalong.com/notes/mlops/gateway-service-mesh/)。第 10 篇只写了一份最小 `Ingress`，这里补上它欠下的：限流、请求体上限、并发上限、IP 白名单和安全响应头。

- `traefik-middleware.yaml`：6 个 `Middleware`（`traefik.io/v1alpha1`），命名空间 `intent-mlops`。

## 挂载方式

本系列坚持用 Kubernetes 原生 `Ingress`（不用 Traefik 私有的 `IngressRoute`），所以 Middleware 通过 **annotation** 挂到 Ingress 的 router 上，引用格式是 `<middleware-namespace>-<middleware-name>@kubernetescrd`，多个用逗号分隔，**从左到右依次执行**：

```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.middlewares: >-
      intent-mlops-intent-api-ipallowlist@kubernetescrd,
      intent-mlops-intent-api-ratelimit@kubernetescrd,
      intent-mlops-intent-api-buffering@kubernetescrd,
      intent-mlops-intent-api-inflight@kubernetescrd,
      intent-mlops-intent-api-secheaders@kubernetescrd
spec:
  tls:
    - hosts: [intent-api.example.com]
      secretName: intent-api-tls
```

`base/ingress.yaml` 保持教学用的最小形态，上面这段是生产环境要往里加的部分。

## 应用与验证

```bash
kubectl apply -f deploy/gateway/traefik-middleware.yaml
kubectl get middleware -n intent-mlops
kubectl describe middleware intent-api-ratelimit -n intent-mlops

# 限流生效：连打 60 次应出现 429
for i in $(seq 60); do
  curl -s -o /dev/null -w '%{http_code}\n' \
    https://intent-api.example.com/healthz
done | sort | uniq -c

# 请求体上限生效：超过 64 KiB 应在网关被 413 掉
head -c 100000 /dev/zero | tr '\0' 'a' > /tmp/big.txt
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://intent-api.example.com/predict \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/big.txt
```

## 注意

- **超时不是 Middleware**。Traefik 的读写超时配在 entryPoint 上（Helm values 里的 `ports.websecure.transport.respondingTimeouts`），后端超时配在 `ServersTransport`，不要在这里找。
- `ipAllowList` 是 Traefik v3 的名字，v2 叫 `ipWhiteList`。
- `sourceCriterion.ipStrategy.depth` 必须等于 Traefik 前面可信代理的层数，写错会让所有请求被算成同一个来源，限流直接失效或误伤。
- `retry` 只对**幂等**请求安全。`/predict` 无副作用可以重试，写接口不要照抄。
- TLS 证书由 cert-manager 通过 `cluster-issuer` annotation 签发，`secretName` 由它填充；提交前确认 Issuer 已存在。
