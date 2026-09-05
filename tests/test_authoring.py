"""Tests for canonical protocol-file authoring and run-plan freezing."""

import hashlib
import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError

import viper.params as params
from viper import _subprocess as subprocess
from viper import parameters
from viper._schema import (
    PARAMETERS,
    RESUME_STATE,
)
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
from viper.experiments import (
    ExperimentSpec,
    FactorSpec,
    ReplicateSpec,
    TrainVariantStageParams,
    VariantSpec,
)
from viper.http import CustomHttpDraft, HttpContext, HttpResult, http
from viper.metrics import (
    FloatComparator,
    MetricDependency,
    MetricImplementationRef,
    MetricSpec,
    measure,
    metric,
    min,
)
from viper.parameters import ParameterModelRef
from viper.preflight import preflight_plan
from viper.references import GitSource, LocalFileRef, ResolvedRunRef
from viper.runs import RunSpec
from viper.runtime import EnvSpec, ReproducibilitySpec
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
        "python_environment": {
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
    parameter_model: ParameterModelRef,
    implementation: StageImplementationRef,
    *,
    commit: str = COMMIT,
) -> TrainSpec:
    """Build one valid training stage with its terminal checkpoint."""
    return TrainSpec.model_validate(
        {
            "kind": "train",
            "implementation": implementation.model_dump(mode="json"),
            "parameter_model": parameter_model.model_dump(mode="json"),
            "inputs": {
                "training_dataset": {
                    "kind": "stored",
                    "pointer": {
                        "kind": "git",
                        "repository": "https://github.com/example/viper-project",
                        "commit": commit,
                        "path": "inputs/datasets/replogle/current.pointer.yaml",
                    },
                    "path": "inputs/datasets/replogle/dataset.h5ad",
                    "data_role": "training",
                }
            },
            "params": {"schema_version": 1, "epochs": 2},
            "artifacts": {
                PARAMETERS: {
                    "kind": "file",
                    "path": (
                        f"{RUN_ROOT}/artifacts/models/strand/parameters.safetensors"
                    ),
                    "loader": loader_ref(
                        "project_code/loaders/parameters.py"
                    ).model_dump(mode="json"),
                    "data_role": "training",
                },
                RESUME_STATE: {
                    "kind": "file",
                    "path": (f"{RUN_ROOT}/artifacts/models/strand/resume_state.pt"),
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
                b"from viper import parameters\n\n"
                b"class StrandTrainParameters(parameters.Train):\n"
                b"    epochs: int = Field(gt=0)\n"
            )
            parameter_path = root / "project/parameters/train.py"
            parameter_path.parent.mkdir(parents=True)
            parameter_path.write_bytes(parameter_raw)
            implementation_raw = (
                b"from project.parameters.train import StrandTrainParameters\n"
                b"from viper.stages import train\n\n"
                b"@train(params=StrandTrainParameters)\n"
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
            parameter_model = ParameterModelRef(
                owner="project",
                path="project/parameters/train.py",
                symbol="StrandTrainParameters",
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
                        parameter_model,
                        implementation,
                        commit=source_commit,
                    )
                )
            )
            draft = RunPlanDraft.model_validate(
                {
                    "run_id": RUN_ID,
                    "experiment_id": "e001_strand",
                    "variant_id": "baseline",
                    "replicate_id": "replicate_01",
                    "seed": 42,
                    "source": {
                        "kind": "git",
                        "repository": "https://github.com/example/viper-project",
                        "commit": source_commit,
                    },
                    "environment": environment_payload(source_commit),
                    "reproducibility": reproducibility_payload(),
                    "stages": [
                        {"stage_id": "train", "spec_source": "drafts/train.yaml"}
                    ],
                    "estimator": {
                        "stage_id": "train",
                        "artifact_name": PARAMETERS,
                    },
                }
            )

            frozen = freeze_run_plan(root, draft)
            stage_path, run_path = frozen.files
            stage_raw = stage_path.read_bytes()
            loaded_run = RunSpec.model_validate(parse_yaml_bytes(run_path.read_bytes()))

        self.assertEqual(
            loaded_run.stages[0].sha256,
            hashlib.sha256(stage_raw).hexdigest(),
        )
        self.assertEqual(loaded_run.stages[0].bytes, len(stage_raw))
        self.assertEqual(
            stage_path.relative_to(root).as_posix(),
            f"{RUN_ROOT}/stages/train/spec.yaml",
        )
        self.assertEqual(run_path.relative_to(root).as_posix(), f"{RUN_ROOT}/spec.yaml")

    def test_experiment_and_variant_writers_use_identity_paths(self) -> None:
        """Write experiment and variant records under one experiment identity."""
        metric = MetricSpec(
            parameter_model=parameters.model_ref(parameters.Metric),
            metric_id="training_loss",
            implementation=MetricImplementationRef(
                path="project_code/metrics/training_loss.py",
                symbol="compute",
                sha256="a" * 64,
                bytes=1,
            ),
            params=parameters.Metric(),
            mode="in_stage",
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
            stage_params=(
                TrainVariantStageParams(
                    stage_id="train",
                    params=parameters.Train.model_validate({"epochs": 2}),
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
    def fetch(context: HttpContext[params.Http]) -> HttpResult:
        return HttpResult(body=context.destination, response=context.request)

    artifact_draft = artifact(
        path="artifacts/data.csv", loader=load, data_role="training"
    )
    http_draft = CustomHttpDraft(implementation=fetch, params=params.Http())

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

    @metric(metric_id="training_loss", mode="in_stage")
    def training_loss(context) -> float:
        """Return one stable loss for the authoring boundary."""
        return 1.0

    @train(params=params.Train)
    def fit(context: Context[params.Train]) -> None:
        context.artifacts["model"].write_bytes(b"model")

    model = artifact(
        path="artifacts/model.bin",
        loader=lambda path: path.read_bytes(),
        data_role="training",
    )
    dataset = external_input(
        path="inputs/raw/dataset.csv",
        data_role="training",
    )
    loss = measure(training_loss, params=params.Metric())
    draft = stage(
        fit,
        params=params.Train(),
        inputs={"dataset": dataset},
        artifacts={"model": model},
        metrics=(loss,),
        objective=min(loss),
    )

    assert draft.spec.implementation is fit
    assert draft.artifacts["model"].producer is draft


def _immutable_plan() -> tuple[RunPlanDraft, dict[str, VariantDraft]]:
    """Build one small plan and retain its caller-owned variant mapping."""

    @metric(metric_id="training_loss", mode="in_stage")
    def training_loss(context) -> float:
        return 1.0

    @train(params=params.Train)
    def fit(context: Context[params.Train]) -> None:
        context.artifacts["model"].write_bytes(b"model")

    loss = measure(training_loss, params=params.Metric())
    train_stage = stage(
        fit,
        params=params.Train(),
        inputs={
            "dataset": external_input(
                path="inputs/raw/dataset.csv",
                data_role="training",
            )
        },
        artifacts={
            "model": artifact(
                path="artifacts/model.bin",
                loader=lambda path: path.read_bytes(),
                data_role="training",
            )
        },
        metrics=(loss,),
        objective=min(loss),
    )
    variants = {
        "baseline": variant(
            levels={"rank": "full"},
            stages={"train": train_stage},
            estimator=train_stage.artifacts["model"],
        )
    }
    authored = experiment(
        experiment_id="e001_strand",
        factors={"rank": factor(levels=("full", "low"))},
        variants=variants,
        replicates={"replicate_01": replicate(seed=42)},
    )
    env_payload = environment_payload()
    env_payload["python_env"] = env_payload.pop("python_environment")
    return (
        plan(
            experiment=authored,
            variant="baseline",
            replicate="replicate_01",
            source=GitSource(
                repository="https://github.com/example/viper-project",
                commit=COMMIT,
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
    (tmp_path / "viper.toml").write_text("[project]\nschema_version = 1\n")
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
        "from viper import params\n"
        "from viper.metrics import metric\n"
        "from viper.stages import Context, train\n\n"
        "@metric(metric_id='training_loss', mode='in_stage')\n"
        "def training_loss(context):\n"
        "    return 1.0\n\n"
        "@train(params=params.Train)\n"
        "def fit(context: Context[params.Train]):\n"
        "    context.artifacts['model'].write_bytes(b'model')\n\n"
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
    loss = measure(module.training_loss, params=params.Metric())
    train_stage = stage(
        module.fit,
        params=params.Train(),
        inputs={
            "dataset": external_input(
                path="inputs/raw/dataset.csv",
                data_role="training",
            )
        },
        artifacts={
            "model": artifact(
                path="artifacts/models/model/model.bin",
                loader=module.load,
                data_role="training",
            ),
            "state": artifact(
                path="artifacts/models/state/state.bin",
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
                estimator=train_stage.artifacts["model"],
            )
        },
        replicates={"replicate_01": replicate(seed=42)},
    )
    env_payload = environment_payload(commit)
    env_payload["python_env"] = env_payload.pop("python_environment")
    draft = plan(
        experiment=authored,
        variant="baseline",
        replicate="replicate_01",
        source=GitSource(
            repository="https://github.com/example/viper-project",
            commit=commit,
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

    @metric(metric_id="accuracy", mode="post_stage")
    def accuracy(context) -> float:
        return 0.95

    selected_metric = measure(
        accuracy,
        dependencies=(
            MetricDependency(
                source="artifact",
                name="predictions",
                required_data_role="benchmark",
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


def test_experiment_expansion_is_canonical() -> None:
    """Use declaration order and the caller's exact run IDs."""
    single, _ = _immutable_plan()
    baseline = single.experiment.variants["baseline"]
    draft = experiment(
        experiment_id=single.experiment.experiment_id,
        factors=single.experiment.factors,
        variants={"baseline": baseline, "l2": baseline},
        replicates={
            "replicate_01": replicate(seed=42),
            "replicate_02": replicate(seed=43),
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
