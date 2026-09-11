"""Verify documented release and continuous-integration workflows."""

from __future__ import annotations

import re

from tests._documentation import (
    ROOT,
)

RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"

WORKFLOWS = tuple(sorted((ROOT / ".github/workflows").glob("*.yml")))


def test_release_workflow_copies_only_existing_acceptance_inputs() -> None:
    """Require every copied release-acceptance input to exist in the repository."""
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    copy_commands = re.findall(
        r'^\s*cp -R (?P<sources>.+?) "\$ACCEPTANCE_ROOT/"$',
        workflow,
        flags=re.MULTILINE,
    )

    assert copy_commands
    for sources in copy_commands:
        for source in sources.split():
            assert (ROOT / source).exists(), source


def test_workflows_pin_actions_to_full_commit_shas() -> None:
    """Require immutable full-length commit references for external actions."""
    references = tuple(
        (match.group("action"), match.group("revision"))
        for workflow in WORKFLOWS
        for match in re.finditer(
            r"uses:\s+(?P<action>[^\s@]+)@(?P<revision>[^\s#]+)",
            workflow.read_text(encoding="utf-8"),
        )
    )

    assert references
    for action, revision in references:
        assert re.fullmatch(r"[0-9a-f]{40}", revision), action


def test_workflows_limit_token_and_checkout_credentials() -> None:
    """Keep workflow tokens read-only and remove unused checkout credentials."""
    checkout = re.compile(
        r"uses: actions/checkout@[0-9a-f]{40}[^\n]*\n"
        r"\s+with:\n"
        r"\s+persist-credentials: false"
    )

    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        assert re.search(r"^permissions:\n  contents: read$", text, re.MULTILINE)
        assert len(checkout.findall(text)) == text.count("uses: actions/checkout@")


def test_wheel_smoke_gates_use_the_public_module_contract() -> None:
    """Run the installed-package inventory instead of expecting root exports."""
    workflows = "\n".join(
        workflow.read_text(encoding="utf-8") for workflow in WORKFLOWS
    )

    assert "viper.__all__" not in workflows
    assert workflows.count("python -I -m pytest tests/test_public_api.py -q") >= 4


def test_release_downloads_distributions_from_successful_ci() -> None:
    """Publish CI's retained files without rebuilding after GPU acceptance."""
    workflow = RELEASE_WORKFLOW.read_text()
    build_job = workflow.split("  publish-testpypi:", 1)[0]
    ci = (ROOT / ".github/workflows/ci.yml").read_text()

    assert '--commit "$RELEASE_COMMIT" --status success' in build_job
    assert 'gh run download "$CI_RUN_ID"' in build_job
    assert "python -m build" not in build_job
    assert "name: python-package-distributions" in ci
    assert "path: dist/" in ci
