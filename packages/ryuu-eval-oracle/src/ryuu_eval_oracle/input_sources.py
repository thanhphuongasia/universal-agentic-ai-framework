from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


class FileInputSource:
    """Load case inputs from YAML or JSON files under a root directory.

    ``fetch(case_id)`` reads ``<root_dir>/<case_id><ext>``.
    Supported extensions: ``.yaml``, ``.yml``, ``.json``.
    """

    def __init__(self, root_dir: str | Path, ext: str = ".yaml") -> None:
        self._root = Path(root_dir)
        self._ext = ext

    async def fetch(self, case_id: str) -> dict[str, Any]:
        path = self._root / f"{case_id}{self._ext}"
        text = path.read_text(encoding="utf-8")
        if self._ext in (".yaml", ".yml"):
            return yaml.safe_load(text)  # type: ignore[no-any-return]
        return json.loads(text)  # type: ignore[no-any-return]
