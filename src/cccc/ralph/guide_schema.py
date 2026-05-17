"""Plan schema reference generation for Ralph guide output."""

from __future__ import annotations

from typing import Iterable, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import PydanticUndefined

from .models import Plan

ModelReference = tuple[str, str, type[BaseModel]]
COLLECTION_ORIGINS = {list, tuple, set, frozenset}


def generate_schema_reference_section() -> str:
    return _format_schema_section(_schema_model_references())


def _schema_model_references() -> tuple[ModelReference, ...]:
    ordered: list[type[BaseModel]] = []
    expanded: set[type[BaseModel]] = set()
    paths: dict[type[BaseModel], list[str]] = {}

    def visit(model_cls: type[BaseModel], path: str) -> None:
        _record_model_path(paths, model_cls, path)
        if model_cls in expanded:
            return
        expanded.add(model_cls)
        ordered.append(model_cls)
        for field_name, field_info in model_cls.model_fields.items():
            for nested_model, repeated in _nested_model_classes(field_info.annotation):
                child_path = _schema_child_path(path, field_name, repeated)
                visit(nested_model, child_path)

    visit(Plan, "top level")
    return tuple(
        (model_cls.__name__, " / ".join(paths[model_cls]), model_cls)
        for model_cls in ordered
    )


def _record_model_path(
    paths: dict[type[BaseModel], list[str]],
    model_cls: type[BaseModel],
    path: str,
) -> None:
    model_paths = paths.setdefault(model_cls, [])
    if path not in model_paths:
        model_paths.append(path)


def _nested_model_classes(
    annotation: object,
    repeated: bool = False,
) -> tuple[tuple[type[BaseModel], bool], ...]:
    if _is_model_class(annotation):
        return ((annotation, repeated),)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if not args:
        return ()
    next_repeated = repeated or origin in COLLECTION_ORIGINS
    nested: list[tuple[type[BaseModel], bool]] = []
    for arg in args:
        if arg is type(None):
            continue
        nested.extend(_nested_model_classes(arg, next_repeated))
    return tuple(nested)


def _is_model_class(value: object) -> bool:
    return isinstance(value, type) and issubclass(value, BaseModel)


def _schema_child_path(parent_path: str, field_name: str, repeated: bool) -> str:
    field_path = f"{field_name}[]" if repeated else field_name
    if parent_path == "top level":
        return field_path
    return f"{parent_path}.{field_path}"


def _format_schema_section(models: Iterable[ModelReference]) -> str:
    parts = []
    for name, path, model_cls in models:
        lines = [f"### {name}", f"- Path: `{path}`", ""]
        lines.append("| Field | Type | Default | Description |")
        lines.append("| --- | --- | --- | --- |")
        for field_name, field_info in model_cls.model_fields.items():
            lines.append(_format_field_row(field_name, field_info))
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _format_field_row(field_name: str, field_info: object) -> str:
    alias = getattr(field_info, "alias", None)
    display_name = f"{field_name} (alias: `{alias}`)" if alias else field_name
    type_name = _format_annotation(getattr(field_info, "annotation", None))
    default = _format_default(field_info)
    description = _field_description(field_info)
    return f"| `{display_name}` | `{type_name}` | `{default}` | {description} |"


def _field_description(field_info: object) -> str:
    description = getattr(field_info, "description", None)
    if description:
        return str(description)
    nested_field_info = getattr(field_info, "field_info", None)
    nested_description = getattr(nested_field_info, "description", None)
    return str(nested_description) if nested_description else ""


def _format_annotation(annotation: object) -> str:
    if annotation is None:
        return ""
    type_name = getattr(annotation, "__name__", str(annotation))
    return type_name.replace("typing.", "")


def _format_default(field_info: object) -> str:
    default = getattr(field_info, "default", PydanticUndefined)
    if default is not PydanticUndefined:
        return repr(default)
    factory = getattr(field_info, "default_factory", None)
    if factory is not None:
        return f"<factory {_callable_name(factory)}>"
    return "(required)"


def _callable_name(value: object) -> str:
    return getattr(value, "__name__", value.__class__.__name__)
