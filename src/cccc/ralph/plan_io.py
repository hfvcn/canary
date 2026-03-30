"""Load and save Ralph plan files (YAML/JSON)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .models import Plan


def load_plan(path: Path) -> Plan:
    """Load a plan from a YAML or JSON file."""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        # Try YAML first (superset of JSON)
        try:
            data = yaml.safe_load(text)
        except Exception:
            data = json.loads(text)

    if data is None:
        data = {}

    return Plan.model_validate(data)
