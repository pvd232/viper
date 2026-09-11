"""Run the complete CPU example with a selected execution policy."""

from argparse import ArgumentParser

from cpu_quickstart import study

from viper import execution
from viper.authoring import plan
from viper.references import GitFileRef
from viper.repository import read_source
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


def main() -> None:
    """Select a policy, create its plan, and execute the training experiment."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("policy", choices=("reproducible", "relaxed", "custom"))
    arguments = parser.parse_args()
    selection = arguments.policy
    if selection == "custom":
        selection = ReproducibilitySpec(
            determinism=TorchDeterminismSpec(
                deterministic_algorithms=False,
                deterministic_warn_only=False,
                cudnn_deterministic=False,
                cudnn_benchmark=True,
                cublas_workspace_config=None,
            ),
            precision=TorchPrecisionSpec(
                float32_matmul_precision="highest",
                cudnn_allow_tf32=False,
                autocast_enabled=False,
                autocast_dtype=None,
            ),
            parallelism=ParallelismSpec(
                process_count=1,
                torch_intraop_threads=2,
                torch_interop_threads=1,
                dataloader=DataLoaderConfiguration(workers=0),
            ),
            numpy_randomness=NumPyRandomnessSpec(
                generators={},
                capture_legacy_global=True,
            ),
        )

    source = read_source()
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    draft = plan(
        experiment=study,
        source=source,
        env=environment,
        reproducibility=selection,
    )
    resolved_run = execution.run(draft)
    model_path = resolved_run.path.parent / "artifacts/train/model/model.json"
    print(f"status: {resolved_run.status}")
    print(f"model: {model_path.read_text(encoding='utf-8').strip()}")
    print(f"result: {resolved_run.path}")


if __name__ == "__main__":
    main()
