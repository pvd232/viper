"""Author canonical experiment, variant, benchmark, stage, and run-plan files."""

from __future__ import annotations

import hashlib
import os
import re
import string
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter

from ._parameter_validation import (
    ParameterValidationError,
    validate_stage_parameters,
    verify_parameter_model_bytes,
)
from ._schema import (
    BenchmarkId,
    RNGSeed,
)
from .artifacts import StageArtifactRef
from .benchmark import BenchmarkSpec
from .experiments import (
    ExperimentSpec,
    VariantSpec,
)
from .http import ProjectHttpTransportSpec, resolve_transport, validate_request_policy
from .ids import ExperimentId, ReplicateId, RunId, StageId, VariantId
from .references import GitSource
from .runs import (
    RunSpec,
    RunStageRef,
)
from .runtime import (
    EnvironmentSpec,
    ReproducibilitySpec,
)
from .serialization import parse_yaml_bytes, serialize_document
from .stages import (
    DownloadSpec,
    ParameterizedSpec,
    Spec,
    StageDefinitionError,
    validate_stage_definition,
)

SPEC_ADAPTER = TypeAdapter(Spec)
HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)
UrlValue = str | int | float | bool


class StageDraft(BaseModel):
    """Select one authored stage-spec file and its run-stage identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_id: StageId
    spec_source: Path


class RunPlanDraft(BaseModel):
    """Collect run-level selections before exact stage bytes are frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    run_id: RunId
    experiment_id: ExperimentId
    variant_id: VariantId
    replicate_id: ReplicateId
    benchmark_id: BenchmarkId | None = None
    seed: RNGSeed
    source: GitSource
    environment: EnvironmentSpec
    reproducibility: ReproducibilitySpec
    stages: tuple[StageDraft, ...] = Field(min_length=1)
    estimator: StageArtifactRef


