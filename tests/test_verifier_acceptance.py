"""End-to-end tests for complete VIPER provenance chains.

The fixtures publish run plans, stage results, artifacts, measurements, and
resolved runs to an in-memory document store. The tests then exercise the
public verifier against valid chains and deliberately broken relationships.
"""

from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

import torch
import yaml
from pydantic import HttpUrl, TypeAdapter

from tests.fixtures import (
    builtin_http_transport,
    http_policy,
    http_request,
    metric_source,
    metric_spec,
    parameter_model_ref,
    parameter_model_source,
    python_environment,
    resume_state,
    stage_implementation_ref,
    verification_policy,
)
from viper import parameters
from viper.paths import retrieval_body_path
from viper.protocol import (
    PARAMETERS,
    PREDICTIONS,
    RESUME_STATE,
    ArtifactComparisonReceipt,
    ArtifactLoaderRef,
    ArtifactPointer,
    ArtifactPointerRef,
    AttemptFailure,
    AttemptJournalRef,
    BaseSpec,
    BenchmarkResult,
    BenchmarkSpec,
    BuildSpec,
    BuildVariantStageParams,
    BundleArtifactSpec,
    CPUBackendContext,
    CPUComputeSpec,
    CPUContext,
    DataLoaderConfiguration,
    DataRole,
    DownloadSpec,
    DownloadVariantStageParams,
    EvaluateSpec,
    EvaluateVariantStageParams,
    ExecutionContext,
    ExperimentSpec,
    FutureInputRef,
    GCEBootImageRef,
    GCEEnvironmentSpec,
    GCEHostContext,
    GeneratorInitializationReceipt,
    GitFileRef,
    GitSource,
    HttpRetrievalContextBinding,
    HuggingFaceFileRef,
    LocalFileRef,
    LocalStageResultSnapshotRef,
    Measurement,
    MetricCriterion,
    MetricCriterionReceipt,
    MetricExecutionReceipt,
    MetricSpec,
    MetricVerificationReceipt,
    NativeLibraryContext,
    NativeThreadPoolContext,
    NumericalRuntimeContext,
    NumPyRandomnessSpec,
    ObservedHttpResponse,
    ParallelismSpec,
    ParameterizedStageSpec,
    ProcessStartupReceipt,
    ReplicateSpec,
    ReproducibilitySpec,
    ResolvedArtifactPointerRef,
    ResolvedAttemptRef,
    ResolvedBenchmarkSpecRef,
    ResolvedBuildSpec,
    ResolvedBundleArtifact,
    ResolvedBundleMember,
    ResolvedDownloadSpec,
    ResolvedEvaluateSpec,
    ResolvedFileRef,
    ResolvedFutureInputRef,
    ResolvedGCEEnvironment,
    ResolvedGitFileRef,
    ResolvedHttpRetrieval,
    ResolvedHttpTransport,
    ResolvedMetricDependency,
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
    StorageModel,
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
    verify_benchmark_result,
    verify_promoted_artifact,
    verify_run_result,
)

SOURCE_REPOSITORY = HttpUrl("https://github.com/example/viper-project")
ARTIFACT_REPOSITORY = "example/viper-runs"
PRODUCER_SOURCE_COMMIT = "1" * 40
PRODUCER_PLAN_COMMIT = "2" * 40
PRODUCER_RESULT_COMMIT = "3" * 40
MAIN_SOURCE_COMMIT = "4" * 40
MAIN_PLAN_COMMIT = "5" * 40
MAIN_FILES_COMMIT = "6" * 40
YAML_ADAPTER = TypeAdapter(Any)
POLICY = verification_policy(SOURCE_REPOSITORY)
DOWNLOAD_SOURCE = b"def download(context):\n    pass\n"
BUILD_SOURCE = b"def build_prior(context):\n    pass\n"
TRAIN_SOURCE = b"def fit(context):\n    pass\n"
EVALUATE_SOURCE = b"def predict(context):\n    pass\n"


def loader_path(name: str) -> str:
    """Return one exact user-repository artifact-loader path."""
    return f"project/loaders/{name}.py"


def loader_source(loader_id: str, *, bundle: bool = False) -> bytes:
    """Return the exact source bytes for one simulated artifact loader."""
    if loader_id == "resume_state":
        return (
            b"from viper.resume "
            b"import load_resume_state\n\n"
            b"def load(path):\n"
            b"    return load_resume_state(path)\n"
        )
    if bundle:
        return (
            b"def load(path):\n"
            b"    return tuple(p.read_bytes() for p in sorted(path.rglob('*')) "
            b"if p.is_file())\n"
        )
    return b"def load(path):\n    return path.read_bytes()\n"


def loader_ref(loader_id: str, *, bundle: bool = False) -> ArtifactLoaderRef:
    """Identify one simulated loader by its exact source bytes."""
    raw = loader_source(loader_id, bundle=bundle)
    return ArtifactLoaderRef(
        path=loader_path(loader_id),
        symbol="load",
        sha256=sha256(raw),
        bytes=len(raw),
    )


def yaml_bytes(value: object) -> bytes:
    """Serialize one protocol record as deterministic YAML bytes."""
    data = YAML_ADAPTER.dump_python(value, mode="json")
    data_s = yaml.safe_dump(data, sort_keys=True)
    assert isinstance(data_s, str)
    return data_s.encode("utf-8")


def resume_state_bytes() -> bytes:
    """Serialize one valid training resume-state artifact."""
    stream = BytesIO()
    torch.save(
        resume_state().model_dump(mode="python"),
        stream,
    )
    return stream.getvalue()


def sha256(raw: bytes) -> str:
    """Return the SHA-256 identity of stored bytes."""
    return hashlib.sha256(raw).hexdigest()


class DocumentStore:
    """Store immutable test documents by their complete storage identity."""

    def __init__(self) -> None:
        """Initialize an empty in-memory document store."""
        self.documents: dict[tuple[str, str, str, str, str], bytes] = {}

    @staticmethod
    def key(location: StorageModel) -> tuple[str, str, str, str, str]:
        """Return the immutable storage identity used as the document key."""
        if isinstance(location, LocalFileRef):
            return (
                location.kind,
                str(location.store),
                location.commit,
                str(location.path),
                "",
            )
        repo_type = getattr(location, "repo_type", "")
        return (
            location.kind,
            str(location.repository),
            location.commit,
            str(location.path),
            repo_type,
        )

    def put(self, location: StorageModel, raw: bytes) -> None:
        """Store exact bytes at one immutable location."""
        self.documents[self.key(location)] = raw

    def fetch(self, location: StorageModel) -> bytes:
        """Retrieve exact bytes from one immutable location."""
        return self.documents[self.key(location)]

    def list_snapshot_files(
        self,
        snapshot: StageResultSnapshotRef | LocalStageResultSnapshotRef,
    ) -> tuple[str, ...]:
        """List every file stored in one simulated immutable snapshot."""
        if isinstance(snapshot, LocalStageResultSnapshotRef):
            prefix = (snapshot.kind, str(snapshot.store), snapshot.commit)
        else:
            prefix = (
                snapshot.kind,
                str(snapshot.repository),
                snapshot.commit,
            )
        return tuple(sorted(key[3] for key in self.documents if key[:3] == prefix))


def git_file(commit: str, path: str) -> GitFileRef:
    """Build one source file reference at a selected commit."""
    return GitFileRef(
        repository=SOURCE_REPOSITORY,
        commit=commit,
        path=path,
    )


def hf_file(commit: str, path: str) -> HuggingFaceFileRef:
    """Build one immutable Hugging Face file reference."""
    return HuggingFaceFileRef(
        repository=ARTIFACT_REPOSITORY,
        commit=commit,
        path=path,
        repo_type="dataset",
    )


def snapshot(commit: str) -> StageResultSnapshotRef:
    """Build one immutable stage-result snapshot reference."""
    return StageResultSnapshotRef(
        repository=ARTIFACT_REPOSITORY,
        commit=commit,
        repo_type="dataset",
    )


def environment(source_commit: str) -> GCEEnvironmentSpec:
    """Build the shared requested execution environment."""
    return GCEEnvironmentSpec(
        kind="gce",
        provisioning=GCEBootImageRef(
            project="viper-project",
            name="viper-image",
            id="123456789",
        ),
        machine_type="n2-standard-8",
        compute=CPUComputeSpec(kind="cpu"),
        lockfile=git_file(source_commit, "environment.yml"),
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
            generators={"training": "PCG64"}, capture_legacy_global=True
        ),
    )


