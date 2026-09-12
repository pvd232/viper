"""Execute the public CPU quickstart shown in the repository README."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from tests._documentation import python_blocks
from viper import _subprocess as subprocess
from viper.artifacts import StageArtifactRef
from viper.authoring import run_artifact
from viper.metrics import MeasurementSink, MetricContext, MetricHandle
from viper.references import LocalFileRef, ResolvedRunRef
from viper.repository import RootError, read_source
from viper.resume import load_resume_state
from viper.stages import StageContext

pytest_plugins = ("tests.test_http_retrieval",)


def _run(root: Path, *command: str) -> subprocess.CompletedProcess[str]:
    """Run one command in the temporary quickstart repository."""
    return subprocess.run(
        command,
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize(
    "example",
    (
        "variants.py",
        "evaluation.py",
        "inspect_results.py",
        "stages.py",
        "download_training.py",
        "recovery.py",
    ),
)
def test_extended_examples_execute_complete_workflows(
    tmp_path: Path,
    example: str,
    local_http_server: tuple[str, int, list[tuple[str, str | None]]],
) -> None:
    """Execute documented Python workflows with their source and input dependencies."""
    root = tmp_path / "workspace"
    host, port, received = local_http_server
    shutil.copytree("examples", root / "examples")
    shutil.copy("pyproject.toml", root / "pyproject.toml")
    documents = {
        "variants.py": "docs/how-to/variants-and-replicates.md",
        "inspect_results.py": "docs/tutorials/inspect-results.md",
        "stages.py": "docs/tutorials/stages.md",
    }
    if example in documents:
        # Execute the code readers copy, including its imports and main().
        program = python_blocks(Path(documents[example]).read_text())[0]
        (root / "examples" / example).write_text(program + "\n")
    if example == "download_training.py":
        # Exercise the real HTTP client against a controlled server. Only the
        # endpoint and allowlist change; the declared dataset digest is retained.
        script = root / "examples" / example
        program = script.read_text()
        start = program.index("            url=(")
        end = program.index("            version=", start)
        program = (
            program[:start]
            + f'            url="http://{host}:{port}/tiny.csv",\n'
            + program[end:]
        )
        program = program.replace('frozenset({"https"})', 'frozenset({"http"})')
        program = program.replace(
            'frozenset({"raw.githubusercontent.com"})', f'frozenset({{ "{host}" }})'
        )
        program = program.replace("frozenset({443})", f"frozenset({{{port}}})")
        script.write_text(program)
    (root / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
    _run(root, "git", "init", "--quiet")
    _run(root, "git", "config", "user.email", "viper@example.com")
    _run(root, "git", "config", "user.name", "VIPER Examples")
    _run(root, "git", "remote", "add", "origin", "https://github.com/example/viper")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "--quiet", "-m", "example source")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd() / "src")
    completed = subprocess.run(
        (sys.executable, "-m", f"examples.{Path(example).stem}"),
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    if example == "variants.py":
        assert completed.stdout.count(": succeeded ") == 4, completed.stdout
        weights = [
            json.loads(path.read_text())["weight"]
            for path in root.glob(
                "experiments/training_rows/runs/*/*/artifacts/train/model/model.json"
            )
        ]
        assert len(weights) == 4
        assert len(set(weights)) == 2
    elif example == "evaluation.py":
        assert "benchmark: passed " in completed.stdout
        predictions = list(
            root.glob(
                "experiments/held_out_evaluation/runs/baseline/*/artifacts/eval/predictions/predictions.json"
            )
        )
        assert len(predictions) == 1
        pairs = json.loads(predictions[0].read_text())
        assert [pair[1] for pair in pairs] == [8.0, 12.0]
        assert [pair[0] for pair in pairs] == pytest.approx([8.0, 12.0], abs=0.001)
    elif example == "recovery.py":
        assert "successful attempt: 2" in completed.stdout
        assert "reused run: succeeded" in completed.stdout
        stages = list(
            (root / ".viper/store").glob(
                "*/experiments/recovery/runs/baseline/*/stages/train/resolved.yaml"
            )
        )
        assert any("kind: reused" in path.read_text() for path in stages)
    elif example == "download_training.py":
        assert "result: succeeded" in completed.stdout
        assert ("/tiny.csv", None) in received
        models = list(
            root.glob(
                "experiments/download_training/runs/baseline/*/artifacts/train/model/model.json"
            )
        )
        assert len(models) == 1
        assert json.loads(models[0].read_text())["weight"] == pytest.approx(2, abs=1e-5)
    elif example == "stages.py":
        assert "result: succeeded" in completed.stdout
        runs = list(root.glob("experiments/stage_pipeline/runs/baseline/*"))
        assert len(runs) == 1
        artifacts = runs[0] / "artifacts"
        assert json.loads((artifacts / "embed/features/features.json").read_text()) == [
            [1.0, 1.0],
            [2.0, 4.0],
            [3.0, 9.0],
        ]
        assert (artifacts / "report/report/rows.txt").read_text() == "rows: 3\n"
        assert (
            artifacts / "prepare/dataset/sorted.csv"
        ).read_text() == "x,y\n1,2\n2,4\n3,6\n"
        assert json.loads((artifacts / "train/model/model.json").read_text())[
            "weight"
        ] == pytest.approx(2, abs=1e-5)
    else:
        assert "verified measurements: 20" in completed.stdout
        assert "indexed runs: 2" in completed.stdout
        assert "successful runs: 2" in completed.stdout
        assert "model artifacts: 2" in completed.stdout
        assert "indexed measurements: 40" in completed.stdout
        assert "selected run measurements: 20" in completed.stdout
        assert "observations: 1" in completed.stdout
        restored = list((root / "restored").glob("*.json"))
        assert len(restored) == 1
        assert json.loads(restored[0].read_text())["weight"] == pytest.approx(
            2, abs=1e-5
        )

        # Each how-to block must run with only its displayed imports and paths.
        blocks = python_blocks(Path("docs/how-to/retry-restore-compare.md").read_text())
        runs = sorted(
            root.glob("experiments/cpu_quickstart/runs/baseline/*/resolved.yaml")
        )
        assert len(runs) == 2
        model = runs[0].parent / "artifacts/train/model/model.json"
        expected_model = model.read_bytes()
        model.unlink()
        journals = list(
            root.glob(
                f".viper/store/*/experiments/cpu_quickstart/runs/baseline/"
                f"{runs[0].parent.name}/attempts/1/journal.jsonl"
            )
        )
        assert len(journals) == 1
        for index in (1, 2, 3):
            program = (
                blocks[index]
                .replace("<YOUR_RUN_ID>", runs[0].parent.name)
                .replace("<FIRST_RUN_ID>", runs[0].parent.name)
                .replace("<SECOND_RUN_ID>", runs[1].parent.name)
                .replace("<JOURNAL_PATH>", str(journals[0]))
            )
            observed = _run(root, sys.executable, "-c", program)
            if index == 1:
                assert "restored" in observed.stdout
                assert model.read_bytes() == expected_model


@pytest.mark.parametrize(
    "document", (None, "README.md", "docs/tutorials/getting-started.md")
)
def test_cpu_quickstart_executes_and_verifies_one_run(
    tmp_path: Path, document: str | None
) -> None:
    """Execute the example file and the actual programs printed in the docs."""
    root = tmp_path / "quickstart"
    (root / "examples" / "data").mkdir(parents=True)
    if document is None:
        shutil.copy("examples/cpu_quickstart.py", root / "examples/cpu_quickstart.py")
    else:
        code = "\n\n".join(python_blocks(Path(document).read_text())) + "\n"
        (root / "examples/cpu_quickstart.py").write_text(code)
    shutil.copy("examples/data/tiny.csv", root / "examples/data/tiny.csv")
    shutil.copy("pyproject.toml", root / "pyproject.toml")
    (root / "viper.toml").write_text(
        "[workspace]\nschema_version = 2\n",
        encoding="utf-8",
    )

    _run(root, "git", "init", "--quiet")
    _run(root, "git", "config", "user.email", "viper@example.com")
    _run(root, "git", "config", "user.name", "VIPER Quickstart")
    _run(root, "git", "remote", "add", "origin", "https://github.com/example/viper")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "--quiet", "-m", "quickstart source")

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd() / "src")
    completed = subprocess.run(
        (sys.executable, "examples/cpu_quickstart.py"),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "status: succeeded" in completed.stdout
    assert 'model: {"weight": 1.999' in completed.stdout
    result_line = next(
        line for line in completed.stdout.splitlines() if line.startswith("result: ")
    )
    result_path = root / result_line.removeprefix("result: ")
    assert result_path.is_file()
    measurements = [
        json.loads(line)
        for line in (
            result_path.parent
            / "attempts/1/measurements/train.mean_squared_error.jsonl"
        )
        .read_text()
        .splitlines()
    ]
    assert [item["epoch"] for item in measurements] == list(range(1, 21))
    assert [item["step"] for item in measurements] == list(range(1, 21))
    # For x=(1,2,3), y=2x, each update scales the residual by 8/15.
    expected_losses = [(56 / 3) * (8 / 15) ** (2 * epoch) for epoch in range(20)]
    assert [item["value"] for item in measurements] == pytest.approx(
        expected_losses, rel=1e-8, abs=1e-14
    )
    checkpoint = load_resume_state(
        result_path.parent / "artifacts/train/resume_state/resume_state.pt"
    )
    assert checkpoint.optimizer_state["loss"] == measurements[-1]["value"]


def test_documented_config_stage_writes_the_selected_rows(tmp_path: Path) -> None:
    """Run the printed stage with two configs and inspect its actual output."""
    namespace = {}
    exec(
        python_blocks(Path("docs/reference/configuration.md").read_text())[0], namespace
    )
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n2,4\n3,6\n")
    destination = tmp_path / "limited.csv"
    for count in (1, 2):
        namespace["limit_rows"](
            StageContext(
                run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                attempt_id=1,
                stage_id="build",
                config=namespace["RowLimit"](rows=count),
                inputs={"dataset": source},
                outputs={"dataset": destination},
                metrics={},
                numpy_generators={},
            )
        )
        assert (
            destination.read_text().splitlines() == ["x,y", "1,2", "2,4"][: count + 1]
        )
    with pytest.raises(ValueError):
        namespace["RowLimit"](rows=0)


def test_documented_http_request_identifies_the_example_file() -> None:
    """Validate the printed request and loader against the committed CSV bytes."""
    namespace = {}
    exec(python_blocks(Path("docs/how-to/inputs.md").read_text())[2], namespace)
    request = namespace["fetch_data"].spec.inputs["dataset"]
    source = Path("examples/data/tiny.csv")
    assert (
        request.expected_body_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    )
    assert request.expected_body_bytes == source.stat().st_size
    assert namespace["load_text"](source) == source.read_text(encoding="utf-8")


def test_documented_checkpoint_round_trip(capsys: pytest.CaptureFixture[str]) -> None:
    """Execute the complete checkpoint example as printed in the recovery guide."""
    blocks = python_blocks(Path("docs/how-to/retry-restore-compare.md").read_text())
    exec(blocks[-1], {})
    assert "Restored model and next batch match." in capsys.readouterr().out


def test_documented_evaluation_writes_predictions_and_computes_rmse(
    tmp_path: Path,
) -> None:
    """Execute the printed evaluation and recompute its metric from the output."""
    namespace = {}
    blocks = python_blocks(Path("docs/how-to/stages.md").read_text())
    exec(blocks[2], namespace)
    # Constructor inputs stand in for the earlier run; this check executes evaluation.
    reference = ResolvedRunRef(
        sha256="a" * 64,
        bytes=1,
        stored_at=LocalFileRef(
            workspace=Path("/workspace"),
            store_id="0" * 32,
            commit="b" * 64,
            path="runs/data/resolved.yaml",
        ),
    )
    saved_inputs = {}
    for name in ("test_data", "test_split"):
        saved_inputs[name] = run_artifact(
            reference,
            StageArtifactRef(stage_id="build", artifact_name=name),
            path=f"inputs/{name}.json",
            data_role="benchmark",
        )
    evaluation = namespace["evaluation_stage"](
        saved_inputs["test_data"], saved_inputs["test_split"]
    )
    assert set(evaluation.spec.inputs) == {"model", "test", "holdout"}
    model = tmp_path / "model.json"
    data = tmp_path / "test.csv"
    split = tmp_path / "split.json"
    predictions = tmp_path / "predictions.json"
    model.write_text('{"weight": 2.0}')
    data.write_text("x,y\n1,3\n2,4\n3,7\n")
    split.write_text("[0, 2]")
    namespace["predict"](
        StageContext(
            run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            attempt_id=1,
            stage_id="eval",
            config=namespace["EvalConfig"](),
            inputs={"model": model, "test": data, "holdout": split},
            outputs={"predictions": predictions},
            metrics={},
            numpy_generators={},
        )
    )
    assert json.loads(predictions.read_text()) == [[2.0, 3.0], [6.0, 7.0]]
    metric_context = MetricContext(
        config=namespace["MetricConfig"](), artifacts={"predictions": predictions}
    )
    assert namespace["rmse"].implementation(metric_context) == 1.0

    # The metric guide must consume the evaluation output without relying on
    # imports or objects from another snippet.
    metric_blocks = python_blocks(
        Path("docs/how-to/metrics-and-benchmarks.md").read_text()
    )
    metric_namespace = {}
    rmse_block = next(
        block for block in metric_blocks if "def root_mean_squared_error(" in block
    )
    exec(rmse_block, metric_namespace)
    assert metric_namespace["rmse"].implementation(metric_context) == 1.0
    predictions.write_text("[]")
    with pytest.raises(ValueError, match="at least one prediction"):
        metric_namespace["rmse"].implementation(metric_context)


@pytest.mark.parametrize(
    "block_index, declared", ((0, "prepared"), (1, "embedded"), (3, "report"))
)
def test_documented_stage_declarations_define_their_own_dependencies(
    block_index: int, declared: str
) -> None:
    """Each stage snippet declares successfully without another snippet's variables."""
    block = python_blocks(Path("docs/how-to/stages.md").read_text())[block_index]
    namespace = {}
    exec(block, namespace)
    assert namespace[declared].spec.inputs


