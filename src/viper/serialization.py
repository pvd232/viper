"""Serialize VIPER records and parse duplicate-key-safe YAML documents."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, TypeAdapter
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver

from .stages import (
    ResolvedSpec,
    Spec,
)


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            hash(key)
        except TypeError as exc:
            raise ValueError("YAML mapping keys must be scalar values") from exc
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)

_SPEC_ADAPTER = TypeAdapter(Spec)
_RESOLVED_SPEC_ADAPTER = TypeAdapter(ResolvedSpec)


def serialize_document(document: BaseModel) -> bytes:
    """Serialize one validated protocol document as deterministic YAML bytes."""
    value = document.model_dump(mode="json")
    rendered = yaml.safe_dump(
        value,
        allow_unicode=True,
        sort_keys=False,
    )
    assert isinstance(rendered, str)
    return rendered.encode("utf-8")


def document_digest(document: BaseModel) -> str:
    """Hash one model through a key-order-independent canonical JSON mapping."""
    value = document.model_dump(mode="json")
    raw = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_yaml_bytes(raw: bytes) -> Any:
    """Parse YAML bytes while rejecting duplicate mapping keys."""
    if not isinstance(raw, bytes):
        raise TypeError("YAML content must be bytes")
    return yaml.load(raw, Loader=UniqueKeySafeLoader)


def _load_yaml(path: Path) -> Any:
    """Read and parse one YAML file."""
    return parse_yaml_bytes(path.read_bytes())


def load_stage_spec(path: str | Path) -> Spec:
    """Load and validate a VIPER stage spec."""
    return _SPEC_ADAPTER.validate_python(_load_yaml(Path(path)))


def load_resolved_stage(path: str | Path) -> ResolvedSpec:
    """Load and validate an immutable VIPER resolved spec."""
    return _RESOLVED_SPEC_ADAPTER.validate_python(_load_yaml(Path(path)))
