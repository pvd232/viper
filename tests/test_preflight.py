"""Tests for complete local-plan preflight and same-run input paths."""

import hashlib
from pathlib import Path

from tests.fixtures import (
    artifact_loader_ref,
    builtin_http,
    config_type_ref,
    http_policy,
    http_request,
    stage_implementation_ref,
)
from viper import config
from viper.inputs import FutureInputRef
from viper.keys import Train as TrainKeys
from viper.metrics import MetricObjectiveSpec
from viper.outputs import OutputSpec
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


def _output(path: str) -> OutputSpec:
    """Build one training-role file output for local preflight tests."""
    return OutputSpec(
        path=path,
        loader=artifact_loader_ref("project/loaders/bytes_file.py"),
        data_role="training",
    )


def test_preflight_reports_all_plan_failures(tmp_path: Path) -> None:
    """Return every independent plan, source, environment, and stage failure."""
    run_root = "experiments/example/runs/baseline/01JABCDEFGHJKMNPQRSTVWXYZ0"
    stage = TrainSpec(
        metric_ids=("training_loss",),
        objective=MetricObjectiveSpec(
            metric_id="training_loss",
            direction="min",
        ),
        implementation=stage_implementation_ref("project/build.py"),
        config_type=config_type_ref("train"),
        inputs={
            "dataset": FutureInputRef(
                producer_stage_id="download",
                name="dataset",
            )
        },
        outputs={  # pyright: ignore[reportArgumentType]
            TrainKeys.MODEL: _output(
                f"{run_root}/artifacts/train/model/parameters.bin"
            ),
            TrainKeys.RESUME_STATE: _output(
                f"{run_root}/artifacts/train/resume_state/resume_state.bin"
            ),
        },
        config=config.TrainConfig(),
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
            "env": {
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
                "python_env": {
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
            "execution_policy": {"mode": "custom", "version": 1},
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
                "artifact_name": TrainKeys.MODEL,
            },
        }
    )
    run_path = tmp_path / run_root / "spec.yaml"
    run_path.write_bytes(serialize_document(run))

    report = preflight_plan(tmp_path, run_path)

    failures = {check.code for check in report.checks if check.status == "failure"}
    assert failures == {
        "artifact.loader",
        "env.gce",
        "env.python",
        "input.future",
        "metric.implementation",
        "config_type.identity",
        "config_type.validation",
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
        inputs={"dataset": http_request(url="https://example.com/data")},
        http=builtin_http(),
        policy=http_policy(),
        outputs={  # pyright: ignore[reportArgumentType]
            "dataset": _output(
                "experiments/example/runs/baseline/01JABCDEFGHJKMNPQRSTVWXYZ0/"
                "artifacts/download/dataset/data.bin"
            )
        },
    )
    path = tmp_path / producer.outputs["dataset"].path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"dataset")