def execution_context() -> ExecutionContext:
    """Build the runtime context observed by one stage."""
    return ExecutionContext(
        host=GCEHostContext(
            provider="gce",
            project_id="viper-project",
            provisioning=GCEBootImageRef(
                project="viper-project",
                name="viper-image",
                id="123456789",
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
            python_version="3.14.0",
            pytorch_version="2.8.0",
            numpy_version="2.3.0",
            blas=NativeLibraryContext(implementation="openblas", version="0.3.30"),
            lapack=NativeLibraryContext(implementation="openblas", version="0.3.30"),
            native_thread_pools=(
                NativeThreadPoolContext(
                    implementation="openblas",
                    version="0.3.30",
                    threads=1,
                ),
            ),
        ),
    )


def startup_receipt(run: RunSpec) -> ProcessStartupReceipt:
    """Build valid CPU startup evidence for one acceptance-stage execution."""
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


def publish_metric_verification(
    store: DocumentStore,
    *,
    run: RunSpec,
    attempt_id: int,
    stage_id: str,
    metric: MetricSpec,
    measurement_raw: bytes,
    stage_completed_at: datetime,
    dependency_files: tuple[ResolvedFileRef, ...],
    commit: str,
) -> ResolvedFileRef:
    """Publish one complete synthetic metric-verification receipt."""
    measurement = Measurement.model_validate_json(measurement_raw)
    assert metric.comparator is not None
    dependencies = tuple(
        ResolvedMetricDependency(
            dependency=dependency,
            files=dependency_files,
        )
        for dependency in metric.dependencies
    )
    production = MetricExecutionReceipt(
        run_id=run.run_id,
        attempt_id=attempt_id,
        metric_id=metric.metric_id,
        stage_id=stage_id,
        purpose="measurement",
        implementation=metric.implementation,
        params=metric.params,
        dependencies=dependencies,
        startup=startup_receipt(run),
        execution_context=execution_context(),
        python_environment=python_environment(),
        value=measurement.value,
        started_at=stage_completed_at + timedelta(seconds=10),
        completed_at=stage_completed_at + timedelta(seconds=20),
    )
    recomputation = production.model_copy(
        update={
            "purpose": "verification",
            "started_at": measurement.measured_at + timedelta(seconds=10),
            "completed_at": measurement.measured_at + timedelta(seconds=20),
        }
    )
    receipt = MetricVerificationReceipt(
        metric_id=metric.metric_id,
        stage_id=stage_id,
        measurement=measurement,
        production=production,
        recomputation=recomputation,
        comparator=metric.comparator,
        passed=True,
        completed_at=measurement.measured_at + timedelta(seconds=30),
    )
    path = (
        f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}/"
        f"attempts/{attempt_id}/metric_verification/"
        f"{stage_id}.{metric.metric_id}.yaml"
    )
    raw = yaml_bytes(receipt)
    location = hf_file(commit, path)
    store.put(location, raw)
    return ResolvedFileRef(
        sha256=sha256(raw),
        bytes=len(raw),
        stored_at=location,
    )


def publish_invocation(
    store: DocumentStore,
    *,
    run: RunSpec,
    stage_id: str,
    stage: ParameterizedStageSpec,
    input_paths: dict[str, str],
    started_at: datetime,
    completed_at: datetime,
    commit: str,
    attempt_id: int = 1,
    retrievals: dict[str, ResolvedHttpRetrieval] | None = None,
) -> ResolvedStageInvocationRef:
    """Publish one successful stage-invocation receipt."""
    binding = StageContextBinding(
        run_id=run.run_id,
        attempt_id=attempt_id,
        stage_id=stage_id,
        parameter_model=stage.parameter_model,
        parameter_digest=document_digest(stage.params),
        inputs=input_paths,
        retrievals={
            name: HttpRetrievalContextBinding(
                response=retrieval.response,
                body=SnapshotFileRef(
                    path=retrieval.body.stored_at.path,
                    sha256=retrieval.body.sha256,
                    bytes=retrieval.body.bytes,
                ),
            )
            for name, retrieval in ({} if retrievals is None else retrievals).items()
        },
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
    root = f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}"
    location = hf_file(
        commit,
        f"{root}/attempts/{attempt_id}/invocations/{stage_id}.yaml",
    )
    store.put(location, raw)
    return ResolvedStageInvocationRef(
        sha256=sha256(raw),
        bytes=len(raw),
        stored_at=location,
    )


def add_source_file(
    store: DocumentStore,
    source_commit: str,
    path: str,
    raw: bytes,
) -> ResolvedGitFileRef:
    """Publish one source file into the in-memory store."""
    location = git_file(source_commit, path)
    store.put(location, raw)
    return ResolvedGitFileRef(
        sha256=sha256(raw),
        bytes=len(raw),
        stored_at=location,
    )


def publish_attempt_journal(
    store: DocumentStore,
    *,
    run_root_path: str,
    attempt_id: int,
    commit: str,
) -> AttemptJournalRef:
    """Publish one terminal attempt journal for a complete fixture chain."""
    raw = (
        b'{"sequence":1,"state":"allocated",'
        b'"recorded_at":"2026-08-20T19:00:00Z",'
        b'"event":"attempt allocated","details":{}}\n'
        b'{"sequence":2,"state":"terminal",'
        b'"recorded_at":"2026-08-20T19:01:00Z",'
        b'"event":"attempt terminal","details":{}}\n'
    )
    location = hf_file(
        commit,
        f"{run_root_path}/attempts/{attempt_id}/journal.jsonl",
    )
    store.put(location, raw)
    return AttemptJournalRef(
        sha256=sha256(raw),
        bytes=len(raw),
        stored_at=location,
    )


def publish_attempt(
    store: DocumentStore,
    *,
    run_root_path: str,
    attempt: RunAttempt,
    commit: str,
) -> ResolvedAttemptRef:
    """Publish one canonical attempt document and return its exact reference."""
    raw = yaml_bytes(attempt)
    location = hf_file(
        commit,
        f"{run_root_path}/attempts/{attempt.attempt_id}/resolved.yaml",
    )
    store.put(location, raw)
    return ResolvedAttemptRef(
        sha256=sha256(raw),
        bytes=len(raw),
        stored_at=location,
    )


def fetch_attempt(store: DocumentStore, reference: ResolvedAttemptRef) -> RunAttempt:
    """Load one attempt fixture through its immutable reference."""
    return RunAttempt.model_validate(yaml.safe_load(store.fetch(reference.stored_at)))


def replace_run_attempts(
    store: DocumentStore,
    resolved_run: ResolvedRun,
    attempts: tuple[RunAttempt, ...],
) -> ResolvedRun:
    """Publish replacement attempt fixtures and return their terminal run."""
    run_root_path = str(resolved_run.spec.stored_at.path).removesuffix("/spec.yaml")
    references = tuple(
        publish_attempt(
            store,
            run_root_path=run_root_path,
            attempt=attempt,
            commit="a" * 40,
        )
        for attempt in attempts
    )
    return resolved_run.model_copy(update={"attempts": references})


def replace_confirmation(
    store: DocumentStore,
    result: BenchmarkResult,
    confirmation: RunAttempt,
) -> BenchmarkResult:
    """Publish a replacement confirmation and return its benchmark result."""
    run_root_path = str(result.run.stored_at.path).removesuffix("/resolved.yaml")
    reference = publish_attempt(
        store,
        run_root_path=run_root_path,
        attempt=confirmation,
        commit="b" * 40,
    )
    return result.model_copy(update={"confirmation": reference})


def resolved_environment(
    store: DocumentStore,
    source_commit: str,
) -> ResolvedGCEEnvironment:
    """Bind the requested environment to resolved image and lockfile identities."""
    lock_raw = b"name: mantra\n"
    lockfile = add_source_file(store, source_commit, "environment.yml", lock_raw)
    return ResolvedGCEEnvironment(
        kind="gce",
        provisioning=GCEBootImageRef(
            project="viper-project",
            name="viper-image",
            id="123456789",
        ),
        machine_type="n2-standard-8",
        compute=CPUComputeSpec(kind="cpu"),
        lockfile=lockfile,
        python_environment=python_environment(),
    )


def add_loader(
    store: DocumentStore,
    source_commit: str,
    loader_id: str,
    *,
    bundle: bool = False,
) -> None:
    """Publish one artifact-loader module into the simulated source commit."""
    raw = loader_source(loader_id, bundle=bundle)
    store.put(
        git_file(
            source_commit,
            loader_path(loader_id),
        ),
        raw,
    )


def add_plan_records(
    store: DocumentStore,
    *,
    run: RunSpec,
    stage_specs: list[tuple[str, BaseSpec]],
    experiment: ExperimentSpec,
    variant: VariantSpec,
    plan_commit: str,
    benchmark: BenchmarkSpec | None = None,
) -> ResolvedRunSpecRef:
    """Publish the experiment, variant, metrics, stage specs, and run plan."""
    source_commit = run.source.commit
    store.put(
        git_file(source_commit, f"experiments/{run.experiment_id}/spec.yaml"),
        yaml_bytes(experiment),
    )
    store.put(
        git_file(
            source_commit,
            f"experiments/{run.experiment_id}/variants/{run.variant_id}.spec.yaml",
        ),
        yaml_bytes(variant),
    )
    if benchmark is not None:
        store.put(
            git_file(
                source_commit,
                f"benchmarks/{benchmark.benchmark_id}.spec.yaml",
            ),
            yaml_bytes(benchmark),
        )

    for metric in experiment.metrics:
        store.put(
            git_file(source_commit, metric.implementation.path),
            metric_source(metric.metric_id, metric.kind),
        )

    for run_stage, (_, spec) in zip(run.stages, stage_specs, strict=True):
        store.put(git_file(plan_commit, str(run_stage.spec)), yaml_bytes(spec))

    run_path = (
        f"experiments/{run.experiment_id}/runs/{run.variant_id}/{run.run_id}/spec.yaml"
    )
    run_raw = yaml_bytes(run)
    run_location = git_file(plan_commit, run_path)
    store.put(run_location, run_raw)
    return ResolvedRunSpecRef(
        sha256=sha256(run_raw),
        bytes=len(run_raw),
        stored_at=run_location,
    )


def make_run(
    *,
    experiment_id: str,
    run_id: str,
    source_commit: str,
    plan_commit: str,
    stage_specs: list[tuple[str, BaseSpec]],
    estimator_stage_id: str,
) -> RunSpec:
    """Construct one frozen run plan from exact stage-spec bytes."""
    stage_refs: list[RunStageRef] = []
    for stage_id, spec in stage_specs:
        raw = yaml_bytes(spec)
        path = (
            f"experiments/{experiment_id}/runs/baseline/{run_id}/"
            f"stages/{stage_id}/spec.yaml"
        )
        stage_refs.append(
            RunStageRef(
                stage_id=stage_id,
                spec=path,
                sha256=sha256(raw),
                bytes=len(raw),
            )
        )

    return RunSpec(
        run_id=run_id,
        experiment_id=experiment_id,
        variant_id="baseline",
        replicate_id="replicate_01",
        seed=42,
        source=GitSource(
            repository=SOURCE_REPOSITORY,
            commit=source_commit,
        ),
        environment=environment(source_commit),
        reproducibility=reproducibility(),
        stages=tuple(stage_refs),
        estimator=StageArtifactRef(
            stage_id=estimator_stage_id,
            artifact_name=PARAMETERS,
        ),
    )


