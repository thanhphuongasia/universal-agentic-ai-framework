import json
from pathlib import Path

import pytest
import yaml

from ryuu_eval_oracle import FileInputSource


@pytest.fixture()
def tmp_inputs(tmp_path: Path) -> Path:
    return tmp_path


async def test_load_yaml(tmp_inputs: Path) -> None:
    data = {"route": "POST /orders", "entities": ["Order"]}
    (tmp_inputs / "case1.yaml").write_text(yaml.dump(data), encoding="utf-8")

    src = FileInputSource(tmp_inputs, ext=".yaml")
    result = await src.fetch("case1")

    assert result == data


async def test_load_json(tmp_inputs: Path) -> None:
    data = {"route": "GET /users", "entities": ["User"]}
    (tmp_inputs / "case2.json").write_text(json.dumps(data), encoding="utf-8")

    src = FileInputSource(tmp_inputs, ext=".json")
    result = await src.fetch("case2")

    assert result == data


async def test_missing_file_raises(tmp_inputs: Path) -> None:
    src = FileInputSource(tmp_inputs, ext=".yaml")
    with pytest.raises(FileNotFoundError):
        await src.fetch("nonexistent")


async def test_default_ext_is_yaml(tmp_inputs: Path) -> None:
    data = {"x": 1}
    (tmp_inputs / "case3.yaml").write_text(yaml.dump(data), encoding="utf-8")

    src = FileInputSource(tmp_inputs)  # default ext=".yaml"
    result = await src.fetch("case3")

    assert result == data
