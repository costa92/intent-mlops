# Kubernetes deployment assets

完整版本矩阵、安装顺序和升级说明见[附录 D](https://costalong.com/notes/mlops/appendix-k8s-baseline/)。

本目录的目标基线是 Kubernetes/EKS `1.34.x`：

- `base/`：原生 Deployment、Service、Ingress、HPA 和 PDB；
- `kserve/`：KServe `0.18.0` Standard mode 的 `InferenceService` 示例；
- 清单使用 `kubectl v1.35.0` 内置 Kustomize `v5.7.1` 完成静态渲染。

部署前必须替换 `REGISTRY`、`REPLACE_*`、`ACCOUNT_ID`、域名和 IAM Role。`serviceaccount.yaml` 中的 annotation 属于 IRSA；使用 EKS Pod Identity 时应删除该 annotation，并通过 EKS Pod Identity association 绑定角色。

```bash
kubectl create namespace intent-mlops --dry-run=client -o yaml | kubectl apply -f -
kubectl kustomize base > /tmp/intent-api.yaml
kubectl apply --server-side --dry-run=server -n intent-mlops -f /tmp/intent-api.yaml
kubectl apply -n intent-mlops -f /tmp/intent-api.yaml
```

CPU HPA 需要 Metrics Server；Ingress 需要 `traefik` IngressClass。提交 KServe 清单前，还要安装 KServe 0.18.0 CRD、controller、ClusterServingRuntime 和证书组件。

KServe 示例的 `storageUri` 目录必须包含 sklearn runtime 期望的 `model.joblib`。本地生成的 `artifacts/intent-model.joblib` 应在受控发布步骤中校验 checksum、复制并改为该文件名；训练和 serving 端的 Python、scikit-learn、joblib 版本不兼容时，必须使用带相同依赖锁的自定义 ServingRuntime。