def add_single_artifact(
    store: DocumentStore,
    snapshot_commit: str,
    path: str,
    raw: bytes,
) -> ResolvedSingleFileArtifact:
    """Publish one single-file artifact into a stage-result snapshot."""
    store.put(hf_file(snapshot_commit, path), raw)
    return ResolvedSingleFileArtifact(
        kind="file",
        file=SnapshotFileRef(path=path, sha256=sha256(raw), bytes=len(raw)),
    )


def add_bundle_artifact(
    store: DocumentStore,
    snapshot_commit: str,
    root: str,
    members: dict[str, bytes],
) -> ResolvedBundleArtifact:
    """Publish one bundle artifact into a stage-result snapshot."""
    resolved_members = []
    for relative_path in sorted(members):
        raw = members[relative_path]
        path = f"{root}/{relative_path}"
        store.put(hf_file(snapshot_commit, path), raw)
        resolved_members.append(
            ResolvedBundleMember(
                relative_path=relative_path,
                file=SnapshotFileRef(path=path, sha256=sha256(raw), bytes=len(raw)),
            )
        )
    return ResolvedBundleArtifact(kind="bundle", members=tuple(resolved_members))


def publish_resolved_stage(
    store: DocumentStore,
    *,
    run_root_path: str,
    stage_id: str,
    snapshot_commit: str,
    resolved_spec: object,
) -> ResolvedStageRef:
    """Publish one resolved stage record into its result snapshot."""
    path = f"{run_root_path}/stages/{stage_id}/resolved.yaml"
    raw = yaml_bytes(resolved_spec)
    store.put(hf_file(snapshot_commit, path), raw)
    return ResolvedStageRef(
        stage_id=stage_id,
        snapshot=snapshot(snapshot_commit),
        resolved_spec=SnapshotFileRef(path=path, sha256=sha256(raw), bytes=len(raw)),
    )


def resolved_pointer(
    store: DocumentStore,
    source_commit: str,
    path: str,
    pointer: ArtifactPointer,
) -> ResolvedArtifactPointerRef:
    """Build one resolved promoted-artifact pointer reference."""
    raw = yaml_bytes(pointer)
    location = ArtifactPointerRef(
        repository=SOURCE_REPOSITORY,
        commit=source_commit,
        path=path,
    )
    store.put(location, raw)
    return ResolvedArtifactPointerRef(
        sha256=sha256(raw),
        bytes=len(raw),
        stored_at=location,
    )


def publish_producer_run(
    store: DocumentStore,
    *,
    evaluation_role: DataRole = "evaluation",
) -> tuple[ResolvedRunRef, dict[str, Any]]:
    """Publish a complete upstream run for stored-input verification."""
    run_root = "experiments/source_data/runs/baseline/01ARZ3NDEKTSV4RRFFQ69G5FAA"
    retrieved_body_raw = b"fixture HTTP body"
    download = DownloadSpec(
        implementation=stage_implementation_ref(
            "pipelines/download.py",
            DOWNLOAD_SOURCE,
            symbol="download",
        ),
        parameter_model=parameter_model_ref("download"),
        inputs={
            "archive": http_request(
                url="https://example.com/toy-v1.tar.gz",
                body=retrieved_body_raw,
            )
        },
        transport=builtin_http_transport(),
        policy=http_policy(),
        artifacts={
            "dataset": SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/datasets/toy/dataset.bin",
                loader=loader_ref("bytes_file"),
                data_role="training",
            ),
            "evaluation_dataset": SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/datasets/toy/evaluation.bin",
                loader=loader_ref("bytes_file"),
                data_role=evaluation_role,
            ),
            "split": SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/datasets/toy/split.json",
                loader=loader_ref("bytes_file"),
                data_role=evaluation_role,
            ),
        },
        params=parameters.Download(),
    )
    train = TrainSpec(
        implementation=stage_implementation_ref(
            "training/fit.py",
            TRAIN_SOURCE,
            symbol="fit",
        ),
        parameter_model=parameter_model_ref("train"),
        inputs={
            "training_dataset": FutureInputRef(
                kind="future",
                producer_stage_id="download",
                producer_artifact="dataset",
            )
        },
        params=parameters.Train.model_validate(
            {"epochs": 1, "batch_size": 2, "learning_rate": 0.01}
        ),
        artifacts={
            PARAMETERS: SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/models/toy/parameters.bin",
                loader=loader_ref("bytes_file"),
                data_role="training",
            ),
            RESUME_STATE: SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/models/toy/resume_state.bin",
                loader=loader_ref("resume_state"),
                data_role="training",
            ),
        },
    )
    stage_specs: list[tuple[str, BaseSpec]] = [
        ("download", download),
        ("train", train),
    ]
    run = make_run(
        experiment_id="source_data",
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAA",
        source_commit=PRODUCER_SOURCE_COMMIT,
        plan_commit=PRODUCER_PLAN_COMMIT,
        stage_specs=stage_specs,
        estimator_stage_id="train",
    )
    experiment = ExperimentSpec(
        experiment_id="source_data",
        factors=(),
        variant_ids=("baseline",),
        replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
        metrics=(),
    )
    variant = VariantSpec(
        experiment_id="source_data",
        variant_id="baseline",
        levels={},
        stage_params=(
            DownloadVariantStageParams(
                kind="download", stage_id="download", params=download.params
            ),
            TrainVariantStageParams(
                kind="train", stage_id="train", params=train.params
            ),
        ),
    )
    run_reference = add_plan_records(
        store,
        run=run,
        stage_specs=stage_specs,
        experiment=experiment,
        variant=variant,
        plan_commit=PRODUCER_PLAN_COMMIT,
    )

    add_loader(store, PRODUCER_SOURCE_COMMIT, "bytes_file")
    add_loader(store, PRODUCER_SOURCE_COMMIT, "resume_state")
    add_source_file(
        store,
        PRODUCER_SOURCE_COMMIT,
        parameter_model_ref("download").path,
        parameter_model_source("download"),
    )
    add_source_file(
        store,
        PRODUCER_SOURCE_COMMIT,
        parameter_model_ref("train").path,
        parameter_model_source("train"),
    )
    resolved_env = resolved_environment(store, PRODUCER_SOURCE_COMMIT)
    download_source = add_source_file(
        store,
        PRODUCER_SOURCE_COMMIT,
        str(download.implementation.path),
        DOWNLOAD_SOURCE,
    )
    train_source = add_source_file(
        store,
        PRODUCER_SOURCE_COMMIT,
        str(train.implementation.path),
        TRAIN_SOURCE,
    )

    download_commit = "7" * 40
    training_dataset_raw = b"fixed training dataset bytes"
    evaluation_dataset_raw = b"fixed evaluation dataset bytes"
    split_raw = b'{"test":[0,1]}\n'
    retrieved_body_path = retrieval_body_path(run, "download", "archive")
    store.put(hf_file(download_commit, retrieved_body_path), retrieved_body_raw)
    archive_retrieval = ResolvedHttpRetrieval(
        input_name="archive",
        request=download.inputs["archive"],
        transport=ResolvedHttpTransport(spec=download.transport),
        response=ObservedHttpResponse(
            response_url=download.inputs["archive"].url,
            status=200,
            response_headers={"content-length": str(len(retrieved_body_raw))},
        ),
        body=ResolvedFileRef(
            sha256=sha256(retrieved_body_raw),
            bytes=len(retrieved_body_raw),
            stored_at=hf_file(download_commit, retrieved_body_path),
        ),
        started_at=datetime(2026, 8, 20, 20, 2, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 20, 5, tzinfo=UTC),
    )
    download_invocation = publish_invocation(
        store,
        run=run,
        stage_id="download",
        stage=download,
        input_paths={"archive": retrieved_body_path},
        started_at=datetime(2026, 8, 20, 20, 1, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 20, 9, tzinfo=UTC),
        commit=PRODUCER_RESULT_COMMIT,
        retrievals={"archive": archive_retrieval},
    )
    resolved_download = ResolvedDownloadSpec(
        spec=download,
        source=download_source,
        environment=resolved_env,
        execution_context=execution_context(),
        startup=startup_receipt(run),
        invocation=download_invocation,
        command=("python", "-m", "viper.stage_worker"),
        retrievals={"archive": archive_retrieval},
        artifacts={
            "dataset": add_single_artifact(
                store,
                download_commit,
                str(download.artifacts["dataset"].path),
                training_dataset_raw,
            ),
            "evaluation_dataset": add_single_artifact(
                store,
                download_commit,
                str(download.artifacts["evaluation_dataset"].path),
                evaluation_dataset_raw,
            ),
            "split": add_single_artifact(
                store,
                download_commit,
                str(download.artifacts["split"].path),
                split_raw,
            ),
        },
        completed_at=datetime(2026, 8, 20, 20, 10, tzinfo=UTC),
    )
    download_stage = publish_resolved_stage(
        store,
        run_root_path=run_root,
        stage_id="download",
        snapshot_commit=download_commit,
        resolved_spec=resolved_download,
    )

    train_commit = "8" * 40
    train_invocation = publish_invocation(
        store,
        run=run,
        stage_id="train",
        stage=train,
        input_paths={
            "training_dataset": str(download.artifacts["dataset"].path),
        },
        started_at=datetime(2026, 8, 20, 20, 11, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 20, 29, tzinfo=UTC),
        commit=PRODUCER_RESULT_COMMIT,
    )
    resolved_train = ResolvedTrainSpec(
        spec=train,
        source=train_source,
        environment=resolved_env,
        execution_context=execution_context(),
        startup=startup_receipt(run),
        invocation=train_invocation,
        command=("python", "-m", "viper.stage_worker"),
        inputs={
            "training_dataset": ResolvedFutureInputRef(producer=download_stage),
        },
        artifacts={
            PARAMETERS: add_single_artifact(
                store,
                train_commit,
                str(train.artifacts[PARAMETERS].path),
                b"producer model",
            ),
            RESUME_STATE: add_single_artifact(
                store,
                train_commit,
                str(train.artifacts[RESUME_STATE].path),
                resume_state_bytes(),
            ),
        },
        completed_at=datetime(2026, 8, 20, 20, 30, tzinfo=UTC),
    )
    train_stage = publish_resolved_stage(
        store,
        run_root_path=run_root,
        stage_id="train",
        snapshot_commit=train_commit,
        resolved_spec=resolved_train,
    )
    attempt = RunAttempt(
        attempt_id=1,
        purpose="run",
        status="succeeded",
        started_at=datetime(2026, 8, 20, 20, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 20, 35, tzinfo=UTC),
        resolved_stages=(download_stage, train_stage),
        invocations=(download_invocation, train_invocation),
        journal=publish_attempt_journal(
            store,
            run_root_path=run_root,
            attempt_id=1,
            commit=PRODUCER_RESULT_COMMIT,
        ),
        measurement_files=(),
        log_files=(),
        failure=None,
    )
    resolved_run = ResolvedRun(
        spec=run_reference,
        status="succeeded",
        attempts=(
            publish_attempt(
                store,
                run_root_path=run_root,
                attempt=attempt,
                commit=PRODUCER_RESULT_COMMIT,
            ),
        ),
        successful_attempt_id=1,
        completed_at=datetime(2026, 8, 20, 20, 36, tzinfo=UTC),
    )
    resolved_run_raw = yaml_bytes(resolved_run)
    resolved_run_location = hf_file(
        PRODUCER_RESULT_COMMIT,
        f"{run_root}/resolved.yaml",
    )
    store.put(resolved_run_location, resolved_run_raw)
    reference = ResolvedRunRef(
        sha256=sha256(resolved_run_raw),
        bytes=len(resolved_run_raw),
        stored_at=resolved_run_location,
    )
    return reference, {
        "dataset": training_dataset_raw,
        "dataset_ref": download_stage,
        "run": resolved_run,
    }


