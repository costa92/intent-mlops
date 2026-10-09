FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODEL_PATH=/app/artifacts/intent-model.joblib \
    MODEL_METADATA_PATH=/app/artifacts/metadata.json

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY data/ ./data/
RUN pip install --no-cache-dir . && \
    python -m intent_mlops.validate && \
    python -m intent_mlops.train && \
    useradd --create-home --uid 10001 appuser

USER 10001:10001
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "intent_mlops.app:create_app()"]
