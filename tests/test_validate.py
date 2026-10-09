from pathlib import Path

import pytest

from intent_mlops.validate import validate_dataset


def test_example_dataset_is_valid():
    result = validate_dataset(Path("data/intents.csv"))
    assert result["rows"] == 30
    assert set(result["labels"]) == {"billing", "technical_support", "account"}


def test_missing_dataset_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        validate_dataset(tmp_path / "missing.csv")

