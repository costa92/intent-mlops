"""模型注册与晋级：register → staging → production。

对应第 15 篇第 2 节。生命周期用 MLflow 3 的 alias 表达，
stage API（transition_model_version_stage）在 3.x 已被移除，这里不使用。

用法：

    python -m intent_mlops.promote register --run-id <RUN_ID>
    python -m intent_mlops.promote staging  --version 3
    python -m intent_mlops.promote production --approver ci-oidc:... --ticket CHG-2841
    python -m intent_mlops.promote current
    python -m intent_mlops.promote rollback

mlflow 属于可选依赖，安装：pip install '.[mlops]'
"""

from __future__ import annotations

import argparse
import os
import sys

MODEL_NAME = os.getenv("MODEL_NAME", "intent-classifier")

# 离线门禁阈值：改这里等于改标准，git log 就是审计记录
MIN_MACRO_F1 = 0.82
MIN_TECHNICAL_SUPPORT_RECALL = 0.78
MAX_P95_INFERENCE_MS = 50.0

_IMPORT_HINT = (
    "promote.py 需要 mlflow，但当前环境没有安装。\n"
    "请执行：pip install '.[mlops]'"
)


def _load_mlflow():
    """延迟导入 mlflow，缺失时给出可操作的提示而不是 ImportError 堆栈。"""
    try:
        import mlflow
        from mlflow import MlflowClient
    except ImportError as exc:  # pragma: no cover - 依赖缺失路径
        raise SystemExit(_IMPORT_HINT) from exc
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    return mlflow, MlflowClient()


def register(run_id: str) -> str:
    """从 run 注册出一个模型版本，并写入审计 tag。返回版本号。"""
    mlflow, client = _load_mlflow()

    # 注册表条目只需创建一次；已存在时不要让脚本崩掉
    try:
        client.create_registered_model(MODEL_NAME)
    except mlflow.exceptions.MlflowException as exc:
        # 只吞"已存在"。宽 except 会把认证失败、网络中断、数据库故障
        # 一并当成"已存在"，后面的操作在一个根本没连上的 Registry 上
        # 静默失败。
        if getattr(exc, "error_code", "") != "RESOURCE_ALREADY_EXISTS":
            raise

    version = client.create_model_version(
        name=MODEL_NAME,
        # 与 train_mlflow.py 里 log_artifacts(artifact_path="intent-model") 一致
        source=f"runs:/{run_id}/intent-model",
        run_id=run_id,
        description="编排产出的候选，待离线门禁",
    )

    run = client.get_run(run_id)
    tags = {
        "git_sha": run.data.params.get("git_sha", "unknown"),
        "dataset_sha256": run.data.params.get("dataset_sha256", "unknown"),
        "training_image": os.getenv("TRAINING_IMAGE_DIGEST", "unknown"),
        "workflow_id": os.getenv("ARGO_WORKFLOW_NAME", "local"),
        "owner": os.getenv("MODEL_OWNER", "customer-platform"),
        "risk_level": os.getenv("MODEL_RISK_LEVEL", "medium"),
    }
    artifact_sha256 = os.getenv("ARTIFACT_SHA256")
    if artifact_sha256:
        tags["artifact_sha256"] = artifact_sha256
    for key, value in tags.items():
        client.set_model_version_tag(MODEL_NAME, version.version, key, value)

    print(f"registered {MODEL_NAME} version={version.version}")
    return version.version


def offline_gate(metrics: dict) -> bool:
    """离线门禁：由代码判定，不是在 UI 上点。

    缺省值一律朝"拒绝"方向倒：指标没打上来等同于没通过，而不是自动放行。
    上限类指标（越小越好）缺省用 inf，下限类用 0.0。
    """
    return (
        metrics.get("macro_f1", 0.0) >= MIN_MACRO_F1
        and metrics.get("technical_support_recall", 0.0)
        >= MIN_TECHNICAL_SUPPORT_RECALL
        and metrics.get("p95_inference_ms", float("inf")) <= MAX_P95_INFERENCE_MS
    )


