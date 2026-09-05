"""Acceptance test for a complete two-stage trusted-local VIPER run."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import os
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import viper.params as current_params
from tests.fixtures import (
    builtin_http,
    http_policy,
    http_request,
    python_environment,
    reproducibility,
    resume_state,
)
from tests.git_repository import REPOSITORY, run_git
from viper import parameters
from viper._schema import (
    PARAMETERS,
    RESUME_STATE,
)
from viper._verification.storage import read_attempt_reference, snapshot_identity
from viper.api import CompareRunsRequest, RunSuccess
from viper.api import compare_runs as compare_runs_application
from viper.api import run as run_stage
from viper.artifacts import (
    ArtifactLoaderRef,
    SingleFileArtifactSpec,
    StageArtifactRef,
    artifact,
)
from viper.authoring import (
    RunPlanDraft,
    StageDraft,
    experiment,
    freeze_run_plan,
    plan,
    replicate,
    stage,
    variant,
)
from viper.authoring import input as external_input
from viper.catalog import Catalog, CatalogRunSource
from viper.execution import _batch
from viper.execution import retry as execute_retry
from viper.execution import run as execute_run
from viper.execution._attempt import execute_attempt
from viper.execution._materialization import (
    capture_external_input,
    verify_captured_inputs,
)
from viper.execution._metric import MetricWorkerResult
from viper.execution._run import execute_benchmark_confirmation
from viper.execution._source import RunFetcher
from viper.execution._stage import StageExecutionError, execute_stage_process
from viper.execution.errors import RunError
from viper.execution.results import RunResult
from viper.experiments import (
    ExperimentSpec,
    ReplicateSpec,
    TrainVariantStageParams,
    VariantSpec,
)
from viper.inputs import (
    ExternalInputRef,
    FutureInputRef,
    LocalSource,
    ResolvedExternalInputRef,
)
from viper.journal import DurableJournal
from viper.metrics import (
    FloatComparator,
    Measurement,
    MetricDependency,
    MetricImplementationRef,
    MetricSpec,
    measure,
)
from viper.metrics import (
    min as minimize,
)
from viper.parameters import ParameterModelRef
from viper.references import (
    GitFileRef,
    GitSource,
    HuggingFaceFileRef,
)
from viper.reuse import (
    ReusedStageCompletion,
    catalog_reuse_candidates,
)
from viper.runs import (
    ResolvedRun,
    RunSpec,
)
from viper.runtime import (
    CUDAComputeSpec,
    LocalEnvSpec,
    observe_gce_provisioning,
)
from viper.runtime import GCEEnvSpec as GCEEnvironmentSpec
from viper.runtime import LocalEnvSpec as LocalEnvironmentSpec
from viper.serialization import parse_yaml_bytes, serialize_document
from viper.stages import (
    DownloadSpec,
    ResolvedTrainSpec,
    StageImplementationRef,
    TrainSpec,
    load_stage_callable,
)
from viper.storage import LocalArtifactStore
from viper.verification import verify_run_result
from viper.verification.models import VerificationError, VerificationPolicy
from viper.workspace import AttemptWorkspace, captured_input_path

RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
RUN_ROOT = f"experiments/example/runs/baseline/{RUN_ID}"


@pytest.fixture
def http_source() -> Iterator[tuple[str, int]]:
    """Serve one redirect followed by the exact body selected by the run."""

    class Handler(BaseHTTPRequestHandler):
        """Return the deterministic HTTP exchange used by the acceptance run."""

        def do_GET(self) -> None:
            """Redirect the initial request and serve the selected body."""
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/prior")
                self.end_headers()
                return
            if self.path == "/prior":
                body = b"prior"
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:
            """Suppress HTTP server logs inside the acceptance output."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", server.server_port
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_local_fetcher_dispatches_hugging_face_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrieve a Hugging Face input through its declared remote backend."""
    reference = HuggingFaceFileRef(
        repository="example/dataset",
        commit="a" * 40,
        path="data.bin",
        repo_type="dataset",
    )
    monkeypatch.setattr(
        "viper.execution._source.fetch_huggingface_file_bytes",
        lambda location: b"remote bytes",
    )
    fetcher = RunFetcher(
        tmp_path,
        LocalArtifactStore(tmp_path),
        REPOSITORY,
    )

    assert fetcher(reference) == b"remote bytes"


def test_two_stage_local_run_writes_and_verifies_terminal_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    http_source: tuple[str, int],
) -> None:
    """Execute source-frozen stages through immutable local publication."""
    root = tmp_path / "project"
    root.mkdir()
    run_git(root, "init", "--quiet")
    run_git(root, "config", "user.email", "viper@example.com")
    run_git(root, "config", "user.name", "VIPER Test")
    run_git(root, "remote", "add", "origin", REPOSITORY)

    train_params = parameters.Train.model_validate(
        {"epochs": 1, "batch_size": 1, "learning_rate": 0.1}
    )
    metric_source = (
        b"from viper.metrics import metric\n\n"
        b'@metric(metric_id="parameter_bytes", kind="diagnostic", '
        b'mode="recompute")\n'
        b"def compute(context):\n"
        b"    return float(len(context.artifacts['parameters'].read_bytes()))\n"
    )
    live_metric_source = (
        b"from viper.metrics import StatefulMetric, metric\n\n"
        b'@metric(metric_id="epoch_mean", kind="training", mode="live")\n'
        b"class EpochMean(StatefulMetric):\n"
        b"    def __init__(self):\n"
        b"        self.values = []\n"
        b"    def update(self, value):\n"
        b"        self.values.append(float(value))\n"
        b"    def compute(self):\n"
        b"        return sum(self.values) / len(self.values)\n"
    )
    parameter_bytes = MetricSpec(
        parameter_model=parameters.model_ref(parameters.Metric),
        metric_id="parameter_bytes",
        implementation=MetricImplementationRef(
            path="project/metrics/parameter_bytes.py",
            symbol="compute",
            sha256=hashlib.sha256(metric_source).hexdigest(),
            bytes=len(metric_source),
        ),
        params=parameters.Metric(),
        mode="recompute",
        dependencies=(
            MetricDependency(
                source="artifact",
                name=PARAMETERS,
                required_data_role="training",
            ),
        ),
        comparator=FloatComparator(),
    )
    epoch_mean = MetricSpec(
        parameter_model=parameters.model_ref(parameters.Metric),
        metric_id="epoch_mean",
        implementation=MetricImplementationRef(
            path="project/metrics/epoch_mean.py",
            symbol="EpochMean",
            sha256=hashlib.sha256(live_metric_source).hexdigest(),
            bytes=len(live_metric_source),
        ),
        params=parameters.Metric(),
        mode="live",
    )
    experiment = ExperimentSpec(
        experiment_id="example",
        factors=(),
        variant_ids=("baseline",),
        replicates=(ReplicateSpec(replicate_id="r1", seed=7),),
        metrics=(parameter_bytes, epoch_mean),
    )
    variant = VariantSpec(
        experiment_id="example",
        variant_id="baseline",
        levels={},
        stage_params=(TrainVariantStageParams(stage_id="train", params=train_params),),
    )
    source_files = {
        "viper.toml": b"[project]\nschema_version = 1\n",
        "environment.yml": b"name: viper-test\n",
        "project/loaders/bytes_file.py": (
            b"def load(path):\n    return path.read_bytes()\n"
        ),
        "project/loaders/resume_state.py": (
            "def load(path):\n"
            f"    return {resume_state().model_dump(mode='python')!r}\n"
        ).encode(),
        "project/metrics/parameter_bytes.py": metric_source,
        "project/metrics/epoch_mean.py": live_metric_source,
        "project/parameters/train.py": (
            b"from pydantic import Field\n"
            b"from viper import parameters\n\n"
            b"class TinyTrainParameters(parameters.Train):\n"
            b"    epochs: int = Field(gt=0)\n"
            b"    batch_size: int = Field(gt=0)\n"
            b"    learning_rate: float = Field(gt=0)\n"
        ),
        "jobs/train.py": (
            b"from project.parameters.train import TinyTrainParameters\n"
            b"from viper.stages import train\n\n"
            b"@train(params=TinyTrainParameters)\n"
            b"def train(context):\n"
            b"    assert context.params.epochs == 1\n"
            b"    assert context.params.batch_size == 1\n"
            b"    assert context.params.learning_rate == 0.1\n"
            b"    assert context.inputs['prior'].read_bytes() == b'prior'\n"
            b"    context.artifacts['parameters'].parent.mkdir(\n"
            b"        parents=True, exist_ok=True\n"
            b"    )\n"
            b"    context.artifacts['parameters'].write_bytes(b'parameters')\n"
            b"    context.artifacts['resume_state'].write_bytes(b'resume')\n"
            b"    live_metric = context.metrics['epoch_mean']\n"
            b"    live_metric.update(1.0)\n"
            b"    live_metric.update(3.0)\n"
            b"    live_metric.record(epoch=0, step=1)\n"
        ),
        "experiments/example/spec.yaml": serialize_document(experiment),
        "experiments/example/variants/baseline.spec.yaml": serialize_document(variant),
    }
    for relative_path, raw in source_files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    run_git(root, "add", ".")
    run_git(root, "commit", "--quiet", "-m", "source")
    source_commit = run_git(root, "rev-parse", "HEAD")

    source = GitSource.model_validate(
        {"repository": REPOSITORY, "commit": source_commit}
    )
    lockfile = GitFileRef.model_validate(
        {
            "repository": REPOSITORY,
            "commit": source_commit,
            "path": "environment.yml",
        }
    )
    if os.environ.get("VIPER_LIVE_GCE") == "1":
        environment = GCEEnvironmentSpec(
            provisioning=observe_gce_provisioning(),
            machine_type="g2-standard-12",
            compute=CUDAComputeSpec(model="NVIDIA L4", count=1),
            lockfile=lockfile,
            python_environment=python_environment(),
        )
    else:
        environment = LocalEnvironmentSpec(
            lockfile=lockfile,
            python_environment=python_environment(),
        )
    host, port = http_source
    download = DownloadSpec(
        inputs={
            "prior": http_request(
                url=f"http://{host}:{port}/redirect",
                body=b"prior",
            )
        },
        http=builtin_http(),
        policy=http_policy(
            hosts=frozenset({host}),
            ports=frozenset({port}),
        ),
        artifacts={
            "prior": SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/datasets/tiny/prior.bin",
                loader=ArtifactLoaderRef(
                    path="project/loaders/bytes_file.py",
                    symbol="load",
                    sha256=hashlib.sha256(
                        source_files["project/loaders/bytes_file.py"]
                    ).hexdigest(),
                    bytes=len(source_files["project/loaders/bytes_file.py"]),
                ),
                data_role="training",
            )
        },
    )
    train = TrainSpec(
        implementation=StageImplementationRef(
            path="jobs/train.py",
            symbol="train",
            sha256=hashlib.sha256(source_files["jobs/train.py"]).hexdigest(),
            bytes=len(source_files["jobs/train.py"]),
        ),
        parameter_model=ParameterModelRef(
            owner="project",
            path="project/parameters/train.py",
            symbol="TinyTrainParameters",
            sha256=hashlib.sha256(
                source_files["project/parameters/train.py"]
            ).hexdigest(),
            bytes=len(source_files["project/parameters/train.py"]),
        ),
        metric_ids=("parameter_bytes", "epoch_mean"),
        inputs={
            "prior": FutureInputRef(
                producer_stage_id="download",
                name="prior",
            )
        },
        params=train_params,
        artifacts={
            PARAMETERS: SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/models/tiny/parameters.bin",
                loader=ArtifactLoaderRef(
                    path="project/loaders/bytes_file.py",
                    symbol="load",
                    sha256=hashlib.sha256(
                        source_files["project/loaders/bytes_file.py"]
                    ).hexdigest(),
                    bytes=len(source_files["project/loaders/bytes_file.py"]),
                ),
                data_role="training",
            ),
            RESUME_STATE: SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/models/tiny/resume_state.bin",
                loader=ArtifactLoaderRef(
                    path="project/loaders/resume_state.py",
                    symbol="load",
                    sha256=hashlib.sha256(
                        source_files["project/loaders/resume_state.py"]
                    ).hexdigest(),
                    bytes=len(source_files["project/loaders/resume_state.py"]),
                ),
                data_role="training",
            ),
        },
    )
    draft_root = tmp_path / "drafts"
    draft_root.mkdir()
    download_draft = draft_root / "download.yaml"
    train_draft = draft_root / "train.yaml"
    download_draft.write_bytes(serialize_document(download))
    train_draft.write_bytes(serialize_document(train))
    frozen = freeze_run_plan(
        root,
        RunPlanDraft(
            run_id=RUN_ID,
            experiment_id="example",
            variant_id="baseline",
            replicate_id="r1",
            seed=7,
            source=source,
            environment=environment,
            reproducibility=reproducibility(),
            stages=(
                StageDraft(stage_id="download", spec_source=download_draft),
                StageDraft(stage_id="train", spec_source=train_draft),
            ),
            estimator=StageArtifactRef(
                stage_id="train",
                artifact_name=PARAMETERS,
            ),
        ),
    )
    run_git(root, "add", "experiments/example/runs")
    run_git(root, "commit", "--quiet", "-m", "plan")

    requests = []

    def fake_run_request(request):
        requests.append(request)
        return RunSuccess(
            run_id=RUN_ID,
            attempt_id=1,
            resolved_attempt=root / RUN_ROOT / "attempts/1/resolved.yaml",
            resolved_run=root / RUN_ROOT / "resolved.yaml",
            journal=root / ".viper" / "attempt.jsonl",
        )

    monkeypatch.setattr("viper.api.run_request", fake_run_request)
    train_callable = load_stage_callable(
        root / train.implementation.path,
        train.implementation,
        import_root=root,
    )
    run_stage(
        train_callable,
        argv=(
            "--run",
            str(frozen.files[-1]),
            "--stage",
            "train",
            "--root",
            str(root),
        ),
    )
    assert len(requests) == 1
    assert requests[0].run_spec == frozen.files[-1].resolve()

    orphan = AttemptWorkspace.create(
        root / ".viper" / "workspaces",
        RUN_ID,
        1,
    )
    orphan_journal = DurableJournal(orphan.control / "journal.jsonl")
    orphan_started = datetime.now(UTC)
    orphan_journal.append(
        "allocated",
        "attempt allocated",
        recorded_at=orphan_started,
    )
    orphan_journal.append(
        "preflighting",
        "coordinator exited during preflight",
        recorded_at=datetime.now(UTC),
    )

    def fail_first_train(*args, **kwargs):
        """Return real child evidence, then simulate one transient train failure ."""
        process = execute_stage_process(*args, **kwargs)
        stage_reference = args[2]

        if stage_reference.stage_id == "train":
            raise StageExecutionError(
                "transient train failure",
                invocation=process.invocation.model_copy(update={"outcome": "failed"}),
                stdout=process.stdout,
                stderr=b"transient train failure\n",
            )

        return process

    monkeypatch.setattr(
        "viper.execution._attempt.execute_stage_process",
        fail_first_train,
    )

    with pytest.raises(RunError, match="attempt 2 failed"):
        execute_run(root, frozen.files[-1])

    failed_run = ResolvedRun.model_validate(
        parse_yaml_bytes((root / RUN_ROOT / "resolved.yaml").read_bytes())
    )
    run_plan = RunSpec.model_validate(parse_yaml_bytes(frozen.files[-1].read_bytes()))
    store = LocalArtifactStore(root)
    fetcher = RunFetcher(root, store, REPOSITORY)
    failed_attempts = tuple(
        read_attempt_reference(reference, run_plan, fetcher=fetcher)
        for reference in failed_run.attempts
    )
    assert failed_run.status == "failed"
    assert failed_attempts[0].failure is not None
    assert failed_attempts[0].failure.code == "coordinator_lost"
    failed_attempt = failed_attempts[1]
    assert failed_attempt.failure is not None
    assert failed_attempt.failure.code == "execution_failed"
    assert len(failed_attempt.resolved_stages) == 1
    assert len(failed_attempt.invocations) == 1
    assert (root / RUN_ROOT / "attempts/1/resolved.yaml").is_file()
    assert (root / RUN_ROOT / "attempts/2/resolved.yaml").is_file()

    monkeypatch.setattr(
        "viper.execution._attempt.execute_stage_process",
        execute_stage_process,
    )
    result = execute_retry(root, frozen.files[-1])

    assert result.resolved_run.status == "succeeded"
    destination_path = (
        root / ".viper" / "workspaces" / RUN_ID / "storage-destination.json"
    )
    assert destination_path.read_bytes() == b'{"kind":"local"}\n'
    assert result.resolved_run_path.is_file()
    attempts = tuple(
        read_attempt_reference(reference, run_plan, fetcher=fetcher)
        for reference in result.resolved_run.attempts
    )
    assert [attempt.attempt_id for attempt in attempts] == [1, 2, 3]
    assert (root / RUN_ROOT / "attempts/3/resolved.yaml").is_file()
    successful_attempt = attempts[2]
    assert len(successful_attempt.resolved_stages) == 2
    assert len(successful_attempt.measurement_files) == 2
    assert len(successful_attempt.metric_verification_files) == 1
    assert result.journal_path.is_file()
    assert (result.journal_path.parent / "preflight.json").is_file()
    metric_runtime = root / ".viper" / "runtime"
    production_result = MetricWorkerResult.model_validate_json(
        next(
            metric_runtime.glob("*.parameter_bytes.measurement.result.json")
        ).read_text(encoding="utf-8")
    )
    assert production_result.receipt is not None
    assert production_result.receipt.purpose == "measurement"
    assert tuple(
        entry.state for entry in DurableJournal(result.journal_path).read()
    ) == (
        "allocated",
        "preflighting",
        "running_stage",
        "publishing_stage",
        "running_stage",
        "publishing_stage",
        "closing_attempt",
        "publishing_attempt_files",
        "terminal",
    )

    live_reference = next(
        reference
        for reference in successful_attempt.measurement_files
        if str(reference.stored_at.path).endswith("train.epoch_mean.jsonl")
    )
    live_measurement = Measurement.model_validate_json(
        fetcher(live_reference.stored_at)
    )
    assert live_measurement.value == 2.0
    assert live_measurement.epoch == 0
    assert live_measurement.step == 1
    comparison = compare_runs_application(
        CompareRunsRequest(
            left_path=result.resolved_run_path,
            right_path=result.resolved_run_path,
            left_root=root,
            right_root=root,
            trusted_source_repositories=frozenset({REPOSITORY}),
        ),
        left_fetcher=fetcher,
        right_fetcher=fetcher,
    )
    assert comparison.identical is True
    assert comparison.changes == ()

    candidate_run_raw = result.resolved_run_path.read_bytes()
    confirmation = execute_benchmark_confirmation(root, frozen.files[-1])
    assert confirmation.attempt.attempt_id == 4
    assert confirmation.attempt.purpose == "benchmark_confirmation"
    assert confirmation.attempt.status == "succeeded"
    assert confirmation.attempt_path.is_file()
    assert result.resolved_run_path.read_bytes() == candidate_run_raw
    candidate_snapshots = {
        snapshot_identity(stage.snapshot)
        for stage in successful_attempt.resolved_stages
    }
    confirmation_snapshots = {
        snapshot_identity(stage.snapshot)
        for stage in confirmation.attempt.resolved_stages
    }
    assert candidate_snapshots.isdisjoint(confirmation_snapshots)

    first_snapshot = attempts[1].resolved_stages[0].snapshot
    assert first_snapshot.kind == "local"
    stored_artifact = (
        root
        / first_snapshot.store
        / first_snapshot.commit
        / f"{RUN_ROOT}/artifacts/datasets/tiny/prior.bin"
    )
    stored_artifact.write_bytes(b"tampered")
    with pytest.raises(VerificationError, match="byte-count mismatch"):
        verify_run_result(
            result.resolved_run,
            policy=VerificationPolicy(
                trusted_source_repositories=frozenset({REPOSITORY})
            ),
            fetcher=RunFetcher(root, store, REPOSITORY),
        )
    stored_artifact.write_bytes(b"prior")


def test_train_stage_captures_local_external_input(
    tmp_path: Path,
) -> None:
    """Execute source-frozen stages through immutable local publication."""
    root = tmp_path / "project"
    root.mkdir()
    run_git(root, "init", "--quiet")
    run_git(root, "config", "user.email", "viper@example.com")
    run_git(root, "config", "user.name", "VIPER Test")
    run_git(root, "remote", "add", "origin", REPOSITORY)

    train_params = parameters.Train.model_validate(
        {"epochs": 1, "batch_size": 1, "learning_rate": 0.1}
    )
    metric_source = (
        b"from viper.metrics import metric\n\n"
        b'@metric(metric_id="parameter_bytes", kind="diagnostic", '
        b'mode="recompute")\n'
        b"def compute(context):\n"
        b"    return float(len(context.artifacts['parameters'].read_bytes()))\n"
    )
    live_metric_source = (
        b"from viper.metrics import StatefulMetric, metric\n\n"
        b'@metric(metric_id="epoch_mean", kind="training", mode="live")\n'
        b"class EpochMean(StatefulMetric):\n"
        b"    def __init__(self):\n"
        b"        self.values = []\n"
        b"    def update(self, value):\n"
        b"        self.values.append(float(value))\n"
        b"    def compute(self):\n"
        b"        return sum(self.values) / len(self.values)\n"
    )
    parameter_bytes = MetricSpec(
        parameter_model=parameters.model_ref(parameters.Metric),
        metric_id="parameter_bytes",
        implementation=MetricImplementationRef(
            path="project/metrics/parameter_bytes.py",
            symbol="compute",
            sha256=hashlib.sha256(metric_source).hexdigest(),
            bytes=len(metric_source),
        ),
        params=parameters.Metric(),
        mode="recompute",
        dependencies=(
            MetricDependency(
                source="artifact",
                name=PARAMETERS,
                required_data_role="training",
            ),
        ),
        comparator=FloatComparator(),
    )
    epoch_mean = MetricSpec(
        parameter_model=parameters.model_ref(parameters.Metric),
        metric_id="epoch_mean",
        implementation=MetricImplementationRef(
            path="project/metrics/epoch_mean.py",
            symbol="EpochMean",
            sha256=hashlib.sha256(live_metric_source).hexdigest(),
            bytes=len(live_metric_source),
        ),
        params=parameters.Metric(),
        mode="live",
    )
    experiment = ExperimentSpec(
        experiment_id="example",
        factors=(),
        variant_ids=("baseline",),
        replicates=(ReplicateSpec(replicate_id="r1", seed=7),),
        metrics=(parameter_bytes, epoch_mean),
    )
    variant = VariantSpec(
        experiment_id="example",
        variant_id="baseline",
        levels={},
        stage_params=(TrainVariantStageParams(stage_id="train", params=train_params),),
    )
    source_files = {
        "viper.toml": b"[project]\nschema_version = 1\n",
        "environment.yml": b"name: viper-test\n",
        "project/loaders/bytes_file.py": (
            b"def load(path):\n    return path.read_bytes()\n"
        ),
        "project/loaders/resume_state.py": (
            "def load(path):\n"
            f"    return {resume_state().model_dump(mode='python')!r}\n"
        ).encode(),
        "project/metrics/parameter_bytes.py": metric_source,
        "project/metrics/epoch_mean.py": live_metric_source,
        "project/parameters/train.py": (
            b"from pydantic import Field\n"
            b"from viper import parameters\n\n"
            b"class TinyTrainParameters(parameters.Train):\n"
            b"    epochs: int = Field(gt=0)\n"
            b"    batch_size: int = Field(gt=0)\n"
            b"    learning_rate: float = Field(gt=0)\n"
        ),
        "jobs/train.py": (
            b"from project.parameters.train import TinyTrainParameters\n"
            b"from viper.stages import train\n\n"
            b"@train(params=TinyTrainParameters)\n"
            b"def train(context):\n"
            b"    assert context.params.epochs == 1\n"
            b"    assert context.params.batch_size == 1\n"
            b"    assert context.params.learning_rate == 0.1\n"
            b"    assert context.inputs['prior'].read_bytes() == b'prior'\n"
            b"    context.artifacts['parameters'].parent.mkdir(\n"
            b"        parents=True, exist_ok=True\n"
            b"    )\n"
            b"    context.artifacts['parameters'].write_bytes(b'parameters')\n"
            b"    context.artifacts['resume_state'].write_bytes(b'resume')\n"
            b"    live_metric = context.metrics['epoch_mean']\n"
            b"    live_metric.update(1.0)\n"
            b"    live_metric.update(3.0)\n"
            b"    live_metric.record(epoch=0, step=1)\n"
        ),
        "inputs/raw/prior.bin": b"prior",
        "experiments/example/spec.yaml": serialize_document(experiment),
        "experiments/example/variants/baseline.spec.yaml": serialize_document(variant),
    }
    for relative_path, raw in source_files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    run_git(root, "add", ".")
    run_git(root, "commit", "--quiet", "-m", "source")
    source_commit = run_git(root, "rev-parse", "HEAD")

    source = GitSource.model_validate(
        {"repository": REPOSITORY, "commit": source_commit}
    )
    lockfile = GitFileRef.model_validate(
        {
            "repository": REPOSITORY,
            "commit": source_commit,
            "path": "environment.yml",
        }
    )
    if os.environ.get("VIPER_LIVE_GCE") == "1":
        environment = GCEEnvironmentSpec(
            provisioning=observe_gce_provisioning(),
            machine_type="g2-standard-12",
            compute=CUDAComputeSpec(model="NVIDIA L4", count=1),
            lockfile=lockfile,
            python_environment=python_environment(),
        )
    else:
        environment = LocalEnvironmentSpec(
            lockfile=lockfile,
            python_environment=python_environment(),
        )

    train = TrainSpec(
        implementation=StageImplementationRef(
            path="jobs/train.py",
            symbol="train",
            sha256=hashlib.sha256(source_files["jobs/train.py"]).hexdigest(),
            bytes=len(source_files["jobs/train.py"]),
        ),
        parameter_model=ParameterModelRef(
            owner="project",
            path="project/parameters/train.py",
            symbol="TinyTrainParameters",
            sha256=hashlib.sha256(
                source_files["project/parameters/train.py"]
            ).hexdigest(),
            bytes=len(source_files["project/parameters/train.py"]),
        ),
        metric_ids=("parameter_bytes", "epoch_mean"),
        inputs={
            "prior": ExternalInputRef(
                source=LocalSource(path="inputs/raw/prior.bin"),
                data_role="training",
            )
        },
        params=train_params,
        artifacts={
            PARAMETERS: SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/models/tiny/parameters.bin",
                loader=ArtifactLoaderRef(
                    path="project/loaders/bytes_file.py",
                    symbol="load",
                    sha256=hashlib.sha256(
                        source_files["project/loaders/bytes_file.py"]
                    ).hexdigest(),
                    bytes=len(source_files["project/loaders/bytes_file.py"]),
                ),
                data_role="training",
            ),
            RESUME_STATE: SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/models/tiny/resume_state.bin",
                loader=ArtifactLoaderRef(
                    path="project/loaders/resume_state.py",
                    symbol="load",
                    sha256=hashlib.sha256(
                        source_files["project/loaders/resume_state.py"]
                    ).hexdigest(),
                    bytes=len(source_files["project/loaders/resume_state.py"]),
                ),
                data_role="training",
            ),
        },
    )
    draft_root = tmp_path / "drafts"
    draft_root.mkdir()
    train_draft = draft_root / "train.yaml"
    train_draft.write_bytes(serialize_document(train))
    frozen = freeze_run_plan(
        root,
        RunPlanDraft(
            run_id=RUN_ID,
            experiment_id="example",
            variant_id="baseline",
            replicate_id="r1",
            seed=7,
            source=source,
            environment=environment,
            reproducibility=reproducibility(),
            stages=(StageDraft(stage_id="train", spec_source=train_draft),),
            estimator=StageArtifactRef(
                stage_id="train",
                artifact_name=PARAMETERS,
            ),
        ),
    )
    run_git(root, "add", "experiments/example/runs")
    run_git(root, "commit", "--quiet", "-m", "plan")

    result = execute_run(root, frozen.files[-1])

    assert result.resolved_run.status == "succeeded"
    store = LocalArtifactStore(root)
    verified = verify_run_result(
        result.resolved_run,
        policy=VerificationPolicy(trusted_source_repositories=frozenset({REPOSITORY})),
        fetcher=RunFetcher(root, store, REPOSITORY),
    )

    resolved_train = verified.resolved_stages["train"]
    assert isinstance(resolved_train, ResolvedTrainSpec)
    resolved_input = resolved_train.inputs["prior"]

    assert isinstance(resolved_input, ResolvedExternalInputRef)
    expected_path = captured_input_path(
        run_id=RUN_ID,
        attempt_id=verified.attempts[-1].attempt_id,
        stage_id="train",
        input_name="prior",
        source_path="inputs/raw/prior.bin",
    )
    assert resolved_input.file.path == expected_path
    assert (root / expected_path).read_bytes() == b"prior"


def test_local_input_is_captured_by_attempt(tmp_path: Path) -> None:
    """Copy one declared source to its canonical attempt-owned path."""
    root = tmp_path / "project"
    source = root / "inputs/raw/dataset.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"dataset")
    workspace = AttemptWorkspace.create(root / ".viper/workspaces", RUN_ID, 1)
    declared = ExternalInputRef(
        source=LocalSource(path="inputs/raw/dataset.bin"),
        data_role="training",
    )

    resolved, captured = capture_external_input(
        root,
        workspace,
        run_id=RUN_ID,
        attempt_id=1,
        stage_id="train",
        input_name="dataset",
        input_ref=declared,
    )

    expected = captured_input_path(
        run_id=RUN_ID,
        attempt_id=1,
        stage_id="train",
        input_name="dataset",
        source_path=declared.source.path,
    )
    assert captured == root / expected
    assert captured.read_bytes() == b"dataset"
    assert resolved.source == declared.source
    assert resolved.file.path == expected
    assert resolved.file.sha256 == hashlib.sha256(b"dataset").hexdigest()
    assert resolved.file.bytes == len(b"dataset")


def test_local_input_rejects_symlink_escape(tmp_path: Path) -> None:
    """Reject a declared source link before VIPER reads outside bytes."""
    root = tmp_path / "project"
    source = root / "inputs/raw/dataset.bin"
    source.parent.mkdir(parents=True)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    source.symlink_to(outside)
    workspace = AttemptWorkspace.create(root / ".viper/workspaces", RUN_ID, 1)

    with pytest.raises(RunError, match="input.local.capture"):
        capture_external_input(
            root,
            workspace,
            run_id=RUN_ID,
            attempt_id=1,
            stage_id="train",
            input_name="dataset",
            input_ref=ExternalInputRef(
                source=LocalSource(path="inputs/raw/dataset.bin"),
                data_role="training",
            ),
        )


def test_local_input_mutation_fails_attempt(tmp_path: Path) -> None:
    """Reject a captured input whose bytes change during stage execution."""
    root = tmp_path / "project"
    source = root / "inputs/raw/dataset.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"dataset")
    workspace = AttemptWorkspace.create(root / ".viper/workspaces", RUN_ID, 1)
    resolved, captured = capture_external_input(
        root,
        workspace,
        run_id=RUN_ID,
        attempt_id=1,
        stage_id="train",
        input_name="dataset",
        input_ref=ExternalInputRef(
            source=LocalSource(path="inputs/raw/dataset.bin"),
            data_role="training",
        ),
    )
    captured.write_bytes(b"changed")

    with pytest.raises(RunError, match="input.local.identity"):
        verify_captured_inputs(root, {"dataset": resolved.file})


def test_attempt_rechecks_and_publishes_captured_local_inputs() -> None:
    """Keep the post-process identity check before snapshot publication."""
    source = inspect.getsource(execute_attempt)
    tree = ast.parse(source)
    call_lines: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        else:
            continue
        call_lines.setdefault(name, []).append(node.lineno)

    stage_exit = min(call_lines["execute_stage_process"])
    custody_check = min(call_lines["verify_captured_inputs"])
    resolution = min(call_lines["resolve_stage"])
    publication = min(call_lines["publish"])

    assert stage_exit < custody_check < resolution < publication
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "verify_captured_inputs"
        for handler in ast.walk(tree)
        if isinstance(handler, ast.ExceptHandler)
        for node in ast.walk(handler)
    )
    exception_lines = {
        node.lineno
        for handler in ast.walk(tree)
        if isinstance(handler, ast.ExceptHandler)
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "verify_captured_inputs"
    }
    assert any(
        line not in exception_lines for line in call_lines["verify_captured_inputs"]
    )
    assert "for reference in captured_inputs.values()" in source


def test_run_many_retains_one_result_per_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bound active runs and preserve success, failure, and skip positions."""
    paths = tuple(tmp_path / f"{name}.yaml" for name in ("first", "second", "third"))
    run_ids = (
        "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "01ARZ3NDEKTSV4RRFFQ69G5FAW",
        "01ARZ3NDEKTSV4RRFFQ69G5FAX",
    )
    specs = {
        path: RunSpec.model_construct(
            run_id=run_id,
            variant_id="baseline",
            replicate_id=f"replicate_{index}",
        )
        for index, (path, run_id) in enumerate(zip(paths, run_ids, strict=True), 1)
    }
    monkeypatch.setattr(
        _batch,
        "_load_run_spec",
        lambda root, path: (path, specs[path]),
    )
    lock = threading.Lock()
    active = 0
    maximum = 0

    def execute(root: Path, path: Path, **kwargs) -> RunResult:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02 if path == paths[0] else 0.01)
        with lock:
            active -= 1
        if path == paths[1]:
            raise RunError("planned failure")
        return RunResult.model_construct(
            resolved_run_path=path.with_suffix(".resolved.yaml"),
            journal_path=path.with_suffix(".jsonl"),
        )

    monkeypatch.setattr(_batch, "execute_run", execute)

    continued = _batch.run_many(tmp_path, paths, max_concurrency=2)
    assert maximum == 2
    assert tuple(item.status for item in continued.runs) == (
        "succeeded",
        "failed",
        "succeeded",
    )
    assert tuple(item.run_spec_path for item in continued.runs) == paths

    stopped = _batch.run_many(
        tmp_path,
        paths,
        max_concurrency=1,
        stop_on_failure=True,
    )
    assert tuple(item.status for item in stopped.runs) == (
        "succeeded",
        "failed",
        "skipped",
    )


