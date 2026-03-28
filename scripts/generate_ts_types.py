from __future__ import annotations

import sys
from pathlib import Path
from types import NoneType, UnionType
from typing import Any, Literal, Union, get_args, get_origin

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cccc.contracts.v1.actor import Actor


def python_type_to_ts(annotation: Any) -> str:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation in (str,):
        return "string"
    if annotation in (int, float):
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation in (Any, dict):
        return "Record<string, unknown>"
    if annotation is NoneType:
        return "null"
    if origin in (list,):
        inner = python_type_to_ts(args[0]) if args else "unknown"
        return f"{inner}[]"
    if origin in (dict,):
        value_type = python_type_to_ts(args[1]) if len(args) > 1 else "unknown"
        return f"Record<string, {value_type}>"
    if origin in (Literal,):
        values = [repr(value) for value in args]
        return " | ".join(values) or "unknown"
    if origin in (Union, UnionType):
        members = [python_type_to_ts(arg) for arg in args]
        return " | ".join(dict.fromkeys(members))
    return "unknown"


def generate_interface() -> str:
    lines = ["export interface Actor {"]
    for field_name, field_info in Actor.model_fields.items():
        optional = "?" if not field_info.is_required() else ""
        ts_type = python_type_to_ts(field_info.annotation)
        lines.append(f"  {field_name}{optional}: {ts_type};")
    lines.append("}")
    return "\n".join(lines)


def main() -> None:
    print(generate_interface())


if __name__ == "__main__":
    main()