class FrozenPlanFiles(BaseModel):
    """Return the validated run plan and every file written for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: RunSpec
    files: tuple[Path, ...]


def expand_http_url(
    template: str,
    *,
    path_values: Mapping[str, UrlValue] | None = None,
    query_values: Mapping[str, UrlValue] | None = None,
) -> HttpUrl:
    """Expand path fields and freeze one normalized, ordered HTTP URL."""
    components = urlsplit(template)
    if components.scheme not in {"http", "https"} or components.hostname is None:
        raise ValueError("HTTP URL template requires an HTTP origin")
    if components.username is not None or components.password is not None:
        raise ValueError("HTTP URL template must not contain user information")
    if components.fragment:
        raise ValueError("HTTP URL template must not contain a fragment")
    if any(
        "{" in value or "}" in value for value in (components.netloc, components.query)
    ):
        raise ValueError("HTTP URL fields are permitted only in the path")

    supplied_paths = {} if path_values is None else dict(path_values)
    expected_paths: set[str] = set()
    rendered_path: list[str] = []
    formatter = string.Formatter()
    for literal, field_name, format_spec, conversion in formatter.parse(
        components.path
    ):
        rendered_path.append(literal)
        if field_name is None:
            continue
        if (
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field_name) is None
            or format_spec
            or conversion is not None
        ):
            raise ValueError("HTTP path fields must be simple identifiers")
        if field_name not in supplied_paths:
            raise ValueError(f"HTTP path field {field_name!r} has no value")
        expected_paths.add(field_name)
        rendered_path.append(quote(str(supplied_paths[field_name]), safe=""))
    if set(supplied_paths) != expected_paths:
        raise ValueError("HTTP path values contain an unused field")

    query = list(parse_qsl(components.query, keep_blank_values=True))
    for name, value in sorted(({} if query_values is None else query_values).items()):
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        query.append((name, rendered))
    query.sort()
    expanded = urlunsplit(
        (
            components.scheme.lower(),
            components.netloc.lower(),
            "".join(rendered_path),
            urlencode(query),
            "",
        )
    )
    return HTTP_URL_ADAPTER.validate_python(expanded)


def _target_path(repository_root: Path, relative_path: str) -> Path:
    """Resolve one protocol path while keeping it beneath the repository root."""
    root = repository_root.resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("protocol output path escapes the repository root")
    return target


def _write_exact_file(path: Path, raw: bytes) -> None:
    """Write exact bytes atomically and preserve an identical existing file."""
    if path.exists():
        if path.read_bytes() == raw:
            return
        raise FileExistsError(f"refusing to replace a different file: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def write_experiment_spec(
    repository_root: Path,
    experiment: ExperimentSpec,
) -> Path:
    """Write one experiment definition at its canonical identity path."""
    target = _target_path(
        repository_root,
        f"experiments/{experiment.experiment_id}/spec.yaml",
    )
    _write_exact_file(target, serialize_document(experiment))
    return target


def write_variant_spec(repository_root: Path, variant: VariantSpec) -> Path:
    """Write one variant definition at its canonical experiment path."""
    target = _target_path(
        repository_root,
        (
            f"experiments/{variant.experiment_id}/variants/"
            f"{variant.variant_id}.spec.yaml"
        ),
    )
    _write_exact_file(target, serialize_document(variant))
    return target


def write_benchmark_spec(repository_root: Path, benchmark: BenchmarkSpec) -> Path:
    """Write one benchmark definition at its canonical identity path."""
    target = _target_path(
        repository_root,
        f"benchmarks/{benchmark.benchmark_id}.spec.yaml",
    )
    _write_exact_file(target, serialize_document(benchmark))
    return target


def load_run_plan_draft(path: Path) -> RunPlanDraft:
    """Load one duplicate-key-safe run-plan draft."""
    return RunPlanDraft.model_validate(parse_yaml_bytes(path.read_bytes()))


def freeze_run_plan(
    repository_root: Path,
    draft: RunPlanDraft,
) -> FrozenPlanFiles:
    """Validate stage drafts, hash their bytes, and write one frozen run plan."""
    root = repository_root.resolve()
    run_root = (
        f"experiments/{draft.experiment_id}/runs/{draft.variant_id}/{draft.run_id}"
    )
    staged_files: list[tuple[Path, bytes]] = []
    references: list[RunStageRef] = []

    for stage in draft.stages:
        source = stage.spec_source
        if not source.is_absolute():
            source = root / source
        raw_source = source.read_bytes()
        spec = SPEC_ADAPTER.validate_python(parse_yaml_bytes(raw_source))
        if isinstance(spec, ParameterizedSpec):
            reference = spec.parameter_model
            model_path = root / reference.path
            model_raw = model_path.read_bytes()
            verify_parameter_model_bytes(reference, model_raw)
            try:
                committed_model_raw = subprocess.run(
                    (
                        "git",
                        "-C",
                        str(root),
                        "show",
                        f"{draft.source.commit}:{reference.path}",
                    ),
                    check=True,
                    capture_output=True,
                ).stdout
            except (FileNotFoundError, subprocess.CalledProcessError) as exc:
                raise ParameterValidationError(
                    "parameter model is absent from the frozen source commit"
                ) from exc
            if model_raw != committed_model_raw:
                raise ParameterValidationError(
                    "parameter model differs from the frozen source commit"
                )
            validate_stage_parameters(root, source, spec)
            implementation = spec.implementation
            implementation_path = root / implementation.path
            implementation_raw = implementation_path.read_bytes()
            try:
                committed_implementation_raw = subprocess.run(
                    (
                        "git",
                        "-C",
                        str(root),
                        "show",
                        f"{draft.source.commit}:{implementation.path}",
                    ),
                    check=True,
                    capture_output=True,
                ).stdout
            except (FileNotFoundError, subprocess.CalledProcessError) as exc:
                raise StageDefinitionError(
                    "stage implementation is absent from the frozen source commit"
                ) from exc
            if implementation_raw != committed_implementation_raw:
                raise StageDefinitionError(
                    "stage implementation differs from the frozen source commit"
                )
            validate_stage_definition(root, spec)
            if isinstance(spec, DownloadSpec):
                for request in spec.inputs.values():
                    validate_request_policy(request, spec.policy)
                resolve_transport(root, spec.transport)
                if isinstance(spec.transport, ProjectHttpTransportSpec):
                    for reference in (
                        spec.transport.implementation,
                        spec.transport.parameter_model,
                    ):
                        local_raw = (root / reference.path).read_bytes()
                        committed_raw = subprocess.run(
                            (
                                "git",
                                "-C",
                                str(root),
                                "show",
                                f"{draft.source.commit}:{reference.path}",
                            ),
                            check=True,
                            capture_output=True,
                        ).stdout
                        if local_raw != committed_raw:
                            raise ValueError(
                                "HTTP transport source differs from the frozen commit"
                            )
        for artifact in spec.artifacts.values():
            loader = artifact.loader
            try:
                local_loader_raw = (root / loader.path).read_bytes()
                committed_loader_raw = subprocess.run(
                    (
                        "git",
                        "-C",
                        str(root),
                        "show",
                        f"{draft.source.commit}:{loader.path}",
                    ),
                    check=True,
                    capture_output=True,
                ).stdout
            except (OSError, subprocess.CalledProcessError) as exc:
                raise ValueError(
                    "artifact loader is absent from the frozen source commit"
                ) from exc
            if len(local_loader_raw) != loader.bytes:
                raise ValueError("artifact loader byte count differs")
            if hashlib.sha256(local_loader_raw).hexdigest() != loader.sha256:
                raise ValueError("artifact loader SHA-256 differs")
            if local_loader_raw != committed_loader_raw:
                raise ValueError(
                    "artifact loader differs from the frozen source commit"
                )
        raw = serialize_document(spec)
        relative_path = f"{run_root}/stages/{stage.stage_id}/spec.yaml"
        target = _target_path(root, relative_path)
        staged_files.append((target, raw))
        references.append(
            RunStageRef(
                stage_id=stage.stage_id,
                spec=relative_path,
                sha256=hashlib.sha256(raw).hexdigest(),
                bytes=len(raw),
            )
        )

    run = RunSpec(
        run_id=draft.run_id,
        experiment_id=draft.experiment_id,
        variant_id=draft.variant_id,
        replicate_id=draft.replicate_id,
        benchmark_id=draft.benchmark_id,
        seed=draft.seed,
        source=draft.source,
        environment=draft.environment,
        reproducibility=draft.reproducibility,
        stages=tuple(references),
        estimator=draft.estimator,
    )
    run_target = _target_path(root, f"{run_root}/spec.yaml")
    files = (*staged_files, (run_target, serialize_document(run)))

    # Validate every destination before writing any member of the frozen group.
    for target, raw in files:
        if target.exists() and target.read_bytes() != raw:
            raise FileExistsError(f"refusing to replace a different file: {target}")
    for target, raw in files:
        _write_exact_file(target, raw)

    return FrozenPlanFiles(run=run, files=tuple(target for target, _ in files))
