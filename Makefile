.PHONY: install install-mlops validate baseline train train-mlflow test serve clean

install:
	python -m pip install --upgrade pip
	python -m pip install -e '.[dev]'

install-mlops:
	python -m pip install -e '.[dev,mlops]'

validate:
	python -m intent_mlops.validate

# 对比门：退出码 0 通过 / 1 warning / 2 fail，基线默认取 artifacts/validation.baseline.json
baseline:
	python -m intent_mlops.validate > artifacts/validation.json
	python -m intent_mlops.baseline

train: validate
	python -m intent_mlops.train

train-mlflow: validate
	python -m intent_mlops.train_mlflow

test: train
	pytest -q

serve:
	gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 4 'intent_mlops.app:create_app()'

clean:
	rm -f artifacts/intent-model.joblib artifacts/metadata.json artifacts/metrics.json artifacts/validation.json
