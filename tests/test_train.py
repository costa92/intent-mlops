from pathlib import Path

import joblib

from intent_mlops.train import train


def test_training_writes_loadable_artifacts(tmp_path):
    result = train(Path("data/intents.csv"), tmp_path)
    model = joblib.load(tmp_path / "intent-model.joblib")
    prediction = model.predict(["我需要修改账户资料"])
    assert prediction[0] in {"billing", "technical_support", "account"}
    assert (tmp_path / "metadata.json").exists()
    assert result["metrics"]["macro_f1"] >= 0

