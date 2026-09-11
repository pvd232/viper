"""Tests for canonical protocol-file authoring and run-plan freezing."""

import hashlib
import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

import viper.authoring as authoring
import viper.config as config
from examples.cpu_quickstart import training as example_training
from viper import _subprocess as subprocess
from viper.artifacts import (
    ArtifactLoaderRef,
    BundleArtifactDraft,
    SingleFileArtifactDraft,
    StageArtifactRef,
    artifact,
)
from viper.authoring import (
    RunIdMap,
    RunPlanDraft,
    TrainSpecDraft,
    VariantDraft,
    _compile_plan,
    _CompiledPlan,
    expand,
    expand_http_url,
    experiment,
    factor,
    freeze_run_plan,
    plan,
    replicate,
    stage,
    variant,
    write_experiment_spec,
    write_variant_spec,
)
from viper.authoring import input as external_input
from viper.benchmark import RunArtifactDraft, at_least, benchmark
from viper.config import ConfigTypeRef
from viper.experiments import (
    ExperimentSpec,
    FactorSpec,
    ReplicateSpec,
    TrainVariantStageConfig,
    VariantSpec,
)
from viper.http import (
    CustomHttpDraft,
    HttpContext,
    HttpResult,
    ObservedHttpResponse,
    http,
)
from viper.keys import Train as TrainKeys
from viper.metrics import (
    FloatComparator,
    MetricDependency,
    MetricImplementationRef,
    MetricSpec,
    measure,
    metric,
    min,
)
from viper.outputs import EvalOutputs, output
from viper.preflight import preflight_plan
from viper.references import GitSource, LocalFileRef, ResolvedRunRef
from viper.resume import DataLoaderConfiguration
from viper.runs import RunSpec
from viper.runtime import (
    EnvSpec,
    ParallelismSpec,
    ReproducibilitySpec,
    resolve_execution_policy,
)
from viper.serialization import parse_yaml_bytes, serialize_document
from viper.stages import (
    Context,
    StageImplementationRef,
    TrainSpec,
    train,
)
from viper.storage import LocalArtifactStore

RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
RUN_ROOT = f"experiments/e001_strand/runs/baseline/{RUN_ID}"
COMMIT = "a" * 40
LOADER_RAW = b"def load(path):\n    return path.read_bytes()\n"


def loader_ref(path: str) -> ArtifactLoaderRef:
    """Identify the shared test loader by its exact source bytes."""
    return ArtifactLoaderRef(
        path=path,
        symbol="load",
        sha256=hashlib.sha256(LOADER_RAW).hexdigest(),
        bytes=len(LOADER_RAW),
    )


def _git(root: Path, *arguments: str) -> str:
    """Run one successful Git command in an authoring test repository."""
    return subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def environment_payload(commit: str = COMMIT) -> dict[str, object]:
    """Build the shared GCE environment used by an authored run plan."""
    return {
        "kind": "gce",
        "provisioning": {
            "kind": "boot_image",
            "project": "mantra",
            "name": "strict-v1",
            "id": "123456789",
        },
        "machine_type": "n2-standard-8",
        "compute": {"kind": "cpu"},
        "lockfile": {
            "kind": "git",
            "repository": "https://github.com/example/viper-project",
            "commit": commit,
            "path": "environment.yml",
        },
        "python_env": {
            "python_version": "3.13.0",
            "distributions": [{"name": "viper-provenance", "version": "0.1.0"}],
        },
    }


def reproducibility_payload() -> dict[str, object]:
    """Build the run-wide controls used by an authored run plan."""
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
            "generators": {"training": "PCG64"},
            "capture_legacy_global": True,
        },
    }


def training_spec(
    config_type: ConfigTypeRef,
    implementation: StageImplementationRef,
    *,
    commit: str = COMMIT,
) -> TrainSpec:
    """Build one valid training stage with its terminal checkpoint."""
    return TrainSpec.model_validate(
        {
            "kind": "train",
            "metric_ids": ["training_loss"],
            "objective": {"metric_id": "training_loss", "direction": "min"},
            "implementation": implementation.model_dump(mode="json"),
            "config_type": config_type.model_dump(mode="json"),
            "inputs": {
                "training_dataset": {
                    "kind": "stored",
                    "pointer": {
                        "kind": "git",
                        "repository": "https://github.com/example/viper-project",
                        "commit": commit,
                        "path": (
                            ".viper/pointers/"
                            + "a" * 64
                            + "/download/training_dataset.pointer.yaml"
                        ),
                    },
                    "path": "inputs/datasets/replogle/dataset.h5ad",
                    "data_role": "training",
                }
            },
            "config": {"schema_version": 2, "epochs": 2},
            "outputs": {
                TrainKeys.MODEL: {
                    "kind": "file",
                    "path": (
                        f"{RUN_ROOT}/artifacts/train/model/parameters.safetensors"
                    ),
                    "loader": loader_ref(
                        "project_code/loaders/parameters.py"
                    ).model_dump(mode="json"),
                    "data_role": "training",
                },
                TrainKeys.RESUME_STATE: {
                    "kind": "file",
                    "path": (
                        f"{RUN_ROOT}/artifacts/train/resume_state/resume_state.pt"
                    ),
                    "loader": loader_ref(
                        "project_code/loaders/resume_state.py"
                    ).model_dump(mode="json"),
                    "data_role": "training",
                },
            },
        }
    )