_POLICY_VERIFY_PROGRAM = """
import hashlib
import json
import sys
from pathlib import Path

from viper.execution._source import RunFetcher
from viper.runs import ResolvedRun, RunSpec
from viper.serialization import parse_yaml_bytes
from viper.storage import LocalArtifactStore
from viper.verification import verify_run_result
from viper.evidence import VerificationPolicy

root = Path(sys.argv[1])
result = ResolvedRun.model_validate(parse_yaml_bytes(Path(sys.argv[2]).read_bytes()))
store = LocalArtifactStore(root)
run = RunSpec.model_validate(parse_yaml_bytes(store.fetch(result.spec.stored_at)))
fetcher = RunFetcher(root, store, str(run.source.repository))
policy = VerificationPolicy(
    trusted_source_repositories=frozenset({str(run.source.repository)})
)
verified = verify_run_result(result, policy=policy, fetcher=fetcher)
stage = verified.resolved_stages["train"]
reference = verified.attempts[-1].resolved_stages[0]
model = stage.artifacts["model"].file
model_path = root / reference.snapshot.store / reference.snapshot.commit / model.path
print(json.dumps({
    "run_id": run.run_id,
    "policy": run.execution_policy.mode,
    "controls": stage.completion.startup.observed_controls.model_dump(),
    "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
    "model_path": str(model_path),
}))
"""


