"""Prepare, freeze, execute, and verify the three-arm VIPER experiment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from types import ModuleType

from viper import execution
from viper._contract_traceability import RepoSymbolRef
from viper._system_impact.codeql import (
    analyze_source,
    resolve_analysis_specs,
    source_digest,
)
from viper.api import VerifyRunRequest, verify_run
from viper.artifacts import artifact
from viper.authoring import (
    experiment,
    factor,
    input,
    plan,
    replicate,
    stage,
    variant,
)
from viper.metrics import max, measure
from viper.params import Metric, Train
from viper.references import GitFileRef, GitSource
from viper.resume import DataLoaderConfiguration
from viper.runtime import (
    LocalEnvSpec,
    NumPyRandomnessSpec,
    ParallelismSpec,
    ReproducibilitySpec,
    TorchDeterminismSpec,
    TorchPrecisionSpec,
    observe_python_env,
)
from viper.system_impact.models import SourceSnapshot
from viper.system_impact.rename import RenameSpec, compile_rename_obligations

ROOT = Path(__file__).parents[2]
RENAME_PLAN = ROOT / "plans/rename-obligation-check"
ARMS = ("ordinary", "static_graph", "graph_predicate")
STAGES = (
    ("fetch", "fetch_verified"),
    ("normalize", "normalize_verified"),
    ("validate", "validate_verified"),
    ("publish", "publish_verified"),
    ("execute", "execute_verified"),
)
SOURCE_REPOSITORY = "https://example.invalid/viper-agent-graph-memory"


def _write(path: Path, value: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value.encode() if isinstance(value, str) else value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _archive_tree(source: Path, destination: Path) -> None:
    """Archive one complete tree beneath its relative member paths."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(source.rglob("*")):
            archive.add(
                path,
                arcname=path.relative_to(source).as_posix(),
                recursive=False,
            )


def _unsegmented_task() -> str:
    return """# Task

Update the Orbit repository to its final verified interface.

- Rename `fetch`, `normalize`, `validate`, `publish`, and `execute` to
  `fetch_verified`, `normalize_verified`, `validate_verified`,
  `publish_verified`, and `execute_verified`.
- Update every governed import and call. Leave `src/orbit/decoys/` unchanged.
- Each renamed definition must accept `*, policy: str = "verified"`. Every
  governed call must pass `policy="verified"` explicitly.
- Update `config/registry.json`, `config/commands.txt`, all five contracts,
  `docs/master-execution-checklist.md`, and `docs/contract-baselines.json`.
- Use the repository's ordinary tests as you judge appropriate.

Do not commit.
"""


def _build_fixture(destination: Path) -> str:
    namespace = runpy.run_path(str(RENAME_PLAN / "build_pairblock_stress.py"))
    build = namespace["build"]
    if not callable(build):
        raise TypeError("fixture builder is not callable")
    build(destination, visible_gates=False)
    _write(destination / "TASK.md", _unsegmented_task())
    _git(destination, "add", "TASK.md")
    _git(destination, "commit", "-qm", "Use unsegmented final-state task")
    return _git(destination, "rev-parse", "HEAD")