class RunPlanAuthoringTests(unittest.TestCase):
    """Verify canonical paths and byte identities written by plan authoring."""

    def test_freeze_run_plan_writes_hash_bound_stage_and_run_files(self) -> None:
        """Write canonical files whose RunStageRef matches exact stage bytes."""
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _git(root, "init", "--quiet")
            _git(root, "config", "user.email", "viper@example.com")
            _git(root, "config", "user.name", "VIPER Test")
            _git(
                root,
                "remote",
                "add",
                "origin",
                "https://github.com/example/viper-project",
            )
            parameter_raw = (
                b"from pydantic import Field\n"
                b"from viper import config\n\n"
                b"class StrandTrainConfig(config.TrainConfig):\n"
                b"    epochs: int = Field(gt=0)\n"
            )
            config_path = root / "project/config/train.py"
            config_path.parent.mkdir(parents=True)
            config_path.write_bytes(parameter_raw)
            implementation_raw = (
                b"from project.config.train import StrandTrainConfig\n"
                b"from viper.stages import train\n\n"
                b"@train(config=StrandTrainConfig)\n"
                b"def fit(context):\n"
                b"    pass\n"
            )
            implementation_path = root / "project_code/strand/fit.py"
            implementation_path.parent.mkdir(parents=True)
            implementation_path.write_bytes(implementation_raw)
            environment_path = root / "environment.yml"
            environment_path.write_text("name: viper-test\n", encoding="utf-8")
            pointer_path = root / "inputs/datasets/replogle/current.pointer.yaml"
            pointer_path.parent.mkdir(parents=True)
            pointer_path.write_text("schema_version: 1\n", encoding="utf-8")
            for relative_path in (
                "project_code/loaders/parameters.py",
                "project_code/loaders/resume_state.py",
            ):
                loader_path = root / relative_path
                loader_path.parent.mkdir(parents=True, exist_ok=True)
                loader_path.write_bytes(LOADER_RAW)
            _git(root, "add", ".")
            _git(root, "commit", "--quiet", "-m", "source")
            source_commit = _git(root, "rev-parse", "HEAD")
            config_type = ConfigTypeRef(
                owner="workspace",
                path="project/config/train.py",
                symbol="StrandTrainConfig",
                sha256=hashlib.sha256(parameter_raw).hexdigest(),
                bytes=len(parameter_raw),
            )
            implementation = StageImplementationRef(
                path="project_code/strand/fit.py",
                symbol="fit",
                sha256=hashlib.sha256(implementation_raw).hexdigest(),
                bytes=len(implementation_raw),
            )
            draft_stage = root / "drafts/train.yaml"
            draft_stage.parent.mkdir(parents=True)
            draft_stage.write_bytes(
                serialize_document(
                    training_spec(
                        config_type,
                        implementation,
                        commit=source_commit,
                    )
                )
            )
            current_root = root / "current"
            current_root.mkdir()
            _, draft = _compiled_plan(current_root)
            root = current_root

            frozen = freeze_run_plan(root, draft)
            stage_path = next(path for path in frozen.files if "/stages/" in str(path))
            run_path = frozen.files[-1]
            stage_raw = stage_path.read_bytes()
            loaded_run = RunSpec.model_validate(parse_yaml_bytes(run_path.read_bytes()))

        self.assertEqual(
            loaded_run.stages[0].sha256,
            hashlib.sha256(stage_raw).hexdigest(),
        )
        self.assertEqual(loaded_run.stages[0].bytes, len(stage_raw))
        self.assertEqual(
            stage_path.relative_to(root).as_posix(),
            "experiments/e001_strand/runs/"
            f"baseline/{draft.run_id}/stages/train/spec.yaml",
        )
        self.assertEqual(
            run_path.relative_to(root).as_posix(),
            f"experiments/e001_strand/runs/baseline/{draft.run_id}/spec.yaml",
        )

    def test_experiment_and_variant_writers_use_identity_paths(self) -> None:
        """Write experiment and variant records under one experiment identity."""
        metric = MetricSpec(
            config_type=config.type_ref(config.MetricConfig),
            metric_id="training_loss",
            implementation=MetricImplementationRef(
                path="project_code/metrics/training_loss.py",
                symbol="compute",
                sha256="a" * 64,
                bytes=1,
            ),
            config=config.MetricConfig(),
            mode="stateless",
        )
        experiment = ExperimentSpec(
            experiment_id="e001_strand",
            factors=(FactorSpec(factor_id="rank", levels=("full", "low")),),
            variant_ids=("baseline",),
            replicates=(ReplicateSpec(replicate_id="replicate_01", seed=42),),
            metrics=(metric,),
        )
        variant = VariantSpec(
            experiment_id="e001_strand",
            variant_id="baseline",
            levels={"rank": "full"},
            stage_configs=(
                TrainVariantStageConfig(
                    stage_id="train",
                    config=config.TrainConfig.model_validate({"epochs": 2}),
                ),
            ),
        )

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            experiment_path = write_experiment_spec(root, experiment)
            variant_path = write_variant_spec(root, variant)

            self.assertTrue(yaml.safe_load(experiment_path.read_text()))
            self.assertTrue(yaml.safe_load(variant_path.read_text()))
            self.assertEqual(
                experiment_path.relative_to(root).as_posix(),
                "experiments/e001_strand/spec.yaml",
            )
            self.assertEqual(
                variant_path.relative_to(root).as_posix(),
                "experiments/e001_strand/variants/baseline.spec.yaml",
            )

    def test_expand_http_url_freezes_path_and_ordered_query_values(self) -> None:
        """Encode path values and order the complete frozen query mapping."""
        url = expand_http_url(
            "https://DATA.example.test/files/{archive}?format=raw",
            path_values={"archive": "batch 1/data.tar.gz"},
            query_values={"page": 2, "compressed": True},
        )

        self.assertEqual(
            str(url),
            "https://data.example.test/files/"
            "batch%201%2Fdata.tar.gz?compressed=true&format=raw&page=2",
        )

        with self.assertRaisesRegex(ValueError, "no value"):
            expand_http_url("https://example.test/{missing}")


