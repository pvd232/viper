"""Tests for complete local-plan preflight and same-run input paths."""

import hashlib
from pathlib import Path

from tests.fixtures import (
    artifact_loader_ref,
    builtin_http_transport,
    http_policy,
    http_request,
    parameter_model_ref,
    stage_implementation_ref,
)
from viper import parameters
from viper._schema import (
    PARAMETERS,
    RESUME_STATE,
)
from viper.artifacts import SingleFileArtifactSpec
from viper.inputs import FutureInputRef
from viper.preflight import preflight_plan
from viper.runs import (
    RunSpec,
    RunStageRef,
)
from viper.serialization import serialize_document
from viper.stages import (
    DownloadSpec,
    TrainSpec,
)


def _artifact(path: str) -> SingleFileArtifactSpec:
    """Build one training-role file artifact for local preflight tests."""
    return SingleFileArtifactSpec(
        path=path,
        loader=artifact_loader_ref("project/loaders/bytes_file.py"),
        data_role="training",
    )


def test_preflight_reports_all_plan_failures(tmp_path: Path) -> None:
    """Return every independent plan, source, environment, and stage failure."""
    run_root = "experiments/example/runs/baseline/01JABCDEFGHJKMNPQRSTVWXYZ0"
    stage = TrainSpec(
        implementation=stage_implementation_ref("project/build.py"),
        parameter_model=parameter_model_ref("train"),
        inputs={
            "dataset": FutureInputRef(
                producer_stage_id="download",
                producer_artifact="dataset",
            )
        },
        artifacts={
            PARAMETERS: _artifact(f"{run_root}/artifacts/models/main/parameters.bin"),
            RESUME_STATE: _artifact(
                f"{run_root}/artifacts/models/main/resume_state.bin"
            ),
        },
        params=parameters.Train(),
    )
    stage_path = f"{run_root}/stages/train/spec.yaml"
    raw = serialize_document(stage)
    target = tmp_path / stage_path
    target.parent.mkdir(parents=True)
    target.write_bytes(raw)
    run = RunSpec.model_validate(
        {
            "run_id": "01JABCDEFGHJKMNPQRSTVWXYZ0",
            "experiment_id": "example",
            "variant_id": "baseline",
            "replicate_id": "replicate_01",
            "seed": 42,
            "source": {
                "kind": "git",
                "repository": "https://github.com/example/project",
                "commit": "a" * 40,
            },
            "environment": {
                "kind": "gce",
                "provisioning": {
                    "kind": "boot_image",
                    "project": "example",
                    "name": "image",
                    "id": "123456789",
                },
                "machine_type": "n2-standard-8",
                "compute": {"kind": "cpu"},
                "lockfile": {
                    "kind": "git",
                    "repository": "https://github.com/example/project",
                    "commit": "a" * 40,
                    "path": "environment.yml",
                },
                "python_environment": {
                    "python_version": "3.13.0",
                    "distributions": [{"name": "viper-provenance", "version": "0.1.0"}],
                },
            },
            "reproducibility": {
                "determinism": {
                    "deterministic_algorithms": True,
                    "deterministic_warn_only": False,
                    "cudnn_deterministic": True,
                    "cudnn_benchmark": False,
                    "cublas_workspace_config": ":4096:8",
                },
                "precision": {
                    "float32_matmul_precision": "highest",
                    "cudnn_allow_tf32": False,
                    "autocast_enabled": False,
                    "autocast_dtype": None,
                },
                "parallelism": {
                    "process_count": 1,
                    "torch_intraop_threads": 1,
                    "torch_interop_threads": 1,
                    "dataloader": {
                        "workers": 0,
                        "prefetch_factor": None,
                        "persistent_workers": False,
                        "in_order": True,
                    },
                },
                "numpy_randomness": {
                    "generators": {"training": "PCG64"},
                    "capture_legacy_global": True,
                },
            },
            "stages": [
                RunStageRef(
                    stage_id="train",
                    spec=stage_path,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    bytes=len(raw),
                )
            ],
            "estimator": {
                "stage_id": "train",
                "artifact_name": PARAMETERS,
            },
        }
    )
    run_path = tmp_path / run_root / "spec.yaml"
    run_path.write_bytes(serialize_document(run))

    report = preflight_plan(tmp_path, run_path)

    failures = {check.code for check in report.checks if check.status == "failure"}
    assert failures == {
        "artifact.loader",
        "environment.gce",
        "environment.python",
        "input.future",
        "metric.implementation",
        "parameter_model.identity",
        "parameter_model.validation",
        "plan.git_identity",
        "plan.records",
        "plan.relationships",
        "source.repository",
        "stage.callable",
        "stage.implementation",
    }
    assert not report.ready


def test_future_input_uses_canonical_producer_path(tmp_path: Path) -> None:
    """Resolve one consumer input to the materialized producer artifact."""
    producer = DownloadSpec(
        implementation=stage_implementation_ref("project/download.py"),
        parameter_model=parameter_model_ref("download"),
        inputs={"remote": http_request(url="https://example.com/data")},
        transport=builtin_http_transport(),
        policy=http_policy(),
        artifacts={
            "dataset": _artifact(
                "experiments/example/runs/baseline/01JABCDEFGHJKMNPQRSTVWXYZ0/"
                "artifacts/datasets/main/data.bin"
            )
        },
        params=parameters.Download(),
    )
    path = tmp_path / producer.artifacts["dataset"].path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"dataset")