def build_complete_fixture(
    *,
    benchmark_enabled: bool = False,
    benchmark_threshold: float = 0.9,
    producer_evaluation_role: DataRole | None = None,
) -> tuple[
    ResolvedRun,
    DocumentStore,
    HuggingFaceFileRef,
]:
    """Publish one complete valid provenance chain and return its roots."""
    store = DocumentStore()
    evaluation_role = "benchmark" if benchmark_enabled else "evaluation"
    producer_run_ref, _ = publish_producer_run(
        store,
        evaluation_role=producer_evaluation_role or evaluation_role,
    )

    training_dataset_pointer = ArtifactPointer(
        run=producer_run_ref,
        artifact=StageArtifactRef(stage_id="download", artifact_name="dataset"),
    )
    evaluation_dataset_pointer = ArtifactPointer(
        run=producer_run_ref,
        artifact=StageArtifactRef(
            stage_id="download",
            artifact_name="evaluation_dataset",
        ),
    )
    split_pointer = ArtifactPointer(
        run=producer_run_ref,
        artifact=StageArtifactRef(stage_id="download", artifact_name="split"),
    )
    training_dataset_pointer_path = "inputs/datasets/toy/training.pointer.yaml"
    evaluation_dataset_pointer_path = "inputs/datasets/toy/evaluation.pointer.yaml"
    split_pointer_path = "inputs/benchmarks/toy/test_split.pointer.yaml"
    resolved_training_dataset_pointer = resolved_pointer(
        store,
        MAIN_SOURCE_COMMIT,
        training_dataset_pointer_path,
        training_dataset_pointer,
    )
    resolved_evaluation_dataset_pointer = resolved_pointer(
        store,
        MAIN_SOURCE_COMMIT,
        evaluation_dataset_pointer_path,
        evaluation_dataset_pointer,
    )
    resolved_split_pointer = resolved_pointer(
        store,
        MAIN_SOURCE_COMMIT,
        split_pointer_path,
        split_pointer,
    )

    run_id = "01ARZ3NDEKTSV4RRFFQ69G5FAB"
    run_root = f"experiments/model_eval/runs/baseline/{run_id}"
    build = BuildSpec(
        implementation=stage_implementation_ref(
            "features/build_prior.py",
            BUILD_SOURCE,
            symbol="build_prior",
        ),
        parameter_model=parameter_model_ref("build"),
        inputs={
            "dataset": StoredInputRef(
                kind="stored",
                pointer=resolved_training_dataset_pointer.stored_at,
                path="inputs/datasets/toy/current.bin",
                data_role="training",
            )
        },
        params=parameters.Build(),
        artifacts={
            "prior": BundleArtifactSpec(
                kind="bundle",
                path=f"{run_root}/artifacts/priors/toy",
                loader=loader_ref("prior_bundle", bundle=True),
                data_role="training",
            )
        },
    )
    train = TrainSpec(
        implementation=stage_implementation_ref(
            "training/fit.py",
            TRAIN_SOURCE,
            symbol="fit",
        ),
        parameter_model=parameter_model_ref("train"),
        inputs={
            "prior": FutureInputRef(
                kind="future",
                producer_stage_id="build",
                producer_artifact="prior",
            )
        },
        params=parameters.Train.model_validate(
            {"epochs": 2, "batch_size": 2, "learning_rate": 0.01}
        ),
        artifacts={
            PARAMETERS: SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/models/toy/parameters.bin",
                loader=loader_ref("bytes_file"),
                data_role="training",
            ),
            RESUME_STATE: SingleFileArtifactSpec(
                kind="file",
                path=f"{run_root}/artifacts/models/toy/resume_state.bin",
                loader=loader_ref("resume_state"),
                data_role="training",
            ),
        },
    )
    evaluate = EvaluateSpec(
        implementation=stage_implementation_ref(
            "evaluation/predict.py",
            EVALUATE_SOURCE,
            symbol="predict",
        ),
        parameter_model=parameter_model_ref("evaluate"),
        evaluation_id="toy_predictions",
        metric_ids=("pearson_correlation",),
        split_inputs=("test_split",),
        inputs={
            "parameters": FutureInputRef(
                kind="future",
                producer_stage_id="train",
                producer_artifact=PARAMETERS,
            ),
            "evaluation_dataset": StoredInputRef(
                kind="stored",
                pointer=resolved_evaluation_dataset_pointer.stored_at,
                path="inputs/datasets/toy/evaluation.bin",
                data_role=evaluation_role,
            ),
            "test_split": StoredInputRef(
                kind="stored",
                pointer=resolved_split_pointer.stored_at,
                path="inputs/benchmarks/toy/test_split.json",
                data_role=evaluation_role,
            ),
        },
        params=parameters.Evaluate(),
        artifacts={
            "predictions": SingleFileArtifactSpec(
                kind="file",
                path=(
                    f"{run_root}/artifacts/evaluations/toy_predictions/predictions.json"
                ),
                loader=loader_ref("json_file"),
                data_role=evaluation_role,
            )
        },
    )
    stage_specs: list[tuple[str, BaseSpec]] = [
        ("build", build),
        ("train", train),
        ("evaluate", evaluate),
    ]
    run = make_run(
        experiment_id="model_eval",
        run_id=run_id,
        source_commit=MAIN_SOURCE_COMMIT,
        plan_commit=MAIN_PLAN_COMMIT,
        stage_specs=stage_specs,
        estimator_stage_id="train",
    )
    benchmark = None
    if benchmark_enabled:
        benchmark = BenchmarkSpec(
            benchmark_id="toy_strict",
            evaluation_id="toy_predictions",
            evaluation_dataset=resolved_evaluation_dataset_pointer.stored_at,
            splits={"test_split": resolved_split_pointer.stored_at},
            metrics=(
                MetricCriterion(
                    metric_id="pearson_correlation",
                    comparison="ge",
                    threshold=benchmark_threshold,
                ),
            ),
        )
        run = run.model_copy(update={"benchmark_id": benchmark.benchmark_id})
    experiment = ExperimentSpec(
        experiment_id="model_eval",
        factors=(),
        variant_ids=("baseline",),
        replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
        metrics=(
            metric_spec(
                "pearson_correlation",
                "evaluation",
                required_data_role=evaluation_role,
            ),
        ),
    )
    variant = VariantSpec(
        experiment_id="model_eval",
        variant_id="baseline",
        levels={},
        stage_params=(
            BuildVariantStageParams(
                kind="build", stage_id="build", params=build.params
            ),
            TrainVariantStageParams(
                kind="train", stage_id="train", params=train.params
            ),
            EvaluateVariantStageParams(
                kind="evaluate",
                stage_id="evaluate",
                params=evaluate.params,
            ),
        ),
    )
    run_reference = add_plan_records(
        store,
        run=run,
        stage_specs=stage_specs,
        experiment=experiment,
        variant=variant,
        plan_commit=MAIN_PLAN_COMMIT,
        benchmark=benchmark,
    )

    add_loader(store, MAIN_SOURCE_COMMIT, "prior_bundle", bundle=True)
    add_loader(store, MAIN_SOURCE_COMMIT, "bytes_file")
    add_loader(store, MAIN_SOURCE_COMMIT, "resume_state")
    add_loader(store, MAIN_SOURCE_COMMIT, "json_file")
    for parameter_kind in ("build", "train", "evaluate"):
        add_source_file(
            store,
            MAIN_SOURCE_COMMIT,
            parameter_model_ref(parameter_kind).path,
            parameter_model_source(parameter_kind),
        )
    resolved_env = resolved_environment(store, MAIN_SOURCE_COMMIT)
    build_source = add_source_file(
        store,
        MAIN_SOURCE_COMMIT,
        str(build.implementation.path),
        BUILD_SOURCE,
    )
    train_source = add_source_file(
        store,
        MAIN_SOURCE_COMMIT,
        str(train.implementation.path),
        TRAIN_SOURCE,
    )
    evaluate_source = add_source_file(
        store,
        MAIN_SOURCE_COMMIT,
        str(evaluate.implementation.path),
        EVALUATE_SOURCE,
    )

    build_commit = "9" * 40
    prior_members = {
        "adjacency.bin": b"adjacency",
        "metadata.json": b'{"genes":2}\n',
    }
    prior_artifact = add_bundle_artifact(
        store,
        build_commit,
        str(build.artifacts["prior"].path),
        prior_members,
    )
    build_invocation = publish_invocation(
        store,
        run=run,
        stage_id="build",
        stage=build,
        input_paths={"dataset": "inputs/datasets/toy/current.bin"},
        started_at=datetime(2026, 8, 20, 21, 1, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 21, 9, tzinfo=UTC),
        commit=MAIN_FILES_COMMIT,
    )
    resolved_build = ResolvedBuildSpec(
        spec=build,
        source=build_source,
        environment=resolved_env,
        execution_context=execution_context(),
        startup=startup_receipt(run),
        invocation=build_invocation,
        command=("python", "-m", "viper.stage_worker"),
        inputs={
            "dataset": ResolvedStoredInputRef(
                kind="stored", pointer=resolved_training_dataset_pointer
            ),
        },
        artifacts={"prior": prior_artifact},
        completed_at=datetime(2026, 8, 20, 21, 10, tzinfo=UTC),
    )
    build_stage = publish_resolved_stage(
        store,
        run_root_path=run_root,
        stage_id="build",
        snapshot_commit=build_commit,
        resolved_spec=resolved_build,
    )

    train_commit = "a" * 40
    train_invocation = publish_invocation(
        store,
        run=run,
        stage_id="train",
        stage=train,
        input_paths={"prior": str(build.artifacts["prior"].path)},
        started_at=datetime(2026, 8, 20, 21, 11, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 21, 29, tzinfo=UTC),
        commit=MAIN_FILES_COMMIT,
    )
    resolved_train = ResolvedTrainSpec(
        spec=train,
        source=train_source,
        environment=resolved_env,
        execution_context=execution_context(),
        startup=startup_receipt(run),
        invocation=train_invocation,
        command=("python", "-m", "viper.stage_worker"),
        inputs={"prior": ResolvedFutureInputRef(producer=build_stage)},
        artifacts={
            PARAMETERS: add_single_artifact(
                store,
                train_commit,
                str(train.artifacts[PARAMETERS].path),
                b"final model parameters",
            ),
            RESUME_STATE: add_single_artifact(
                store,
                train_commit,
                str(train.artifacts[RESUME_STATE].path),
                resume_state_bytes(),
            ),
        },
        completed_at=datetime(2026, 8, 20, 21, 30, tzinfo=UTC),
    )
    train_stage = publish_resolved_stage(
        store,
        run_root_path=run_root,
        stage_id="train",
        snapshot_commit=train_commit,
        resolved_spec=resolved_train,
    )

    evaluate_commit = "b" * 40
    evaluate_invocation = publish_invocation(
        store,
        run=run,
        stage_id="evaluate",
        stage=evaluate,
        input_paths={
            "parameters": str(train.artifacts[PARAMETERS].path),
            "evaluation_dataset": "inputs/datasets/toy/evaluation.bin",
            "test_split": "inputs/benchmarks/toy/test_split.json",
        },
        started_at=datetime(2026, 8, 20, 21, 31, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 21, 39, tzinfo=UTC),
        commit=MAIN_FILES_COMMIT,
    )
    resolved_evaluate = ResolvedEvaluateSpec(
        spec=evaluate,
        source=evaluate_source,
        environment=resolved_env,
        execution_context=execution_context(),
        startup=startup_receipt(run),
        invocation=evaluate_invocation,
        command=("python", "-m", "viper.stage_worker"),
        inputs={
            "parameters": ResolvedFutureInputRef(producer=train_stage),
            "evaluation_dataset": ResolvedStoredInputRef(
                kind="stored",
                pointer=resolved_evaluation_dataset_pointer,
            ),
            "test_split": ResolvedStoredInputRef(
                kind="stored", pointer=resolved_split_pointer
            ),
        },
        artifacts={
            "predictions": add_single_artifact(
                store,
                evaluate_commit,
                str(evaluate.artifacts["predictions"].path),
                b"fixed predictions",
            )
        },
        completed_at=datetime(2026, 8, 20, 21, 40, tzinfo=UTC),
    )
    evaluate_stage = publish_resolved_stage(
        store,
        run_root_path=run_root,
        stage_id="evaluate",
        snapshot_commit=evaluate_commit,
        resolved_spec=resolved_evaluate,
    )

    measurement_raw = (
        b'{"run_id":"01ARZ3NDEKTSV4RRFFQ69G5FAB",'
        b'"attempt_id":1,"stage_id":"evaluate",'
        b'"metric_id":"pearson_correlation","value":0.91,'
        b'"measured_at":"2026-08-20T21:41:00Z"}\n'
    )
    measurement_location = hf_file(
        MAIN_FILES_COMMIT,
        f"{run_root}/attempts/1/measurements/evaluate.pearson_correlation.jsonl",
    )
    store.put(measurement_location, measurement_raw)
    measurement_reference = ResolvedFileRef(
        sha256=sha256(measurement_raw),
        bytes=len(measurement_raw),
        stored_at=measurement_location,
    )
    predictions = resolved_evaluate.artifacts["predictions"]
    assert isinstance(predictions, ResolvedSingleFileArtifact)
    metric_verification_reference = publish_metric_verification(
        store,
        run=run,
        attempt_id=1,
        stage_id="evaluate",
        metric=experiment.metrics[0],
        measurement_raw=measurement_raw,
        stage_completed_at=resolved_evaluate.completed_at,
        dependency_files=(
            ResolvedFileRef(
                sha256=predictions.file.sha256,
                bytes=predictions.file.bytes,
                stored_at=hf_file(evaluate_commit, str(predictions.file.path)),
            ),
        ),
        commit=MAIN_FILES_COMMIT,
    )
    attempt = RunAttempt(
        attempt_id=1,
        purpose="run",
        status="succeeded",
        started_at=datetime(2026, 8, 20, 21, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 21, 45, tzinfo=UTC),
        resolved_stages=(build_stage, train_stage, evaluate_stage),
        invocations=(build_invocation, train_invocation, evaluate_invocation),
        journal=publish_attempt_journal(
            store,
            run_root_path=run_root,
            attempt_id=1,
            commit=MAIN_FILES_COMMIT,
        ),
        measurement_files=(measurement_reference,),
        metric_verification_files=(metric_verification_reference,),
        log_files=(),
        failure=None,
    )
    resolved_run = ResolvedRun(
        spec=run_reference,
        status="succeeded",
        attempts=(
            publish_attempt(
                store,
                run_root_path=run_root,
                attempt=attempt,
                commit=MAIN_FILES_COMMIT,
            ),
        ),
        successful_attempt_id=1,
        completed_at=datetime(2026, 8, 20, 21, 46, tzinfo=UTC),
    )
    tamper_location = hf_file(
        build_commit,
        f"{build.artifacts['prior'].path}/adjacency.bin",
    )
    return resolved_run, store, tamper_location