@pytest.fixture
def policy_workspace(tmp_path: Path) -> Path:
    """Create a committed workspace containing both complete policy examples."""
    root = tmp_path / "policy"
    (root / "examples/data").mkdir(parents=True)
    for name in ("cpu_quickstart.py", "execution_policies.py"):
        shutil.copy(Path("examples") / name, root / "examples" / name)
    shutil.copy("examples/data/tiny.csv", root / "examples/data/tiny.csv")
    shutil.copy("pyproject.toml", root / "pyproject.toml")
    (root / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
    _run(root, "git", "init", "--quiet")
    _run(root, "git", "config", "user.email", "viper@example.com")
    _run(root, "git", "config", "user.name", "VIPER Policy Test")
    _run(root, "git", "remote", "add", "origin", "https://github.com/example/viper")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "--quiet", "-m", "policy source")
    return root


def test_read_source_identifies_commit_and_selected_remote(
    policy_workspace: Path,
) -> None:
    """Return HEAD and the requested remote through the public repository API."""
    source = read_source(policy_workspace)
    assert (
        source.commit
        == _run(policy_workspace, "git", "rev-parse", "HEAD").stdout.strip()
    )
    assert str(source.repository) == "https://github.com/example/viper"
    _run(
        policy_workspace,
        "git",
        "remote",
        "add",
        "mirror",
        "https://github.com/example/mirror",
    )
    mirror = read_source(policy_workspace, remote="mirror")
    assert mirror.commit == source.commit
    assert str(mirror.repository) == "https://github.com/example/mirror"