def _compile_graph(fixture: Path, destination: Path, revision: str) -> None:
    """Build one graph and every arm's relationship evidence from it."""
    codeql_value = shutil.which("codeql")
    if codeql_value is None:
        raise RuntimeError("CodeQL is unavailable")
    codeql = Path(codeql_value).resolve()
    query_pack = ROOT / "tools/codeql/viper-python-impact"
    extraction, query, graph_format = resolve_analysis_specs(
        fixture,
        codeql_executable=codeql,
        query_pack=query_pack,
        suite="rename-facts.qls",
    )
    graph = analyze_source(
        fixture,
        snapshot=SourceSnapshot(
            base_revision=revision,
            source_sha256=source_digest(fixture),
            revision=revision,
        ),
        extraction=extraction,
        query=query,
        format=graph_format,
        codeql_executable=codeql,
        query_pack=query_pack,
        cache_root=destination.parent / "codeql-cache",
        artifact_root=destination.parent / "codeql-artifacts",
        overlay_base=True,
    )
    _write(destination / "baseline-source-graph.json", graph.model_dump_json())
    nodes: dict[tuple[str, str], dict[str, str]] = {}
    edges: list[dict[str, object]] = []
    for old, new in STAGES:
        spec = RenameSpec(
            old_target=RepoSymbolRef(path=f"src/orbit/{old}.py", symbol=old),
            new_target=RepoSymbolRef(path=f"src/orbit/{old}.py", symbol=new),
            edge_kinds=("imports", "calls", "reads", "writes"),
        )
        obligations = compile_rename_obligations(
            root=fixture,
            graph=graph,
            spec=spec,
        )
        _write(
            destination / "obligations" / f"{old}.json",
            obligations.model_dump_json(),
        )
        for target in (spec.old_target, spec.new_target):
            nodes[(str(target.path), target.symbol)] = {
                "path": str(target.path),
                "symbol": target.symbol,
            }
        for obligation in obligations.obligations:
            dependent = {
                "path": str(obligation.dependent.path),
                "symbol": obligation.dependent.symbol,
            }
            nodes[(dependent["path"], dependent["symbol"])] = dependent
            for site in obligation.baseline_sites:
                edges.append(
                    {
                        "source": dependent,
                        "target": spec.old_target.model_dump(mode="json"),
                        "required_target": spec.new_target.model_dump(mode="json"),
                        "kind": site.kind,
                        "path": str(site.path),
                        "line": site.line,
                        "column": site.column,
                        "binding_form": site.binding_form,
                    }
                )
    _write(
        destination / "impact-relationships.json",
        json.dumps(
            {
                "schema_version": 1,
                "graph_sha256": graph.receipt.graph.sha256,
                "nodes": sorted(nodes.values(), key=lambda item: tuple(item.values())),
                "edges": sorted(
                    edges,
                    key=lambda item: (
                        item["path"],
                        item["line"],
                        item["column"],
                        item["kind"],
                    ),
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    shutil.copytree(query_pack, destination / "query-pack")


def _prompts() -> dict[str, str]:
    """Return the complete accepted prompt bytes for each arm."""
    return {
        "ordinary": "Read TASK.md and complete it.\n",
        "static_graph": (
            "Read TASK.md and IMPACT_RELATIONSHIPS.json. Complete the task.\n"
        ),
        "graph_predicate": (
            "Read TASK.md and IMPACT_RELATIONSHIPS.json. Query unresolved "
            "relationships with `python .viper/unresolved.py` while working. "
            "Complete the task.\n"
        ),
    }


def prepare_project(root: Path) -> str:
    """Create one committed VIPER project containing every frozen input."""
    root.mkdir(parents=True, exist_ok=False)
    inputs = root / "inputs"
    with tempfile.TemporaryDirectory(prefix="viper-agent-inputs-") as directory:
        temporary = Path(directory)
        fixture = temporary / "fixture"
        fixture_revision = _build_fixture(fixture)
        graph = temporary / "graph"
        _compile_graph(fixture, graph, fixture_revision)
        _archive_tree(fixture, inputs / "fixture.tar.gz")
        _archive_tree(graph, inputs / "graph-evidence.tar.gz")
    for arm, prompt in _prompts().items():
        _write(inputs / "prompts" / f"{arm}.txt", prompt)
    _write(
        inputs / "hidden-evaluator.py",
        (RENAME_PLAN / "evaluate_pairblock_candidate.py").read_bytes(),
    )
    _write(root / "trial.py", Path(__file__).with_name("trial.py").read_bytes())
    _write(root / "predicate.py", Path(__file__).with_name("predicate.py").read_bytes())
    _write(root / "viper.toml", "[project]\nschema_version = 1\n")
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    _write(root / "environment.lock", f"python=={python_version}\n")
    _write(root / ".gitignore", ".viper/\n__pycache__/\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "experiment@example.invalid")
    _git(root, "config", "user.name", "VIPER Experiment")
    _git(root, "remote", "add", "origin", SOURCE_REPOSITORY)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "Freeze agent experiment inputs")
    return _git(root, "rev-parse", "HEAD")


def _load_trial(project: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "agent_graph_memory_trial",
        project / "trial.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load generated trial module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _reproducibility() -> ReproducibilitySpec:
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
            dataloader=DataLoaderConfiguration(workers=0),
        ),
        numpy_randomness=NumPyRandomnessSpec(),
    )


def run_experiment(project: Path, *, model: str, timeout_seconds: int) -> Path:
    """Freeze and execute one verified VIPER run per arm."""
    commit = prepare_project(project)
    trial = _load_trial(project)
    fixtures = {
        "fixture": input("inputs/fixture.tar.gz", data_role="validation"),
        "graph_evidence": input(
            "inputs/graph-evidence.tar.gz",
            data_role="validation",
        ),
        "evaluator": input("inputs/hidden-evaluator.py", data_role="validation"),
    }
    drafts = {}
    for arm in ARMS:
        params = Train.model_validate(
            {
                "arm": arm,
                "model": model,
                "timeout_seconds": timeout_seconds,
                "fixture_sha256": _sha256(project / "inputs/fixture.tar.gz"),
                "graph_evidence_sha256": _sha256(
                    project / "inputs/graph-evidence.tar.gz"
                ),
                "prompt_sha256": _sha256(project / f"inputs/prompts/{arm}.txt"),
                "evaluator_sha256": _sha256(project / "inputs/hidden-evaluator.py"),
            }
        )
        outputs = {
            name: artifact(
                path=f"artifacts/models/agent_trial/{filename}",
                loader=trial.load_bytes,
                data_role="validation",
            )
            for name, filename in {
                "transcript": "transcript.jsonl",
                "patch": "candidate.patch",
                "model": "candidate.tar.gz",
                "state": "trial-state.json",
                "usage": "usage.json",
                "verdict": "verdict.json",
                "evaluator_output": "hidden-evaluator.txt",
            }.items()
        }
        acceptance = measure(trial.candidate_acceptance, params=Metric())
        trial_stage = stage(
            trial.run_agent_trial,
            params=params,
            inputs={
                **fixtures,
                "prompt": input(
                    f"inputs/prompts/{arm}.txt",
                    data_role="validation",
                ),
            },
            artifacts=outputs,
            metrics=(acceptance,),
            objective=max(acceptance),
        )
        drafts[arm] = variant(
            levels={"arm": arm},
            stages={"agent_trial": trial_stage},
            estimator=trial_stage.artifacts["model"],
        )
    study = experiment(
        experiment_id="agent_graph_memory",
        factors={"arm": factor(levels=ARMS)},
        variants=drafts,
        replicates={"replicate_01": replicate(seed=7)},
    )
    source = GitSource.model_validate(
        {"repository": SOURCE_REPOSITORY, "commit": commit}
    )
    environment = LocalEnvSpec(
        lockfile=GitFileRef.model_validate(
            {
                "repository": SOURCE_REPOSITORY,
                "commit": commit,
                "path": "environment.lock",
            }
        ),
        python_env=observe_python_env(),
    )
    results: dict[str, object] = {}
    for arm in ARMS:
        draft = plan(
            experiment=study,
            variant=arm,
            replicate="replicate_01",
            source=source,
            env=environment,
            reproducibility=_reproducibility(),
        )
        print(f"{arm}: starting VIPER run", flush=True)
        result = execution.run(
            project,
            draft,
            timeout_seconds=timeout_seconds + 180,
        )
        verified = verify_run(
            VerifyRunRequest(
                path=result.resolved_run_path,
                root=project,
                trusted_source_repositories=frozenset({SOURCE_REPOSITORY}),
            )
        )
        run_root = result.resolved_run_path.parent
        verdict = json.loads(
            (run_root / "artifacts/models/agent_trial/verdict.json").read_text()
        )
        usage = json.loads(
            (run_root / "artifacts/models/agent_trial/usage.json").read_text()
        )
        verification_path = project / "results" / f"{arm}-verification.json"
        _write(
            verification_path,
            verified.model_dump_json(indent=2) + "\n",
        )
        results[arm] = {
            "run_id": verified.run_id,
            "resolved_run": result.resolved_run_path.relative_to(project).as_posix(),
            "verification": verification_path.relative_to(project).as_posix(),
            "verification_sha256": _sha256(verification_path),
            "verdict": verdict,
            "usage": usage,
        }
        print(
            f"{arm}: verified; hidden evaluator "
            f"{'passed' if verdict['accepted'] else 'failed'}",
            flush=True,
        )
    summary = project / "results/summary.json"
    _write(
        summary,
        json.dumps(
            {
                "schema_version": 1,
                "experiment_id": "agent_graph_memory",
                "source_commit": commit,
                "model": model,
                "timeout_seconds": timeout_seconds,
                "arms": results,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return summary


def main() -> int:
    """Parse pilot controls and run the complete verified experiment."""
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--timeout-seconds", type=int, default=480)
    arguments = parser.parse_args()
    summary = run_experiment(
        arguments.project.resolve(),
        model=arguments.model,
        timeout_seconds=arguments.timeout_seconds,
    )
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
