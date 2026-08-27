"""Focused tests for cross-record, file-identity, and lineage verification."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import HttpUrl, TypeAdapter

from tests.fixtures import (
    DEFAULT_ARTIFACT_LOADER_SOURCE,
    artifact_loader_ref,
    metric_spec,
    parameter_model_ref,
    parameter_model_source,
    python_environment,
    resume_state,
    stage_implementation_ref,
    verification_policy,
)
from viper import parameters
from viper.ids import InputName
from viper.protocol import (
    PARAMETERS,
    RESUME_STATE,
    ArtifactLoaderRef,
    ArtifactPointer,
    ArtifactPointerRef,
    AttemptFailure,
    AttemptJournalRef,
    BenchmarkSpec,
    BuildSpec,
    BuildVariantStageParams,
    CPUBackendContext,
    CPUComputeSpec,
    CPUContext,
    DataLoaderConfiguration,
    EvaluateSpec,
    EvaluateVariantStageParams,
    ExecutionContext,
    ExperimentSpec,
    FutureInputRef,
    GCEBootImageRef,
    GCEEnvironmentSpec,
    GCEHostContext,
    GitFileRef,
    GitSource,
    HuggingFaceFileRef,
    InternalInputRef,
    MetricCriterion,
    NativeLibraryContext,
    NativeThreadPoolContext,
    NonEmptyStr,
    NumericalRuntimeContext,
    NumPyRandomnessSpec,
    ParallelismSpec,
    ProcessStartupReceipt,
    ReplicateSpec,
    ReproducibilitySpec,
    ResolvedArtifactPointerRef,
    ResolvedAttemptRef,
    ResolvedBuildSpec,
    ResolvedFileRef,
    ResolvedFutureInputRef,
    ResolvedGCEEnvironment,
    ResolvedGitFileRef,
    ResolvedRun,
    ResolvedRunRef,
    ResolvedRunSpecRef,
    ResolvedSingleFileArtifact,
    ResolvedStageInvocationRef,
    ResolvedStageRef,
    ResolvedStoredInputRef,
    ResolvedTrainSpec,
    RunAttempt,
    RunSpec,
    RunStageRef,
    SingleFileArtifactSpec,
    SnapshotFileRef,
    StageArtifactRef,
    StageContextBinding,
    StageInvocationReceipt,
    StageResultSnapshotRef,
    StoredInputRef,
    TorchDeterminismSpec,
    TorchPrecisionSpec,
    TrainSpec,
    TrainVariantStageParams,
    VariantSpec,
)
from viper.runtime import process_environment
from viper.serialization import document_digest
from viper.verifier import (
    VerificationError,
    VerificationPolicy,
    VerifiedArtifact,
    VerifiedSnapshotFile,
    fetch_git_file_bytes,
    load_verified_artifact,
    read_resolved_file,
    read_snapshot_file,
    verify_attempt_files,
    verify_attempt_future_inputs,
    verify_future_inputs,
    verify_parameter_model_references,
    verify_resolved_stages,
    verify_run_plan_relationships,
    verify_run_spec,
    verify_stage_plan,
    verify_stored_input_selections,
)

GIT_COMMIT = "a" * 40
PLAN_COMMIT = "b" * 40
SNAPSHOT_COMMIT = "c" * 40
REPOSITORY = HttpUrl("https://github.com/example/viper-project")
HF_REPOSITORY: NonEmptyStr = "example/viper-runs"
RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
RUN_ROOT = f"experiments/e001_strand/runs/baseline/{RUN_ID}"
YAML_ADAPTER = TypeAdapter(Any)
INSTRUCTION_SET: NonEmptyStr = "avx2"
POLICY = verification_policy(REPOSITORY)
ATTEMPT_JOURNAL_RAW = (
    b'{"sequence":1,"state":"allocated",'
    b'"recorded_at":"2026-08-21T12:00:00Z",'
    b'"event":"attempt allocated","details":{}}\n'
    b'{"sequence":2,"state":"terminal",'
    b'"recorded_at":"2026-08-21T12:59:00Z",'
    b'"event":"attempt terminal","details":{}}\n'
)


def attempt_journal(attempt_id: int) -> AttemptJournalRef:
    """Build one exact synthetic journal reference for an attempt fixture."""
    return AttemptJournalRef(
        sha256=sha256(ATTEMPT_JOURNAL_RAW),
        bytes=len(ATTEMPT_JOURNAL_RAW),
        stored_at=git_file(f"{RUN_ROOT}/attempts/{attempt_id}/journal.jsonl"),
    )


def attempt_reference(attempt: RunAttempt) -> tuple[ResolvedAttemptRef, bytes]:
    """Serialize one attempt and return its immutable fixture reference."""
    raw = yaml_bytes(attempt)
    return (
        ResolvedAttemptRef(
            sha256=sha256(raw),
            bytes=len(raw),
            stored_at=HuggingFaceFileRef(
                repository=HF_REPOSITORY,
                commit=SNAPSHOT_COMMIT,
                path=f"{RUN_ROOT}/attempts/{attempt.attempt_id}/resolved.yaml",
                repo_type="dataset",
            ),
        ),
        raw,
    )


def loader_path(name: str) -> str:
    """Return one exact user-repository artifact-loader path."""
    return f"project/loaders/{name}.py"


def loader_ref(
    name: str,
    raw: bytes = DEFAULT_ARTIFACT_LOADER_SOURCE,
) -> ArtifactLoaderRef:
    """Return one exact user-repository artifact-loader reference."""
    return artifact_loader_ref(loader_path(name), raw)


def yaml_bytes(value: object) -> bytes:
    """Serialize one value as YAML bytes."""
    data = YAML_ADAPTER.dump_python(value, mode="json")
    data_s = yaml.safe_dump(data, sort_keys=True)
    assert isinstance(data_s, str)
    return data_s.encode("utf-8")


def sha256(raw: bytes) -> str:
    """Return the SHA-256 digest of exact bytes."""
    return hashlib.sha256(raw).hexdigest()


def git_file(path: str, *, commit: str = GIT_COMMIT) -> GitFileRef:
    """Build one immutable Git file reference."""
    return GitFileRef(
        repository=REPOSITORY,
        commit=commit,
        path=path,
    )


def artifact_pointer(path: str) -> ArtifactPointerRef:
    """Build one canonical promoted-artifact pointer reference."""
    return ArtifactPointerRef(
        repository=REPOSITORY,
        commit=GIT_COMMIT,
        path=path,
    )


def environment() -> GCEEnvironmentSpec:
    """Build the shared requested GCE environment."""
    return GCEEnvironmentSpec(
        kind="gce",
        provisioning=GCEBootImageRef(
            project="viper-project",
            name="viper-image",
            id="123456",
        ),
        machine_type="n2-standard-8",
        compute=CPUComputeSpec(kind="cpu"),
        lockfile=git_file("uv.lock"),
        python_environment=python_environment(),
    )


def reproducibility() -> ReproducibilitySpec:
    """Build the run-wide reproducibility controls."""
    return ReproducibilitySpec(
        determinism=TorchDeterminismSpec(
            deterministic_algorithms=True,
            deterministic_warn_only=False,
            cudnn_deterministic=True,
            cudnn_benchmark=False,
            cublas_workspace_config=":4096:8",
        ),
        precision=TorchPrecisionSpec(
            float32_matmul_precision="highest",
            cudnn_allow_tf32=False,
            autocast_enabled=False,
            autocast_dtype=None,
        ),
        parallelism=ParallelismSpec(
            process_count=1,
            torch_intraop_threads=1,
            torch_interop_threads=1,
            dataloader=DataLoaderConfiguration(
                workers=0,
                prefetch_factor=None,
                persistent_workers=False,
                in_order=True,
            ),
        ),
        numpy_randomness=NumPyRandomnessSpec(
            generators={"training": "PCG64"},
            capture_legacy_global=True,
        ),
    )


def execution_context(seed: int = 42) -> ExecutionContext:
    """Build the runtime context observed by one stage."""
    return ExecutionContext(
        host=GCEHostContext(
            provider="gce",
            project_id="viper-project",
            provisioning=GCEBootImageRef(
                project="viper-project",
                name="viper-image",
                id="123456",
            ),
            machine_type="n2-standard-8",
            zone="us-central1-a",
            guest_os_name="debian",
            guest_os_version="12",
            kernel_release="6.1",
        ),
        cpu=CPUContext(
            architecture="x86_64",
            model="Intel Cascade Lake",
            instruction_features=("avx2",),
        ),
        backend=CPUBackendContext(kind="cpu", device="cpu"),
        numerical_runtime=NumericalRuntimeContext(
            python_version="3.12.4",
            pytorch_version="2.7.1",
            numpy_version="2.2.6",
            blas=NativeLibraryContext(implementation="openblas", version="0.3.29"),
            lapack=NativeLibraryContext(implementation="openblas", version="0.3.29"),
            native_thread_pools=(
                NativeThreadPoolContext(
                    implementation="openblas",
                    version="0.3.29",
                    threads=1,
                ),
            ),
        ),
    )


def resolved_git(raw: bytes, path: str) -> ResolvedGitFileRef:
    """Bind exact bytes to their immutable Git location."""
    return ResolvedGitFileRef(
        sha256=sha256(raw),
        bytes=len(raw),
        stored_at=git_file(path),
    )


def resolved_pointer(path: str) -> ResolvedArtifactPointerRef:
    """Build one resolved artifact-pointer reference."""
    raw = b"pointer"
    return ResolvedArtifactPointerRef(
        sha256=sha256(raw),
        bytes=len(raw),
        stored_at=artifact_pointer(path),
    )


def snapshot(*, commit: str = SNAPSHOT_COMMIT) -> StageResultSnapshotRef:
    """Build one immutable stage-result snapshot reference."""
    return StageResultSnapshotRef(
        repository=HF_REPOSITORY,
        commit=commit,
        repo_type="dataset",
    )


def run_spec(stage_specs: list[tuple[str, object]]) -> tuple[RunSpec, dict[str, bytes]]:
    """Build a run plan and the stage-spec files it identifies."""
    documents: dict[str, bytes] = {}
    stage_refs = []

    for stage_id, spec in stage_specs:
        path = f"{RUN_ROOT}/stages/{stage_id}/spec.yaml"
        raw = yaml_bytes(spec)
        documents[path] = raw
        stage_refs.append(
            RunStageRef(
                stage_id=stage_id,
                spec=path,
                sha256=sha256(raw),
                bytes=len(raw),
            )
        )
        if isinstance(spec, TrainSpec):
            documents[str(spec.implementation.path)] = b"def fit(context):\n    pass\n"
        elif isinstance(spec, BuildSpec):
            documents[str(spec.implementation.path)] = (
                b"def build_prior(context):\n    pass\n"
            )

    run = RunSpec(
        run_id=RUN_ID,
        experiment_id="e001_strand",
        variant_id="baseline",
        replicate_id="replicate_01",
        seed=42,
        source=GitSource(repository=REPOSITORY, commit=GIT_COMMIT),
        environment=environment(),
        reproducibility=reproducibility(),
        stages=tuple(stage_refs),
        estimator=StageArtifactRef(
            stage_id="train",
            artifact_name=PARAMETERS,
        ),
    )
    return run, documents


def train_spec(*, future_prior: bool = False) -> TrainSpec:
    """Build a valid training-stage request."""
    inputs: dict[InputName, InternalInputRef] = {}
    if future_prior:
        inputs["prior"] = FutureInputRef(
            kind="future",
            producer_stage_id="build",
            producer_artifact="prior",
        )
    else:
        inputs["training_dataset"] = StoredInputRef(
            kind="stored",
            pointer=artifact_pointer("inputs/datasets/replogle/current.pointer.yaml"),
            path="inputs/datasets/replogle/dataset.h5ad",
            data_role="training",
        )

    return TrainSpec(
        implementation=stage_implementation_ref(
            "project/training/fit.py",
            b"def fit(context):\n    pass\n",
            symbol="fit",
        ),
        parameter_model=parameter_model_ref("train"),
        inputs=inputs,
        params=parameters.Train.model_validate(
            {"epochs": 10, "batch_size": 64, "learning_rate": 0.001}
        ),
        artifacts={
            PARAMETERS: SingleFileArtifactSpec(
                kind="file",
                path=(f"{RUN_ROOT}/artifacts/models/strand/parameters.safetensors"),
                loader=loader_ref("parameters"),
                data_role="training",
            ),
            RESUME_STATE: SingleFileArtifactSpec(
                kind="file",
                path=f"{RUN_ROOT}/artifacts/models/strand/resume_state.pt",
                loader=loader_ref("resume_state"),
                data_role="training",
            ),
        },
    )


def build_spec() -> BuildSpec:
    """Build a valid prior-construction request."""
    return BuildSpec(
        implementation=stage_implementation_ref(
            "domain/prior_builder.py",
            b"def build_prior(context):\n    pass\n",
            symbol="build_prior",
        ),
        parameter_model=parameter_model_ref("build"),
        inputs={
            "depmap": StoredInputRef(
                kind="stored",
                pointer=artifact_pointer("inputs/priors/depmap/current.pointer.yaml"),
                path="inputs/priors/depmap/prior.parquet",
                data_role="training",
            )
        },
        params=parameters.Build(),
        artifacts={
            "prior": SingleFileArtifactSpec(
                kind="file",
                path=f"{RUN_ROOT}/artifacts/priors/depmap/prior.pt",
                loader=loader_ref("prior"),
                data_role="training",
            )
        },
    )


def resolved_environment(lock_raw: bytes) -> ResolvedGCEEnvironment:
    """Bind the requested environment to its immutable machine image and lockfile."""
    return ResolvedGCEEnvironment(
        kind="gce",
        provisioning=GCEBootImageRef(
            project="viper-project",
            name="viper-image",
            id="123456",
        ),
        machine_type="n2-standard-8",
        compute=CPUComputeSpec(kind="cpu"),
        lockfile=resolved_git(lock_raw, "uv.lock"),
        python_environment=python_environment(),
    )


def startup_receipt(run: RunSpec) -> ProcessStartupReceipt:
    """Build the minimum valid CPU startup evidence for one test run."""
    from viper.protocol import GeneratorInitializationReceipt

    generators = [
        GeneratorInitializationReceipt(
            family="python",
            seed=run.seed,
            state_sha256="1" * 64,
        ),
        GeneratorInitializationReceipt(
            family="torch_cpu",
            seed=run.seed,
            state_sha256="2" * 64,
        ),
    ]
    generators.extend(
        GeneratorInitializationReceipt(
            family="numpy_generator",
            seed=run.seed,
            name=name,
            state_sha256="3" * 64,
        )
        for name in sorted(run.reproducibility.numpy_randomness.generators)
    )
    if run.reproducibility.numpy_randomness.capture_legacy_global:
        generators.append(
            GeneratorInitializationReceipt(
                family="numpy_legacy",
                seed=run.seed,
                state_sha256="4" * 64,
            )
        )
    return ProcessStartupReceipt(
        environment=process_environment(
            run.seed,
            run.reproducibility,
            CPUComputeSpec(),
        ),
        reproducibility=run.reproducibility,
        generators=tuple(generators),
    )


def invocation_evidence(
    run: RunSpec,
    stage_id: str,
    stage: TrainSpec | BuildSpec,
    *,
    inputs: dict[str, str],
    started_at: datetime,
    completed_at: datetime,
) -> tuple[ResolvedStageInvocationRef, bytes]:
    """Build one invocation receipt and its immutable reference."""
    binding = StageContextBinding(
        run_id=run.run_id,
        attempt_id=1,
        stage_id=stage_id,
        parameter_model=stage.parameter_model,
        parameter_digest=document_digest(stage.params),
        inputs=inputs,
        artifacts={name: artifact.path for name, artifact in stage.artifacts.items()},
        metric_ids=stage.metric_ids,
        numpy_generator_names=tuple(
            sorted(run.reproducibility.numpy_randomness.generators)
        ),
    )
    receipt = StageInvocationReceipt(
        implementation=stage.implementation,
        context=binding,
        context_digest=document_digest(binding),
        started_at=started_at,
        completed_at=completed_at,
        outcome="succeeded",
    )
    raw = yaml_bytes(receipt)
    path = f"{RUN_ROOT}/attempts/1/invocations/{stage_id}.yaml"
    reference = ResolvedStageInvocationRef(
        sha256=sha256(raw),
        bytes=len(raw),
        stored_at=HuggingFaceFileRef(
            repository=HF_REPOSITORY,
            commit=SNAPSHOT_COMMIT,
            repo_type="dataset",
            path=path,
        ),
    )
    return reference, raw


class FileVerificationTests(unittest.TestCase):
    """Verify byte identity, artifact loading, and resume records."""

    def test_artifact_loader_uses_the_consumer_materialization_path(self) -> None:
        """Verify that artifact loader uses the consumer materialization path."""
        loader_raw = (
            b"def load(path):\n"
            b"    assert path.as_posix().endswith("
            b"'/inputs/models/strand/selected.bin')\n"
            b"    return path.read_bytes()\n"
        )
        base = train_spec()
        artifacts = dict(base.artifacts)
        artifacts[PARAMETERS] = artifacts[PARAMETERS].model_copy(
            update={"loader": loader_ref("parameters", loader_raw)}
        )
        spec = base.model_copy(
            update={"metric_ids": ("training_loss",), "artifacts": artifacts}
        )
        run, _ = run_spec([("train", spec)])
        declaration = spec.artifacts[PARAMETERS]
        content = b"model parameters"
        resolved = ResolvedSingleFileArtifact(
            file=SnapshotFileRef(
                path=str(declaration.path),
                sha256=sha256(content),
                bytes=len(content),
            )
        )
        verified = VerifiedArtifact(
            artifact=resolved,
            data_role=declaration.data_role,
            files=(
                VerifiedSnapshotFile(
                    reference=resolved.file,
                    content=content,
                ),
            ),
        )
        consumer_path = "inputs/models/strand/selected.bin"

        validation = load_verified_artifact(
            run,
            declaration,
            PARAMETERS,
            verified,
            policy=POLICY,
            materialization_path=consumer_path,
            fetcher=lambda _: loader_raw,
        )

        self.assertEqual(validation.guarantee, "artifact.loadability")

    def test_artifact_loader_requires_explicit_source_trust(self) -> None:
        """Reject loader execution when the source repository is not trusted."""
        spec = train_spec()
        run, _ = run_spec([("train", spec)])
        declaration = spec.artifacts[PARAMETERS]
        content = b"model parameters"
        resolved = ResolvedSingleFileArtifact(
            file=SnapshotFileRef(
                path=str(declaration.path),
                sha256=sha256(content),
                bytes=len(content),
            )
        )
        verified = VerifiedArtifact(
            artifact=resolved,
            data_role=declaration.data_role,
            files=(
                VerifiedSnapshotFile(
                    reference=resolved.file,
                    content=content,
                ),
            ),
        )

        with self.assertRaisesRegex(VerificationError, "explicitly trusted"):
            load_verified_artifact(
                run,
                declaration,
                PARAMETERS,
                verified,
                policy=VerificationPolicy(trusted_source_repositories=frozenset()),
                fetcher=lambda _: b"def load(path): return path.read_bytes()\n",
            )

    def test_artifact_loader_rejects_same_length_source_tampering(self) -> None:
        """Reject loader bytes whose SHA-256 differs at the same byte count."""
        spec = train_spec()
        run, _ = run_spec([("train", spec)])
        declaration = spec.artifacts[PARAMETERS]
        content = b"model parameters"
        resolved = ResolvedSingleFileArtifact(
            file=SnapshotFileRef(
                path=str(declaration.path),
                sha256=sha256(content),
                bytes=len(content),
            )
        )
        verified = VerifiedArtifact(
            artifact=resolved,
            data_role=declaration.data_role,
            files=(VerifiedSnapshotFile(reference=resolved.file, content=content),),
        )
        tampered = bytearray(DEFAULT_ARTIFACT_LOADER_SOURCE)
        tampered[-2] = ord(" ")

        with self.assertRaisesRegex(VerificationError, "loader SHA-256 differs"):
            load_verified_artifact(
                run,
                declaration,
                PARAMETERS,
                verified,
                policy=POLICY,
                fetcher=lambda _: bytes(tampered),
            )

    def test_artifact_loader_failure_rejects_loadability(self) -> None:
        """Reject a verified representation that its frozen loader cannot load."""
        loader_raw = b"def load(path):\n    raise ValueError('broken')\n"
        base = train_spec()
        artifacts = dict(base.artifacts)
        artifacts[PARAMETERS] = artifacts[PARAMETERS].model_copy(
            update={"loader": loader_ref("parameters", loader_raw)}
        )
        spec = base.model_copy(update={"artifacts": artifacts})
        run, _ = run_spec([("train", spec)])
        declaration = spec.artifacts[PARAMETERS]
        content = b"model parameters"
        resolved = ResolvedSingleFileArtifact(
            file=SnapshotFileRef(
                path=str(declaration.path),
                sha256=sha256(content),
                bytes=len(content),
            )
        )
        verified = VerifiedArtifact(
            artifact=resolved,
            data_role=declaration.data_role,
            files=(VerifiedSnapshotFile(reference=resolved.file, content=content),),
        )

        with self.assertRaisesRegex(VerificationError, "artifact.loadability"):
            load_verified_artifact(
                run,
                declaration,
                PARAMETERS,
                verified,
                policy=POLICY,
                fetcher=lambda _: loader_raw,
            )

    def test_resume_state_requires_the_reserved_value_schema(self) -> None:
        """Reject a loadable resume_state value outside the reserved schema."""
        loader_raw = b"def load(path):\n    return {}\n"
        base = train_spec()
        artifacts = dict(base.artifacts)
        artifacts[RESUME_STATE] = artifacts[RESUME_STATE].model_copy(
            update={"loader": loader_ref("resume_state", loader_raw)}
        )
        spec = base.model_copy(update={"artifacts": artifacts})
        run, _ = run_spec([("train", spec)])
        declaration = spec.artifacts[RESUME_STATE]
        content = b"resume state"
        resolved = ResolvedSingleFileArtifact(
            file=SnapshotFileRef(
                path=str(declaration.path),
                sha256=sha256(content),
                bytes=len(content),
            )
        )
        verified = VerifiedArtifact(
            artifact=resolved,
            data_role=declaration.data_role,
            files=(VerifiedSnapshotFile(reference=resolved.file, content=content),),
        )

        with self.assertRaisesRegex(
            VerificationError,
            "artifact.semantic.resume_state: loaded value is invalid",
        ):
            load_verified_artifact(
                run,
                declaration,
                RESUME_STATE,
                verified,
                policy=POLICY,
                fetcher=lambda _: loader_raw,
            )

    def test_resume_state_must_match_run_dataloader(self) -> None:
        """Verify that resume state must match run dataloader."""
        spec = train_spec()
        run, _ = run_spec([("train", spec)])
        declaration = spec.artifacts[RESUME_STATE]
        content = b"resume state"

        resolved = ResolvedSingleFileArtifact(
            file=SnapshotFileRef(
                path=str(declaration.path),
                sha256=sha256(content),
                bytes=len(content),
            )
        )
        verified = VerifiedArtifact(
            artifact=resolved,
            data_role=declaration.data_role,
            files=(
                VerifiedSnapshotFile(
                    reference=resolved.file,
                    content=content,
                ),
            ),
        )

        resume_value = resume_state(
            workers=2,
            prefetch_factor=2,
        ).model_dump(mode="python")
        loader_raw = (f"def load(path):\n    return {resume_value!r}\n").encode()
        declaration = declaration.model_copy(
            update={"loader": loader_ref("resume_state", loader_raw)}
        )

        with self.assertRaisesRegex(
            VerificationError,
            "artifact.semantic.resume_state: DataLoader configuration differs",
        ):
            load_verified_artifact(
                run,
                declaration,
                RESUME_STATE,
                verified,
                policy=POLICY,
                fetcher=lambda _: loader_raw,
            )

    def test_resume_state_must_match_run_numpy_controls(self) -> None:
        """Verify that resume state must match run numpy controls."""
        spec = train_spec()
        run, _ = run_spec([("train", spec)])
        declaration = spec.artifacts[RESUME_STATE]
        content = b"resume state"
        resolved = ResolvedSingleFileArtifact(
            file=SnapshotFileRef(
                path=str(declaration.path),
                sha256=sha256(content),
                bytes=len(content),
            )
        )
        verified = VerifiedArtifact(
            artifact=resolved,
            data_role=declaration.data_role,
            files=(
                VerifiedSnapshotFile(
                    reference=resolved.file,
                    content=content,
                ),
            ),
        )
        baseline = resume_state()
        numpy_state = baseline.main_process_rng.numpy
        mismatches = (
            (
                "artifact.semantic.resume_state: NumPy generator names differ",
                numpy_state.model_copy(update={"generators": {}}),
            ),
            (
                "artifact.semantic.resume_state: legacy NumPy state differs",
                numpy_state.model_copy(update={"legacy_global": None}),
            ),
        )

        for message, mismatched_numpy in mismatches:
            with self.subTest(message=message):
                mismatched = baseline.model_copy(
                    update={
                        "main_process_rng": baseline.main_process_rng.model_copy(
                            update={"numpy": mismatched_numpy}
                        )
                    }
                )
                value = mismatched.model_dump(mode="python")
                loader_raw = (f"def load(path):\n    return {value!r}\n").encode()
                declaration = spec.artifacts[RESUME_STATE].model_copy(
                    update={"loader": loader_ref("resume_state", loader_raw)}
                )

                with self.assertRaisesRegex(VerificationError, message):
                    load_verified_artifact(
                        run,
                        declaration,
                        RESUME_STATE,
                        verified,
                        policy=POLICY,
                        fetcher=lambda _: loader_raw,
                    )

    def test_git_retrieval_supports_sha256_repositories(self) -> None:
        """Verify that git retrieval supports sha256 repositories."""
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "source"
            subprocess.run(
                ("git", "init", "--quiet", "--object-format=sha256", repository),
                check=True,
            )
            subprocess.run(
                ("git", "-C", repository, "config", "user.name", "Test Author"),
                check=True,
            )
            subprocess.run(
                (
                    "git",
                    "-C",
                    repository,
                    "config",
                    "user.email",
                    "test@example.com",
                ),
                check=True,
            )
            expected = b"sha256 repository file\n"
            (repository / "record.txt").write_bytes(expected)
            subprocess.run(
                ("git", "-C", repository, "add", "record.txt"),
                check=True,
            )
            subprocess.run(
                ("git", "-C", repository, "commit", "--quiet", "-m", "record"),
                check=True,
            )
            commit = subprocess.run(
                ("git", "-C", repository, "rev-parse", "HEAD"),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            location = GitFileRef.model_construct(
                kind="git",
                repository=repository.as_uri(),
                commit=commit,
                path="record.txt",
            )

            self.assertEqual(fetch_git_file_bytes(location), expected)

    def test_resolved_file_requires_matching_bytes(self) -> None:
        """Verify that resolved file requires matching bytes."""
        raw = b"exact bytes"
        reference = ResolvedFileRef(
            sha256=sha256(raw),
            bytes=len(raw),
            stored_at=git_file("records/value.bin"),
        )

        self.assertEqual(read_resolved_file(reference, fetcher=lambda _: raw), raw)

        with self.assertRaisesRegex(VerificationError, "byte-count mismatch"):
            read_resolved_file(
                reference.model_copy(update={"bytes": len(raw) + 1}),
                fetcher=lambda _: raw,
            )

    def test_snapshot_file_uses_snapshot_commit_and_exact_identity(self) -> None:
        """Verify that snapshot file uses snapshot commit and exact identity."""
        raw = b"snapshot bytes"
        reference = {
            "path": "artifacts/train/parameters.safetensors",
            "sha256": sha256(raw),
            "bytes": len(raw),
        }
        seen: list[HuggingFaceFileRef] = []

        def fetcher(location: object) -> bytes:
            """Return fixture bytes for one storage location."""
            self.assertIsInstance(location, HuggingFaceFileRef)
            assert isinstance(location, HuggingFaceFileRef)
            seen.append(location)
            return raw

        content = read_snapshot_file(
            snapshot(),
            SnapshotFileRef.model_validate(reference),
            fetcher=fetcher,
        )

        self.assertEqual(content, raw)
        self.assertEqual(seen[0].commit, SNAPSHOT_COMMIT)


class RunAndStageVerificationTests(unittest.TestCase):
    """Verify resolved run, stage, attempt, measurement, and log relationships."""

    def test_resolved_run_spec_is_loaded_from_its_reference(self) -> None:
        """Verify that resolved run spec is loaded from its reference."""
        spec = train_spec()
        run, _ = run_spec([("train", spec)])
        raw = yaml_bytes(run)
        run_reference = ResolvedRunSpecRef(
            sha256=sha256(raw),
            bytes=len(raw),
            stored_at=git_file(f"{RUN_ROOT}/spec.yaml"),
        )
        record = ResolvedRun.model_construct(spec=run_reference)

        self.assertEqual(
            verify_run_spec(record, fetcher=lambda _: raw),
            run,
        )

        duplicate_raw = raw + b"seed: 43\n"
        duplicate_record = record.model_copy(
            update={
                "spec": run_reference.model_copy(
                    update={
                        "sha256": sha256(duplicate_raw),
                        "bytes": len(duplicate_raw),
                    }
                )
            }
        )
        with self.assertRaisesRegex(VerificationError, "not a valid RunSpec"):
            verify_run_spec(duplicate_record, fetcher=lambda _: duplicate_raw)

    def test_resolved_run_spec_uses_the_source_repository(self) -> None:
        """Verify that resolved run spec uses the source repository."""
        spec = train_spec()
        run, _ = run_spec([("train", spec)])
        raw = yaml_bytes(run)
        location = git_file(f"{RUN_ROOT}/spec.yaml").model_copy(
            update={"repository": "https://github.com/example/other"}
        )
        record = ResolvedRun.model_construct(
            spec=ResolvedRunSpecRef(
                sha256=sha256(raw),
                bytes=len(raw),
                stored_at=location,
            )
        )

        with self.assertRaisesRegex(VerificationError, "one Git repository"):
            verify_run_spec(record, fetcher=lambda _: raw)

    def test_stage_plan_loads_named_future_artifact(self) -> None:
        """Verify that stage plan loads named future artifact."""
        build = build_spec()
        train = train_spec(future_prior=True)
        run, documents = run_spec([("build", build), ("train", train)])
        run_reference = ResolvedRunSpecRef(
            sha256="f" * 64,
            bytes=1,
            stored_at=git_file(f"{RUN_ROOT}/spec.yaml"),
        )

        loaded = verify_stage_plan(
            run,
            run_reference,
            fetcher=lambda location: documents[location.path],
        )

        self.assertEqual(set(loaded), {"build", "train"})
        self.assertIn("prior", loaded["build"].artifacts)

        outside_ref = run.stages[0].model_copy(
            update={"spec": "stages/build/spec.yaml"}
        )
        outside_run = run.model_copy(update={"stages": (outside_ref, *run.stages[1:])})
        with self.assertRaisesRegex(VerificationError, "canonical run path"):
            verify_stage_plan(
                outside_run,
                run_reference,
                fetcher=lambda location: documents[location.path],
            )

    def test_distinct_stage_snapshots_may_reuse_artifact_paths(self) -> None:
        """Verify that distinct stage snapshots may reuse artifact paths."""
        first = train_spec()
        second = train_spec()
        run, documents = run_spec([("train", first), ("train_02", second)])
        run_reference = ResolvedRunSpecRef(
            sha256="f" * 64,
            bytes=1,
            stored_at=git_file(f"{RUN_ROOT}/spec.yaml"),
        )

        loaded = verify_stage_plan(
            run,
            run_reference,
            fetcher=lambda location: documents[location.path],
        )

        self.assertEqual(set(loaded), {"train", "train_02"})

    def test_consumer_rejects_colliding_same_run_input_paths(self) -> None:
        """Verify that consumer rejects colliding same run input paths."""
        first = train_spec()
        second = train_spec()
        consumer_payload = build_spec().model_dump(mode="python")
        consumer_payload["inputs"] = {
            "first_model": {
                "kind": "future",
                "producer_stage_id": "train",
                "producer_artifact": PARAMETERS,
            },
            "second_model": {
                "kind": "future",
                "producer_stage_id": "train_02",
                "producer_artifact": PARAMETERS,
            },
        }
        consumer = BuildSpec.model_validate(consumer_payload)
        run, documents = run_spec(
            [("train", first), ("train_02", second), ("build", consumer)]
        )
        run_reference = ResolvedRunSpecRef(
            sha256="f" * 64,
            bytes=1,
            stored_at=git_file(f"{RUN_ROOT}/spec.yaml"),
        )

        with self.assertRaisesRegex(VerificationError, "future input paths"):
            verify_stage_plan(
                run,
                run_reference,
                fetcher=lambda location: documents[location.path],
            )

    def test_resolved_stage_checks_run_controls_and_snapshot_files(self) -> None:
        """Verify that resolved stage checks run controls and snapshot files."""
        spec = train_spec()
        run, _ = run_spec([("train", spec)])
        source_raw = b"def fit(context):\n    pass\n"
        lock_raw = b"lockfile"
        model_raw = b"model parameters"
        resume_raw = b"optimizer rng sampler"

        resume_value = resume_state().model_dump(mode="python")
        loader_raw = (
            "def load(path):\n"
            "    if path.name == 'resume_state.pt':\n"
            f"        return {resume_value!r}\n"
            "    return path.read_bytes()\n"
        ).encode()
        artifacts = dict(spec.artifacts)
        artifacts[PARAMETERS] = artifacts[PARAMETERS].model_copy(
            update={"loader": loader_ref("parameters", loader_raw)}
        )
        artifacts[RESUME_STATE] = artifacts[RESUME_STATE].model_copy(
            update={"loader": loader_ref("resume_state", loader_raw)}
        )
        spec = spec.model_copy(update={"artifacts": artifacts})
        run, _ = run_spec([("train", spec)])

        invocation, invocation_raw = invocation_evidence(
            run,
            "train",
            spec,
            inputs={"training_dataset": "inputs/datasets/replogle/dataset.h5ad"},
            started_at=datetime(2026, 8, 21, 12, 5, tzinfo=UTC),
            completed_at=datetime(2026, 8, 21, 12, 25, tzinfo=UTC),
        )
        resolved = ResolvedTrainSpec(
            spec=spec,
            source=resolved_git(source_raw, str(spec.implementation.path)),
            environment=resolved_environment(lock_raw),
            execution_context=execution_context(),
            startup=startup_receipt(run),
            invocation=invocation,
            command=("python", "-m", "viper.stage_worker"),
            inputs={
                "training_dataset": ResolvedStoredInputRef(
                    kind="stored",
                    pointer=resolved_pointer(
                        "inputs/datasets/replogle/current.pointer.yaml"
                    ),
                )
            },
            artifacts={
                PARAMETERS: ResolvedSingleFileArtifact(
                    kind="file",
                    file=SnapshotFileRef(
                        path=f"{RUN_ROOT}/artifacts/models/strand/parameters.safetensors",
                        sha256=sha256(model_raw),
                        bytes=len(model_raw),
                    ),
                ),
                RESUME_STATE: ResolvedSingleFileArtifact(
                    kind="file",
                    file=SnapshotFileRef(
                        path=f"{RUN_ROOT}/artifacts/models/strand/resume_state.pt",
                        sha256=sha256(resume_raw),
                        bytes=len(resume_raw),
                    ),
                ),
            },
            completed_at=datetime(2026, 8, 21, 12, 30, tzinfo=UTC),
        )
        resolved_raw = yaml_bytes(resolved)
        stage = ResolvedStageRef(
            stage_id="train",
            snapshot=snapshot(),
            resolved_spec=SnapshotFileRef(
                path=f"{RUN_ROOT}/stages/train/resolved.yaml",
                sha256=sha256(resolved_raw),
                bytes=len(resolved_raw),
            ),
        )
        attempt = RunAttempt(
            attempt_id=1,
            purpose="run",
            status="succeeded",
            started_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
            completed_at=datetime(2026, 8, 21, 13, tzinfo=UTC),
            resolved_stages=(stage,),
            invocations=(invocation,),
            journal=attempt_journal(1),
            measurement_files=(),
            log_files=(),
            failure=None,
        )
        run_raw = yaml_bytes(run)
        attempt_ref, attempt_raw = attempt_reference(attempt)
        record = ResolvedRun(
            spec=ResolvedRunSpecRef(
                sha256=sha256(run_raw),
                bytes=len(run_raw),
                stored_at=git_file(f"{RUN_ROOT}/spec.yaml"),
            ),
            status="succeeded",
            attempts=(attempt_ref,),
            successful_attempt_id=1,
            completed_at=datetime(2026, 8, 21, 13, 1, tzinfo=UTC),
        )
        documents = {
            f"{RUN_ROOT}/stages/train/resolved.yaml": resolved_raw,
            str(spec.implementation.path): source_raw,
            invocation.stored_at.path: invocation_raw,
            "uv.lock": lock_raw,
            (f"{RUN_ROOT}/artifacts/models/strand/parameters.safetensors"): model_raw,
            (f"{RUN_ROOT}/artifacts/models/strand/resume_state.pt"): resume_raw,
            "project/loaders/parameters.py": loader_raw,
            "project/loaders/resume_state.py": loader_raw,
            attempt_ref.stored_at.path: attempt_raw,
        }

        verified = verify_resolved_stages(
            record,
            run,
            {"train": spec},
            policy=POLICY,
            fetcher=lambda location: documents[location.path],
        )

        self.assertEqual(verified["train"], resolved)

        changed_precision = run.reproducibility.precision.model_copy(
            update={"float32_matmul_precision": "high"}
        )
        changed_controls = run.reproducibility.model_copy(
            update={"precision": changed_precision}
        )
        changed_resolved = resolved.model_copy(
            update={
                "startup": resolved.startup.model_copy(
                    update={"reproducibility": changed_controls}
                )
            }
        )
        changed_resolved_raw = yaml_bytes(changed_resolved)
        changed_stage = stage.model_copy(
            update={
                "resolved_spec": stage.resolved_spec.model_copy(
                    update={
                        "sha256": sha256(changed_resolved_raw),
                        "bytes": len(changed_resolved_raw),
                    }
                )
            }
        )
        changed_attempt = attempt.model_copy(
            update={"resolved_stages": (changed_stage,)}
        )
        changed_attempt_ref, changed_attempt_raw = attempt_reference(changed_attempt)
        changed_record = record.model_copy(update={"attempts": (changed_attempt_ref,)})
        changed_documents = dict(documents)
        changed_documents[f"{RUN_ROOT}/stages/train/resolved.yaml"] = (
            changed_resolved_raw
        )
        changed_documents[changed_attempt_ref.stored_at.path] = changed_attempt_raw

        with self.assertRaisesRegex(VerificationError, "startup controls differ"):
            verify_resolved_stages(
                changed_record,
                run,
                {"train": spec},
                policy=POLICY,
                fetcher=lambda location: changed_documents[location.path],
            )

    def test_attempt_measurements_and_logs_are_verified(self) -> None:
        """Verify that attempt measurements and logs are verified."""
        spec = train_spec().model_copy(update={"metric_ids": ("training_loss",)})
        run, _ = run_spec([("train", spec)])
        measured_at = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        measurement_raw = (
            '{"run_id":"01ARZ3NDEKTSV4RRFFQ69G5FAV",'
            '"attempt_id":1,"stage_id":"train",'
            '"metric_id":"training_loss","value":0.1,'
            f'"measured_at":"{measured_at.isoformat()}"}}\n'
        ).encode()
        log_raw = b"training complete\n"
        stage = ResolvedStageRef(
            stage_id="train",
            snapshot=snapshot(),
            resolved_spec=SnapshotFileRef(
                path=f"{RUN_ROOT}/stages/train/resolved.yaml",
                sha256="e" * 64,
                bytes=10,
            ),
        )
        attempt = RunAttempt(
            attempt_id=1,
            purpose="run",
            status="succeeded",
            started_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
            completed_at=datetime(2026, 8, 21, 13, tzinfo=UTC),
            resolved_stages=(stage,),
            invocations=(),
            journal=attempt_journal(1),
            measurement_files=(
                ResolvedFileRef(
                    sha256=sha256(measurement_raw),
                    bytes=len(measurement_raw),
                    stored_at=HuggingFaceFileRef(
                        repository=HF_REPOSITORY,
                        commit=SNAPSHOT_COMMIT,
                        path=(
                            f"{RUN_ROOT}/attempts/1/measurements/"
                            "train.training_loss.jsonl"
                        ),
                        repo_type="dataset",
                    ),
                ),
            ),
            log_files=(
                ResolvedFileRef(
                    sha256=sha256(log_raw),
                    bytes=len(log_raw),
                    stored_at=HuggingFaceFileRef(
                        repository=HF_REPOSITORY,
                        commit=SNAPSHOT_COMMIT,
                        path=f"{RUN_ROOT}/attempts/1/logs/train.stdout.log",
                        repo_type="dataset",
                    ),
                ),
            ),
            failure=None,
        )
        experiment = ExperimentSpec(
            experiment_id="e001_strand",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
            metrics=(metric_spec("training_loss", "training"),),
        )
        documents = {
            f"{RUN_ROOT}/attempts/1/measurements/"
            "train.training_loss.jsonl": measurement_raw,
            f"{RUN_ROOT}/attempts/1/logs/train.stdout.log": log_raw,
        }

        measurements = verify_attempt_files(
            attempt,
            run,
            experiment,
            {"train": spec},
            fetcher=lambda location: documents[location.path],
        )

        self.assertEqual(len(measurements), 1)
        self.assertEqual(measurements[0].value, 0.1)

        split_snapshot = attempt.model_copy(
            update={
                "log_files": (
                    attempt.log_files[0].model_copy(
                        update={
                            "stored_at": attempt.log_files[0].stored_at.model_copy(
                                update={"commit": "d" * 40}
                            )
                        }
                    ),
                )
            }
        )
        with self.assertRaisesRegex(VerificationError, "one immutable snapshot"):
            verify_attempt_files(
                split_snapshot,
                run,
                experiment,
                {"train": spec},
                fetcher=lambda location: documents[location.path],
            )

    def test_failed_attempt_may_retain_log_for_interrupted_stage(self) -> None:
        """Verify that failed attempt may retain log for interrupted stage."""
        spec = train_spec().model_copy(update={"metric_ids": ("training_loss",)})
        run, _ = run_spec([("train", spec)])
        log_raw = b"training failed\n"
        attempt = RunAttempt(
            attempt_id=1,
            purpose="run",
            status="failed",
            started_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
            completed_at=datetime(2026, 8, 21, 13, tzinfo=UTC),
            resolved_stages=(),
            invocations=(),
            journal=attempt_journal(1),
            measurement_files=(),
            log_files=(
                ResolvedFileRef(
                    sha256=sha256(log_raw),
                    bytes=len(log_raw),
                    stored_at=HuggingFaceFileRef(
                        repository=HF_REPOSITORY,
                        commit=SNAPSHOT_COMMIT,
                        path=f"{RUN_ROOT}/attempts/1/logs/train.stderr.log",
                        repo_type="dataset",
                    ),
                ),
            ),
            failure=AttemptFailure(
                code="execution_failed",
                stage_id="train",
                message="training process exited with status 1",
                occurred_at=datetime(2026, 8, 21, 12, 30, tzinfo=UTC),
            ),
        )
        experiment = ExperimentSpec(
            experiment_id="e001_strand",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
            metrics=(metric_spec("training_loss", "training"),),
        )

        measurements = verify_attempt_files(
            attempt,
            run,
            experiment,
            {"train": spec},
            fetcher=lambda _: log_raw,
        )

        self.assertEqual(measurements, ())


class RunPlanRelationshipTests(unittest.TestCase):
    """Verify relationships among experiments, variants, stages, and benchmarks."""

    def test_training_accepts_validation_inputs_and_preserves_the_role(self) -> None:
        """Allow validation-guided training when every output stays validation."""
        train = train_spec()
        training_dataset = train.inputs["training_dataset"]
        if not isinstance(training_dataset, StoredInputRef):
            self.fail("training_dataset must be a stored input")
        train = train.model_copy(
            update={
                "inputs": {
                    "training_dataset": training_dataset,
                    "validation_dataset": StoredInputRef(
                        kind="stored",
                        pointer=artifact_pointer(
                            "inputs/datasets/replogle_validation/current.pointer.yaml"
                        ),
                        path=("inputs/datasets/replogle_validation/dataset.h5ad"),
                        data_role="validation",
                    ),
                },
                "artifacts": {
                    name: artifact.model_copy(update={"data_role": "validation"})
                    for name, artifact in train.artifacts.items()
                },
            }
        )
        run, _ = run_spec([("train", train)])
        experiment = ExperimentSpec(
            experiment_id="e001_strand",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
            metrics=(),
        )
        variant = VariantSpec(
            experiment_id="e001_strand",
            variant_id="baseline",
            levels={},
            stage_params=(
                TrainVariantStageParams(
                    kind="train", stage_id="train", params=train.params
                ),
            ),
        )

        verify_run_plan_relationships(
            run,
            experiment,
            variant,
            None,
            {"train": train},
        )

    def test_training_rejects_evaluation_inputs(self) -> None:
        """Reject evaluation data supplied to a training stage."""
        train = train_spec()
        training_dataset = train.inputs["training_dataset"]
        if not isinstance(training_dataset, StoredInputRef):
            self.fail("training_dataset must be a stored input")
        train = train.model_copy(
            update={
                "inputs": {
                    "training_dataset": training_dataset.model_copy(
                        update={"data_role": "evaluation"}
                    )
                }
            }
        )
        run, _ = run_spec([("train", train)])
        experiment = ExperimentSpec(
            experiment_id="e001_strand",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
            metrics=(),
        )
        variant = VariantSpec(
            experiment_id="e001_strand",
            variant_id="baseline",
            levels={},
            stage_params=(
                TrainVariantStageParams(
                    kind="train", stage_id="train", params=train.params
                ),
            ),
        )

        with self.assertRaisesRegex(VerificationError, "cannot consume evaluation"):
            verify_run_plan_relationships(
                run,
                experiment,
                variant,
                None,
                {"train": train},
            )

    def test_training_inherits_a_future_artifact_data_role(self) -> None:
        """Reject a restricted future artifact supplied to a training stage."""
        build = build_spec()
        prior = build.artifacts["prior"]
        build = build.model_copy(
            update={
                "artifacts": {
                    "prior": prior.model_copy(update={"data_role": "evaluation"})
                }
            }
        )
        train = train_spec(future_prior=True)
        run, _ = run_spec([("build", build), ("train", train)])
        experiment = ExperimentSpec(
            experiment_id="e001_strand",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
            metrics=(),
        )
        variant = VariantSpec(
            experiment_id="e001_strand",
            variant_id="baseline",
            levels={},
            stage_params=(
                BuildVariantStageParams(
                    kind="build", stage_id="build", params=build.params
                ),
                TrainVariantStageParams(
                    kind="train", stage_id="train", params=train.params
                ),
            ),
        )

        with self.assertRaisesRegex(VerificationError, "cannot consume evaluation"):
            verify_run_plan_relationships(
                run,
                experiment,
                variant,
                None,
                {"build": build, "train": train},
            )

    def test_artifact_role_cannot_downgrade_an_input_role(self) -> None:
        """Reject an output whose role is weaker than one of its inputs."""
        build = build_spec()
        depmap = build.inputs["depmap"]
        if not isinstance(depmap, StoredInputRef):
            self.fail("depmap must be a stored input")
        build = build.model_copy(
            update={
                "inputs": {
                    "depmap": depmap.model_copy(update={"data_role": "evaluation"})
                }
            }
        )
        train = train_spec(future_prior=True)
        run, _ = run_spec([("build", build), ("train", train)])
        experiment = ExperimentSpec(
            experiment_id="e001_strand",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
            metrics=(),
        )
        variant = VariantSpec(
            experiment_id="e001_strand",
            variant_id="baseline",
            levels={},
            stage_params=(
                BuildVariantStageParams(
                    kind="build", stage_id="build", params=build.params
                ),
                TrainVariantStageParams(
                    kind="train", stage_id="train", params=train.params
                ),
            ),
        )

        with self.assertRaisesRegex(VerificationError, "less restricted"):
            verify_run_plan_relationships(
                run,
                experiment,
                variant,
                None,
                {"build": build, "train": train},
            )

    def test_variant_parameters_match_the_loaded_training_stage(self) -> None:
        """Verify that variant parameters match the loaded training stage."""
        train = train_spec()
        run, _ = run_spec([("train", train)])
        experiment = ExperimentSpec(
            experiment_id="e001_strand",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
            metrics=(metric_spec("pearson_correlation", "evaluation"),),
        )
        variant = VariantSpec(
            experiment_id="e001_strand",
            variant_id="baseline",
            levels={},
            stage_params=(
                TrainVariantStageParams(
                    kind="train",
                    stage_id="train",
                    params=train.params,
                ),
            ),
        )

        verify_run_plan_relationships(
            run,
            experiment,
            variant,
            None,
            {"train": train},
        )

        mismatched_variant = variant.model_copy(
            update={
                "stage_params": (
                    variant.stage_params[0].model_copy(
                        update={
                            "params": train.params.model_copy(update={"epochs": 11})
                        }
                    ),
                )
            }
        )
        with self.assertRaisesRegex(VerificationError, "parameters do not match"):
            verify_run_plan_relationships(
                run,
                experiment,
                mismatched_variant,
                None,
                {"train": train},
            )

    def test_environment_lockfiles_belong_to_the_source_snapshot(self) -> None:
        """Bind environment lockfiles to the implementation source snapshot."""
        train = train_spec()
        run, _ = run_spec([("train", train)])
        experiment = ExperimentSpec(
            experiment_id="e001_strand",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
            metrics=(metric_spec("pearson_correlation", "evaluation"),),
        )
        variant = VariantSpec(
            experiment_id="e001_strand",
            variant_id="baseline",
            levels={},
            stage_params=(
                TrainVariantStageParams(
                    kind="train", stage_id="train", params=train.params
                ),
            ),
        )

        wrong_lockfile = run.model_copy(
            update={
                "environment": run.environment.model_copy(
                    update={
                        "lockfile": run.environment.lockfile.model_copy(
                            update={"commit": "d" * 40}
                        )
                    }
                )
            }
        )
        with self.assertRaisesRegex(VerificationError, "source snapshot"):
            verify_run_plan_relationships(
                wrong_lockfile,
                experiment,
                variant,
                None,
                {"train": train},
            )

    def test_stored_pointer_may_precede_the_source_snapshot(self) -> None:
        """Select a promoted pointer from its own earlier immutable commit."""
        train = train_spec()
        run, _ = run_spec([("train", train)])
        experiment = ExperimentSpec(
            experiment_id="e001_strand",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
            metrics=(metric_spec("pearson_correlation", "evaluation"),),
        )
        variant = VariantSpec(
            experiment_id="e001_strand",
            variant_id="baseline",
            levels={},
            stage_params=(
                TrainVariantStageParams(
                    kind="train",
                    stage_id="train",
                    params=train.params,
                ),
            ),
        )
        input_ref = train.inputs["training_dataset"]
        if not isinstance(input_ref, StoredInputRef):
            self.fail("training_dataset must be a stored input")
        earlier_input = input_ref.model_copy(
            update={
                "pointer": input_ref.pointer.model_copy(update={"commit": "d" * 40})
            }
        )
        selected_train = train.model_copy(
            update={"inputs": {"training_dataset": earlier_input}}
        )

        verify_run_plan_relationships(
            run,
            experiment,
            variant,
            None,
            {"train": selected_train},
        )

    def test_benchmark_matches_evaluation_inputs_splits_and_metrics(self) -> None:
        """Verify that benchmark matches evaluation inputs splits and metrics."""
        train = train_spec()
        evaluation = EvaluateSpec(
            implementation=stage_implementation_ref(
                "analysis/predict.py",
                b"def predict(context):\n    pass\n",
                symbol="predict",
            ),
            parameter_model=parameter_model_ref("evaluate"),
            evaluation_id="replogle_predictions",
            metric_ids=("pearson_correlation",),
            split_inputs=("perturbation_split",),
            inputs={
                "parameters": FutureInputRef(
                    kind="future",
                    producer_stage_id="train",
                    producer_artifact=PARAMETERS,
                ),
                "evaluation_dataset": StoredInputRef(
                    kind="stored",
                    pointer=artifact_pointer(
                        "inputs/datasets/replogle_test/current.pointer.yaml"
                    ),
                    path="inputs/datasets/replogle_test/dataset.h5ad",
                    data_role="benchmark",
                ),
                "perturbation_split": StoredInputRef(
                    kind="stored",
                    pointer=artifact_pointer(
                        "inputs/benchmarks/replogle/test_split.pointer.yaml"
                    ),
                    path="inputs/benchmarks/replogle/test_split.json",
                    data_role="benchmark",
                ),
            },
            params=parameters.Evaluate(),
            artifacts={
                "predictions": SingleFileArtifactSpec(
                    kind="file",
                    path=(
                        f"{RUN_ROOT}/artifacts/evaluations/"
                        "replogle_predictions/predictions.json"
                    ),
                    loader=loader_ref("json_file"),
                    data_role="benchmark",
                )
            },
        )

        run, _ = run_spec([("train", train), ("evaluate", evaluation)])
        run = run.model_copy(update={"benchmark_id": "replogle_strict"})
        experiment = ExperimentSpec(
            experiment_id="e001_strand",
            factors=(),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
            metrics=(
                metric_spec(
                    "pearson_correlation",
                    "evaluation",
                    required_data_role="benchmark",
                ),
            ),
        )
        variant = VariantSpec(
            experiment_id="e001_strand",
            variant_id="baseline",
            levels={},
            stage_params=(
                TrainVariantStageParams(
                    kind="train", stage_id="train", params=train.params
                ),
                EvaluateVariantStageParams(
                    kind="evaluate", stage_id="evaluate", params=evaluation.params
                ),
            ),
        )
        benchmark = BenchmarkSpec(
            benchmark_id="replogle_strict",
            evaluation_id="replogle_predictions",
            evaluation_dataset=artifact_pointer(
                "inputs/datasets/replogle_test/current.pointer.yaml"
            ),
            splits={
                "perturbation_split": artifact_pointer(
                    "inputs/benchmarks/replogle/test_split.pointer.yaml"
                )
            },
            metrics=(
                MetricCriterion(
                    metric_id="pearson_correlation",
                    comparison="ge",
                    threshold=0.8,
                ),
            ),
        )

        verify_run_plan_relationships(
            run,
            experiment,
            variant,
            benchmark,
            {"train": train, "evaluate": evaluation},
        )

        selected_metric = experiment.metrics[0]
        missing_dependency = selected_metric.dependencies[0].model_copy(
            update={"name": "missing_predictions"}
        )
        invalid_experiment = experiment.model_copy(
            update={
                "metrics": (
                    selected_metric.model_copy(
                        update={"dependencies": (missing_dependency,)}
                    ),
                )
            }
        )
        with self.assertRaisesRegex(VerificationError, "selects absent artifact"):
            verify_run_plan_relationships(
                run,
                invalid_experiment,
                variant,
                benchmark,
                {"train": train, "evaluate": evaluation},
            )

        ordinary_payload = evaluation.model_dump(mode="python")
        ordinary_payload["inputs"]["evaluation_dataset"]["data_role"] = "evaluation"
        ordinary_payload["inputs"]["perturbation_split"]["data_role"] = "evaluation"
        ordinary_payload["artifacts"]["predictions"]["data_role"] = "evaluation"
        ordinary_evaluation = EvaluateSpec.model_validate(ordinary_payload)
        with self.assertRaisesRegex(VerificationError, "must use 'benchmark'"):
            verify_run_plan_relationships(
                run,
                experiment,
                variant,
                benchmark,
                {"train": train, "evaluate": ordinary_evaluation},
            )

        wrong_benchmark = benchmark.model_copy(
            update={"evaluation_id": "other_evaluation"}
        )
        with self.assertRaisesRegex(VerificationError, "evaluation ID"):
            verify_run_plan_relationships(
                run,
                experiment,
                variant,
                wrong_benchmark,
                {"train": train, "evaluate": evaluation},
            )

        other_train = train_spec()
        wrong_evaluation_payload = evaluation.model_dump(mode="python")
        wrong_evaluation_payload["inputs"]["parameters"]["producer_stage_id"] = (
            "other_train"
        )
        wrong_evaluation = EvaluateSpec.model_validate(wrong_evaluation_payload)
        wrong_run, _ = run_spec(
            [
                ("train", train),
                ("other_train", other_train),
                ("evaluate", wrong_evaluation),
            ]
        )
        wrong_run = wrong_run.model_copy(update={"benchmark_id": "replogle_strict"})
        wrong_variant_payload = variant.model_dump(mode="python")
        wrong_variant_payload["stage_params"] = (
            *wrong_variant_payload["stage_params"],
            {
                "kind": "train",
                "stage_id": "other_train",
                "params": other_train.params,
            },
        )
        wrong_variant = VariantSpec.model_validate(wrong_variant_payload)
        with self.assertRaisesRegex(VerificationError, "run estimator"):
            verify_run_plan_relationships(
                wrong_run,
                experiment,
                wrong_variant,
                benchmark,
                {
                    "train": train,
                    "other_train": other_train,
                    "evaluate": wrong_evaluation,
                },
            )


class ParameterModelReferenceTests(unittest.TestCase):
    """Verify project parameter classes against the run source snapshot."""

    def test_parameter_model_matches_frozen_source(self) -> None:
        """Accept the exact class file selected by an internal stage."""
        stage = train_spec()
        run, _ = run_spec([("train", stage)])

        verify_parameter_model_references(
            run,
            {"train": stage},
            fetcher=lambda _: parameter_model_source("train"),
        )

    def test_parameter_model_rejects_changed_source_bytes(self) -> None:
        """Reject source bytes that differ from the frozen class identity."""
        stage = train_spec()
        run, _ = run_spec([("train", stage)])

        with self.assertRaisesRegex(VerificationError, "source verification"):
            verify_parameter_model_references(
                run,
                {"train": stage},
                fetcher=lambda _: b'class Changed:\n    """Changed bytes."""\n',
            )


class StoredInputSelectionTests(unittest.TestCase):
    """Verify promoted checkpoint selections and their producer lineage."""

    def test_stored_checkpoint_pair_selects_one_run_and_stage(self) -> None:
        """Verify that stored checkpoint pair selects one run and stage."""
        payload = train_spec().model_dump(mode="python")
        payload["inputs"].update(
            {
                "parameters": {
                    "kind": "stored",
                    "data_role": "training",
                    "pointer": artifact_pointer(
                        "inputs/models/toy/parameters.pointer.yaml"
                    ),
                    "path": "inputs/models/toy/parameters.bin",
                },
                "resume_state": {
                    "kind": "stored",
                    "data_role": "training",
                    "pointer": artifact_pointer(
                        "inputs/models/toy/resume_state.pointer.yaml"
                    ),
                    "path": "inputs/models/toy/resume_state.bin",
                },
            }
        )
        spec = TrainSpec.model_validate(payload)

        run_reference = ResolvedRunRef(
            sha256="3" * 64,
            bytes=100,
            stored_at=HuggingFaceFileRef(
                repository=HF_REPOSITORY,
                commit="4" * 40,
                path=f"{RUN_ROOT}/resolved.yaml",
                repo_type="dataset",
            ),
        )
        model_pointer = ArtifactPointer(
            run=run_reference,
            artifact=StageArtifactRef(stage_id="train", artifact_name=PARAMETERS),
        )
        state_pointer = ArtifactPointer(
            run=run_reference,
            artifact=StageArtifactRef(stage_id="train", artifact_name=RESUME_STATE),
        )

        verify_stored_input_selections(
            "train_resume",
            spec,
            {
                "parameters": model_pointer,
                "resume_state": state_pointer,
            },
        )

        other_run = run_reference.model_copy(
            update={
                "stored_at": run_reference.stored_at.model_copy(
                    update={"commit": "5" * 40}
                )
            }
        )
        with self.assertRaisesRegex(VerificationError, "one resolved run"):
            verify_stored_input_selections(
                "train_resume",
                spec,
                {
                    "parameters": model_pointer,
                    "resume_state": state_pointer.model_copy(update={"run": other_run}),
                },
            )


class FutureInputVerificationTests(unittest.TestCase):
    """Verify same-run artifact selections from completed producer stages."""

    def test_future_input_selects_named_artifact_from_recorded_producer(self) -> None:
        """Verify that future input selects named artifact from recorded producer."""
        build = build_spec()
        train = train_spec(future_prior=True)
        run, _ = run_spec([("build", build), ("train", train)])
        lock_raw = b"lockfile"
        prior_raw = b"prior tensor"
        build_source_raw = b"def build_prior(context):\n    pass\n"
        train_source_raw = b"def fit(context):\n    pass\n"

        producer_stage = ResolvedStageRef(
            stage_id="build",
            snapshot=snapshot(),
            resolved_spec=SnapshotFileRef(
                path=f"{RUN_ROOT}/stages/build/resolved.yaml",
                sha256="e" * 64,
                bytes=100,
            ),
        )
        consumer_stage = ResolvedStageRef(
            stage_id="train",
            snapshot=snapshot(commit="d" * 40),
            resolved_spec=SnapshotFileRef(
                path=f"{RUN_ROOT}/stages/train/resolved.yaml",
                sha256="f" * 64,
                bytes=100,
            ),
        )

        build_invocation, build_invocation_raw = invocation_evidence(
            run,
            "build",
            build,
            inputs={"depmap": "inputs/priors/depmap/prior.parquet"},
            started_at=datetime(2026, 8, 21, 12, 5, tzinfo=UTC),
            completed_at=datetime(2026, 8, 21, 12, 15, tzinfo=UTC),
        )
        train_invocation, train_invocation_raw = invocation_evidence(
            run,
            "train",
            train,
            inputs={"prior": f"{RUN_ROOT}/artifacts/priors/depmap/prior.pt"},
            started_at=datetime(2026, 8, 21, 12, 25, tzinfo=UTC),
            completed_at=datetime(2026, 8, 21, 12, 35, tzinfo=UTC),
        )
        resolved_build = ResolvedBuildSpec(
            spec=build,
            source=resolved_git(
                build_source_raw,
                str(build.implementation.path),
            ),
            environment=resolved_environment(lock_raw),
            execution_context=execution_context(),
            startup=startup_receipt(run),
            invocation=build_invocation,
            command=("python", "-m", "viper.stage_worker"),
            inputs={
                "depmap": ResolvedStoredInputRef(
                    kind="stored",
                    pointer=resolved_pointer(
                        "inputs/priors/depmap/current.pointer.yaml"
                    ),
                )
            },
            artifacts={
                "prior": ResolvedSingleFileArtifact(
                    kind="file",
                    file=SnapshotFileRef(
                        path=f"{RUN_ROOT}/artifacts/priors/depmap/prior.pt",
                        sha256=sha256(prior_raw),
                        bytes=len(prior_raw),
                    ),
                )
            },
            completed_at=datetime(2026, 8, 21, 12, 20, tzinfo=UTC),
        )
        resolved_train = ResolvedTrainSpec(
            spec=train,
            source=resolved_git(
                train_source_raw,
                str(train.implementation.path),
            ),
            environment=resolved_environment(lock_raw),
            execution_context=execution_context(),
            startup=startup_receipt(run),
            invocation=train_invocation,
            command=("python", "-m", "viper.stage_worker"),
            inputs={
                "prior": ResolvedFutureInputRef(producer=producer_stage),
            },
            artifacts={
                PARAMETERS: ResolvedSingleFileArtifact(
                    kind="file",
                    file=SnapshotFileRef(
                        path=f"{RUN_ROOT}/artifacts/models/strand/parameters.safetensors",
                        sha256="1" * 64,
                        bytes=1,
                    ),
                ),
                RESUME_STATE: ResolvedSingleFileArtifact(
                    kind="file",
                    file=SnapshotFileRef(
                        path=f"{RUN_ROOT}/artifacts/models/strand/resume_state.pt",
                        sha256="2" * 64,
                        bytes=1,
                    ),
                ),
            },
            completed_at=datetime(2026, 8, 21, 12, 40, tzinfo=UTC),
        )
        attempt = RunAttempt(
            attempt_id=1,
            purpose="run",
            status="succeeded",
            started_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
            completed_at=datetime(2026, 8, 21, 13, tzinfo=UTC),
            resolved_stages=(producer_stage, consumer_stage),
            invocations=(build_invocation, train_invocation),
            journal=attempt_journal(1),
            measurement_files=(),
            log_files=(),
            failure=None,
        )
        run_raw = yaml_bytes(run)
        attempt_ref, attempt_raw = attempt_reference(attempt)
        record = ResolvedRun(
            spec=ResolvedRunSpecRef(
                sha256=sha256(run_raw),
                bytes=len(run_raw),
                stored_at=git_file(f"{RUN_ROOT}/spec.yaml"),
            ),
            status="succeeded",
            attempts=(attempt_ref,),
            successful_attempt_id=1,
            completed_at=datetime(2026, 8, 21, 13, 1, tzinfo=UTC),
        )

        verified = verify_future_inputs(
            record,
            run,
            {"build": resolved_build, "train": resolved_train},
            fetcher=lambda location: {
                f"{RUN_ROOT}/artifacts/priors/depmap/prior.pt": prior_raw,
                attempt_ref.stored_at.path: attempt_raw,
            }[location.path],
        )

        self.assertEqual(
            verified["train"]["prior"].files[0].content,
            prior_raw,
        )

        failed_attempt = attempt.model_copy(
            update={
                "status": "failed",
                "failure": AttemptFailure(
                    code="execution_failed",
                    stage_id=None,
                    message="later stage failed",
                    occurred_at=datetime(2026, 8, 21, 12, 59, tzinfo=UTC),
                ),
            }
        )
        failed_verified = verify_attempt_future_inputs(
            failed_attempt,
            run,
            {"build": resolved_build, "train": resolved_train},
            fetcher=lambda location: {
                f"{RUN_ROOT}/artifacts/priors/depmap/prior.pt": prior_raw
            }[location.path],
        )
        self.assertEqual(
            failed_verified["train"]["prior"].files[0].content,
            prior_raw,
        )

        wrong_producer = producer_stage.model_copy(update={"stage_id": "other"})
        mismatched_train = resolved_train.model_copy(
            update={
                "inputs": {
                    "prior": ResolvedFutureInputRef(producer=wrong_producer),
                }
            }
        )
        with self.assertRaisesRegex(VerificationError, "completed producer"):
            verify_future_inputs(
                record,
                run,
                {"build": resolved_build, "train": mismatched_train},
                fetcher=lambda location: {
                    f"{RUN_ROOT}/artifacts/priors/depmap/prior.pt": prior_raw,
                    attempt_ref.stored_at.path: attempt_raw,
                }[location.path],
            )


if __name__ == "__main__":
    unittest.main()