def test_artifact_and_http_drafts_preserve_callable_identity() -> None:
    """Keep selected Python callables attached to their authoring drafts."""

    def load(path: Path) -> bytes:
        return path.read_bytes()

    @http(id="dataset")
    def fetch(context: HttpContext[config.HttpConfig]) -> HttpResult:
        return HttpResult(
            body=context.destination,
            response=ObservedHttpResponse(
                response_url=context.request.url,
                status=200,
                response_headers={},
            ),
        )

    artifact_draft = artifact(
        path="artifacts/data.csv", loader=load, data_role="training"
    )
    http_draft = CustomHttpDraft(implementation=fetch, config=config.HttpConfig())

    assert artifact_draft.loader is load
    assert http_draft.implementation is fetch


def test_artifact_constructor_selects_file_or_bundle() -> None:
    """Select the artifact draft type from the explicit kind."""

    def load(path: Path) -> bytes:
        return path.read_bytes()

    file = artifact(path="artifacts/model.bin", loader=load, data_role="training")
    bundle = artifact(
        path="artifacts/tokenizer",
        loader=load,
        data_role="training",
        kind="bundle",
    )

    assert isinstance(file, SingleFileArtifactDraft)
    assert isinstance(bundle, BundleArtifactDraft)


def test_python_stage_drafts_replace_yaml_authoring() -> None:
    """Keep a decorated callable and artifact handle in one Python stage draft."""

    @metric(metric_id="training_loss", mode="stateless")
    def training_loss(context) -> float:
        """Return one stable loss for the authoring boundary."""
        return 1.0

    @train(config=config.TrainConfig)
    def fit(context: Context[config.TrainConfig]) -> None:
        context.outputs["model"].write_bytes(b"model")

    model = output(
        path="model.bin",
        loader=lambda path: path.read_bytes(),
        data_role="training",
    )
    dataset = external_input(
        "dataset",
        path="inputs/raw/dataset.csv",
        data_role="training",
    )
    loss = measure(training_loss, config=config.MetricConfig())
    draft = stage(
        fit,
        config=config.TrainConfig(),
        inputs={"dataset": dataset},
        outputs={  # pyright: ignore[reportArgumentType]
            "model": model,
            "resume_state": output(
                path="resume_state.bin",
                loader=lambda path: path.read_bytes(),
                data_role="training",
            ),
        },
        metrics=(loss,),
        objective=min(loss),
    )

    assert isinstance(draft.spec, TrainSpecDraft)
    assert draft.spec.implementation is fit
    assert draft.outputs["model"].producer is draft


def _immutable_plan() -> tuple[RunPlanDraft, dict[str, VariantDraft]]:
    """Build one small plan and retain its caller-owned variant mapping."""

    @metric(metric_id="training_loss", mode="stateless")
    def training_loss(context) -> float:
        return 1.0

    @train(config=config.TrainConfig)
    def fit(context: Context[config.TrainConfig]) -> None:
        context.outputs["model"].write_bytes(b"model")

    loss = measure(training_loss, config=config.MetricConfig())
    train_stage = stage(
        fit,
        config=config.TrainConfig(),
        inputs={
            "dataset": external_input(
                "dataset",
                path="inputs/raw/dataset.csv",
                data_role="training",
            )
        },
        outputs={  # pyright: ignore[reportArgumentType]
            "model": output(
                path="model.bin",
                loader=lambda path: path.read_bytes(),
                data_role="training",
            ),
            "resume_state": output(
                path="resume_state.bin",
                loader=lambda path: path.read_bytes(),
                data_role="training",
            ),
        },
        metrics=(loss,),
        objective=min(loss),
    )
    variants = {
        "baseline": variant(
            levels={"rank": "full"},
            stages={"train": train_stage},
            estimator=train_stage.outputs["model"],
        )
    }
    authored = experiment(
        experiment_id="e001_strand",
        factors={"rank": factor(levels=("full", "low"))},
        variants=variants,
        replicates={"replicate_01": replicate("replicate_01", seed=42)},
    )
    env_payload = environment_payload()
    return (
        plan(
            experiment=authored,
            variant="baseline",
            replicate="replicate_01",
            source=GitSource.model_validate(
                {
                    "repository": "https://github.com/example/viper-project",
                    "commit": COMMIT,
                }
            ),
            env=TypeAdapter(EnvSpec).validate_python(env_payload),
            reproducibility=ReproducibilitySpec.model_validate(
                reproducibility_payload()
            ),
        ),
        variants,
    )


def test_plan_generates_read_only_run_id() -> None:
    """Generate one valid identity that callers cannot replace afterward."""
    draft, _ = _immutable_plan()

    assert len(draft.run_id) == 26
    with pytest.raises(ValidationError):
        draft.run_id = RUN_ID


def test_plan_rejects_every_nested_mutator() -> None:
    """Detach the plan from caller aliases and reject nested mutation."""
    draft, variants = _immutable_plan()
    variants.clear()

    assert tuple(draft.experiment.variants) == ("baseline",)
    with pytest.raises(TypeError, match="frozen plan"):
        draft.experiment.variants.clear()
    with pytest.raises(TypeError, match="frozen plan"):
        draft.experiment.variants["baseline"].stages.update({})