def copy_snapshot_files(
    store: DocumentStore,
    source_commit: str,
    target_commit: str,
) -> None:
    """Copy all files between immutable stage-result snapshots."""
    for key, raw in tuple(store.documents.items()):
        kind, repository, commit, path, repo_type = key
        if (
            kind == "huggingface"
            and repository == ARTIFACT_REPOSITORY
            and commit == source_commit
            and repo_type == "dataset"
        ):
            store.put(hf_file(target_commit, path), raw)


def build_benchmark_fixture(
    *,
    threshold: float = 0.9,
) -> tuple[
    BenchmarkResult,
    ResolvedRun,
    DocumentStore,
]:
    """Publish a strict benchmark and its independent confirmation run."""
    resolved_run, store, _ = build_complete_fixture(
        benchmark_enabled=True,
        benchmark_threshold=threshold,
    )
    selected_attempt = fetch_attempt(store, resolved_run.attempts[-1])
    run_root = str(resolved_run.spec.stored_at.path).removesuffix("/spec.yaml")
    run = RunSpec.model_validate(
        yaml.safe_load(store.fetch(resolved_run.spec.stored_at))
    )

    original_build, original_train, original_evaluate = selected_attempt.resolved_stages
    build_commit = "c" * 40
    train_commit = "d" * 40
    evaluate_commit = "e" * 40

    copy_snapshot_files(store, original_build.snapshot.commit, build_commit)
    resolved_build = ResolvedBuildSpec.model_validate(
        yaml.safe_load(
            store.fetch(
                hf_file(
                    original_build.snapshot.commit,
                    str(original_build.resolved_spec.path),
                )
            )
        )
    )
    build_invocation = publish_invocation(
        store,
        run=run,
        stage_id="build",
        stage=resolved_build.spec,
        input_paths={"dataset": "inputs/datasets/toy/current.bin"},
        started_at=datetime(2026, 8, 20, 21, 1, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 21, 9, tzinfo=UTC),
        commit="f" * 40,
        attempt_id=2,
    )
    resolved_build = resolved_build.model_copy(update={"invocation": build_invocation})
    confirmation_build = publish_resolved_stage(
        store,
        run_root_path=run_root,
        stage_id="build",
        snapshot_commit=build_commit,
        resolved_spec=resolved_build,
    )

    copy_snapshot_files(store, original_train.snapshot.commit, train_commit)
    resolved_train = ResolvedTrainSpec.model_validate(
        yaml.safe_load(
            store.fetch(
                hf_file(
                    original_train.snapshot.commit,
                    str(original_train.resolved_spec.path),
                )
            )
        )
    )
    candidate_parameters = resolved_train.artifacts[PARAMETERS]
    resolved_train = resolved_train.model_copy(
        update={
            "inputs": {"prior": ResolvedFutureInputRef(producer=confirmation_build)}
        }
    )
    train_invocation = publish_invocation(
        store,
        run=run,
        stage_id="train",
        stage=resolved_train.spec,
        input_paths={"prior": str(resolved_build.spec.artifacts["prior"].path)},
        started_at=datetime(2026, 8, 20, 21, 11, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 21, 29, tzinfo=UTC),
        commit="f" * 40,
        attempt_id=2,
    )
    resolved_train = resolved_train.model_copy(update={"invocation": train_invocation})
    confirmation_train = publish_resolved_stage(
        store,
        run_root_path=run_root,
        stage_id="train",
        snapshot_commit=train_commit,
        resolved_spec=resolved_train,
    )

    copy_snapshot_files(store, original_evaluate.snapshot.commit, evaluate_commit)
    resolved_evaluate = ResolvedEvaluateSpec.model_validate(
        yaml.safe_load(
            store.fetch(
                hf_file(
                    original_evaluate.snapshot.commit,
                    str(original_evaluate.resolved_spec.path),
                )
            )
        )
    )
    candidate_predictions = resolved_evaluate.artifacts[PREDICTIONS]
    resolved_evaluate = resolved_evaluate.model_copy(
        update={
            "inputs": {
                **resolved_evaluate.inputs,
                "parameters": ResolvedFutureInputRef(producer=confirmation_train),
            }
        }
    )
    evaluate_invocation = publish_invocation(
        store,
        run=run,
        stage_id="evaluate",
        stage=resolved_evaluate.spec,
        input_paths={
            "parameters": str(resolved_train.spec.artifacts[PARAMETERS].path),
            "evaluation_dataset": "inputs/datasets/toy/evaluation.bin",
            "test_split": "inputs/benchmarks/toy/test_split.json",
        },
        started_at=datetime(2026, 8, 20, 21, 31, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 21, 39, tzinfo=UTC),
        commit="f" * 40,
        attempt_id=2,
    )
    resolved_evaluate = resolved_evaluate.model_copy(
        update={"invocation": evaluate_invocation}
    )
    confirmation_evaluate = publish_resolved_stage(
        store,
        run_root_path=run_root,
        stage_id="evaluate",
        snapshot_commit=evaluate_commit,
        resolved_spec=resolved_evaluate,
    )

    measurement_raw = (
        b'{"run_id":"01ARZ3NDEKTSV4RRFFQ69G5FAB",'
        b'"attempt_id":2,"stage_id":"evaluate",'
        b'"metric_id":"pearson_correlation","value":0.91,'
        b'"measured_at":"2026-08-20T21:41:00Z"}\n'
    )
    measurement_location = hf_file(
        "f" * 40,
        f"{run_root}/attempts/2/measurements/evaluate.pearson_correlation.jsonl",
    )
    store.put(measurement_location, measurement_raw)
    experiment = ExperimentSpec.model_validate(
        yaml.safe_load(
            store.fetch(
                git_file(
                    MAIN_SOURCE_COMMIT,
                    "experiments/model_eval/spec.yaml",
                )
            )
        )
    )
    predictions = resolved_evaluate.artifacts["predictions"]
    assert isinstance(predictions, ResolvedSingleFileArtifact)
    metric_verification_reference = publish_metric_verification(
        store,
        run=run,
        attempt_id=2,
        stage_id="evaluate",
        metric=experiment.metrics[0],
        measurement_raw=measurement_raw,
        stage_completed_at=resolved_evaluate.completed_at,
        dependency_files=(
            ResolvedFileRef(
                sha256=predictions.file.sha256,
                bytes=predictions.file.bytes,
                stored_at=hf_file(evaluate_commit, str(predictions.file.path)),
            ),
        ),
        commit="f" * 40,
    )
    confirmation = RunAttempt(
        attempt_id=2,
        purpose="benchmark_confirmation",
        status="succeeded",
        started_at=datetime(2026, 8, 20, 21, tzinfo=UTC),
        completed_at=datetime(2026, 8, 20, 21, 45, tzinfo=UTC),
        resolved_stages=(
            confirmation_build,
            confirmation_train,
            confirmation_evaluate,
        ),
        invocations=(build_invocation, train_invocation, evaluate_invocation),
        journal=publish_attempt_journal(
            store,
            run_root_path=run_root,
            attempt_id=2,
            commit="f" * 40,
        ),
        measurement_files=(
            ResolvedFileRef(
                sha256=sha256(measurement_raw),
                bytes=len(measurement_raw),
                stored_at=measurement_location,
            ),
        ),
        metric_verification_files=(metric_verification_reference,),
        log_files=(),
        failure=None,
    )

    resolved_run_raw = yaml_bytes(resolved_run)
    resolved_run_location = hf_file("0" * 40, f"{run_root}/resolved.yaml")
    store.put(resolved_run_location, resolved_run_raw)
    run_reference = ResolvedRunRef(
        sha256=sha256(resolved_run_raw),
        bytes=len(resolved_run_raw),
        stored_at=resolved_run_location,
    )

    benchmark_path = "benchmarks/toy_strict.spec.yaml"
    benchmark_location = git_file(MAIN_SOURCE_COMMIT, benchmark_path)
    benchmark_raw = store.fetch(benchmark_location)
    benchmark_reference = ResolvedBenchmarkSpecRef(
        sha256=sha256(benchmark_raw),
        bytes=len(benchmark_raw),
        stored_at=benchmark_location,
    )
    result = BenchmarkResult(
        benchmark=benchmark_reference,
        run=run_reference,
        confirmation=publish_attempt(
            store,
            run_root_path=run_root,
            attempt=confirmation,
            commit="f" * 40,
        ),
        artifacts=(
            ArtifactComparisonReceipt(
                artifact=run.estimator,
                candidate_stage=original_train,
                confirmation_stage=confirmation_train,
                candidate_digest=document_digest(candidate_parameters),
                confirmation_digest=document_digest(
                    resolved_train.artifacts[PARAMETERS]
                ),
                passed=True,
            ),
            ArtifactComparisonReceipt(
                artifact=StageArtifactRef(
                    stage_id="evaluate",
                    artifact_name=PREDICTIONS,
                ),
                candidate_stage=original_evaluate,
                confirmation_stage=confirmation_evaluate,
                candidate_digest=document_digest(candidate_predictions),
                confirmation_digest=document_digest(
                    resolved_evaluate.artifacts[PREDICTIONS]
                ),
                passed=True,
            ),
        ),
        metrics=(
            MetricCriterionReceipt(
                metric_id="pearson_correlation",
                candidate_verification=selected_attempt.metric_verification_files[0],
                confirmation_verification=metric_verification_reference,
                comparison="ge",
                threshold=threshold,
                passed=0.91 >= threshold,
            ),
        ),
        status="passed" if 0.91 >= threshold else "failed",
        completed_at=datetime(2026, 8, 20, 21, 50, tzinfo=UTC),
    )
    return result, resolved_run, store


