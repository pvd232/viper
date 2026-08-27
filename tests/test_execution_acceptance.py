"""Acceptance test for a real stage command and its produced artifact files."""

import hashlib
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.fixtures import (
    artifact_loader_ref,
    builtin_http_transport,
    http_policy,
    http_request,
    python_environment,
)
from viper import parameters
from viper.artifacts import (
    ResolvedSingleFileArtifact,
    SingleFileArtifactSpec,
)
from viper.execution._stage import execute_stage_process
from viper.http import (
    ObservedHttpResponse,
    ResolvedHttpRetrieval,
    ResolvedHttpTransport,
)
from viper.parameters import ParameterModelRef
from viper.paths import retrieval_body_path
from viper.runs import (
    RunSpec,
    RunStageRef,
)
from viper.serialization import serialize_document
from viper.stages import (
    DownloadSpec,
    StageImplementationRef,
)
from viper.storage import LocalArtifactStore

RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
RUN_ROOT = f"experiments/e001_download/runs/baseline/{RUN_ID}"


class StageExecutionAcceptanceTests(unittest.TestCase):
    """Verify one actual entrypoint invocation through artifact identification."""

    def test_stage_command_writes_and_hashes_its_declared_artifact(self) -> None:
        """Run a download stage and record the exact bytes it produces."""
        artifact_path = f"{RUN_ROOT}/artifacts/datasets/tiny/dataset.bin"
        parameter_source = (
            b"from viper import parameters\n\n"
            b"class TinyDownloadParameters(parameters.Download):\n"
            b'    """Validate parameters for the execution fixture."""\n'
        )
        implementation_source = (
            b"from project.parameters.download import TinyDownloadParameters\n"
            b"from viper import download_stage\n\n"
            b"@download_stage(parameter_model=TinyDownloadParameters)\n"
            b"def ingest(context):\n"
            b"    target = context.artifacts['dataset']\n"
            b"    target.parent.mkdir(parents=True, exist_ok=True)\n"
            b"    source = context.retrievals['source'].body\n"
            b"    target.write_bytes(source.read_bytes())\n"
        )
        response_body = b"tiny response body"
        spec = DownloadSpec(
            implementation=StageImplementationRef(
                path="jobs/ingest_tiny.py",
                symbol="ingest",
                sha256=hashlib.sha256(implementation_source).hexdigest(),
                bytes=len(implementation_source),
            ),
            parameter_model=ParameterModelRef(
                path="project/parameters/download.py",
                symbol="TinyDownloadParameters",
                sha256=hashlib.sha256(parameter_source).hexdigest(),
                bytes=len(parameter_source),
            ),
            inputs={
                "source": http_request(
                    url="https://example.com/tiny-v1",
                    body=response_body,
                )
            },
            transport=builtin_http_transport(),
            policy=http_policy(),
            artifacts={
                "dataset": SingleFileArtifactSpec(
                    path=artifact_path,
                    loader=artifact_loader_ref("project/loaders/bytes_file.py"),
                    data_role="training",
                )
            },
            params=parameters.Download(),
        )

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            script_path = root / spec.implementation.path
            script_path.parent.mkdir(parents=True)
            script_path.write_bytes(implementation_source)
            parameter_path = root / spec.parameter_model.path
            parameter_path.parent.mkdir(parents=True)
            parameter_path.write_bytes(parameter_source)
            stage_path = root / f"{RUN_ROOT}/stages/download/spec.yaml"
            stage_path.parent.mkdir(parents=True)
            stage_raw = serialize_document(spec)
            stage_path.write_bytes(stage_raw)
            reference = RunStageRef(
                stage_id="download",
                spec=stage_path.relative_to(root).as_posix(),
                sha256=hashlib.sha256(stage_raw).hexdigest(),
                bytes=len(stage_raw),
            )

            run = RunSpec.model_validate(
                {
                    "run_id": RUN_ID,
                    "experiment_id": "e001_download",
                    "variant_id": "baseline",
                    "replicate_id": "r1",
                    "seed": 7,
                    "source": {
                        "kind": "git",
                        "repository": "https://github.com/example/project",
                        "commit": "a" * 40,
                    },
                    "environment": {
                        "kind": "local",
                        "python_environment": python_environment().model_dump(
                            mode="json"
                        ),
                        "lockfile": {
                            "kind": "git",
                            "repository": "https://github.com/example/project",
                            "commit": "a" * 40,
                            "path": "environment.yml",
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
                            "generators": {},
                            "capture_legacy_global": False,
                        },
                    },
                    "stages": [
                        reference.model_dump(mode="json"),
                        {
                            "stage_id": "train",
                            "spec": f"{RUN_ROOT}/stages/train/spec.yaml",
                            "sha256": "b" * 64,
                            "bytes": 1,
                        },
                    ],
                    "estimator": {
                        "stage_id": "train",
                        "artifact_name": "parameters",
                    },
                }
            )
            run_path = root / f"{RUN_ROOT}/spec.yaml"
            run_path.write_bytes(serialize_document(run))
            body_path = retrieval_body_path(run, "download", "source")
            materialized_body = root / body_path
            materialized_body.parent.mkdir(parents=True)
            materialized_body.write_bytes(response_body)
            body_reference = LocalArtifactStore(root).resolved_files(
                {body_path: response_body}
            )[0]
            started = datetime.now(UTC)
            retrieval = ResolvedHttpRetrieval(
                input_name="source",
                request=spec.inputs["source"],
                transport=ResolvedHttpTransport(spec=spec.transport),
                response=ObservedHttpResponse(
                    response_url=spec.inputs["source"].url,
                    status=200,
                    response_headers={"content-length": str(len(response_body))},
                ),
                body=body_reference,
                started_at=started,
                completed_at=started + timedelta(microseconds=1),
            )
            result = execute_stage_process(
                root,
                run,
                reference,
                spec,
                input_paths={"source": materialized_body},
                retrievals={"source": retrieval},
            )
            produced = result.artifacts["dataset"]
            assert isinstance(produced, ResolvedSingleFileArtifact)
            raw = (root / produced.file.path).read_bytes()

        self.assertEqual(
            result.command,
            ("python", "-m", "viper._workers.stages"),
        )
        self.assertEqual(result.invocation.outcome, "succeeded")
        self.assertEqual(raw, response_body)
        self.assertEqual(produced.file.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(produced.file.bytes, len(raw))
