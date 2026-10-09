# Argo CD Application

这个目录有**两份互斥的 Application，二选一，不要同时 apply**：

| 文件 | Application 名 | 同步的 path | 对应的服务路径 |
|---|---|---|---|
| `application.yaml` | `intent-api` | [`deploy/base`](../base/) | 原生 Deployment + Service + Ingress + HPA + PDB（第 10 篇） |
| `application-kserve.yaml` | `intent-classifier-kserve` | [`deploy/kserve`](../kserve/) | InferenceService（第 11 篇） |

两者部署的是**同一个模型的两种服务形态**，同时启用会在 `intent-mlops` 这一个
namespace 里跑起两套服务栈，互相抢 Ingress 和端口。按第 11 篇的选择留一个。

发布新模型版本的动作也因此不同：走 base 路径改的是 Deployment 的镜像 digest，
走 KServe 路径改的是 `inferenceservice.yaml` 的 `storageUri`（第 15 篇第 5 节）。
**改错文件不会报错，只是什么都不会发生。**

## 应用前必须改的两处

1. `spec.source.repoURL` —— 占位符 `https://github.com/costa92/intent-mlops.git`
   换成你自己的 GitOps 仓库地址；
2. `spec.project` —— 换成集群里已存在的 AppProject（没有就先改成 `default`）。

`targetRevision` 保持指向受保护分支（如 `main`），不要写 `HEAD` 或可移动 tag。

## 应用方式

```bash
# Application 本身也应该由 Git 管理，这里的 apply 只用于首次 bootstrap
kubectl apply -f example/deploy/argocd/application.yaml

# 查看同步状态
kubectl -n argocd get application intent-api
argocd app get intent-api
```

之后**不要**再用 `kubectl apply` 改集群里的工作负载：改 `example/deploy/base`
下的清单并合入受保护分支，Argo CD 会自己收敛（`selfHeal: true` + `prune: true`）。

## 发布与回滚

- 发布：改 `storageUri` 指向新的不可变版本前缀 → 提 PR → merge；
- 回滚：`git revert` 那次提交，同时把 MLflow 的 `production` alias 指回
  `previous-production`（见 [`promote.py`](../../src/intent_mlops/promote.py) 的
  `rollback` 子命令）。
