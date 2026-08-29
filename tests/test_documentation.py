"""Keep the published documentation aligned with the executable package."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote

from viper.api import OPERATIONS

ROOT = Path(__file__).parents[1]
PROTOCOL = ROOT / "docs/reference/protocol.md"
API_REFERENCE = ROOT / "docs/reference/api.md"
TRAINING_GUIDES = (
    ROOT / "README.md",
    API_REFERENCE,
    ROOT / "docs/tutorials/getting-started.md",
    ROOT / "docs/explanation/how-viper-works.md",
)

PUBLIC_MARKDOWN = (
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "CONTRIBUTING.md",
    *sorted((ROOT / "docs").rglob("*.md")),
    *sorted((ROOT / "examples").rglob("*.md")),
    ROOT / "tests/README.md",
)

PROTOCOL_MODULES = (
    "_schema.py",
    "parameters.py",
    "references.py",
    "artifacts.py",
    "inputs.py",
    "stages.py",
    "runtime.py",
    "resume.py",
    "metrics.py",
    "experiments.py",
    "runs.py",
    "benchmark.py",
    "http.py",
)

PROTOCOL_ALIASES = {
    "ArtifactSpec",
    "AttemptFailureCode",
    "AttemptPurpose",
    "AttemptStatus",
    "ComputeBackendContext",
    "ComputeSpec",
    "DataRole",
    "EnvironmentSpec",
    "GeneratorFamily",
    "GCEProvisioningRef",
    "HostContext",
    "HttpTransportSpec",
    "InputRef",
    "MetricKind",
    "MetricMode",
    "ParameterizedStageSpec",
    "ResolvedArtifact",
    "ResolvedEnvironment",
    "ResolvedInputRef",
    "ResolvedSpec",
    "Spec",
    "StageResultSnapshot",
    "StartupVariable",
    "StorageModel",
    "StorageRef",
    "VariantStageParams",
}


def _python_blocks(markdown: str) -> tuple[str, ...]:
    """Return every complete Python fence from one Markdown document."""
    return tuple(re.findall(r"```python\n(.*?)\n```", markdown, flags=re.DOTALL))


def _normalized(node: ast.AST | None) -> str | None:
    """Render one declaration while ignoring qualified package prefixes."""
    if node is None:
        return None
    return ast.unparse(node).replace("viper.", "")


def _class_fields(node: ast.ClassDef) -> tuple[tuple[str, str | None, str | None], ...]:
    """Describe fields declared directly by one class."""
    fields = []
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign):
            continue
        if not isinstance(statement.target, ast.Name):
            continue
        fields.append(
            (
                statement.target.id,
                _normalized(statement.annotation),
                _normalized(statement.value),
            )
        )
    return tuple(fields)


def _class_bases(node: ast.ClassDef) -> tuple[str | None, ...]:
    """Describe the declared bases of one class."""
    return tuple(_normalized(base) for base in node.bases)


def _definitions(
    paths: tuple[Path, ...],
) -> tuple[dict[str, ast.ClassDef], dict[str, ast.AST]]:
    """Collect top-level classes and type aliases from Python source files."""
    classes: dict[str, ast.ClassDef] = {}
    aliases: dict[str, ast.AST] = {}
    for path in paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes[node.name] = node
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    aliases[target.id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    aliases[node.target.id] = node.value
    return classes, aliases


def _protocol_definitions() -> tuple[dict[str, ast.ClassDef], dict[str, ast.AST]]:
    """Collect the classes and aliases shown in the formal protocol."""
    classes: dict[str, ast.ClassDef] = {}
    aliases: dict[str, ast.AST] = {}
    for block in _python_blocks(PROTOCOL.read_text()):
        tree = ast.parse(block, filename=str(PROTOCOL))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                if node.name in classes:
                    raise AssertionError(f"duplicate protocol class: {node.name}")
                classes[node.name] = node
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    aliases[target.id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    aliases[node.target.id] = node.value
    return classes, aliases


def _github_anchors(markdown: str) -> set[str]:
    """Derive the GitHub-style anchor for every Markdown heading."""
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*$", markdown, flags=re.MULTILINE):
        plain = re.sub(r"<[^>]+>", "", heading)
        plain = plain.replace("`", "").strip().lower()
        slug = re.sub(r"[^\w\- ]", "", plain, flags=re.UNICODE)
        slug = re.sub(r"\s+", "-", slug)
        occurrence = counts.get(slug, 0)
        counts[slug] = occurrence + 1
        anchors.add(slug if occurrence == 0 else f"{slug}-{occurrence}")
    return anchors


def _local_links(markdown: str) -> tuple[str, ...]:
    """Return local Markdown link targets while excluding image sources."""
    return tuple(re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", markdown))


def test_protocol_class_fields_match_their_defining_modules() -> None:
    """Require every repeated protocol class to show exact current fields."""
    source_paths = tuple(ROOT / "src/viper" / name for name in PROTOCOL_MODULES)
    source_classes, _ = _definitions(source_paths)
    protocol_classes, _ = _protocol_definitions()
    repeated = source_classes.keys() & protocol_classes.keys()

    assert len(repeated) >= 45
    mismatches = {
        name: (
            (_class_bases(source_classes[name]), _class_fields(source_classes[name])),
            (
                _class_bases(protocol_classes[name]),
                _class_fields(protocol_classes[name]),
            ),
        )
        for name in sorted(repeated)
        if (
            _class_bases(source_classes[name]),
            _class_fields(source_classes[name]),
        )
        != (
            _class_bases(protocol_classes[name]),
            _class_fields(protocol_classes[name]),
        )
    }
    assert mismatches == {}


def test_protocol_type_aliases_match_their_defining_modules() -> None:
    """Require claim-bearing protocol unions to match their source aliases."""
    source_paths = tuple(ROOT / "src/viper" / name for name in PROTOCOL_MODULES)
    _, source_aliases = _definitions(source_paths)
    _, protocol_aliases = _protocol_definitions()

    assert PROTOCOL_ALIASES <= source_aliases.keys()
    assert PROTOCOL_ALIASES <= protocol_aliases.keys()
    mismatches = {
        name: (_normalized(source_aliases[name]), _normalized(protocol_aliases[name]))
        for name in sorted(PROTOCOL_ALIASES)
        if _normalized(source_aliases[name]) != _normalized(protocol_aliases[name])
    }
    assert mismatches == {}


def test_protocol_uses_renderer_safe_math_fences() -> None:
    """Keep multiline protocol equations inside balanced GitHub math fences."""
    text = PROTOCOL.read_text()
    open_fence: str | None = None
    math_fences = 0
    for line in text.splitlines():
        if not line.startswith("```"):
            continue
        if open_fence is None:
            open_fence = line
            math_fences += line == "```math"
        else:
            assert line == "```"
            open_fence = None

    assert not re.search(r"^\$\$$", text, flags=re.MULTILINE)
    assert math_fences > 0
    assert open_fence is None


def test_public_python_examples_are_syntactically_valid() -> None:
    """Require every published Python fence to parse with supported syntax."""
    for document in PUBLIC_MARKDOWN:
        for block in _python_blocks(document.read_text()):
            ast.parse(block, filename=str(document))


def test_public_markdown_links_resolve() -> None:
    """Require every repository-relative documentation link to resolve."""
    failures: list[str] = []
    for document in PUBLIC_MARKDOWN:
        text = document.read_text()
        for raw_target in _local_links(text):
            target = raw_target.strip().strip("<>")
            if target.startswith(("https://", "http://", "mailto:")):
                continue

            path_text, separator, anchor = target.partition("#")
            linked_path = (
                document if not path_text else document.parent / unquote(path_text)
            )
            linked_path = linked_path.resolve()
            if not linked_path.exists():
                failures.append(
                    f"{document.relative_to(ROOT)} -> {target}: missing file"
                )
                continue
            if separator and linked_path.suffix == ".md":
                anchors = _github_anchors(linked_path.read_text())
                if unquote(anchor) not in anchors:
                    failures.append(
                        f"{document.relative_to(ROOT)} -> {target}: missing anchor"
                    )

    assert failures == []


def test_api_operation_table_matches_python_and_cli_surfaces() -> None:
    """Keep every typed API operation beside its exact CLI command."""
    rows = re.findall(
        r"^\| `([a-z_]+)` \| `[^`]+` \| `[^`]+` \| `([a-z-]+)` \|$",
        API_REFERENCE.read_text(),
        flags=re.MULTILINE,
    )
    documented = dict(rows)

    cli_tree = ast.parse((ROOT / "src/viper/cli.py").read_text())
    cli_mapping: dict[str, str] | None = None
    for node in ast.walk(cli_tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "mapping":
            continue
        if isinstance(node.value, ast.Dict):
            cli_mapping = {
                ast.literal_eval(key): ast.literal_eval(value)
                for key, value in zip(node.value.keys, node.value.values, strict=True)
                if key is not None
            }
            break

    assert cli_mapping is not None
    expected = {operation: command for command, operation in cli_mapping.items()}
    assert tuple(documented) == OPERATIONS
    assert documented == expected


def test_changelog_starts_with_the_package_version() -> None:
    """Keep the first changelog release aligned with package metadata."""
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package_version = metadata["project"]["version"]
    first_release = re.search(r"^## ([^ ]+)", (ROOT / "CHANGELOG.md").read_text(), re.M)

    assert first_release is not None
    assert first_release.group(1) == package_version


def test_public_examples_distinguish_weights_from_the_artifact_key() -> None:
    """Keep tutorial vocabulary clear without changing the protocol artifact name."""
    public_text = "\n".join(path.read_text() for path in PUBLIC_MARKDOWN)

    assert 'weights_path = context.artifacts["parameters"]' in public_text
    assert "parameters_path" not in public_text


def test_training_examples_name_the_project_owned_training_function() -> None:
    """Keep project computation separate from VIPER's stage context."""
    undefined_calls = (
        "run_training(",
        "model = fit(",
        "update_model(",
        "save_weights(",
    )

    for path in TRAINING_GUIDES:
        text = path.read_text()
        assert "from my_project.training import train_model" in text
        assert "train_model(" in text
        assert all(call not in text for call in undefined_calls)


def test_current_docs_do_not_reference_retired_public_modules() -> None:
    """Keep current guides on the single-owner public module layout."""
    current_guides = tuple(
        path
        for path in PUBLIC_MARKDOWN
        if path.name not in {"CHANGELOG.md", "0.1.0a1.md"}
    )
    text = "\n".join(path.read_text() for path in current_guides)

    assert "viper.protocol" not in text
    assert "viper.runner" not in text
    assert "viper.verifier" not in text
    assert "docs/contracts" not in text
    assert "PUBLICATION_TODO" not in text