def test_read_source_rejects_missing_remote(policy_workspace: Path) -> None:
    """Report an unavailable source remote at the repository API boundary."""
    with pytest.raises(RootError, match="selected Git remote"):
        read_source(policy_workspace, remote="absent")


@pytest.mark.parametrize("mode", ["reproducible", "relaxed", "custom"])
def test_policy_example_verifies_after_exit(policy_workspace: Path, mode: str) -> None:
    """Verify each saved policy run and reject changed artifact bytes."""
    root = policy_workspace
    environment = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    # A relaxed child must discard an inherited strict cuBLAS setting.
    environment["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    records = []
    result_paths: list[Path] = []
    for _ in range(2 if mode == "reproducible" else 1):
        completed = subprocess.run(
            (sys.executable, "examples/execution_policies.py", mode),
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        result_line = next(
            line
            for line in completed.stdout.splitlines()
            if line.startswith("result: ")
        )
        result_path = root / result_line.removeprefix("result: ")
        result_paths.append(result_path)
        # The producer has exited; this independent interpreter reads its saved run.
        verification = subprocess.run(
            (sys.executable, "-c", _POLICY_VERIFY_PROGRAM, str(root), str(result_path)),
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        record = json.loads(verification.stdout)
        assert record["policy"] == mode
        assert record["controls"]["deterministic_algorithms"] == (
            mode == "reproducible"
        )
        assert record["controls"]["autocast_enabled"] is False
        records.append(record)
    if mode == "reproducible":
        assert records[0]["run_id"] != records[1]["run_id"]
        assert records[0]["model_sha256"] == records[1]["model_sha256"]
    if mode == "custom":
        assert records[-1]["controls"]["torch_intraop_threads"] == 2
    # Corrupt the stored artifact, rather than the mutable workspace copy.
    Path(records[-1]["model_path"]).write_bytes(b"changed model\n")
    rejected = subprocess.run(
        (
            sys.executable,
            "-c",
            _POLICY_VERIFY_PROGRAM,
            str(root),
            str(result_paths[-1]),
        ),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert rejected.returncode != 0
    assert "VerificationError" in rejected.stderr


def test_read_source_discovers_from_nested_directory(
    policy_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Find the containing workspace without a caller-supplied root."""
    expected = read_source(policy_workspace)
    monkeypatch.chdir(policy_workspace / "examples")
    assert read_source() == expected


def test_documented_metrics_compute_and_persist_values(tmp_path: Path) -> None:
    """Run the printed metric implementations through their recording handles."""
    blocks = python_blocks(Path("docs/how-to/metrics-and-benchmarks.md").read_text())
    namespace = {}
    for block in blocks:
        if (
            "def mean_squared_error(" in block
            or "class MeanAbsoluteError(" in block
            or "class DistanceConfig(" in block
        ):
            exec(compile(block, "<documented metric>", "exec"), namespace)
    config = namespace["MetricConfig"]()
    path = tmp_path / "measurements.jsonl"
    sink = MeasurementSink(
        path,
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        attempt_id=1,
        stage_id="train",
        metric_id="mean_squared_error",
    )
    mse = MetricHandle(
        namespace["mean_squared_error"], sink, MetricContext(config=config)
    )
    assert mse.record((1.0, 3.0), (2.0, 5.0), epoch=1, step=1).value == 2.5
    saved = json.loads(path.read_text())
    assert (saved["value"], saved["epoch"], saved["step"]) == (2.5, 1, 1)
    for predictions, targets in [((), ()), ((1.0,), (1.0, 2.0))]:
        with pytest.raises(ValueError):
            mse.record(predictions, targets)
    assert len(path.read_text().splitlines()) == 1

    mae_sink = MeasurementSink(
        tmp_path / "mae.jsonl",
        run_id=sink.run_id,
        attempt_id=1,
        stage_id="train",
        metric_id="mean_absolute_error",
    )
    mae = MetricHandle(
        namespace["MeanAbsoluteError"], mae_sink, MetricContext(config=config)
    )
    with pytest.raises(ValueError, match="at least one observation"):
        mae.record()
    mae.update(1.0, 2.0)
    mae.update(3.0, 5.0)
    assert mae.record(step=2).value == 1.5
    mae.update(5.0, 5.0)
    assert mae.record(step=3).value == 1.0
    assert len(mae_sink.path.read_text().splitlines()) == 2

    for order, expected in [(1, 7.0), (2, 5.0)]:
        context = MetricContext(config=namespace["DistanceConfig"](order=order))
        assert namespace["vector_distance"](context, (0.0, 0.0), (3.0, 4.0)) == expected
        with pytest.raises(ValueError):
            namespace["vector_distance"](context, (0.0,), (3.0, 4.0))
    with pytest.raises(ValueError):
        namespace["DistanceConfig"](order=0)
