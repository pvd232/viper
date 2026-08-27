"""Unit tests for local Pydantic model and YAML-loading contracts."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from pydantic import ValidationError

from tests.fixtures import (
    artifact_loader_ref,
    parameter_model_ref,
    stage_implementation_ref,
)
from viper import parameters
from viper._schema import (
    PARAMETERS,
    PREDICTIONS,
    RESUME_STATE,
    DataRole,
)
from viper.artifacts import ResolvedBundleArtifact
from viper.experiments import VariantSpec
from viper.metrics import (
    FloatComparator,
    MetricDependency,
    MetricImplementationRef,
    MetricSpec,
)
from viper.runs import (
    RunAttempt,
    RunSpec,
)
from viper.runtime import (
    CUDABackendContext,
    GCEEnvironmentSpec,
)
from viper.serialization import load_resolved_stage, load_stage_spec
from viper.stages import (
    EvaluateSpec,
    FutureInputRef,
    TrainSpec,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
GIT_COMMIT = "a" * 40
REPOSITORY = "https://github.com/example/viper-project"
RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
RUN_ROOT = f"experiments/e001_strand/runs/baseline/{RUN_ID}"


def git_file(path: str) -> dict:
    """Build one immutable Git file reference payload."""
    return {
        "kind": "git",
        "repository": REPOSITORY,
        "commit": GIT_COMMIT,
        "path": path,
    }


def environment(*, compute: dict | None = None) -> dict:
    """Build the shared GCE environment payload."""
    return {
        "kind": "gce",
        "provisioning": {
            "kind": "boot_image",
            "project": "viper-project",
            "name": "viper-image",
            "id": "123456789",
        },
        "machine_type": "n2-standard-8",
        "compute": compute or {"kind": "cpu"},
        "lockfile": git_file("uv.lock"),
        "python_environment": {
            "python_version": "3.13.0",
            "distributions": [{"name": "viper-provenance", "version": "0.1.0"}],
        },
    }


def reproducibility() -> dict:
    """Build the run-wide numerical reproducibility payload."""
    return {
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
            "generators": {
                "training": "PCG64",
            },
            "capture_legacy_global": True,
        },
    }


def artifact(path: str, loader: str, data_role: DataRole = "training") -> dict:
    """Build one declared single-file artifact payload."""
    return {
        "kind": "file",
        "path": path,
        "loader": artifact_loader_ref(f"project/loaders/{loader}.py").model_dump(
            mode="json"
        ),
        "data_role": data_role,
    }


def stored_input(
    path: str,
    pointer_path: str,
    data_role: DataRole = "training",
) -> dict:
    """Build one promoted-input materialization payload."""
    return {
        "kind": "stored",
        "pointer": git_file(pointer_path),
        "path": path,
        "data_role": data_role,
    }


def train_payload() -> dict:
    """Build a valid training-stage request payload."""
    return {
        "kind": "train",
        "implementation": stage_implementation_ref(
            "project/training/fit.py", symbol="fit"
        ).model_dump(mode="json"),
        "parameter_model": parameter_model_ref("train").model_dump(mode="json"),
        "inputs": {
            "training_dataset": stored_input(
                "inputs/datasets/replogle/dataset.h5ad",
                "inputs/datasets/replogle/current.pointer.yaml",
            ),
        },
        "params": {
            "epochs": 10,
            "batch_size": 64,
            "learning_rate": 0.001,
        },
        "artifacts": {
            PARAMETERS: artifact(
                f"{RUN_ROOT}/artifacts/models/strand/parameters.safetensors",
                "parameters",
            ),
            RESUME_STATE: artifact(
                f"{RUN_ROOT}/artifacts/models/strand/resume_state.pt",
                "resume_state",
            ),
        },
    }


def run_payload() -> dict:
    """Build a valid frozen run-plan payload."""
    return {
        "run_id": RUN_ID,
        "experiment_id": "e001_strand",
        "variant_id": "baseline",
        "replicate_id": "replicate_01",
        "seed": 42,
        "source": {
            "kind": "git",
            "repository": REPOSITORY,
            "commit": GIT_COMMIT,
        },
        "environment": environment(),
        "reproducibility": reproducibility(),
        "stages": [
            {
                "stage_id": "train",
                "spec": f"{RUN_ROOT}/stages/train/spec.yaml",
                "sha256": SHA_A,
                "bytes": 100,
            }
        ],
        "estimator": {
            "stage_id": "train",
            "artifact_name": PARAMETERS,
        },
    }


class RunPlanTests(unittest.TestCase):
    """Verify run-level identity, seed, stage, and attempt invariants."""

    def test_run_plan_owns_shared_environment_and_reproducibility(self) -> None:
        """Verify that run plan owns shared environment and reproducibility."""
        run = RunSpec.model_validate(run_payload())

        self.assertEqual(run.seed, 42)
        self.assertIsInstance(run.environment, GCEEnvironmentSpec)
        assert isinstance(run.environment, GCEEnvironmentSpec)
        self.assertEqual(run.environment.machine_type, "n2-standard-8")
        self.assertEqual(run.estimator.artifact_name, PARAMETERS)

    def test_estimator_must_select_parameters(self) -> None:
        """Verify that estimator must select model parameters."""
        payload = run_payload()
        payload["estimator"]["artifact_name"] = RESUME_STATE

        with self.assertRaisesRegex(ValidationError, "parameters"):
            RunSpec.model_validate(payload)

    def test_stage_spec_reference_uses_canonical_run_path(self) -> None:
        """Verify that stage spec reference uses canonical run path."""
        payload = run_payload()
        payload["stages"][0]["spec"] = "stages/train/spec.yaml"

        with self.assertRaisesRegex(ValidationError, "canonical run path"):
            RunSpec.model_validate(payload)

    def test_global_seed_uses_the_shared_generator_range(self) -> None:
        """Verify that global seed uses the shared generator range."""
        maximum = run_payload()
        maximum["seed"] = 2**32 - 1
        self.assertEqual(RunSpec.model_validate(maximum).seed, 2**32 - 1)

        for invalid_seed in (-1, 2**32):
            with self.subTest(seed=invalid_seed):
                payload = run_payload()
                payload["seed"] = invalid_seed
                with self.assertRaises(ValidationError):
                    RunSpec.model_validate(payload)

    def test_successful_attempt_requires_a_completed_stage(self) -> None:
        """Verify that successful attempt requires a completed stage."""
        with self.assertRaisesRegex(ValidationError, "completed stage"):
            RunAttempt.model_validate(
                {
                    "attempt_id": 1,
                    "purpose": "run",
                    "status": "succeeded",
                    "started_at": "2026-08-20T20:00:00Z",
                    "completed_at": "2026-08-20T20:01:00Z",
                    "resolved_stages": [],
                    "invocations": [],
                    "journal": {
                        "sha256": SHA_A,
                        "bytes": 1,
                        "stored_at": git_file(f"{RUN_ROOT}/attempts/1/journal.jsonl"),
                    },
                    "measurement_files": [],
                    "log_files": [],
                    "failure": None,
                }
            )

    def test_attempt_file_storage_locations_are_unique(self) -> None:
        """Verify that attempt file storage locations are unique."""
        location = {
            "kind": "huggingface",
            "repository": "example/viper-runs",
            "commit": GIT_COMMIT,
            "path": f"{RUN_ROOT}/logs/1.train.stdout.log",
            "repo_type": "dataset",
        }
        payload = {
            "attempt_id": 1,
            "purpose": "run",
            "status": "failed",
            "started_at": "2026-08-20T20:00:00Z",
            "completed_at": "2026-08-20T20:01:00Z",
            "resolved_stages": [],
            "invocations": [],
            "journal": {
                "sha256": SHA_A,
                "bytes": 1,
                "stored_at": git_file(f"{RUN_ROOT}/attempts/1/journal.jsonl"),
            },
            "measurement_files": [],
            "log_files": [
                {"sha256": SHA_A, "bytes": 1, "stored_at": location},
                {"sha256": SHA_B, "bytes": 1, "stored_at": location},
            ],
            "failure": {
                "code": "execution_failed",
                "stage_id": "train",
                "message": "stage failed",
                "occurred_at": "2026-08-20T20:00:30Z",
            },
        }

        with self.assertRaisesRegex(ValidationError, "storage locations"):
            RunAttempt.model_validate(payload)


class ParameterContractTests(unittest.TestCase):
    """Verify extensible stage and metric parameter records."""

    def test_training_parameters_preserve_project_defined_json_fields(self) -> None:
        """Preserve project-defined values without a VIPER plugin registration."""
        params = parameters.Train.model_validate(
            {
                "schema_version": 1,
                "epochs": 10,
                "optimizer": {
                    "kind": "adam",
                    "learning_rate": 0.001,
                },
            }
        )

        self.assertEqual(params.model_dump()["epochs"], 10)
        self.assertEqual(params.model_dump()["optimizer"]["kind"], "adam")

    def test_evaluation_parameters_reject_shared_evaluation_fields(self) -> None:
        """Keep metrics and split identities on EvaluateSpec."""
        with self.assertRaisesRegex(ValidationError, "belong directly"):
            parameters.Evaluate.model_validate(
                {
                    "schema_version": 1,
                    "metric_ids": ["pearson_correlation"],
                }
            )

    def test_metric_implementation_accepts_user_repository_path(self) -> None:
        """Bind a metric to any exact Python file in the user repository."""
        source = b"def compute(context):\n    return 0.0\n"
        metric = MetricSpec(
            metric_id="pearson_correlation",
            kind="evaluation",
            implementation=MetricImplementationRef(
                path="analysis/quality/correlation.py",
                symbol="compute",
                sha256=hashlib.sha256(source).hexdigest(),
                bytes=len(source),
            ),
            params=parameters.Metric.model_validate({"dim": 1}),
            mode="recompute",
            dependencies=(
                MetricDependency(
                    source="artifact",
                    name="predictions",
                    required_data_role="evaluation",
                ),
            ),
            comparator=FloatComparator(mode="exact", tolerance=0),
        )

        self.assertEqual(metric.params.model_dump()["dim"], 1)

    def test_metric_implementation_requires_python_file(self) -> None:
        """Reject a metric path that does not identify a Python file."""
        with self.assertRaisesRegex(ValidationError, "Python file"):
            MetricSpec(
                metric_id="pearson_correlation",
                kind="evaluation",
                implementation=MetricImplementationRef(
                    path="analysis/quality/correlation.yaml",
                    symbol="compute",
                    sha256="a" * 64,
                    bytes=1,
                ),
                params=parameters.Metric(),
                mode="recompute",
                dependencies=(
                    MetricDependency(
                        source="artifact",
                        name="predictions",
                        required_data_role="evaluation",
                    ),
                ),
                comparator=FloatComparator(mode="exact", tolerance=0),
            )


class RuntimeInvariantTests(unittest.TestCase):
    """Verify observed runtime records reject ambiguous device state."""

    def test_cuda_device_ordinals_are_unique(self) -> None:
        """Verify that cuda device ordinals are unique."""
        device = {
            "ordinal": 0,
            "model": "NVIDIA L4",
            "compute_capability_major": 8,
            "compute_capability_minor": 9,
            "memory_bytes": 24_000_000_000,
        }
        with self.assertRaisesRegex(ValidationError, "ordinals"):
            CUDABackendContext.model_validate(
                {
                    "kind": "cuda",
                    "gpu_devices": [device, device],
                    "nvidia_driver_version": "580.65",
                    "pytorch_cuda_version": "12.8",
                    "cudnn_version": "9.10",
                }
            )


class TrainingCheckpointTests(unittest.TestCase):
    """Verify canonical checkpoint artifacts, inputs, and paths."""

    def test_repository_paths_reject_control_characters(self) -> None:
        """Verify that repository paths reject control characters."""
        payload = train_payload()
        payload["implementation"]["path"] = "project/training/fit.py\nother"

        with self.assertRaisesRegex(ValidationError, "control character"):
            TrainSpec.model_validate(payload)

    def test_stage_source_path_is_repository_agnostic(self) -> None:
        """Accept any repository-relative Python entrypoint selected by the author."""
        payload = train_payload()
        payload["implementation"]["path"] = "unconventional/layout/run_training.py"

        spec = TrainSpec.model_validate(payload)

        self.assertEqual(
            spec.implementation.path, "unconventional/layout/run_training.py"
        )

    def test_protocol_managed_paths_use_protocol_roots(self) -> None:
        """Keep inputs and outputs under their protocol-managed roots."""
        invalid_script = train_payload()
        invalid_script["implementation"]["path"] = "project/training/spec.yaml"
        with self.assertRaisesRegex(ValidationError, "Python file"):
            TrainSpec.model_validate(invalid_script)

        invalid_input = train_payload()
        invalid_input["inputs"]["training_dataset"]["path"] = "data/train.h5ad"
        with self.assertRaisesRegex(ValidationError, "category and entity ID"):
            TrainSpec.model_validate(invalid_input)

        invalid_pointer = train_payload()
        invalid_pointer["inputs"]["training_dataset"]["pointer"]["path"] = (
            "inputs/datasets/replogle.pointer.yaml"
        )
        with self.assertRaisesRegex(ValidationError, "selection_name"):
            TrainSpec.model_validate(invalid_pointer)

        invalid_artifact = train_payload()
        invalid_artifact["artifacts"][PARAMETERS]["path"] = (
            "artifacts/parameters.safetensors"
        )
        with self.assertRaisesRegex(ValidationError, "category and entity ID"):
            TrainSpec.model_validate(invalid_artifact)

        wrong_artifact_category = train_payload()
        wrong_artifact_category["artifacts"][PARAMETERS]["path"] = (
            f"{RUN_ROOT}/artifacts/priors/strand/parameters.safetensors"
        )
        with self.assertRaisesRegex(ValidationError, "category and entity ID"):
            TrainSpec.model_validate(wrong_artifact_category)

    def test_stored_input_path_cannot_overlap_its_pointer_file(self) -> None:
        """Verify that stored input path cannot overlap its pointer file."""
        for path in (
            "inputs/datasets/replogle",
            "inputs/datasets/replogle/current.pointer.yaml/materialized",
            "inputs/datasets/replogle/other.pointer.yaml",
        ):
            with self.subTest(path=path):
                payload = train_payload()
                payload["inputs"]["training_dataset"]["path"] = path

                with self.assertRaisesRegex(ValidationError, "must not"):
                    TrainSpec.model_validate(payload)

    def test_artifact_identity_is_independent_of_script_directory(self) -> None:
        """Allow protocol artifact identity to differ from source-code layout."""
        payload = train_payload()
        payload["artifacts"][PARAMETERS]["path"] = (
            f"{RUN_ROOT}/artifacts/models/other/parameters.safetensors"
        )

        spec = TrainSpec.model_validate(payload)

        self.assertIn("/models/other/", spec.artifacts[PARAMETERS].path)

    def test_reserved_artifact_names_are_stage_specific(self) -> None:
        """Verify that reserved artifact names are stage specific."""
        payload = train_payload()
        payload["artifacts"][PREDICTIONS] = artifact(
            f"{RUN_ROOT}/artifacts/evaluations/invalid/predictions.json",
            "json_file",
        )

        with self.assertRaisesRegex(ValidationError, "reserved for evaluation"):
            TrainSpec.model_validate(payload)

    def test_train_requires_both_terminal_checkpoint_artifacts(self) -> None:
        """Verify that train requires both terminal checkpoint artifacts."""
        payload = train_payload()
        del payload["artifacts"][RESUME_STATE]

        with self.assertRaisesRegex(ValidationError, "resume_state"):
            TrainSpec.model_validate(payload)

    def test_checkpoint_inputs_select_one_producer_and_both_artifacts(self) -> None:
        """Verify that checkpoint inputs select one producer and both artifacts."""
        payload = train_payload()
        payload["inputs"].update(
            {
                "parameters": {
                    "kind": "future",
                    "producer_stage_id": "train_01",
                    "producer_artifact": PARAMETERS,
                },
                "resume_state": {
                    "kind": "future",
                    "producer_stage_id": "train_01",
                    "producer_artifact": RESUME_STATE,
                },
            }
        )

        spec = TrainSpec.model_validate(payload)
        checkpoint = spec.inputs["parameters"]
        assert isinstance(checkpoint, FutureInputRef)
        self.assertEqual(
            checkpoint.producer_stage_id,
            "train_01",
        )

    def test_checkpoint_inputs_must_occur_together(self) -> None:
        """Verify that checkpoint inputs must occur together."""
        payload = train_payload()
        payload["inputs"]["parameters"] = {
            "kind": "future",
            "producer_stage_id": "train_01",
            "producer_artifact": PARAMETERS,
        }

        with self.assertRaisesRegex(ValidationError, "declared together"):
            TrainSpec.model_validate(payload)

    def test_checkpoint_inputs_must_select_one_producer(self) -> None:
        """Verify that checkpoint inputs must select one producer."""
        payload = train_payload()
        payload["inputs"].update(
            {
                "parameters": {
                    "kind": "future",
                    "producer_stage_id": "train_01",
                    "producer_artifact": PARAMETERS,
                },
                "resume_state": {
                    "kind": "future",
                    "producer_stage_id": "train_02",
                    "producer_artifact": RESUME_STATE,
                },
            }
        )

        with self.assertRaisesRegex(ValidationError, "one checkpoint-producing"):
            TrainSpec.model_validate(payload)

    def test_stored_checkpoint_inputs_use_model_paths(self) -> None:
        """Verify that stored checkpoint inputs use model paths."""
        payload = train_payload()
        payload["inputs"].update(
            {
                "parameters": stored_input(
                    "inputs/priors/strand/parameters.safetensors",
                    "inputs/priors/strand/parameters.pointer.yaml",
                ),
                "resume_state": stored_input(
                    "inputs/priors/strand/resume_state.pt",
                    "inputs/priors/strand/resume_state.pointer.yaml",
                ),
            }
        )

        with self.assertRaisesRegex(ValidationError, "inputs/models"):
            TrainSpec.model_validate(payload)


class EvaluationTests(unittest.TestCase):
    """Verify evaluation identity, inputs, metrics, and prediction outputs."""

    def test_evaluation_requires_fixed_inputs_metrics_and_predictions(self) -> None:
        """Verify that evaluation requires fixed inputs metrics and predictions."""
        spec = EvaluateSpec.model_validate(
            {
                "kind": "evaluate",
                "implementation": stage_implementation_ref(
                    "project/evaluation/predict.py", symbol="predict"
                ).model_dump(mode="json"),
                "parameter_model": parameter_model_ref("evaluate").model_dump(
                    mode="json"
                ),
                "evaluation_id": "strand_predictions",
                "metric_ids": ["pearson_correlation"],
                "split_inputs": ["perturbation_split"],
                "inputs": {
                    "parameters": {
                        "kind": "future",
                        "producer_stage_id": "train",
                        "producer_artifact": PARAMETERS,
                    },
                    "evaluation_dataset": stored_input(
                        "inputs/datasets/replogle_test/dataset.h5ad",
                        "inputs/datasets/replogle_test/current.pointer.yaml",
                        "evaluation",
                    ),
                    "perturbation_split": stored_input(
                        "inputs/benchmarks/replogle/perturbations.json",
                        "inputs/benchmarks/replogle/perturbations.pointer.yaml",
                        "evaluation",
                    ),
                },
                "params": {},
                "artifacts": {
                    PREDICTIONS: artifact(
                        f"{RUN_ROOT}/artifacts/evaluations/strand_predictions/predictions.json",
                        "json_file",
                        "evaluation",
                    )
                },
            }
        )

        self.assertIn(PREDICTIONS, spec.artifacts)

    def test_predictions_may_use_a_project_defined_bundle_format(self) -> None:
        """Accept a prediction bundle with an exact project-owned loader path."""
        payload = {
            "kind": "evaluate",
            "implementation": stage_implementation_ref(
                "evaluation/predict.py", symbol="predict"
            ).model_dump(mode="json"),
            "parameter_model": parameter_model_ref("evaluate").model_dump(mode="json"),
            "evaluation_id": "structured_predictions",
            "metric_ids": ["accuracy"],
            "split_inputs": ["test_split"],
            "inputs": {
                "parameters": {
                    "kind": "future",
                    "producer_stage_id": "train",
                    "producer_artifact": PARAMETERS,
                },
                "evaluation_dataset": stored_input(
                    "inputs/datasets/test/data.bin",
                    "inputs/datasets/test/current.pointer.yaml",
                    "evaluation",
                ),
                "test_split": stored_input(
                    "inputs/benchmarks/test/split.json",
                    "inputs/benchmarks/test/current.pointer.yaml",
                    "evaluation",
                ),
            },
            "params": {},
            "artifacts": {
                PREDICTIONS: {
                    "kind": "bundle",
                    "path": (
                        f"{RUN_ROOT}/artifacts/evaluations/structured_predictions"
                    ),
                    "loader": artifact_loader_ref(
                        "custom_code/load_prediction_bundle.py"
                    ).model_dump(mode="json"),
                    "data_role": "evaluation",
                }
            },
        }

        spec = EvaluateSpec.model_validate(payload)

        self.assertEqual(spec.artifacts[PREDICTIONS].kind, "bundle")

    def test_evaluation_inputs_use_role_specific_paths(self) -> None:
        """Verify that evaluation inputs use role specific paths."""
        payload = {
            "kind": "evaluate",
            "implementation": stage_implementation_ref(
                "project/evaluation/predict.py", symbol="predict"
            ).model_dump(mode="json"),
            "parameter_model": parameter_model_ref("evaluate").model_dump(mode="json"),
            "evaluation_id": "strand_predictions",
            "metric_ids": ["pearson_correlation"],
            "split_inputs": ["split"],
            "inputs": {
                "parameters": stored_input(
                    "inputs/priors/strand/parameters.safetensors",
                    "inputs/priors/strand/current.pointer.yaml",
                ),
                "evaluation_dataset": stored_input(
                    "inputs/datasets/replogle_test/dataset.h5ad",
                    "inputs/datasets/replogle_test/current.pointer.yaml",
                    "evaluation",
                ),
                "split": stored_input(
                    "inputs/benchmarks/replogle/split.json",
                    "inputs/benchmarks/replogle/split.pointer.yaml",
                    "evaluation",
                ),
            },
            "params": {},
            "artifacts": {
                PREDICTIONS: artifact(
                    f"{RUN_ROOT}/artifacts/evaluations/strand_predictions/predictions.json",
                    "json_file",
                    "evaluation",
                )
            },
        }

        with self.assertRaisesRegex(ValidationError, "inputs/models"):
            EvaluateSpec.model_validate(payload)

        payload["inputs"]["parameters"] = stored_input(
            "inputs/models/strand/parameters.safetensors",
            "inputs/models/strand/current.pointer.yaml",
        )
        payload["inputs"]["evaluation_dataset"] = stored_input(
            "inputs/priors/replogle_test/dataset.h5ad",
            "inputs/priors/replogle_test/current.pointer.yaml",
            "evaluation",
        )
        with self.assertRaisesRegex(ValidationError, "inputs/datasets"):
            EvaluateSpec.model_validate(payload)

        payload["inputs"]["evaluation_dataset"] = stored_input(
            "inputs/datasets/replogle_test/dataset.h5ad",
            "inputs/datasets/replogle_test/current.pointer.yaml",
            "evaluation",
        )
        payload["inputs"]["split"] = stored_input(
            "inputs/datasets/replogle/split.json",
            "inputs/datasets/replogle/split.pointer.yaml",
            "evaluation",
        )
        with self.assertRaisesRegex(ValidationError, "inputs/benchmarks"):
            EvaluateSpec.model_validate(payload)

    def test_evaluation_rejects_training_checkpoint_outputs(self) -> None:
        """Verify that evaluation rejects training checkpoint outputs."""
        payload = {
            "kind": "evaluate",
            "implementation": stage_implementation_ref(
                "project/evaluation/predict.py", symbol="predict"
            ).model_dump(mode="json"),
            "parameter_model": parameter_model_ref("evaluate").model_dump(mode="json"),
            "evaluation_id": "strand_predictions",
            "metric_ids": ["pearson_correlation"],
            "split_inputs": ["split"],
            "inputs": {
                "parameters": stored_input(
                    "inputs/models/strand/parameters.safetensors",
                    "inputs/models/strand/current.pointer.yaml",
                ),
                "evaluation_dataset": stored_input(
                    "inputs/datasets/replogle_test/dataset.h5ad",
                    "inputs/datasets/replogle_test/current.pointer.yaml",
                    "evaluation",
                ),
                "split": stored_input(
                    "inputs/benchmarks/replogle/split.json",
                    "inputs/benchmarks/replogle/split.pointer.yaml",
                    "evaluation",
                ),
            },
            "params": {},
            "artifacts": {
                PREDICTIONS: artifact(
                    f"{RUN_ROOT}/artifacts/evaluations/strand_predictions/predictions.json",
                    "json_file",
                    "evaluation",
                ),
                PARAMETERS: artifact(
                    f"{RUN_ROOT}/artifacts/evaluations/strand_predictions/parameters.safetensors",
                    "parameters",
                    "evaluation",
                ),
            },
        }

        with self.assertRaisesRegex(ValidationError, "reserved for training"):
            EvaluateSpec.model_validate(payload)


class ArtifactAndVariantTests(unittest.TestCase):
    """Verify artifact partition and variant-parameter invariants."""

    def test_bundle_requires_at_least_two_members(self) -> None:
        """Verify that bundle requires at least two members."""
        with self.assertRaises(ValidationError):
            ResolvedBundleArtifact.model_validate(
                {
                    "kind": "bundle",
                    "members": [
                        {
                            "relative_path": "config.json",
                            "file": {
                                "path": "artifacts/model/config.json",
                                "sha256": SHA_A,
                                "bytes": 10,
                            },
                        }
                    ],
                }
            )

    def test_bundle_member_paths_cannot_overlap(self) -> None:
        """Verify that bundle member paths cannot overlap."""
        with self.assertRaisesRegex(ValidationError, "must not overlap"):
            ResolvedBundleArtifact.model_validate(
                {
                    "kind": "bundle",
                    "members": [
                        {
                            "relative_path": "model",
                            "file": {
                                "path": "artifacts/model",
                                "sha256": SHA_A,
                                "bytes": 10,
                            },
                        },
                        {
                            "relative_path": "model/weights.bin",
                            "file": {
                                "path": "artifacts/model/weights.bin",
                                "sha256": SHA_B,
                                "bytes": 20,
                            },
                        },
                    ],
                }
            )

    def test_variant_stage_ids_are_unique(self) -> None:
        """Verify that variant stage ids are unique."""
        with self.assertRaisesRegex(ValidationError, "stage IDs"):
            VariantSpec.model_validate(
                {
                    "experiment_id": "e001_strand",
                    "variant_id": "baseline",
                    "levels": {"embedding": "learned"},
                    "stage_params": [
                        {
                            "kind": "train",
                            "stage_id": "train",
                            "params": {
                                "epochs": 10,
                                "batch_size": 64,
                                "learning_rate": 0.001,
                            },
                        },
                        {
                            "kind": "train",
                            "stage_id": "train",
                            "params": {
                                "epochs": 20,
                                "batch_size": 64,
                                "learning_rate": 0.001,
                            },
                        },
                    ],
                }
            )

    def test_variant_requires_stage_parameters(self) -> None:
        """Verify that variant requires stage parameters."""
        with self.assertRaisesRegex(ValidationError, "at least 1 item"):
            VariantSpec.model_validate(
                {
                    "experiment_id": "e001_strand",
                    "variant_id": "baseline",
                    "levels": {},
                    "stage_params": [],
                }
            )


class YAMLLoadingTests(unittest.TestCase):
    """Verify canonical examples and YAML parsing boundaries."""

    def test_active_examples_load_through_v4_unions(self) -> None:
        """Verify that active examples load through v4 unions."""
        examples = (
            ("stages/download/spec.yaml", load_stage_spec),
            ("stages/build/spec.yaml", load_stage_spec),
            ("stages/download/resolved.yaml", load_resolved_stage),
            ("stages/build/resolved.yaml", load_resolved_stage),
        )
        example_root = Path(__file__).parents[1] / "examples" / "provenance"

        for filename, loader in examples:
            with self.subTest(filename=filename):
                loader(example_root / filename)

    def test_stage_spec_loads_through_the_v4_union(self) -> None:
        """Verify that stage spec loads through the v4 union."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "train.spec.yaml"
            dumped = yaml.safe_dump(train_payload())
            assert isinstance(dumped, str)
            path.write_text(dumped, encoding="utf-8")

            loaded = load_stage_spec(path)

        self.assertIsInstance(loaded, TrainSpec)

    def test_duplicate_yaml_keys_are_rejected(self) -> None:
        """Verify that duplicate yaml keys are rejected."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.yaml"
            path.write_text("kind: train\nkind: evaluate\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate YAML key"):
                load_stage_spec(path)

    def test_unhashable_yaml_keys_are_rejected_as_validation_errors(self) -> None:
        """Verify that unhashable yaml keys are rejected as validation errors."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unhashable.yaml"
            path.write_text("? [kind, train]\n: invalid\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "mapping keys must be scalar"):
                load_stage_spec(path)


if __name__ == "__main__":
    unittest.main()
