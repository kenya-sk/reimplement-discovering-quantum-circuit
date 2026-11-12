"""Small file operations shared by evaluation and search artifacts."""

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def read_tail(path: Path, limit: int = 4000) -> str:
    return path.read_text()[-limit:] if path.is_file() else ""
