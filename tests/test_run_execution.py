"""Acceptance test for a complete two-stage trusted-local VIPER run."""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.fixtures import (
    builtin_http_transport,
    http_policy,
    http_request,
    python_environment,
    reproducibility,
    resume_state,
)
from viper import parameters
from viper import run as run_stage
from viper._schema import (
    PARAMETERS,
    RESUME_STATE,
)
from viper.application import CompareRunsRequest, RunSuccess
from viper.application import compare_runs as compare_runs_application
from viper.artifacts import (
    ArtifactLoaderRef,
    SingleFileArtifactSpec,
    StageArtifactRef,
)
from viper.authoring import RunPlanDraft, StageDraft, freeze_run_plan
from viper.execution import RunError, RunFetcher, execute_benchmark_confirmation
from viper.execution import run as execute_run
from viper.experiments import (
    DownloadVariantStageParams,
    ExperimentSpec,
    ReplicateSpec,
    TrainVariantStageParams,
    VariantSpec,
)
from viper.journal import DurableJournal
from viper.local_store import LocalArtifactStore
from viper.metric_execution import MetricWorkerResult
from viper.metrics import (
    FloatComparator,
    Measurement,
    MetricDependency,
    MetricImplementationRef,
    MetricSpec,
)
from viper.parameters import ParameterModelRef
from viper.references import (
    GitFileRef,
    GitSource,
    HuggingFaceFileRef,
)
from viper.runs import (
    ResolvedRun,
    RunSpec,
)
from viper.runtime import (
    CUDAComputeSpec,
    GCEEnvironmentSpec,
    LocalEnvironmentSpec,
    observe_gce_provisioning,
)
from viper.serialization import parse_yaml_bytes, serialize_document
from viper.stage_execution import StageExecutionError, execute_stage_process
from viper.stages import (
    DownloadSpec,
    FutureInputRef,
    StageImplementationRef,
    TrainSpec,
    load_stage_callable,
)
from viper.verification import (
    VerificationError,
    VerificationPolicy,
    read_attempt_reference,
    verify_run_result,
)
from viper.workspace import AttemptWorkspace

REPOSITORY = "https://github.com/example/viper-local-project"
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


def _git(root: Path, *arguments: str) -> str:
    """Run one successful Git command in the acceptance repository."""
    return subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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
        "viper.execution.fetch_huggingface_file_bytes",
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
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "viper@example.com")
    _git(root, "config", "user.name", "VIPER Test")
    _git(root, "remote", "add", "origin", REPOSITORY)

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
        metric_id="parameter_bytes",
        kind="diagnostic",
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
        metric_id="epoch_mean",
        kind="training",
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
        stage_params=(
            DownloadVariantStageParams(
                stage_id="download",
                params=parameters.Download(),
            ),
            TrainVariantStageParams(stage_id="train", params=train_params),
        ),
    )
    source_files = {
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
        "project/parameters/download.py": (
            b"from viper import parameters\n\n"
            b"class TinyDownloadParameters(parameters.Download):\n"
            b'    """Validate the download parameters used by this project."""\n'
        ),
        "jobs/download.py": (
            b"from project.parameters.download import TinyDownloadParameters\n"
            b"from viper import download_stage\n\n"
            b"@download_stage(parameter_model=TinyDownloadParameters)\n"
            b"def download(context):\n"
            b"    path = context.artifacts['prior']\n"
            b"    path.parent.mkdir(parents=True, exist_ok=True)\n"
            b"    body = context.retrievals['source'].body\n"
            b"    path.write_bytes(body.read_bytes())\n"
        ),
        "jobs/train.py": (
            b"from project.parameters.train import TinyTrainParameters\n"
            b"from viper import train_stage\n\n"
            b"@train_stage(parameter_model=TinyTrainParameters)\n"
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
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "source")
    source_commit = _git(root, "rev-parse", "HEAD")

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
        implementation=StageImplementationRef(
            path="jobs/download.py",
            symbol="download",
            sha256=hashlib.sha256(source_files["jobs/download.py"]).hexdigest(),
            bytes=len(source_files["jobs/download.py"]),
        ),
        parameter_model=ParameterModelRef(
            path="project/parameters/download.py",
            symbol="TinyDownloadParameters",
            sha256=hashlib.sha256(
                source_files["project/parameters/download.py"]
            ).hexdigest(),
            bytes=len(source_files["project/parameters/download.py"]),
        ),
        inputs={
            "source": http_request(
                url=f"http://{host}:{port}/redirect",
                body=b"prior",
            )
        },
        transport=builtin_http_transport(),
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
        params=parameters.Download(),
    )
    train = TrainSpec(
        implementation=StageImplementationRef(
            path="jobs/train.py",
            symbol="train",
            sha256=hashlib.sha256(source_files["jobs/train.py"]).hexdigest(),
            bytes=len(source_files["jobs/train.py"]),
        ),
        parameter_model=ParameterModelRef(
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
                producer_artifact="prior",
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
    _git(root, "add", "experiments/example/runs")
    _git(root, "commit", "--quiet", "-m", "plan")

    requests = []
    monkeypatch.setattr(
        "viper.api.application_run",
        lambda request: (
            requests.append(request)
            or RunSuccess(
                run_id=RUN_ID,
                attempt_id=1,
                resolved_attempt=root / RUN_ROOT / "attempts/1/resolved.yaml",
                resolved_run=root / RUN_ROOT / "resolved.yaml",
                journal=root / ".viper" / "attempt.jsonl",
            )
        ),
    )
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
            "--repository-root",
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

    first_train_call = True

    def fail_first_train(*args, **kwargs):
        """Return real child evidence, then simulate one transient train failure."""
        nonlocal first_train_call
        process = execute_stage_process(*args, **kwargs)
        stage_reference = args[2]
        if stage_reference.stage_id == "train" and first_train_call:
            first_train_call = False
            raise StageExecutionError(
                "transient train failure",
                invocation=process.invocation.model_copy(update={"outcome": "failed"}),
                stdout=process.stdout,
                stderr=b"transient train failure\n",
            )
        return process

    monkeypatch.setattr("viper.execution.execute_stage_process", fail_first_train)
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
    assert len(failed_attempt.invocations) == 2
    assert (root / RUN_ROOT / "attempts/1/resolved.yaml").is_file()
    assert (root / RUN_ROOT / "attempts/2/resolved.yaml").is_file()

    monkeypatch.setattr("viper.execution.execute_stage_process", execute_stage_process)
    result = execute_run(root, frozen.files[-1], retry=True)

    assert result.resolved_run.status == "succeeded"
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
        stage.snapshot.commit for stage in successful_attempt.resolved_stages
    }
    confirmation_snapshots = {
        stage.snapshot.commit for stage in confirmation.attempt.resolved_stages
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
    stored_retrieval = (
        root
        / first_snapshot.store
        / first_snapshot.commit
        / f"{RUN_ROOT}/stages/download/retrievals/source/body"
    )
    stored_retrieval.write_bytes(b"PRIOR")
    with pytest.raises(VerificationError, match="SHA-256 mismatch"):
        verify_run_result(
            result.resolved_run,
            policy=VerificationPolicy(
                trusted_source_repositories=frozenset({REPOSITORY})
            ),
            fetcher=RunFetcher(root, store, REPOSITORY),
        )
