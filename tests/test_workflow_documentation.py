"""Verify documented release and continuous-integration workflows."""

from __future__ import annotations

import re

from tests._documentation import (
    ROOT,
)

MASTER_EXECUTION_CHECKLIST = ROOT / "docs/development/master-execution-checklist.md"

RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"

WORKFLOWS = tuple(sorted((ROOT / ".github/workflows").glob("*.yml")))

_PHASE_HEADING = re.compile(r"^## \d+\. Master Phase (?P<phase>\d+)\b.*$", re.MULTILINE)


def test_terminal_release_gate_follows_every_implementation_phase() -> None:
    """Keep full repository and wheel validation after the last build phase."""
    checklist = MASTER_EXECUTION_CHECKLIST.read_text()
    phases = tuple(_PHASE_HEADING.finditer(checklist))
    assert phases
    assert int(phases[-1].group("phase")) == 21
    terminal = checklist[phases[-1].start() :]
    earlier = checklist[: phases[-1].start()]

    for command in ("make check", "make check-integration", "make check-release"):
        assert command in terminal
        assert command not in earlier
    assert (
        "Install the wheel with the `mcp`, `knowledge`, and `research` extras"
        in terminal
    )


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
