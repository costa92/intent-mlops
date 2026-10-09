# Intent MLOps 示例工程

这是《[从 DevOps 到 MLOps 实战](https://costalong.com/notes/mlops/)》系列的配套工程，提供数据校验、模型训练、artifact metadata、Flask API、测试，以及可选 CI/DVC/MLflow/Kubernetes/KServe/监控资产。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
make install
make validate
make train
make test
make serve
```

新终端测试：

```bash
curl -s http://localhost:8080/healthz
curl -s http://localhost:8080/readyz
curl -s -X POST http://localhost:8080/predict \
  -H 'Content-Type: application/json' \
  -d '{"text":"为什么重复扣款"}'
```

也可以执行：

```bash
docker compose up --build
```

完整验收步骤见[附录 A](https://costalong.com/notes/mlops/appendix-end-to-end/)。

## 目录

```text
example/
├── data/intents.csv
├── src/intent_mlops/
│   ├── app.py
│   ├── baseline.py     # 与已批准基线对比，退出码分档
│   ├── promote.py      # MLflow Registry 晋级与回滚
│   ├── train.py
│   ├── train_mlflow.py
│   └── validate.py
├── tests/
├── .github/            # CI 与 CODEOWNERS
├── workflows/          # Argo Workflow 与训练 ServiceAccount/RBAC
├── deploy/             # Kubernetes、KServe、Argo CD、canary 门禁、网关与网格
├── monitoring/         # ServiceMonitor、告警、recording rule、PSI 与仪表盘
├── feature_repo/       # Feast 参考定义（不进依赖，需单独安装）
├── scripts/            # asof_join_demo.py 等独立演示
├── dvc.yaml
├── params.yaml
├── thresholds.yaml     # 数据质量门禁阈值
├── artifacts/          # 训练后生成，不提交模型二进制
├── pyproject.toml
├── Makefile
├── Dockerfile
└── compose.yaml
```

当前 CI 文件位于示例子目录的 `.github/workflows/`。将 `example/` 单独作为仓库时它会直接生效；若本系列目录属于更大的仓库，请把工作流移动到仓库根目录的 `.github/workflows/`，并同步调整工作目录。

## 可选 MLOps 依赖

```bash
make install-mlops
dvc repro
MLFLOW_TRACKING_URI=http://localhost:5000 make train-mlflow
```

部署清单包含 `REPLACE_*`、`ACCOUNT_ID` 和 `REGISTRY` 占位符，应用前必须替换并执行服务端 dry-run。

Kubernetes 目标基线是 EKS/Kubernetes `1.34.x`，KServe 使用 `0.18.0` Standard mode。完整兼容矩阵、前置组件、命名空间、RBAC、验收和升级顺序见[部署说明](./deploy/)与[附录 D](https://costalong.com/notes/mlops/appendix-k8s-baseline/)。

这是教学工程。生产环境还需使用正式 Model Registry、Secret 管理、身份认证、指标后端和不可变 artifact 存储。
