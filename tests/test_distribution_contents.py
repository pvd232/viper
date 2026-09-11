"""Build release archives and verify their public file boundary."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from viper import _subprocess as subprocess

ROOT = Path(__file__).parents[1]

FORBIDDEN_PREFIXES = (
    ".vscode/",
    "docs/development/",
    "docs/internal/",
    "plans/",
    "src/viper/_system_impact/",
    "src/viper/system_impact/",
    "tests/data/system_impact/",
    "tools/codeql/",
    "tools/plan/",
    "viper/_system_impact/",
    "viper/system_impact/",
    "workday-",
)

FORBIDDEN_PATHS = {
    "src/viper/_contract_traceability.py",
    "src/viper/scheduling.py",
    "tests/test_codeql_analysis.py",
    "tests/test_codeql_graph_semantics.py",
    "tests/test_contract_documentation.py",
    "tests/test_contract_target_parity.py",
    "tests/test_contract_traceability.py",
    "tests/test_plan_check.py",
    "tests/test_public_authoring_test_plan.py",
    "tests/test_system_impact.py",
    "tests/test_system_impact_explain.py",
    "tools/refresh_contract_baselines.py",
    "viper/_contract_traceability.py",
    "viper/scheduling.py",
}


def _distribution_members(path: Path) -> tuple[str, ...]:
    """Return archive member paths relative to the distribution root."""
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return tuple(sorted(archive.namelist()))

    with tarfile.open(path, mode="r:gz") as archive:
        members = []
        for member in archive.getnames():
            parts = PurePosixPath(member).parts
            if len(parts) > 1:
                members.append(PurePosixPath(*parts[1:]).as_posix())
        return tuple(sorted(members))


def _distribution_metadata(path: Path) -> bytes:
    """Read the core metadata document from one built archive."""
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            name = next(
                member for member in archive.namelist() if member.endswith("/METADATA")
            )
            return archive.read(name)

    with tarfile.open(path, mode="r:gz") as archive:
        member = next(
            item
            for item in archive.getmembers()
            if PurePosixPath(item.name).name == "PKG-INFO"
            and len(PurePosixPath(item.name).parts) == 2
        )
        extracted = archive.extractfile(member)
        assert extracted is not None
        return extracted.read()


def _distribution_file(path: Path, member_path: str) -> bytes:
    """Read one archive member by its distribution-relative path."""
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return archive.read(member_path)

    with tarfile.open(path, mode="r:gz") as archive:
        member = next(
            item
            for item in archive.getmembers()
            if PurePosixPath(*PurePosixPath(item.name).parts[1:]).as_posix()
            == member_path
        )
        extracted = archive.extractfile(member)
        assert extracted is not None
        return extracted.read()


def _experimental_members(members: tuple[str, ...]) -> tuple[str, ...]:
    """Return members owned by the extracted experimental subsystem."""
    return tuple(
        member
        for member in members
        if member in FORBIDDEN_PATHS
        or any(member.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
    )


def test_experimental_member_detection_reports_exact_paths() -> None:
    """Name each offending archive member while retaining public modules."""
    members = (
        "src/viper/knowledge.py",
        "src/viper/system_impact/models.py",
        "tools/refresh_contract_baselines.py",
    )

    assert _experimental_members(members) == (
        "src/viper/system_impact/models.py",
        "tools/refresh_contract_baselines.py",
    )


def test_built_distributions_exclude_experimental_surfaces(tmp_path: Path) -> None:
    """Reject a wheel or source distribution containing an extracted path."""
    subprocess.run(
        (
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--outdir",
            str(tmp_path),
            str(ROOT),
        ),
        check=True,
    )

    distributions = tuple(sorted(tmp_path.iterdir()))
    assert len(distributions) == 2
    assert {path.suffix for path in distributions} == {".gz", ".whl"}

    inventories = {path.name: _distribution_members(path) for path in distributions}
    assert {
        name: _experimental_members(members)
        for name, members in inventories.items()
        if _experimental_members(members)
    } == {}

    wheel_members = next(
        members for name, members in inventories.items() if name.endswith(".whl")
    )
    source_members = next(
        members for name, members in inventories.items() if name.endswith(".tar.gz")
    )
    assert {"viper/catalog.py", "viper/knowledge.py", "viper/mcp.py"} <= set(
        wheel_members
    )
    assert {
        "llms.txt",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        ".github/workflows/release.yml",
        "docs/releases/receipts/v0.1.0a3-mantra-gpu.json",
        "docs/reference/agents.md",
        "src/viper/catalog.py",
        "src/viper/knowledge.py",
        "src/viper/mcp.py",
        "docs/how-to/metrics-and-benchmarks.md",
        "examples/cpu_quickstart.py",
        "examples/evaluation.py",
        "examples/variants.py",
        "examples/workflow_functions.py",
        "examples/data/tiny.csv",
        "examples/data/held_out.csv",
    } <= set(source_members)
    for distribution in distributions:
        metadata = _distribution_metadata(distribution)
        assert b"Provides-Extra: knowledge" not in metadata
        assert b"usearch" not in metadata

        package_prefix = "" if distribution.suffix == ".whl" else "src/"
        for module in ("api.py", "cli.py", "mcp.py"):
            source = _distribution_file(
                distribution,
                f"{package_prefix}viper/{module}",
            )
            assert b'"analyze_impact"' not in source
            assert b'"explain_impact"' not in source