def test_verified_reuse_skips_stage_process(tmp_path: Path) -> None:
    """Reuse verified output without invoking the project stage a second time."""
    root = tmp_path / "project"
    root.mkdir()
    run_git(root, "init", "--quiet")
    run_git(root, "config", "user.email", "viper@example.com")
    run_git(root, "config", "user.name", "VIPER Test")
    run_git(root, "remote", "add", "origin", REPOSITORY)

    source = root / "project/plan.py"
    source.parent.mkdir()
    source.write_text(
        "from pathlib import Path\n"
        "from viper import params\n"
        "from viper.metrics import metric\n"
        "from viper.stages import Context, train\n\n"
        "@metric(metric_id='loss', mode='live')\n"
        "def loss(context, values):\n"
        "    return sum(values) / len(values)\n\n"
        "@train(params=params.Train)\n"
        "def train_model(context: Context[params.Train]):\n"
        "    marker = Path('worker_calls.txt')\n"
        "    marker.write_text(marker.read_text() + '1\\n' if marker.exists() "
        "else '1\\n')\n"
        "    model = context.artifacts['model']\n"
        "    model.parent.mkdir(parents=True, exist_ok=True)\n"
        "    model.write_bytes(context.inputs['dataset'].read_bytes())\n"
        "    context.artifacts['state'].write_bytes(b'state')\n"
        "    context.metrics['loss'].record([1.0], epoch=0, step=1)\n\n"
        "def load(path):\n"
        "    return path.read_bytes()\n\n"
        "def load_state(path):\n"
        "    return path.read_bytes()\n",
        encoding="utf-8",
    )
    dataset = root / "inputs/raw/dataset.bin"
    dataset.parent.mkdir(parents=True)
    dataset.write_bytes(b"dataset")
    (root / "environment.yml").write_text("name: viper-test\n", encoding="utf-8")
    (root / "viper.toml").write_text("[project]\nschema_version = 1\n")
    run_git(root, "add", ".")
    run_git(root, "commit", "--quiet", "-m", "source")
    source_commit = run_git(root, "rev-parse", "HEAD")

    module_spec = importlib.util.spec_from_file_location("project.plan", source)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    loss = measure(module.loss, params=current_params.Metric())
    trained = stage(
        module.train_model,
        params=current_params.Train(),
        inputs={
            "dataset": external_input(
                path="inputs/raw/dataset.bin",
                data_role="training",
            )
        },
        artifacts={
            "model": artifact(
                path="artifacts/models/toy/model.bin",
                loader=module.load,
                data_role="training",
            ),
            "state": artifact(
                path="artifacts/models/toy/state.bin",
                loader=module.load_state,
                data_role="training",
            ),
        },
        metrics=(loss,),
        objective=minimize(loss),
        reuse="verified",
    )
    authored = experiment(
        experiment_id="reuse",
        variants={
            "baseline": variant(
                levels={},
                stages={"train": trained},
                estimator=trained.artifacts["model"],
            )
        },
        replicates={"r1": replicate(seed=7)},
    )
    source_ref = GitSource.model_validate(
        {"repository": REPOSITORY, "commit": source_commit}
    )
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source_ref.repository,
            commit=source_commit,
            path="environment.yml",
        ),
        python_env=python_environment(),
    )

    first_plan = plan(
        experiment=authored,
        variant="baseline",
        replicate="r1",
        source=source_ref,
        env=environment,
        reproducibility=reproducibility(),
    )
    first_frozen = freeze_run_plan(root, first_plan)
    first = execute_attempt(
        root,
        first_frozen.files[-1],
        plan=first_frozen.reference,
    )
    assert isinstance(first, RunResult)
    store = LocalArtifactStore(root)
    fetcher = RunFetcher(root, store, REPOSITORY)
    policy = VerificationPolicy(trusted_source_repositories=frozenset({REPOSITORY}))
    first_verified = verify_run_result(
        first.resolved_run,
        policy=policy,
        fetcher=fetcher,
    )
    Catalog(root).refresh(
        runs=(
            CatalogRunSource(
                reference=first.resolved_run_ref,
                verified=first_verified,
                reuse_candidates=catalog_reuse_candidates(
                    first.resolved_run_ref,
                    first_verified,
                ),
            ),
        )
    )

    second_plan = plan(
        experiment=authored,
        variant="baseline",
        replicate="r1",
        source=source_ref,
        env=environment,
        reproducibility=reproducibility(),
    )
    second_frozen = freeze_run_plan(root, second_plan)
    second = execute_attempt(
        root,
        second_frozen.files[-1],
        plan=second_frozen.reference,
    )
    assert isinstance(second, RunResult)
    second_verified = verify_run_result(
        second.resolved_run,
        policy=policy,
        fetcher=fetcher,
    )
    reused_train = second_verified.resolved_stages["train"]
    assert isinstance(reused_train, ResolvedTrainSpec)
    completion = reused_train.completion

    assert isinstance(completion, ReusedStageCompletion)
    assert second_verified.attempts[-1].invocations == ()
    assert (root / "worker_calls.txt").read_text(encoding="utf-8") == "1\n"
    assert tuple(second_verified.reuse) == ("train",)
