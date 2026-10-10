"""Parse documentation structures shared by the documentation test modules."""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote

from pydantic import BaseModel

import viper.api as api
import viper.artifacts as artifacts
import viper.authoring as authoring
import viper.benchmark as benchmark
import viper.catalog as catalog
import viper.config as config
import viper.execution as execution
import viper.execution.errors as execution_errors
import viper.http as http
import viper.inspection as inspection
import viper.journals as journals
import viper.knowledge as knowledge
import viper.metrics as metrics
import viper.outputs as outputs
import viper.randomness as randomness
import viper.references as references
import viper.repository as repository
import viper.restoration as restoration
import viper.resume as resume
import viper.retention as retention
import viper.runtime as runtime
import viper.serialization as serialization
import viper.stages as stages
import viper.storage as storage
import viper.test_impact as test_impact

ROOT = Path(__file__).parents[1]

DOCUMENTED_MODULES = {
    module.__name__: module
    for module in (
        api,
        artifacts,
        authoring,
        benchmark,
        catalog,
        config,
        execution,
        execution_errors,
        http,
        inspection,
        journals,
        knowledge,
        metrics,
        outputs,
        randomness,
        references,
        repository,
        restoration,
        resume,
        retention,
        runtime,
        serialization,
        stages,
        storage,
        test_impact,
    )
}

_FENCED_CODE = re.compile(r"^```[^\n]*\n.*?^```[ \t]*$", re.MULTILINE | re.DOTALL)


def python_blocks(markdown: str) -> tuple[str, ...]:
    """Return every complete Python fence from one Markdown document."""
    return tuple(re.findall(r"```python\n(.*?)\n```", markdown, flags=re.DOTALL))


def invocation_errors(program: str) -> tuple[str, ...]:
    """Check explicit VIPER imports and direct calls without executing a snippet.

    Resolve documented imports against a fixed inventory of public modules.
    Signature binding checks positional and named arguments; Pydantic fields
    additionally reject unknown keys. Instance methods and names supplied by a
    linked preceding program remain the execution tests' responsibility.
    """
    tree = ast.parse(program)
    bindings: dict[str, object] = {}
    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "viper":
                for alias in node.names:
                    module = DOCUMENTED_MODULES.get(f"viper.{alias.name}")
                    if module is None:
                        errors.append(
                            f"line {node.lineno}: missing module {alias.name}"
                        )
                    else:
                        bindings[alias.asname or alias.name] = module
            elif node.module.startswith("viper."):
                module = DOCUMENTED_MODULES.get(node.module)
                if module is None:
                    errors.append(
                        f"line {node.lineno}: unregistered module {node.module}"
                    )
                    continue
                for alias in node.names:
                    value = getattr(module, alias.name, None)
                    if value is None:
                        errors.append(
                            f"line {node.lineno}: missing {node.module}.{alias.name}"
                        )
                    else:
                        bindings[alias.asname or alias.name] = value
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("viper.") and alias.asname:
                    module = DOCUMENTED_MODULES.get(alias.name)
                    if module is None:
                        errors.append(
                            f"line {node.lineno}: unregistered module {alias.name}"
                        )
                    else:
                        bindings[alias.asname] = module

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        value = None
        if isinstance(node.func, ast.Name):
            value = bindings.get(node.func.id)
        elif isinstance(node.func, ast.Attribute) and isinstance(
            node.func.value, ast.Name
        ):
            parent = bindings.get(node.func.value.id)
            if isinstance(parent, ModuleType):
                value = getattr(parent, node.func.attr, None)
                if value is None:
                    name = f"{parent.__name__}.{node.func.attr}"
                    errors.append(f"line {node.lineno}: missing {name}")
                    continue
        if not callable(value):
            continue
        if any(isinstance(arg, ast.Starred) for arg in node.args) or any(
            keyword.arg is None for keyword in node.keywords
        ):
            continue
        keywords = {keyword.arg: object() for keyword in node.keywords if keyword.arg}
        try:
            inspect.signature(value).bind(*[object() for _ in node.args], **keywords)
            if inspect.isclass(value) and issubclass(value, BaseModel):
                if value.model_config.get("extra") == "forbid":
                    unknown = set(keywords) - set(value.model_fields)
                    if unknown:
                        raise TypeError(f"unknown fields: {sorted(unknown)}")
        except (TypeError, ValueError) as error:
            errors.append(f"line {node.lineno}: {ast.unparse(node.func)}: {error}")
    return tuple(errors)


def dotted_name(node: ast.AST) -> str | None:
    """Return one dotted Python name without evaluating it."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        if parent is not None:
            return f"{parent}.{node.attr}"
    return None


def normalized(node: ast.AST | None) -> str | None:
    """Render one declaration while ignoring qualified package prefixes."""
    if node is None:
        return None
    return ast.unparse(node).replace("viper.", "")


def class_fields(node: ast.ClassDef) -> tuple[tuple[str, str | None, str | None], ...]:
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
                normalized(statement.annotation),
                normalized(statement.value),
            )
        )
    return tuple(fields)


def class_bases(node: ast.ClassDef) -> tuple[str | None, ...]:
    """Describe the declared bases of one class."""
    return tuple(normalized(base) for base in node.bases)


def class_methods(
    node: ast.ClassDef,
) -> tuple[tuple[str, str, str | None, tuple[str, ...]], ...]:
    """Describe methods declared directly by one contract class."""
    return tuple(
        (
            statement.name,
            ast.unparse(statement.args).replace("viper.", ""),
            normalized(statement.returns),
            tuple(
                ast.unparse(decorator).replace("viper.", "")
                for decorator in statement.decorator_list
            ),
        )
        for statement in node.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def definitions(
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


def github_anchors(markdown: str) -> set[str]:
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


def local_links(markdown: str) -> tuple[str, ...]:
    """Return local Markdown link targets while excluding image sources."""
    prose = _FENCED_CODE.sub("", markdown)
    return tuple(re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", prose))


def numbered_contract_section(text: str, number: int) -> str:
    """Return one numbered top-level section from a contract."""
    match = re.search(
        rf"^## {number}\. .+?(?=^## \d+\. |\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    return match.group(0)


def decoded_local_link(link: str) -> tuple[str, str | None]:
    """Split and URL-decode one local Markdown path and optional anchor."""
    path, separator, anchor = link.partition("#")
    return unquote(path), unquote(anchor) if separator else None
