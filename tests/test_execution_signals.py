"""Acceptance tests for signal-driven cancellation and preemption evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import torch

from tests.fixtures import (
    builtin_http,
    http_policy,
    http_request,
    python_environment,
    reproducibility,
    resume_state,
)
from viper import _subprocess as subprocess
from viper import parameters
from viper._schema import (
    PARAMETERS,
    RESUME_STATE,
)
from viper._verification.attempt import _verify_stage_invocation, verify_attempt_stages
from viper._verification.storage import read_attempt_reference
from viper.artifacts import (
    ArtifactLoaderRef,
    SingleFileArtifactSpec,
    StageArtifactRef,
)
from viper.authoring import RunPlanDraft, StageDraft, freeze_run_plan
from viper.execution import run as execute_run
from viper.execution._source import RunFetcher
from viper.experiments import (
    ExperimentSpec,
    ReplicateSpec,
    TrainVariantStageParams,
    VariantSpec,
)
from viper.inputs import FutureInputRef
from viper.journal import DurableJournal
from viper.parameters import ParameterModelRef
from viper.preflight import preflight_plan
from viper.references import (
    GitFileRef,
    GitSource,
    ResolvedStageInvocationRef,
)
from viper.runs import (
    ResolvedRun,
    RunSpec,
)
from viper.runtime import (
    CPUBackendContext,
    CPUComputeSpec,
    CUDABackendContext,
    CUDAComputeSpec,
    LocalEnvironmentSpec,
)
from viper.serialization import document_digest, parse_yaml_bytes, serialize_document
from viper.stages import (
    DownloadSpec,
    ResolvedTrainSpec,
    StageImplementationRef,
    StageInvocationReceipt,
    TrainSpec,
)
from viper.storage import LocalArtifactStore
from viper.verification import verify_run_result
from viper.verification.models import VerificationError, VerificationPolicy

REPOSITORY = "https://github.com/example/viper-signal-project"
RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
RUN_ROOT = f"experiments/signals/runs/baseline/{RUN_ID}"


@pytest.fixture
def signal_http_source() -> Iterator[tuple[str, int]]:
    """Serve the immutable input consumed by the completed first stage."""

    class Handler(BaseHTTPRequestHandler):
        """Return one exact response body for the signal acceptance plan."""

        def do_GET(self) -> None:
            """Serve the selected body at its single declared path."""
            if self.path != "/prior":
                self.send_error(404)
                return
            body = b"prior"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """Suppress request logs inside test output."""

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
    """Run one successful Git command in the isolated test repository."""
    return subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_source_files(root: Path, *, blocking: bool = True) -> dict[str, bytes]:
    """Write the two stage callables and their supporting project code."""
    train_operation = (
        b"    output_root = context.artifacts['parameters'].parent\n"
        b"    output_root.mkdir(parents=True, exist_ok=True)\n"
        b"    child = subprocess.Popen(\n"
        b"        [sys.executable, '-c', 'import time; time.sleep(300)']\n"
        b"    )\n"
        b"    (output_root / 'worker-pids.txt').write_text(\n"
        b"        f'{os.getpid()}\\n{child.pid}\\n', encoding='utf-8'\n"
        b"    )\n"
        b"    print('blocking train started', flush=True)\n"
        b"    while True:\n"
        b"        time.sleep(1)\n"
        if blocking
        else (
            b"    import torch\n"
            b"    assert context.inputs['prior'].read_bytes() == b'prior'\n"
            b"    device = 'cuda' if torch.cuda.is_available() else 'cpu'\n"
            b"    values = torch.tensor([2.0, 3.0], device=device)\n"
            b"    result = values.square().sum().item()\n"
            b"    context.artifacts['parameters'].parent.mkdir(\n"
            b"        parents=True, exist_ok=True\n"
            b"    )\n"
            b"    context.artifacts['parameters'].write_bytes(\n"
            b"        f'{device}:{result}'.encode()\n"
            b"    )\n"
            b"    context.artifacts['resume_state'].write_bytes(b'resume')\n"
        )
    )
    source_files = {
        "viper.toml": b"[project]\nschema_version = 1\n",
        "environment.yml": b"name: viper-signal-test\n",
        "project/loaders/bytes_file.py": (
            b"def load(path):\n    return path.read_bytes()\n"
        ),
        "project/loaders/resume_state.py": (
            "def load(path):\n"
            f"    return {resume_state().model_dump(mode='python')!r}\n"
        ).encode(),
        "project/parameters/train.py": (
            b"from viper import parameters\n\n"
            b"class SignalTrainParameters(parameters.Train):\n"
            b'    """Validate this fixture\'s training parameters."""\n'
        ),
        "jobs/train.py": (
            b"import os\n"
            b"import subprocess\n"
            b"import sys\n"
            b"import time\n\n"
            b"from project.parameters.train import SignalTrainParameters\n"
            b"from viper.api import run\n"
            b"from viper.stages import train\n\n"
            b"@train(params=SignalTrainParameters)\n"
            b"def train(context):\n"
            + train_operation
            + b"\nif __name__ == '__main__':\n"
            b"    run(train)\n"
        ),
    }
    for relative_path, raw in source_files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return source_files


