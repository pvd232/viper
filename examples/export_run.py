"""Run training once, export its evidence, and verify the portable bundle."""

from examples.cpu_quickstart import study
from viper import execution
from viper.authoring import plan
from viper.references import GitFileRef
from viper.repository import read_source, resolve_root
from viper.runtime import LocalEnvSpec, observe_python_env


def main() -> None:
    """Export the complete saved graph without repeating stage computation."""
    root = resolve_root()
    source = read_source(root)
    environment = LocalEnvSpec(
        lockfile=GitFileRef(
            repository=source.repository, commit=source.commit, path="pyproject.toml"
        ),
        python_env=observe_python_env(),
    )
    draft = plan(experiment=study, source=source, env=environment)
    result = execution.run(draft)
    trusted = frozenset({str(source.repository)})
    exported = execution.export_run(
        root,
        result.path,
        root / "exports" / draft.run_id,
        trusted_source_repositories=trusted,
    )
    checked = execution.verify_run_bundle(
        exported.bundle_path,
        trusted_source_repositories=trusted,
        expected_manifest_sha256=exported.manifest_sha256,
    )
    print(f"bundle: {checked.bundle_path}")
    print(f"manifest: {checked.manifest_sha256}")


if __name__ == "__main__":
    main()