class CompleteProvenanceAcceptanceTests(unittest.TestCase):
    """Verify complete run and benchmark chains through the public verifier."""

    def test_complete_dummy_run_passes_full_verification(self) -> None:
        """Verify that complete dummy run passes full verification."""
        resolved_run, store, _ = build_complete_fixture()

        verified = verify_run_result(
            resolved_run,
            policy=POLICY,
            fetcher=store.fetch,
        )

        self.assertEqual(set(verified.resolved_stages), {"build", "train", "evaluate"})
        self.assertEqual(len(verified.measurements), 1)
        self.assertEqual(verified.measurements[0].value, 0.91)

    def test_bundle_rejects_an_unrecorded_published_member(self) -> None:
        """Reject a snapshot file omitted from the resolved bundle member list."""
        resolved_run, store, _ = build_complete_fixture()
        build_stage = fetch_attempt(store, resolved_run.attempts[0]).resolved_stages[0]
        extra_path = (
            "experiments/model_eval/runs/baseline/01ARZ3NDEKTSV4RRFFQ69G5FAB/"
            "artifacts/priors/toy/unrecorded.bin"
        )
        store.put(hf_file(build_stage.snapshot.commit, extra_path), b"extra")

        with self.assertRaisesRegex(VerificationError, "artifact.bundle"):
            verify_run_result(resolved_run, policy=POLICY, fetcher=store.fetch)

    def test_bundle_rejects_a_missing_recorded_member(self) -> None:
        """Reject a resolved bundle member absent from its immutable snapshot."""
        resolved_run, store, _ = build_complete_fixture()
        build_stage = fetch_attempt(store, resolved_run.attempts[0]).resolved_stages[0]
        missing_path = (
            "experiments/model_eval/runs/baseline/01ARZ3NDEKTSV4RRFFQ69G5FAB/"
            "artifacts/priors/toy/metadata.json"
        )
        del store.documents[
            DocumentStore.key(hf_file(build_stage.snapshot.commit, missing_path))
        ]

        with self.assertRaisesRegex(
            VerificationError,
            "artifact.bundle: published members differ",
        ):
            verify_run_result(resolved_run, policy=POLICY, fetcher=store.fetch)

    def test_stored_input_role_must_match_the_selected_artifact(self) -> None:
        """Reject a stored input whose declared role differs from its source."""
        resolved_run, store, _ = build_complete_fixture(
            producer_evaluation_role="validation"
        )

        with self.assertRaisesRegex(VerificationError, "does not match stored input"):
            verify_run_result(
                resolved_run,
                policy=POLICY,
                fetcher=store.fetch,
            )

    def test_complete_verifier_rejects_tampered_referenced_file(self) -> None:
        """Verify that complete verifier rejects tampered referenced file."""
        resolved_run, store, tamper_location = build_complete_fixture()
        store.put(tamper_location, b"Adjacency")

        with self.assertRaisesRegex(VerificationError, "SHA-256 mismatch"):
            verify_run_result(resolved_run, policy=POLICY, fetcher=store.fetch)

    def test_measurement_cannot_follow_its_attempt(self) -> None:
        """Reject a recomputed measurement written after attempt completion."""
        resolved_run, store, _ = build_complete_fixture()
        attempt = fetch_attempt(store, resolved_run.attempts[0])
        measurement_raw = (
            b'{"run_id":"01ARZ3NDEKTSV4RRFFQ69G5FAB",'
            b'"attempt_id":1,"stage_id":"evaluate",'
            b'"metric_id":"pearson_correlation","value":0.91,'
            b'"measured_at":"2026-08-20T21:46:00Z"}\n'
        )
        reference = attempt.measurement_files[0].model_copy(
            update={
                "sha256": sha256(measurement_raw),
                "bytes": len(measurement_raw),
            }
        )
        store.put(reference.stored_at, measurement_raw)
        invalid_attempt = attempt.model_copy(update={"measurement_files": (reference,)})
        invalid_run = replace_run_attempts(store, resolved_run, (invalid_attempt,))

        with self.assertRaisesRegex(VerificationError, "containing attempt"):
            verify_run_result(invalid_run, policy=POLICY, fetcher=store.fetch)

    def test_run_rejects_stage_snapshot_reused_by_a_retry(self) -> None:
        """Verify that run rejects stage snapshot reused by a retry."""
        resolved_run, store, _ = build_complete_fixture()
        successful_attempt = fetch_attempt(store, resolved_run.attempts[0]).model_copy(
            update={"attempt_id": 2}
        )
        failed_attempt = RunAttempt(
            attempt_id=1,
            purpose="run",
            status="failed",
            started_at=datetime(2026, 8, 20, 19, tzinfo=UTC),
            completed_at=datetime(2026, 8, 20, 20, tzinfo=UTC),
            resolved_stages=(successful_attempt.resolved_stages[0],),
            invocations=(successful_attempt.invocations[0],),
            journal=successful_attempt.journal,
            measurement_files=(),
            log_files=(),
            failure=AttemptFailure(
                code="execution_failed",
                stage_id="train",
                message="retry required",
                occurred_at=datetime(2026, 8, 20, 19, 30, tzinfo=UTC),
            ),
        )
        retried_run = replace_run_attempts(
            store,
            resolved_run.model_copy(update={"successful_attempt_id": 2}),
            (failed_attempt, successful_attempt),
        )

        with self.assertRaisesRegex(VerificationError, "stage-result snapshots"):
            verify_run_result(retried_run, policy=POLICY, fetcher=store.fetch)

    def test_run_rejects_attempt_file_snapshot_reused_by_a_retry(self) -> None:
        """Verify that run rejects attempt file snapshot reused by a retry."""
        resolved_run, store, _ = build_complete_fixture()
        successful_attempt = fetch_attempt(store, resolved_run.attempts[0]).model_copy(
            update={"attempt_id": 2}
        )
        failed_attempt = RunAttempt(
            attempt_id=1,
            purpose="run",
            status="failed",
            started_at=datetime(2026, 8, 20, 19, tzinfo=UTC),
            completed_at=datetime(2026, 8, 20, 20, tzinfo=UTC),
            resolved_stages=(),
            invocations=(),
            journal=successful_attempt.journal,
            measurement_files=successful_attempt.measurement_files,
            log_files=(),
            failure=AttemptFailure(
                code="execution_failed",
                stage_id="train",
                message="retry required",
                occurred_at=datetime(2026, 8, 20, 19, 30, tzinfo=UTC),
            ),
        )
        retried_run = replace_run_attempts(
            store,
            resolved_run.model_copy(update={"successful_attempt_id": 2}),
            (failed_attempt, successful_attempt),
        )

        with self.assertRaisesRegex(
            VerificationError,
            "measurement and log snapshots",
        ):
            verify_run_result(retried_run, policy=POLICY, fetcher=store.fetch)

    def test_run_separates_stage_results_from_attempt_files(self) -> None:
        """Verify that run separates stage results from attempt files."""
        resolved_run, store, _ = build_complete_fixture()
        attempt = fetch_attempt(store, resolved_run.attempts[0])
        measurement = attempt.measurement_files[0]
        reused_snapshot_measurement = measurement.model_copy(
            update={
                "stored_at": measurement.stored_at.model_copy(
                    update={"commit": attempt.resolved_stages[0].snapshot.commit}
                )
            }
        )
        invalid_attempt = attempt.model_copy(
            update={"measurement_files": (reused_snapshot_measurement,)}
        )
        invalid_run = replace_run_attempts(store, resolved_run, (invalid_attempt,))

        with self.assertRaisesRegex(
            VerificationError,
            "stage-result and attempt-file snapshots",
        ):
            verify_run_result(invalid_run, policy=POLICY, fetcher=store.fetch)

    def test_strict_benchmark_passes_two_execution_verification(self) -> None:
        """Verify that strict benchmark passes two execution verification."""
        result, _, store = build_benchmark_fixture()

        verified = verify_benchmark_result(
            result,
            policy=POLICY,
            fetcher=store.fetch,
        )

        self.assertEqual(verified.result.status, "passed")
        self.assertEqual(verified.confirmation_measurements[0].value, 0.91)

    def test_strict_benchmark_records_a_threshold_failure(self) -> None:
        """Accept a failed result when both recomputed values miss the threshold."""
        result, _, store = build_benchmark_fixture(threshold=0.95)

        verified = verify_benchmark_result(
            result,
            policy=POLICY,
            fetcher=store.fetch,
        )

        self.assertEqual(verified.result.status, "failed")
        self.assertFalse(verified.result.metrics[0].passed)

    def test_strict_benchmark_rejects_an_artifact_receipt_mismatch(self) -> None:
        """Reject a comparison receipt whose digest differs from the artifact."""
        result, _, store = build_benchmark_fixture()
        changed_receipt = result.artifacts[0].model_copy(
            update={
                "confirmation_digest": "0" * 64,
                "passed": False,
            }
        )
        changed_result = result.model_copy(
            update={
                "artifacts": (changed_receipt, result.artifacts[1]),
                "status": "failed",
            }
        )

        with self.assertRaisesRegex(VerificationError, "artifact comparison receipt"):
            verify_benchmark_result(
                changed_result,
                policy=POLICY,
                fetcher=store.fetch,
            )

    def test_strict_benchmark_rejects_a_prediction_receipt_mismatch(self) -> None:
        """Reject a changed prediction digest in the comparison receipt."""
        result, _, store = build_benchmark_fixture()
        changed_receipt = result.artifacts[1].model_copy(
            update={
                "confirmation_digest": "0" * 64,
                "passed": False,
            }
        )
        changed_result = result.model_copy(
            update={
                "artifacts": (result.artifacts[0], changed_receipt),
                "status": "failed",
            }
        )

        with self.assertRaisesRegex(VerificationError, "artifact comparison receipt"):
            verify_benchmark_result(
                changed_result,
                policy=POLICY,
                fetcher=store.fetch,
            )

    def test_strict_benchmark_rejects_a_source_mismatch(self) -> None:
        """Reject a benchmark specification selected from another source commit."""
        result, _, store = build_benchmark_fixture()
        changed_location = result.benchmark.stored_at.model_copy(
            update={"commit": "9" * 40}
        )
        store.put(changed_location, store.fetch(result.benchmark.stored_at))
        changed_result = result.model_copy(
            update={
                "benchmark": result.benchmark.model_copy(
                    update={"stored_at": changed_location}
                )
            }
        )

        with self.assertRaisesRegex(VerificationError, "run source snapshot"):
            verify_benchmark_result(
                changed_result,
                policy=POLICY,
                fetcher=store.fetch,
            )

    def test_strict_benchmark_rejects_a_metric_receipt_mismatch(self) -> None:
        """Reject a criterion receipt that references the wrong execution."""
        result, _, store = build_benchmark_fixture()
        changed_metric = result.metrics[0].model_copy(
            update={
                "candidate_verification": result.metrics[0].confirmation_verification
            }
        )
        changed_result = result.model_copy(update={"metrics": (changed_metric,)})

        with self.assertRaisesRegex(VerificationError, "metric criterion receipt"):
            verify_benchmark_result(
                changed_result,
                policy=POLICY,
                fetcher=store.fetch,
            )

    def test_strict_benchmark_rejects_reused_stage_snapshots(self) -> None:
        """Verify that strict benchmark rejects reused stage snapshots."""
        result, resolved_run, store = build_benchmark_fixture()
        confirmation = fetch_attempt(store, result.confirmation)
        selected_attempt = fetch_attempt(store, resolved_run.attempts[-1])
        reused_confirmation = confirmation.model_copy(
            update={"resolved_stages": selected_attempt.resolved_stages}
        )
        reused_result = replace_confirmation(store, result, reused_confirmation)

        with self.assertRaisesRegex(VerificationError, "new stage-result snapshots"):
            verify_benchmark_result(
                reused_result,
                policy=POLICY,
                fetcher=store.fetch,
            )

    def test_strict_benchmark_rejects_reused_attempt_file_snapshot(self) -> None:
        """Verify that strict benchmark rejects reused attempt file snapshot."""
        result, resolved_run, store = build_benchmark_fixture()
        confirmation = fetch_attempt(store, result.confirmation)
        selected_attempt = fetch_attempt(store, resolved_run.attempts[-1])
        reused_confirmation = confirmation.model_copy(
            update={"measurement_files": selected_attempt.measurement_files}
        )

        with self.assertRaisesRegex(
            VerificationError,
            "new measurement and log snapshot",
        ):
            verify_benchmark_result(
                replace_confirmation(store, result, reused_confirmation),
                policy=POLICY,
                fetcher=store.fetch,
            )

    def test_confirmation_separates_stage_results_from_attempt_files(self) -> None:
        """Verify that confirmation separates stage results from attempt files."""
        result, _, store = build_benchmark_fixture()
        confirmation = fetch_attempt(store, result.confirmation)
        measurement = confirmation.measurement_files[0]
        reused_snapshot_measurement = measurement.model_copy(
            update={
                "stored_at": measurement.stored_at.model_copy(
                    update={"commit": confirmation.resolved_stages[0].snapshot.commit}
                )
            }
        )
        invalid_confirmation = confirmation.model_copy(
            update={"measurement_files": (reused_snapshot_measurement,)}
        )

        with self.assertRaisesRegex(
            VerificationError,
            "stage-result and attempt-file snapshots",
        ):
            verify_benchmark_result(
                replace_confirmation(store, result, invalid_confirmation),
                policy=POLICY,
                fetcher=store.fetch,
            )

    def test_strict_benchmark_verifies_confirmation_input_lineage(self) -> None:
        """Verify that strict benchmark verifies confirmation input lineage."""
        result, resolved_run, store = build_benchmark_fixture()
        confirmation = fetch_attempt(store, result.confirmation)
        confirmation_build, confirmation_train, confirmation_evaluate = (
            confirmation.resolved_stages
        )
        original_build = fetch_attempt(
            store,
            resolved_run.attempts[-1],
        ).resolved_stages[0]

        resolved_train = ResolvedTrainSpec.model_validate(
            yaml.safe_load(
                store.fetch(
                    hf_file(
                        confirmation_train.snapshot.commit,
                        str(confirmation_train.resolved_spec.path),
                    )
                )
            )
        ).model_copy(
            update={
                "inputs": {"prior": ResolvedFutureInputRef(producer=original_build)}
            }
        )
        tampered_train = publish_resolved_stage(
            store,
            run_root_path=str(result.run.stored_at.path).removesuffix("/resolved.yaml"),
            stage_id="train",
            snapshot_commit=confirmation_train.snapshot.commit,
            resolved_spec=resolved_train,
        )

        resolved_evaluate = ResolvedEvaluateSpec.model_validate(
            yaml.safe_load(
                store.fetch(
                    hf_file(
                        confirmation_evaluate.snapshot.commit,
                        str(confirmation_evaluate.resolved_spec.path),
                    )
                )
            )
        )
        resolved_evaluate = resolved_evaluate.model_copy(
            update={
                "inputs": {
                    **resolved_evaluate.inputs,
                    "parameters": ResolvedFutureInputRef(producer=tampered_train),
                }
            }
        )
        updated_evaluate = publish_resolved_stage(
            store,
            run_root_path=str(result.run.stored_at.path).removesuffix("/resolved.yaml"),
            stage_id="evaluate",
            snapshot_commit=confirmation_evaluate.snapshot.commit,
            resolved_spec=resolved_evaluate,
        )
        confirmation = confirmation.model_copy(
            update={
                "resolved_stages": (
                    confirmation_build,
                    tampered_train,
                    updated_evaluate,
                )
            }
        )

        with self.assertRaisesRegex(
            VerificationError,
            "does not identify the completed producer stage",
        ):
            verify_benchmark_result(
                replace_confirmation(store, result, confirmation),
                policy=POLICY,
                fetcher=store.fetch,
            )

    def test_strict_benchmark_verifies_confirmation_stored_inputs(self) -> None:
        """Verify that strict benchmark verifies confirmation stored inputs."""
        result, _, store = build_benchmark_fixture()
        confirmation = fetch_attempt(store, result.confirmation)
        confirmation_build, confirmation_train, confirmation_evaluate = (
            confirmation.resolved_stages
        )
        resolved_evaluate = ResolvedEvaluateSpec.model_validate(
            yaml.safe_load(
                store.fetch(
                    hf_file(
                        confirmation_evaluate.snapshot.commit,
                        str(confirmation_evaluate.resolved_spec.path),
                    )
                )
            )
        )
        evaluation_dataset = resolved_evaluate.inputs["evaluation_dataset"]
        self.assertEqual(evaluation_dataset.kind, "stored")
        assert isinstance(evaluation_dataset, ResolvedStoredInputRef)
        tampered_dataset = evaluation_dataset.model_copy(
            update={
                "pointer": evaluation_dataset.pointer.model_copy(
                    update={"sha256": "0" * 64}
                )
            }
        )
        tampered_evaluate_spec = resolved_evaluate.model_copy(
            update={
                "inputs": {
                    **resolved_evaluate.inputs,
                    "evaluation_dataset": tampered_dataset,
                }
            }
        )
        tampered_evaluate = publish_resolved_stage(
            store,
            run_root_path=str(result.run.stored_at.path).removesuffix("/resolved.yaml"),
            stage_id="evaluate",
            snapshot_commit=confirmation_evaluate.snapshot.commit,
            resolved_spec=tampered_evaluate_spec,
        )
        confirmation = confirmation.model_copy(
            update={
                "resolved_stages": (
                    confirmation_build,
                    confirmation_train,
                    tampered_evaluate,
                )
            }
        )

        with self.assertRaisesRegex(VerificationError, "SHA-256 mismatch"):
            verify_benchmark_result(
                replace_confirmation(store, result, confirmation),
                policy=POLICY,
                fetcher=store.fetch,
            )

    def test_promoted_artifact_verifies_producer_input_lineage(self) -> None:
        """Verify that promoted artifact verifies producer input lineage."""
        store = DocumentStore()
        run_reference, records = publish_producer_run(store)
        resolved_run = records["run"]
        attempt = fetch_attempt(store, resolved_run.attempts[0])
        download_stage, train_stage = attempt.resolved_stages
        resolved_train = ResolvedTrainSpec.model_validate(
            yaml.safe_load(
                store.fetch(
                    hf_file(
                        train_stage.snapshot.commit,
                        str(train_stage.resolved_spec.path),
                    )
                )
            )
        ).model_copy(
            update={
                "inputs": {
                    "training_dataset": ResolvedFutureInputRef(producer=train_stage)
                }
            }
        )
        tampered_train = publish_resolved_stage(
            store,
            run_root_path=str(run_reference.stored_at.path).removesuffix(
                "/resolved.yaml"
            ),
            stage_id="train",
            snapshot_commit=train_stage.snapshot.commit,
            resolved_spec=resolved_train,
        )
        tampered_attempt = attempt.model_copy(
            update={"resolved_stages": (download_stage, tampered_train)}
        )
        tampered_run = replace_run_attempts(
            store,
            resolved_run,
            (tampered_attempt,),
        )
        tampered_raw = yaml_bytes(tampered_run)
        store.put(run_reference.stored_at, tampered_raw)
        pointer = ArtifactPointer(
            run=run_reference.model_copy(
                update={"sha256": sha256(tampered_raw), "bytes": len(tampered_raw)}
            ),
            artifact=StageArtifactRef(stage_id="train", artifact_name=PARAMETERS),
        )

        with self.assertRaisesRegex(
            VerificationError,
            "does not identify the completed producer stage",
        ):
            verify_promoted_artifact(pointer, policy=POLICY, fetcher=store.fetch)

    def test_benchmarked_estimator_requires_benchmark_result(self) -> None:
        """Verify that benchmarked estimator requires benchmark result."""
        result, _, store = build_benchmark_fixture()
        pointer = ArtifactPointer(
            run=result.run,
            artifact=StageArtifactRef(stage_id="train", artifact_name=PARAMETERS),
        )

        with self.assertRaisesRegex(VerificationError, "requires a benchmark result"):
            verify_promoted_artifact(pointer, policy=POLICY, fetcher=store.fetch)

    def test_benchmark_result_follows_selected_run_completion(self) -> None:
        """Verify that benchmark result follows selected run completion."""
        result, resolved_run, store = build_benchmark_fixture()
        premature = result.model_copy(
            update={
                "completed_at": resolved_run.completed_at.replace(
                    minute=45,
                    second=30,
                )
            }
        )

        with self.assertRaisesRegex(VerificationError, "selected run completion"):
            verify_benchmark_result(
                premature,
                policy=POLICY,
                fetcher=store.fetch,
            )


if __name__ == "__main__":
    unittest.main()
