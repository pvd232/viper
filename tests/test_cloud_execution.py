"""Tests for immutable Python and GCE execution-environment evidence."""

from __future__ import annotations

import platform

import pytest
from pydantic import ValidationError

from viper.references import (
    GitFileRef,
    ResolvedGitFileRef,
)
from viper.runtime import (
    CPUBackendContext,
    CPUComputeSpec,
    GCEBootImageRef,
    GCEEnvironmentSpec,
    GCEHostContext,
    PythonDistributionSpec,
    PythonEnvironmentSpec,
    ResolvedGCEEnvironment,
    observe_gce_execution,
    observe_gce_provisioning,
    observe_python_environment,
)
from viper.verifier import VerificationError, _verify_effective_environment

REPOSITORY = "https://github.com/example/viper-project"


def _metadata(path: str) -> str:
    """Return deterministic metadata for one synthetic GCE instance."""
    values = {
        "project/project-id": "mantra-477901",
        "instance/image": "projects/ubuntu-os-cloud/global/images/ubuntu-2404-v1",
        "instance/machine-type": "projects/123/machineTypes/g2-standard-12",
        "instance/zone": "projects/123/zones/us-central1-a",
    }
    return values[path]


def _provisioning_id(kind: str, project: str, name: str) -> str:
    """Return the immutable ID matched by the synthetic image selection."""
    assert kind == "boot_image"
    assert project == "ubuntu-os-cloud"
    assert name == "ubuntu-2404-v1"
    return "987654321"


def test_python_environment_is_normalized_sorted_and_exact() -> None:
    """Capture one canonical mapping of the active installed distributions."""
    environment = observe_python_environment()
    names = tuple(distribution.name for distribution in environment.distributions)

    assert environment.python_version == platform.python_version()
    assert names == tuple(sorted(names))
    assert len(names) == len(set(names))
    assert "viper-provenance" in names


def test_python_environment_rejects_noncanonical_distribution_order() -> None:
    """Reject authored distribution mappings whose order is ambiguous."""
    with pytest.raises(ValidationError, match="sorted by name"):
        PythonEnvironmentSpec(
            python_version="3.14.0",
            distributions=(
                PythonDistributionSpec(name="zeta", version="1"),
                PythonDistributionSpec(name="alpha", version="1"),
            ),
        )


def test_gce_boot_image_binds_metadata_name_to_server_id() -> None:
    """Combine the active image path with its server-defined immutable ID."""
    image = observe_gce_provisioning(_metadata, _provisioning_id)

    assert image.project == "ubuntu-os-cloud"
    assert image.name == "ubuntu-2404-v1"
    assert image.id == "987654321"


def test_gce_execution_records_host_and_cpu_backend() -> None:
    """Construct complete GCE host evidence for one CPU stage."""
    context = observe_gce_execution(
        CPUComputeSpec(),
        metadata_get=_metadata,
        provisioning_id_get=_provisioning_id,
    )

    assert isinstance(context.host, GCEHostContext)
    assert context.host.project_id == "mantra-477901"
    assert context.host.machine_type == "g2-standard-12"
    assert context.host.zone == "us-central1-a"
    assert context.host.provisioning.id == "987654321"
    assert isinstance(context.backend, CPUBackendContext)


def test_gce_boot_image_rejects_malformed_metadata_path() -> None:
    """Reject a metadata value that cannot identify an immutable boot image."""
    with pytest.raises(RuntimeError, match="invalid GCE image metadata path"):
        observe_gce_provisioning(lambda _: "ubuntu-2404-v1", _provisioning_id)


def test_gce_machine_image_requires_matching_provisioning_attestation() -> None:
    """Resolve an API-validated machine image from provisioning metadata."""
    values = {
        "instance/image": "",
        "instance/attributes/viper-provisioning-kind": "machine_image",
        "instance/attributes/viper-provisioning-project": "mantra-477901",
        "instance/attributes/viper-provisioning-name": "mantra-backup-blueprint",
        "instance/attributes/viper-provisioning-id": "4030260845309136958",
    }

    def resolve(kind: str, project: str, name: str) -> str:
        assert (kind, project, name) == (
            "machine_image",
            "mantra-477901",
            "mantra-backup-blueprint",
        )
        return "4030260845309136958"

    source = observe_gce_provisioning(values.__getitem__, resolve)

    assert source.kind == "machine_image"
    assert source.id == "4030260845309136958"