def _freeze_signal_plan(
    root: Path,
    source_files: dict[str, bytes],
    host: str,
    port: int,
    *,
    compute: CPUComputeSpec | CUDAComputeSpec | None = None,
) -> Path:
    """Freeze one download-then-blocking-train plan for a real coordinator."""
    experiment = ExperimentSpec(
        experiment_id="signals",
        factors=(),
        variant_ids=("baseline",),
        replicates=(ReplicateSpec(replicate_id="r1", seed=7),),
        metrics=(),
    )
    variant = VariantSpec(
        experiment_id="signals",
        variant_id="baseline",
        levels={},
        stage_params=(
            TrainVariantStageParams(stage_id="train", params=parameters.Train()),
        ),
    )
    experiment_path = root / "experiments/signals/spec.yaml"
    variant_path = root / "experiments/signals/variants/baseline.spec.yaml"
    experiment_path.parent.mkdir(parents=True, exist_ok=True)
    variant_path.parent.mkdir(parents=True, exist_ok=True)
    experiment_path.write_bytes(serialize_document(experiment))
    variant_path.write_bytes(serialize_document(variant))
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "source")
    source_commit = _git(root, "rev-parse", "HEAD")

    source = GitSource.model_validate(
        {"repository": REPOSITORY, "commit": source_commit}
    )
    environment = LocalEnvironmentSpec(
        compute=CPUComputeSpec() if compute is None else compute,
        lockfile=GitFileRef.model_validate(
            {
                "repository": REPOSITORY,
                "commit": source_commit,
                "path": "environment.yml",
            }
        ),
        python_environment=python_environment(),
    )
    bytes_loader = ArtifactLoaderRef(
        path="project/loaders/bytes_file.py",
        symbol="load",
        sha256=hashlib.sha256(
            source_files["project/loaders/bytes_file.py"]
        ).hexdigest(),
        bytes=len(source_files["project/loaders/bytes_file.py"]),
    )
    resume_loader = ArtifactLoaderRef(
        path="project/loaders/resume_state.py",
        symbol="load",
        sha256=hashlib.sha256(
            source_files["project/loaders/resume_state.py"]
        ).hexdigest(),
        bytes=len(source_files["project/loaders/resume_state.py"]),
    )
    download = DownloadSpec(
        inputs={
            "prior": http_request(
                url=f"http://{host}:{port}/prior",
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
                loader=bytes_loader,
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
            path="project/parameters/train.py",
            symbol="SignalTrainParameters",
            sha256=hashlib.sha256(
                source_files["project/parameters/train.py"]
            ).hexdigest(),
            bytes=len(source_files["project/parameters/train.py"]),
        ),
        inputs={
            "prior": FutureInputRef(
                producer_stage_id="download",
                producer_artifact="prior",
            )
        },
        params=parameters.Train(),
        artifacts={
            PARAMETERS: SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/models/tiny/parameters.bin",
                loader=bytes_loader,
                data_role="training",
            ),
            RESUME_STATE: SingleFileArtifactSpec(
                path=f"{RUN_ROOT}/artifacts/models/tiny/resume_state.bin",
                loader=resume_loader,
                data_role="training",
            ),
        },
    )
    draft_root = root.parent / "drafts"
    draft_root.mkdir()
    download_draft = draft_root / "download.yaml"
    train_draft = draft_root / "train.yaml"
    download_draft.write_bytes(serialize_document(download))
    train_draft.write_bytes(serialize_document(train))
    frozen = freeze_run_plan(
        root,
        RunPlanDraft(
            run_id=RUN_ID,
            experiment_id="signals",
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
    _git(root, "add", f"experiments/signals/runs/baseline/{RUN_ID}")
    _git(root, "commit", "--quiet", "-m", "plan")
    return frozen.files[-1]


@pytest.mark.live_cuda
@pytest.mark.skipif(
    os.environ.get("VIPER_LIVE_CUDA") != "1",
    reason="set VIPER_LIVE_CUDA=1 to run live CUDA acceptance",
)
@pytest.mark.parametrize(
    ("compute", "expected_backend_type", "expected_artifact"),
    (
        (CPUComputeSpec(), CPUBackendContext, b"cpu:13.0"),
        (
            CUDAComputeSpec(model="NVIDIA L4", count=1),
            CUDABackendContext,
            b"cuda:13.0",
        ),
    ),
    ids=("cpu-on-l4-host", "cuda-on-l4"),
)
def test_live_l4_stage_records_requested_backend(
    tmp_path: Path,
    signal_http_source: tuple[str, int],
    compute: CPUComputeSpec | CUDAComputeSpec,
    expected_backend_type: type[CPUBackendContext] | type[CUDABackendContext],
    expected_artifact: bytes,
) -> None:
    """Execute and verify separate CPU and CUDA plans on the L4 host."""
    assert torch.cuda.is_available()

    root = tmp_path / compute.kind
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "viper@example.com")
    _git(root, "config", "user.name", "VIPER Test")
    _git(root, "remote", "add", "origin", REPOSITORY)

    source_files = _write_source_files(root, blocking=False)
    run_path = _freeze_signal_plan(
        root,
        source_files,
        *signal_http_source,
        compute=compute,
    )

    result = execute_run(root, run_path)
    store = LocalArtifactStore(root)
    fetcher = RunFetcher(root, store, REPOSITORY)
    verified = verify_run_result(
        result.resolved_run,
        policy=VerificationPolicy(trusted_source_repositories=frozenset({REPOSITORY})),
        fetcher=fetcher,
    )

    train_result = verified.resolved_stages["train"]
    assert isinstance(train_result, ResolvedTrainSpec)
    backend = train_result.execution_context.backend

    assert result.resolved_run.status == "succeeded"
    assert verified.attempts[-1].status == "succeeded"
    assert isinstance(backend, expected_backend_type)
    assert train_result.startup.environment["CUDA_VISIBLE_DEVICES"] == (
        "" if compute.kind == "cpu" else "0"
    )

    if isinstance(backend, CUDABackendContext):
        assert len(backend.gpu_devices) == 1
        assert backend.gpu_devices[0].model == "NVIDIA L4"

    parameters_path = root / RUN_ROOT / "artifacts/models/tiny/parameters.bin"
    assert parameters_path.read_bytes() == expected_artifact


def _wait_for_file(path: Path, timeout_seconds: float = 30) -> None:
    """Wait until the blocking stage records its process identities."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def _wait_for_process_exit(pid: int, timeout_seconds: float = 10) -> None:
    """Wait until one interrupted worker or descendant no longer exists."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise AssertionError(f"process {pid} survived coordinator interruption")


@pytest.mark.parametrize(
    ("signal_number", "expected_status", "expected_code"),
    (
        (signal.SIGINT, "cancelled", "cancelled"),
        (signal.SIGTERM, "preempted", "preempted"),
    ),
    ids=("sigint-cancelled", "sigterm-preempted"),
)
def test_signal_closes_attempt_with_active_stage_evidence(
    tmp_path: Path,
    signal_http_source: tuple[str, int],
    signal_number: signal.Signals,
    expected_status: str,
    expected_code: str,
) -> None:
    """Stop a real coordinator and preserve its completed prefix and active child."""
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "viper@example.com")
    _git(root, "config", "user.name", "VIPER Test")
    _git(root, "remote", "add", "origin", REPOSITORY)
    source_files = _write_source_files(root)
    run_path = _freeze_signal_plan(
        root,
        source_files,
        *signal_http_source,
    )
    pid_path = root / RUN_ROOT / "artifacts/models/tiny/worker-pids.txt"
    process = subprocess.Popen(
        (
            sys.executable,
            "-m",
            "viper.cli",
            "--json",
            "run",
            str(run_path),
            "--root",
            str(root),
        ),
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _wait_for_file(pid_path)
        worker_pids = tuple(
            int(value) for value in pid_path.read_text(encoding="utf-8").splitlines()
        )
        os.kill(process.pid, signal_number)
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()

    assert process.returncode == 1
    assert stderr == b""
    assert json.loads(stdout)["code"] == "execution_failed"
    for worker_pid in worker_pids:
        _wait_for_process_exit(worker_pid)

    run = ResolvedRun.model_validate(
        parse_yaml_bytes((root / RUN_ROOT / "resolved.yaml").read_bytes())
    )
    run_spec = RunSpec.model_validate(parse_yaml_bytes(run_path.read_bytes()))
    store = LocalArtifactStore(root)
    fetcher = RunFetcher(root, store, REPOSITORY)
    attempt = read_attempt_reference(
        run.attempts[-1],
        run_spec,
        fetcher=fetcher,
    )
    assert attempt.status == expected_status
    assert attempt.failure is not None
    assert attempt.failure.code == expected_code
    assert tuple(stage.stage_id for stage in attempt.resolved_stages) == ("download",)
    assert len(attempt.invocations) == 1
    interrupted_receipt = StageInvocationReceipt.model_validate(
        parse_yaml_bytes(store.fetch(attempt.invocations[-1].stored_at))
    )
    assert interrupted_receipt.context.stage_id == "train"
    assert interrupted_receipt.outcome == expected_status
    log_paths = {reference.stored_at.path for reference in attempt.log_files}
    assert f"{RUN_ROOT}/attempts/1/logs/train.stdout.log" in log_paths
    assert f"{RUN_ROOT}/attempts/1/logs/train.stderr.log" in log_paths
    stdout_ref = next(
        reference
        for reference in attempt.log_files
        if reference.stored_at.path.endswith("train.stdout.log")
    )
    assert store.fetch(stdout_ref.stored_at) == b"blocking train started\n"
    journal_entry = DurableJournal(
        root / ".viper/workspaces" / RUN_ID / "attempt-1/control/journal.jsonl"
    ).latest()
    assert journal_entry is not None
    assert journal_entry.state == "terminal"
    verified = verify_run_result(
        run,
        policy=VerificationPolicy(trusted_source_repositories=frozenset({REPOSITORY})),
        fetcher=fetcher,
    )
    assert verified.attempts[-1] == attempt


def test_python_adapter_and_cli_share_verification_boundary(
    tmp_path: Path,
    signal_http_source: tuple[str, int],
) -> None:
    """Execute one frozen plan through both public coordinator interfaces."""
    python_root = tmp_path / "python-project"
    python_root.mkdir()
    _git(python_root, "init", "--quiet")
    _git(python_root, "config", "user.email", "viper@example.com")
    _git(python_root, "config", "user.name", "VIPER Test")
    _git(python_root, "remote", "add", "origin", REPOSITORY)
    source_files = _write_source_files(python_root, blocking=False)
    python_run_path = _freeze_signal_plan(
        python_root,
        source_files,
        *signal_http_source,
    )
    cli_root = tmp_path / "cli-project"
    shutil.copytree(python_root, cli_root)
    cli_run_path = cli_root / python_run_path.relative_to(python_root)
    python_environment = os.environ.copy()
    package_root = Path(__file__).resolve().parents[1]
    current_python_path = python_environment.get("PYTHONPATH")
    python_path_parts = [str(python_root), str(package_root)]
    if current_python_path is not None:
        python_path_parts.append(current_python_path)
    python_environment["PYTHONPATH"] = os.pathsep.join(python_path_parts)

    python_process = subprocess.run(
        (
            sys.executable,
            str(python_root / "jobs/train.py"),
            "--run",
            str(python_run_path),
            "--stage",
            "train",
            "--root",
            str(python_root),
        ),
        cwd=package_root,
        env=python_environment,
        check=False,
        capture_output=True,
    )
    cli_process = subprocess.run(
        (
            sys.executable,
            "-m",
            "viper.cli",
            "--json",
            "run",
            str(cli_run_path),
            "--root",
            str(cli_root),
        ),
        cwd=package_root,
        check=False,
        capture_output=True,
    )

    assert python_process.returncode == 0, python_process.stderr.decode()
    assert cli_process.returncode == 0, cli_process.stdout.decode()
    assert json.loads(cli_process.stdout)["status"] == "ok"
    verified_runs = []
    for root in (python_root, cli_root):
        resolved = ResolvedRun.model_validate(
            parse_yaml_bytes((root / RUN_ROOT / "resolved.yaml").read_bytes())
        )
        store = LocalArtifactStore(root)
        verified_runs.append(
            verify_run_result(
                resolved,
                policy=VerificationPolicy(
                    trusted_source_repositories=frozenset({REPOSITORY})
                ),
                fetcher=RunFetcher(root, store, REPOSITORY),
            )
        )
    assert verified_runs[0].plan.run == verified_runs[1].plan.run
    assert (
        verified_runs[0].result.status == verified_runs[1].result.status == "succeeded"
    )
    assert set(verified_runs[0].resolved_stages) == {"download", "train"}
    assert set(verified_runs[1].resolved_stages) == {"download", "train"}
    assert (
        verified_runs[0].resolved_stages["train"].artifacts
        == verified_runs[1].resolved_stages["train"].artifacts
    )

    verified = verified_runs[0]
    attempt = verified.attempts[-1]
    stage = verified.plan.stages["train"]
    assert isinstance(stage, TrainSpec)
    original_reference = attempt.invocations[-1]
    original_receipt = StageInvocationReceipt.model_validate(
        parse_yaml_bytes(
            LocalArtifactStore(python_root).fetch(original_reference.stored_at)
        )
    )
    fetcher = RunFetcher(
        python_root,
        LocalArtifactStore(python_root),
        REPOSITORY,
    )

    def publish_receipt(
        receipt: StageInvocationReceipt,
    ) -> ResolvedStageInvocationRef:
        """Publish one changed receipt at the canonical path for rejection."""
        reference = LocalArtifactStore(python_root).resolved_files(
            {
                original_reference.stored_at.path: serialize_document(receipt),
            }
        )[0]
        return ResolvedStageInvocationRef(
            sha256=reference.sha256,
            bytes=reference.bytes,
            stored_at=reference.stored_at,
        )

    changed_implementation = original_receipt.model_copy(
        update={
            "implementation": original_receipt.implementation.model_copy(
                update={"sha256": "f" * 64}
            )
        }
    )
    with pytest.raises(VerificationError, match="different implementation"):
        _verify_stage_invocation(
            publish_receipt(changed_implementation),
            attempt=attempt,
            run=verified.plan.run,
            stage_id="train",
            stage=stage,
            stage_specs=verified.plan.stages,
            resolved_stage=verified.resolved_stages["train"],
            fetcher=fetcher,
        )

    changed_parameter_binding = original_receipt.context.model_copy(
        update={"parameter_digest": "f" * 64}
    )
    changed_parameters = original_receipt.model_copy(
        update={
            "context": changed_parameter_binding,
            "context_digest": document_digest(changed_parameter_binding),
        }
    )
    with pytest.raises(VerificationError, match="context differs"):
        _verify_stage_invocation(
            publish_receipt(changed_parameters),
            attempt=attempt,
            run=verified.plan.run,
            stage_id="train",
            stage=stage,
            stage_specs=verified.plan.stages,
            resolved_stage=verified.resolved_stages["train"],
            fetcher=fetcher,
        )

    changed_context_binding = original_receipt.context.model_copy(
        update={"stage_id": "download"}
    )
    changed_context = original_receipt.model_copy(
        update={
            "context": changed_context_binding,
            "context_digest": document_digest(changed_context_binding),
        }
    )
    with pytest.raises(VerificationError, match="context differs"):
        _verify_stage_invocation(
            publish_receipt(changed_context),
            attempt=attempt,
            run=verified.plan.run,
            stage_id="train",
            stage=stage,
            stage_specs=verified.plan.stages,
            resolved_stage=verified.resolved_stages["train"],
            fetcher=fetcher,
        )

    duplicate_attempt = attempt.model_copy(
        update={
            "invocations": (*attempt.invocations, attempt.invocations[-1]),
        }
    )
    with pytest.raises(VerificationError, match="more invocations than planned"):
        verify_attempt_stages(
            duplicate_attempt,
            verified.plan.run,
            verified.plan.stages,
            require_complete=True,
            policy=VerificationPolicy(
                trusted_source_repositories=frozenset({REPOSITORY})
            ),
            fetcher=fetcher,
        )


@pytest.mark.parametrize(
    ("compute", "expected_code"),
    (
        (
            CUDAComputeSpec(model="VIPER unavailable test device", count=1),
            "startup.compute",
        ),
        (
            CUDAComputeSpec(model="VIPER unavailable test device", count=2),
            "startup.distributed",
        ),
    ),
    ids=("unavailable-cuda", "multi-gpu"),
)
def test_preflight_rejects_unsupported_cuda_requests(
    tmp_path: Path,
    signal_http_source: tuple[str, int],
    compute: CUDAComputeSpec,
    expected_code: str,
) -> None:
    """Reject unavailable and multi-device requests through named checks."""
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "viper@example.com")
    _git(root, "config", "user.name", "VIPER Test")
    _git(root, "remote", "add", "origin", REPOSITORY)
    source_files = _write_source_files(root, blocking=False)
    run_path = _freeze_signal_plan(
        root,
        source_files,
        *signal_http_source,
        compute=compute,
    )

    report = preflight_plan(root, run_path)

    failures = {check.code for check in report.checks if check.status == "failure"}
    assert expected_code in failures
