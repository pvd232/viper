"""Serialize VIPER records and parse duplicate-key-safe YAML documents."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
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
    loader: yaml.SafeLoader | yaml.CSafeLoader,
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

_YAML_LOADER: type[yaml.SafeLoader] | type[yaml.CSafeLoader] = UniqueKeySafeLoader
if yaml.__with_libyaml__:

    class _UniqueKeyCSafeLoader(yaml.CSafeLoader):
        """Parse safe YAML with LibYAML while retaining duplicate-key rejection."""

    _UniqueKeyCSafeLoader.add_constructor(
        BaseResolver.DEFAULT_MAPPING_TAG,
        _construct_unique_mapping,
    )
    _YAML_LOADER = _UniqueKeyCSafeLoader

_SPEC_ADAPTER = TypeAdapter(Spec)
_RESOLVED_SPEC_ADAPTER = TypeAdapter(ResolvedSpec)


class MigrationRequiredError(ValueError):
    """Explain how to update a retired version-1 authoring document."""


def load_stage_document(value: object) -> Spec:
    """Validate one stage mapping with targeted version-1 migration errors."""
    if isinstance(value, dict) and value.get("schema_version") == 1:
        retired_config_fields = (
            field
            for field in ("params", "parameter_model", "stage_params")
            if field in value
        )
        retired = next(retired_config_fields, None)
        if retired is not None:
            raise MigrationRequiredError(
                f"schema version 1 field {retired!r} was replaced by config vocabulary"
            )
        if "artifacts" in value:
            raise MigrationRequiredError(
                "schema version 1 field 'artifacts' was replaced by 'outputs'"
            )
        raise MigrationRequiredError(
            "schema version 1 stage documents must be regenerated with VIPER 0.1.0a3"
        )
    return _SPEC_ADAPTER.validate_python(value)


def _synchronize_directory(path: Path) -> None:
    """Synchronize a directory's saved entries."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_directory_synchronized(path: Path) -> None:
    """Create a directory and synchronize its entries through the parent chain."""
    path.mkdir(parents=True, exist_ok=True)
    directory = path.resolve()
    while True:
        _synchronize_directory(directory)
        if directory.parent == directory:
            return
        directory = directory.parent


def write_synchronized(
    path: Path, raw: bytes, *, replace_existing: bool = False
) -> None:
    """Save and synchronize bytes, refusing different existing bytes by default."""
    if not path.parent.is_dir():
        ensure_directory_synchronized(path.parent)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if replace_existing:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError:
                with path.open("rb") as current:
                    if current.read() != raw:
                        raise FileExistsError(
                            f"refusing to replace different bytes at {path}"
                        ) from None
                    os.fsync(current.fileno())
    finally:
        temporary.unlink(missing_ok=True)
    _synchronize_directory(path.parent)


def replace_synchronized(path: Path, raw: bytes) -> None:
    """Atomically replace a file and synchronize its bytes and directory entry."""
    write_synchronized(path, raw, replace_existing=True)


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


def semantic_document_digest(document: BaseModel) -> str:
    """Hash present semantic fields while ignoring absent optional extensions."""
    value = document.model_dump(mode="json", exclude_none=True)
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
    return yaml.load(raw, Loader=_YAML_LOADER)


def _load_yaml(path: Path) -> Any:
    """Read and parse one YAML file."""
    return parse_yaml_bytes(path.read_bytes())


def load_stage_spec(path: str | Path) -> Spec:
    """Load and validate a VIPER stage spec."""
    return load_stage_document(_load_yaml(Path(path)))


def load_resolved_stage(path: str | Path) -> ResolvedSpec:
    """Load and validate an immutable VIPER resolved spec."""
    return _RESOLVED_SPEC_ADAPTER.validate_python(_load_yaml(Path(path)))