def to_staging(version: str) -> None:
    """离线门禁通过后打 staging alias。"""
    _, client = _load_mlflow()
    mv = client.get_model_version(MODEL_NAME, version)
    metrics = client.get_run(mv.run_id).data.metrics
    if not offline_gate(metrics):
        raise SystemExit(f"offline gate failed: {metrics}")

    client.set_registered_model_alias(MODEL_NAME, "staging", version)
    client.set_model_version_tag(MODEL_NAME, version, "offline_gate", "passed")
    print(f"{MODEL_NAME}@staging -> version={version}")


def to_production(approver: str, ticket: str) -> None:
    """人工审批通过后把 staging 晋级为 production，旧版本挂 previous-production。"""
    mlflow, client = _load_mlflow()
    staging = client.get_model_version_by_alias(MODEL_NAME, "staging")

    # 记录"上一任 production 是谁"，回滚时就不用翻历史
    try:
        previous = client.get_model_version_by_alias(MODEL_NAME, "production")
    except mlflow.exceptions.MlflowException as exc:
        # 只有"alias 不存在"才是首次晋级的正常路径；其他异常（认证、网络）
        # 必须抛出，否则会被误判成首次发布而丢掉 previous-production 指针，
        # 回滚时就找不到上一任了。
        if getattr(exc, "error_code", "") != "RESOURCE_DOES_NOT_EXIST":
            raise
        previous = None
    if previous is not None:
        client.set_registered_model_alias(
            MODEL_NAME, "previous-production", previous.version
        )

    client.set_model_version_tag(MODEL_NAME, staging.version, "approved_by", approver)
    client.set_model_version_tag(
        MODEL_NAME, staging.version, "approval_ticket", ticket
    )
    client.set_registered_model_alias(MODEL_NAME, "production", staging.version)
    print(
        f"{MODEL_NAME}@production -> version={staging.version} "
        f"(previous={previous.version if previous else 'none'})"
    )


def rollback() -> None:
    """把 production alias 指回 previous-production。"""
    _, client = _load_mlflow()
    previous = client.get_model_version_by_alias(MODEL_NAME, "previous-production")
    client.set_registered_model_alias(MODEL_NAME, "production", previous.version)
    print(f"rolled back {MODEL_NAME}@production -> version={previous.version}")


def current() -> None:
    """查询当前生产事实。"""
    _, client = _load_mlflow()
    mv = client.get_model_version_by_alias(MODEL_NAME, "production")
    print(
        f"version={mv.version} run_id={mv.run_id} "
        f"approved_by={mv.tags.get('approved_by', 'unknown')} "
        f"artifact_sha256={mv.tags.get('artifact_sha256', 'unknown')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m intent_mlops.promote")
    sub = parser.add_subparsers(dest="command", required=True)

    p_register = sub.add_parser("register", help="从 run 注册模型版本")
    p_register.add_argument("--run-id", required=True)

    p_staging = sub.add_parser("staging", help="离线门禁通过后打 staging alias")
    p_staging.add_argument("--version", required=True)

    p_prod = sub.add_parser("production", help="审批通过后晋级 production")
    p_prod.add_argument("--approver", default=os.getenv("APPROVER"))
    p_prod.add_argument("--ticket", default=os.getenv("APPROVAL_TICKET"))

    sub.add_parser("rollback", help="production alias 回退到 previous-production")
    sub.add_parser("current", help="打印当前 production 版本")

    args = parser.parse_args(argv)

    if args.command == "register":
        register(args.run_id)
    elif args.command == "staging":
        to_staging(args.version)
    elif args.command == "production":
        if not args.approver or not args.ticket:
            parser.error("production 需要 --approver 与 --ticket（或对应环境变量）")
        to_production(args.approver, args.ticket)
    elif args.command == "rollback":
        rollback()
    elif args.command == "current":
        current()
    return 0


if __name__ == "__main__":
    sys.exit(main())
