"""Load the YAML rule and play files."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_rules(path: Path | None = None) -> dict[str, Any]:
    return load_yaml(path or CONFIG_DIR / "rules.yaml")


def load_plays(path: Path | None = None) -> dict[str, Any]:
    return load_yaml(path or CONFIG_DIR / "plays.yaml")