def test_gce_environment_joins_requested_resolved_and_observed_evidence() -> None:
    """Accept one complete GCE environment evidence chain."""
    provisioning = GCEBootImageRef(
        project="ubuntu-os-cloud",
        name="ubuntu-2404-v1",
        id="987654321",
    )
    lockfile = GitFileRef.model_validate(
        {
            "repository": REPOSITORY,
            "commit": "a" * 40,
            "path": "uv.lock",
        }
    )
    python = observe_python_environment()
    requested = GCEEnvironmentSpec(
        provisioning=provisioning,
        machine_type="g2-standard-12",
        compute=CPUComputeSpec(),
        lockfile=lockfile,
        python_environment=python,
    )
    resolved = ResolvedGCEEnvironment(
        provisioning=provisioning,
        machine_type="g2-standard-12",
        compute=CPUComputeSpec(),
        lockfile=ResolvedGitFileRef(
            sha256="0" * 64,
            bytes=4,
            stored_at=lockfile,
        ),
        python_environment=python,
    )
    context = observe_gce_execution(
        CPUComputeSpec(),
        metadata_get=_metadata,
        provisioning_id_get=_provisioning_id,
    )

    _verify_effective_environment("train", requested, resolved, context)


def test_gce_environment_rejects_each_changed_identity() -> None:
    """Reject changed provisioning, machine, lockfile, and Python evidence."""
    provisioning = GCEBootImageRef(
        project="ubuntu-os-cloud",
        name="ubuntu-2404-v1",
        id="987654321",
    )
    lockfile = GitFileRef.model_validate(
        {
            "repository": REPOSITORY,
            "commit": "a" * 40,
            "path": "uv.lock",
        }
    )
    python = observe_python_environment()
    requested = GCEEnvironmentSpec(
        provisioning=provisioning,
        machine_type="g2-standard-12",
        compute=CPUComputeSpec(),
        lockfile=lockfile,
        python_environment=python,
    )
    resolved = ResolvedGCEEnvironment(
        provisioning=provisioning,
        machine_type="g2-standard-12",
        compute=CPUComputeSpec(),
        lockfile=ResolvedGitFileRef(
            sha256="0" * 64,
            bytes=4,
            stored_at=lockfile,
        ),
        python_environment=python,
    )
    context = observe_gce_execution(
        CPUComputeSpec(),
        metadata_get=_metadata,
        provisioning_id_get=_provisioning_id,
    )
    changed_provisioning = provisioning.model_copy(update={"id": "111111111"})
    changed_python = python.model_copy(update={"python_version": "0.0.0"})
    assert isinstance(context.host, GCEHostContext)
    cases = (
        (
            resolved.model_copy(update={"provisioning": changed_provisioning}),
            context,
            "gce.provisioning",
        ),
        (
            resolved,
            context.model_copy(
                update={
                    "host": context.host.model_copy(
                        update={"provisioning": changed_provisioning}
                    )
                }
            ),
            "gce.provisioning",
        ),
        (
            resolved.model_copy(update={"machine_type": "a2-highgpu-1g"}),
            context,
            "gce.machine_type",
        ),
        (
            resolved.model_copy(
                update={
                    "lockfile": resolved.lockfile.model_copy(
                        update={
                            "stored_at": lockfile.model_copy(
                                update={"commit": "b" * 40}
                            )
                        }
                    )
                }
            ),
            context,
            "environment.lockfile",
        ),
        (
            resolved.model_copy(update={"python_environment": changed_python}),
            context,
            "environment.python",
        ),
    )
    for changed_resolved, changed_context, message in cases:
        with pytest.raises(VerificationError, match=message):
            _verify_effective_environment(
                "train",
                requested,
                changed_resolved,
                changed_context,
            )