def _compiled_plan(tmp_path: Path) -> tuple[_CompiledPlan, RunPlanDraft]:
    """Compile one plan whose callables live inside a temporary project."""
    (tmp_path / "viper.toml").write_text("[workspace]\nschema_version = 2\n")
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "viper@example.com")
    _git(tmp_path, "config", "user.name", "VIPER Test")
    _git(
        tmp_path,
        "remote",
        "add",
        "origin",
        "https://github.com/example/viper-project",
    )
    dataset = tmp_path / "inputs/raw/dataset.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("value\n1\n")
    (tmp_path / "environment.yml").write_text("name: viper-test\n")
    source = tmp_path / "project/plan.py"
    source.parent.mkdir()
    source.write_text(
        "from viper import config\n"
        "from viper.metrics import metric\n"
        "from viper.stages import Context, train\n\n"
        "@metric(metric_id='training_loss', mode='stateless')\n"
        "def training_loss(context):\n"
        "    return 1.0\n\n"
        "@train(config=config.TrainConfig)\n"
        "def fit(context: Context[config.TrainConfig]):\n"
        "    context.outputs['model'].write_bytes(b'model')\n\n"
        "def load(path):\n"
        "    return path.read_bytes()\n"
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "source")
    commit = _git(tmp_path, "rev-parse", "HEAD")
    spec = importlib.util.spec_from_file_location("project.plan", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loss = measure(module.training_loss, config=config.MetricConfig())
    train_stage = stage(
        module.fit,
        config=config.TrainConfig(),
        inputs={
            "dataset": external_input(
                "dataset",
                path="inputs/raw/dataset.csv",
                data_role="training",
            )
        },
        outputs={  # pyright: ignore[reportArgumentType]
            "model": output(
                path="model.bin",
                loader=module.load,
                data_role="training",
            ),
            "resume_state": output(
                path="resume_state.bin",
                loader=module.load,
                data_role="training",
            ),
        },
        metrics=(loss,),
        objective=min(loss),
    )
    authored = experiment(
        experiment_id="e001_strand",
        factors={"rank": factor(levels=("full", "low"))},
        variants={
            "baseline": variant(
                levels={"rank": "full"},
                stages={"train": train_stage},
                estimator=train_stage.outputs["model"],
            )
        },
        replicates={"replicate_01": replicate("replicate_01", seed=42)},
    )
    env_payload = environment_payload(commit)
    draft = plan(
        experiment=authored,
        variant="baseline",
        replicate="replicate_01",
        source=GitSource.model_validate(
            {
                "repository": "https://github.com/example/viper-project",
                "commit": commit,
            }
        ),
        env=TypeAdapter(EnvSpec).validate_python(env_payload),
        reproducibility=ReproducibilitySpec.model_validate(reproducibility_payload()),
    )
    return _compile_plan(tmp_path, draft), draft


def test_experiment_draft_derives_metric_registry(tmp_path: Path) -> None:
    """Compile every configured metric into the experiment record once."""
    compiled, _ = _compiled_plan(tmp_path)
    experiment_raw = compiled.files["experiments/e001_strand/spec.yaml"]
    experiment_spec = ExperimentSpec.model_validate(parse_yaml_bytes(experiment_raw))

    assert tuple(metric.metric_id for metric in experiment_spec.metrics) == (
        "training_loss",
    )


def test_plan_compiles_complete_protocol_graph(tmp_path: Path) -> None:
    """Compile experiment, variant, stage, and run records before publication."""
    compiled, draft = _compiled_plan(tmp_path)

    assert compiled.run.run_id == draft.run_id
    assert compiled.run_path in compiled.files
    assert "experiments/e001_strand/spec.yaml" in compiled.files
    assert "experiments/e001_strand/variants/baseline.spec.yaml" in compiled.files
    assert any(path.endswith("/stages/train/spec.yaml") for path in compiled.files)


def test_freeze_publishes_one_immutable_plan(tmp_path: Path) -> None:
    """Bind the working plan files to one content-addressed revision."""
    _, draft = _compiled_plan(tmp_path)

    frozen = freeze_run_plan(tmp_path, draft)
    run_raw = LocalArtifactStore(tmp_path).fetch(frozen.reference.stored_at)

    assert run_raw == (tmp_path / frozen.reference.stored_at.path).read_bytes()
    assert frozen.reference.sha256 == hashlib.sha256(run_raw).hexdigest()


def test_preflight_reads_the_published_plan(tmp_path: Path) -> None:
    """Check plan identity against the published revision instead of Git HEAD."""
    _, draft = _compiled_plan(tmp_path)
    frozen = freeze_run_plan(tmp_path, draft)
    run_path = tmp_path / frozen.reference.stored_at.path

    report = preflight_plan(tmp_path, run_path, plan=frozen.reference)
    identity = next(
        check for check in report.checks if check.code == "plan.git_identity"
    )

    assert identity.status == "pass"


def test_benchmark_draft_is_frozen_with_the_run_plan() -> None:
    """Keep benchmark inputs, metrics, and optional criteria immutable."""

    @metric(metric_id="accuracy", mode="stateless")
    def accuracy(context) -> float:
        return 0.95

    selected_metric = measure(
        accuracy,
        dependencies=(
            MetricDependency(
                source="artifact",
                name="predictions",
                data_role="benchmark",
            ),
        ),
        comparator=FloatComparator(),
    )
    prior = RunArtifactDraft(
        run=ResolvedRunRef(
            sha256="a" * 64,
            bytes=1,
            stored_at=LocalFileRef(commit="b" * 64, path="runs/prior/resolved.yaml"),
        ),
        artifact=StageArtifactRef(stage_id="eval", artifact_name="predictions"),
        path="inputs/datasets/holdout/test.bin",
        data_role="benchmark",
    )
    benchmark_draft = benchmark(
        benchmark_id="holdout",
        eval_id="eval",
        test=prior,
        splits={"holdout": prior},
        metrics=(selected_metric,),
        criteria=(at_least(selected_metric, 0.9),),
    )
    existing, _ = _immutable_plan()

    selected = plan(
        experiment=existing.experiment,
        variant=existing.variant,
        replicate=existing.replicate,
        benchmark=benchmark_draft,
        source=existing.source,
        env=existing.env,
        reproducibility=existing.reproducibility,
    )

    assert selected.benchmark is not None
    assert selected.benchmark.benchmark_id == benchmark_draft.benchmark_id
    assert selected.benchmark.criteria[0].threshold == 0.9
    with pytest.raises(TypeError, match="frozen plan"):
        selected.benchmark.splits["new"] = prior


def test_benchmark_compilation_uses_the_evaluation_test_input(tmp_path: Path) -> None:
    """Compile a benchmark whose dataset matches the evaluation's test input."""
    _, existing = _compiled_plan(tmp_path)
    source = tmp_path / "project/evaluation.py"
    source.write_text(
        "from viper.config import EvalConfig\n"
        "from viper.stages import eval\n\n"
        "@eval(config=EvalConfig)\n"
        "def evaluate(context):\n"
        "    context.outputs['predictions'].write_bytes(b'predictions')\n\n"
        "def load(path):\n"
        "    return path.read_bytes()\n"
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "evaluation source")
    spec = importlib.util.spec_from_file_location("project.evaluation", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    training = existing.experiment.variants["baseline"].stages["train"]
    assert isinstance(training.spec, TrainSpecDraft)
    loss = training.spec.metrics[0]
    dataset = RunArtifactDraft(
        run=ResolvedRunRef(
            sha256="a" * 64,
            bytes=1,
            stored_at=LocalFileRef(commit="b" * 64, path="runs/data/resolved.yaml"),
        ),
        artifact=StageArtifactRef(stage_id="build", artifact_name="dataset"),
        path="inputs/holdout.bin",
        data_role="benchmark",
    )
    split = dataset.model_copy(update={"path": "inputs/split.bin"})
    evaluation = stage(
        module.evaluate,
        config=config.EvalConfig(),
        inputs={"model": training.outputs["model"], "test": dataset, "holdout": split},
        outputs=EvalOutputs(
            predictions=output(
                path="predictions.bin", loader=module.load, data_role="benchmark"
            )
        ),
        metrics=(loss,),
        objective=min(loss),
        eval_id="holdout",
        split_inputs=("holdout",),
    )
    study = experiment(
        experiment_id="benchmark_compilation",
        variants={
            "baseline": variant(
                levels={},
                stages={"train": training, "eval": evaluation},
                estimator=training.outputs["model"],
            )
        },
        replicates={"seed_42": replicate(seed=42)},
    )
    selected = plan(
        experiment=study,
        variant="baseline",
        replicate="seed_42",
        benchmark=benchmark(
            benchmark_id="holdout",
            eval_id="holdout",
            test=dataset,
            splits={"holdout": split},
            metrics=(loss,),
        ),
        source=existing.source.model_copy(
            update={"commit": _git(tmp_path, "rev-parse", "HEAD")}
        ),
        env=existing.env,
        reproducibility=existing.reproducibility,
    )

    compiled = _compile_plan(tmp_path, selected)

    assert compiled.run.benchmark_id == "holdout"
    assert "benchmarks/holdout.spec.yaml" in compiled.files


def test_experiment_expansion_is_canonical() -> None:
    """Use declaration order and the caller's exact run IDs."""
    single, _ = _immutable_plan()
    baseline = single.experiment.variants["baseline"]
    draft = experiment(
        experiment_id=single.experiment.experiment_id,
        factors=single.experiment.factors,
        variants={"baseline": baseline, "l2": baseline},
        replicates={
            "replicate_01": replicate("replicate_01", seed=42),
            "replicate_02": replicate("replicate_02", seed=43),
        },
    )
    run_ids: RunIdMap = {
        "l2": {
            "replicate_02": "01ARZ3NDEKTSV4RRFFQ69G5FAY",
            "replicate_01": "01ARZ3NDEKTSV4RRFFQ69G5FAX",
        },
        "baseline": {
            "replicate_02": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
            "replicate_01": RUN_ID,
        },
    }

    plans = expand(
        draft,
        run_ids=run_ids,
        source=single.source,
        env=single.env,
        reproducibility=single.reproducibility,
    )

    assert tuple((item.variant, item.replicate) for item in plans) == (
        ("baseline", "replicate_01"),
        ("baseline", "replicate_02"),
        ("l2", "replicate_01"),
        ("l2", "replicate_02"),
    )
    assert tuple(item.run_id for item in plans) == (
        RUN_ID,
        "01ARZ3NDEKTSV4RRFFQ69G5FAW",
        "01ARZ3NDEKTSV4RRFFQ69G5FAX",
        "01ARZ3NDEKTSV4RRFFQ69G5FAY",
    )


def test_experiment_expansion_generates_unique_ids_and_applies_filters() -> None:
    """Generate fresh IDs for selected pairs across repeated batch declarations."""
    single, _ = _immutable_plan()
    study = single.experiment.model_copy(
        update={
            "replicates": {"seed_7": replicate(seed=7), "seed_19": replicate(seed=19)}
        }
    )
    first = expand(study, source=single.source, env=single.env)
    second = expand(
        study, source=single.source, env=single.env, replicates=("seed_19",)
    )
    assert tuple(item.replicate for item in first) == ("seed_7", "seed_19")
    assert tuple(item.replicate for item in second) == ("seed_19",)
    assert len({item.run_id for item in (*first, *second)}) == 3
    assert all(len(item.run_id) == 26 for item in (*first, *second))


def test_experiment_expansion_rejects_invalid_selection() -> None:
    """Reject unknown filters, incomplete maps, and reused run IDs."""
    single, _ = _immutable_plan()
    arguments = {
        "experiment": single.experiment,
        "source": single.source,
        "env": single.env,
        "reproducibility": single.reproducibility,
    }

    with pytest.raises(ValueError, match="unknown ID"):
        expand(**arguments, run_ids={}, variants=("missing",))
    with pytest.raises(ValueError, match="duplicates"):
        expand(
            **arguments,
            run_ids={"baseline": {"replicate_01": RUN_ID}},
            variants=("baseline", "baseline"),
        )
    with pytest.raises(ValueError, match="selected pairs"):
        expand(**arguments, run_ids={})

    duplicate_replicate = replicate(seed=43)
    duplicated = single.experiment.model_copy(
        update={
            "replicates": {
                **single.experiment.replicates,
                "replicate_02": duplicate_replicate,
            }
        }
    )
    with pytest.raises(ValueError, match="unique"):
        expand(
            **{**arguments, "experiment": duplicated},
            run_ids={
                "baseline": {
                    "replicate_01": RUN_ID,
                    "replicate_02": RUN_ID,
                }
            },
        )


def test_execution_policy_plan_defaults_to_reproducible() -> None:
    """Freeze the default policy identity with its resolved numerical controls."""
    baseline, _ = _immutable_plan()
    selected = plan(
        experiment=baseline.experiment,
        variant=baseline.variant,
        replicate=baseline.replicate,
        source=baseline.source,
        env=baseline.env,
    )
    assert selected.execution_policy is not None
    assert selected.execution_policy.mode == "reproducible"
    assert selected.execution_policy.version == 1
    assert selected.reproducibility.determinism.deterministic_algorithms is True
    with pytest.raises(ValidationError):
        selected.reproducibility.parallelism.torch_intraop_threads = 8


def test_execution_policy_plan_relaxed_with_parallelism() -> None:
    """Freeze relaxed numerical controls and explicit resource settings together."""
    baseline, _ = _immutable_plan()
    resources = ParallelismSpec(
        process_count=1,
        torch_intraop_threads=4,
        torch_interop_threads=2,
        dataloader=DataLoaderConfiguration(workers=2, prefetch_factor=2),
    )
    selected = plan(
        experiment=baseline.experiment,
        variant=baseline.variant,
        replicate=baseline.replicate,
        source=baseline.source,
        env=baseline.env,
        reproducibility="relaxed",
        parallelism=resources,
    )
    assert selected.execution_policy is not None
    assert selected.execution_policy.mode == "relaxed"
    assert selected.reproducibility.determinism.deterministic_algorithms is False
    assert selected.reproducibility.parallelism == resources
    assert selected.reproducibility.parallelism is not resources


def test_execution_policy_plan_custom_is_detached() -> None:
    """Retain custom values without retaining caller-owned generator mappings."""
    baseline, _ = _immutable_plan()
    settings = ReproducibilitySpec.model_validate(baseline.reproducibility.model_dump())
    settings.numpy_randomness.generators["sampling"] = "PCG64"
    expected_generators = dict(settings.numpy_randomness.generators)
    selected = plan(
        experiment=baseline.experiment,
        variant=baseline.variant,
        replicate=baseline.replicate,
        source=baseline.source,
        env=baseline.env,
        reproducibility=settings,
    )
    settings.numpy_randomness.generators.clear()
    assert selected.execution_policy is not None
    assert selected.execution_policy.mode == "custom"
    assert selected.reproducibility.numpy_randomness.generators == expected_generators


def test_execution_policy_expand_resolves_once() -> None:
    """Use one policy resolution for all selected variant-replicate pairs."""
    baseline, _ = _immutable_plan()
    declaration = baseline.experiment.model_copy(
        update={
            "replicates": {
                "replicate_01": replicate("replicate_01", seed=42),
                "replicate_02": replicate("replicate_02", seed=43),
            }
        }
    )
    with patch.object(
        authoring, "resolve_execution_policy", wraps=authoring.resolve_execution_policy
    ) as resolver:
        selected = expand(
            declaration,
            run_ids={
                "baseline": {
                    "replicate_01": RUN_ID,
                    "replicate_02": "01ARZ3NDEKTSV4RRFFQ69G5FAX",
                }
            },
            source=baseline.source,
            env=baseline.env,
            reproducibility="relaxed",
        )
        resolver.assert_called_once_with("relaxed", parallelism=None)
    assert len(selected) == 2
    assert selected[0].execution_policy == selected[1].execution_policy
    assert selected[0].execution_policy is not None
    assert selected[0].execution_policy.mode == "relaxed"
    assert selected[0].reproducibility == selected[1].reproducibility
    assert selected[0].reproducibility is not selected[1].reproducibility


def test_policy_persistence_writer_roundtrip(tmp_path: Path) -> None:
    """Save the selected mode and settings and read both back unchanged."""
    compiled, draft = _compiled_plan(tmp_path)
    raw = compiled.files[compiled.run_path]
    restored = RunSpec.model_validate(parse_yaml_bytes(raw))
    assert restored.execution_policy == draft.execution_policy
    assert restored.reproducibility == draft.reproducibility
    assert serialize_document(restored) == raw
    assert RunSpec.model_json_schema()["required"].count("execution_policy") == 1


def test_policy_persistence_requires_policy_identity(tmp_path: Path) -> None:
    """Reject missing policy identity instead of inferring a historical mode."""
    compiled, _ = _compiled_plan(tmp_path)
    payload = compiled.run.model_dump(mode="json")
    del payload["execution_policy"]
    with pytest.raises(ValidationError, match="execution_policy"):
        RunSpec.model_validate(payload)


def test_policy_persistence_consistency(tmp_path: Path) -> None:
    """Accept matching presets and reject a relabelled relaxed run."""
    compiled, _ = _compiled_plan(tmp_path)
    payload = compiled.run.model_dump(mode="json")
    for mode in ("reproducible", "relaxed"):
        policy, settings = resolve_execution_policy(mode)
        payload.update(
            execution_policy=policy.model_dump(mode="json"),
            reproducibility=settings.model_dump(mode="json"),
        )
        restored = RunSpec.model_validate(payload)
        assert restored.execution_policy.mode == mode
        assert restored.reproducibility == settings

    payload["execution_policy"] = {"mode": "reproducible", "version": 1}
    with pytest.raises(ValidationError, match="saved numerical settings"):
        RunSpec.model_validate(payload)


def test_policy_persistence_replay(tmp_path: Path) -> None:
    """Read the saved controls without consulting current thread defaults."""
    compiled, _ = _compiled_plan(tmp_path)
    policy, settings = resolve_execution_policy("relaxed")
    payload = compiled.run.model_dump(mode="json")
    payload.update(
        execution_policy=policy.model_dump(mode="json"),
        reproducibility=settings.model_dump(mode="json"),
    )
    saved = serialize_document(RunSpec.model_validate(payload))
    with (
        patch(
            "viper.runtime.torch.get_num_threads",
            side_effect=AssertionError("saved runs must not consult thread defaults"),
        ),
        patch(
            "viper.runtime.torch.get_num_interop_threads",
            side_effect=AssertionError("saved runs must not consult thread defaults"),
        ),
    ):
        restored = RunSpec.model_validate(parse_yaml_bytes(saved))
    assert restored.execution_policy == policy
    assert restored.reproducibility == settings
    assert serialize_document(restored) == saved


def test_named_experiment_declarations_preserve_order_and_identity() -> None:
    """Index named objects while preserving output handles and replicate seeds."""
    training = example_training.model_copy(update={"stage_id": "fit_model"})
    baseline = variant(
        "baseline", stages=(training,), estimator=training.outputs["model"]
    )
    study = experiment(
        experiment_id="named",
        variants=(baseline,),
        replicates=(replicate("seed_19", seed=19), replicate("seed_7", seed=7)),
    )
    assert study.variants["baseline"] is baseline
    assert baseline.stages["fit_model"] is training
    assert baseline.estimator.producer is training
    assert baseline.levels == {}
    assert tuple(study.replicates) == ("seed_19", "seed_7")
    assert study.replicates["seed_19"].seed == 19


@pytest.mark.parametrize("identity", ("stage", "variant", "replicate"))
def test_named_declarations_reject_duplicate_names(identity: str) -> None:
    """Reject duplicate declarations before a dictionary could discard one."""
    training = example_training.model_copy(update={"stage_id": "train"})
    baseline = variant(
        "baseline", stages=(training,), estimator=training.outputs["model"]
    )
    seed = replicate("seed_7", seed=7)
    with pytest.raises(ValueError, match=f"duplicate {identity}_id"):
        if identity == "stage":
            variant(
                "baseline",
                stages=(training, training),
                estimator=training.outputs["model"],
            )
        else:
            experiment(
                experiment_id="named",
                variants=(baseline, baseline) if identity == "variant" else (baseline,),
                replicates=(seed, seed) if identity == "replicate" else (seed,),
            )


def test_named_replicates_reject_missing_or_conflicting_names() -> None:
    """Require a sequence name and prevent a mapping from renaming an object."""
    baseline = variant(
        "baseline",
        stages={"train": example_training},
        estimator=example_training.outputs["model"],
    )
    for replicates, message in (
        ((authoring.ReplicateDraft(seed=7),), "replicate_id is required"),
        ({"other": replicate("seed_7", seed=7)}, "replicate_id conflicts"),
    ):
        with pytest.raises(ValueError, match=message):
            experiment(
                experiment_id="named", variants=(baseline,), replicates=replicates
            )


@pytest.mark.parametrize("seed", (0, 7, 2**32 - 1))
def test_replicate_derives_its_name_from_the_validated_seed(seed: int) -> None:
    """Default names are deterministic; explicit names remain available."""
    assert replicate(seed=seed).replicate_id == f"seed_{seed}"
    assert replicate("trial_a", seed=seed).replicate_id == "trial_a"
    with pytest.raises(ValueError):
        replicate(seed=-1)


def test_plan_selects_the_only_variant_and_replicate() -> None:
    """Omitting unambiguous selections preserves the explicitly authored plan."""
    explicit, _ = _immutable_plan()
    automatic = plan(
        experiment=explicit.experiment,
        source=explicit.source,
        env=explicit.env,
        reproducibility=explicit.reproducibility,
    )
    assert automatic.variant == explicit.variant
    assert automatic.replicate == explicit.replicate
    assert automatic.experiment == explicit.experiment


@pytest.mark.parametrize("selection", ("variant", "replicate"))
def test_plan_requires_an_explicit_choice_when_ambiguous(selection: str) -> None:
    """Adding alternatives cannot silently change which experiment is executed."""
    single, _ = _immutable_plan()
    study = single.experiment.model_copy(
        update={
            "variants": dict(single.experiment.variants),
            "replicates": dict(single.experiment.replicates),
        }
    )
    if selection == "variant":
        study.variants["alternative"] = study.variants["baseline"]
    else:
        study.replicates["another"] = replicate("another", seed=43)
    with pytest.raises(ValueError, match=f"{selection} is required"):
        plan(experiment=study, source=single.source, env=single.env)


def test_named_inputs_preserve_paths_roles_and_reject_name_conflicts() -> None:
    """Preserve input values and reject duplicate or conflicting names."""
    assert isinstance(example_training.spec, TrainSpecDraft)
    dataset = external_input(
        "dataset", path="examples/data/tiny.csv", data_role="training"
    )
    arguments = {
        "outputs": example_training.spec.outputs,
        "metrics": example_training.spec.metrics,
        "objective": example_training.spec.objective,
    }
    selected = stage(
        example_training.spec.implementation, inputs=(dataset,), **arguments
    )
    mapped = stage(
        example_training.spec.implementation, inputs={"dataset": dataset}, **arguments
    )
    assert selected.spec == mapped.spec
    assert isinstance(selected.spec, TrainSpecDraft)
    assert selected.spec.inputs["dataset"] == dataset
    assert dataset.path == "examples/data/tiny.csv"
    assert dataset.data_role == "training"
    with pytest.raises(ValueError, match="duplicate input name"):
        stage(
            example_training.spec.implementation, inputs=(dataset, dataset), **arguments
        )
    with pytest.raises(ValueError, match="input name conflicts"):
        stage(
            example_training.spec.implementation, inputs={"other": dataset}, **arguments
        )


def test_stage_uses_the_decorators_config_defaults() -> None:
    """Omitting config preserves the decorator's config class and defaults."""
    assert isinstance(example_training.spec, TrainSpecDraft)
    selected = stage(
        example_training.spec.implementation,
        inputs=example_training.spec.inputs,
        outputs=example_training.spec.outputs,
        metrics=example_training.spec.metrics,
        objective=example_training.spec.objective,
    )
    assert isinstance(selected.spec, TrainSpecDraft)
    assert type(selected.spec.config) is config.TrainConfig
    assert selected.spec.config == example_training.spec.config


def test_upstream_input_tuples_preserve_producers_and_allow_aliases() -> None:
    """Keep upstream identity when inheriting or changing the receiving input name."""
    assert isinstance(example_training.spec, TrainSpecDraft)
    model = example_training.outputs["model"]
    alias = external_input("dataset", source=model)
    arguments = {
        "outputs": example_training.spec.outputs,
        "metrics": example_training.spec.metrics,
        "objective": example_training.spec.objective,
    }
    consumer = stage(
        example_training.spec.implementation, inputs=(model, alias), **arguments
    )
    assert isinstance(consumer.spec, TrainSpecDraft)
    direct = consumer.spec.inputs["model"]
    renamed = consumer.spec.inputs["dataset"]
    assert isinstance(direct, authoring.StageDraftOutputRef)
    assert isinstance(renamed, authoring.StageDraftOutputRef)
    assert direct.producer is renamed.producer is example_training
    assert direct.output_name == renamed.output_name == "model"
    with pytest.raises(ValueError, match="duplicate input name"):
        stage(example_training.spec.implementation, inputs=(model, model), **arguments)
    with pytest.raises(ValueError, match="duplicate input name"):
        stage(
            example_training.spec.implementation,
            inputs=(model, external_input("model", source=model)),
            **arguments,
        )


def test_named_factor_levels_preserve_identity_and_reject_ambiguous_choices() -> None:
    """Select known levels once per named factor in each variant."""
    rows = factor("training_rows", levels=("two", "three"))
    selected = rows.level("two")
    baseline = variant(
        "baseline",
        levels=(selected,),
        stages=(example_training,),
        estimator=example_training.outputs["model"],
    )
    study = experiment(
        experiment_id="named_factors",
        factors=(rows,),
        variants=(baseline,),
        replicates=(replicate(seed=7),),
    )
    assert study.factors["training_rows"] is rows
    assert baseline.levels == {"training_rows": "two"}
    with pytest.raises(ValueError, match="unknown level"):
        rows.level("four")
    with pytest.raises(ValueError, match="name the factor"):
        factor(levels=("two", "three")).level("two")
    with pytest.raises(ValueError, match="duplicate factor selection"):
        variant(
            "baseline",
            levels=(selected, rows.level("three")),
            stages=(example_training,),
            estimator=example_training.outputs["model"],
        )
    with pytest.raises(ValueError, match="duplicate factor_id"):
        experiment(
            experiment_id="named_factors",
            factors=(rows, rows),
            variants=(baseline,),
            replicates=(replicate(seed=7),),
        )


def test_stage_requires_values_for_required_custom_config_fields() -> None:
    """A missing custom setting fails during declaration, before execution."""
    assert isinstance(example_training.spec, TrainSpecDraft)

    class RequiredConfig(config.TrainConfig):
        epochs: int

    @train(config=RequiredConfig)
    def fit(context: Context[RequiredConfig]) -> None:
        """Expose a required setting for this declaration test."""

    with pytest.raises(ValidationError, match="epochs"):
        stage(
            fit,
            inputs=example_training.spec.inputs,
            outputs=example_training.spec.outputs,
            metrics=example_training.spec.metrics,
            objective=example_training.spec.objective,
        )
