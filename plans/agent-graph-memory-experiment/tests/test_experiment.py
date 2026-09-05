"""Verify the graph-memory experiment apparatus before agent execution."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from viper._parameter.validation import validate_parameters
from viper.params import ParameterModelRef, Train

PLAN_ROOT = Path(__file__).parents[1]


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, PLAN_ROOT / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


experiment = _module("experiment")
trial = _module("trial")


def test_prompts_are_complete_and_parsimonious() -> None:
    """Freeze only the task and the operation available to each arm."""
    assert experiment._prompts() == {
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


def test_trial_parameters_freeze_input_digests() -> None:
    """Reject a plan without exact identities for every delivered input."""
    payload = {
        "arm": "ordinary",
        "model": "gpt-5.4-mini",
        "timeout_seconds": 480,
        "fixture_sha256": "a" * 64,
        "graph_evidence_sha256": "b" * 64,
        "prompt_sha256": "c" * 64,
        "evaluator_sha256": "d" * 64,
    }
    value = trial.AgentTrialParameters.model_validate(payload)
    assert value.arm == "ordinary"
    with pytest.raises(ValueError):
        trial.AgentTrialParameters.model_validate(
            {**payload, "prompt_sha256": "not-a-digest"}
        )


def test_trial_parameters_reload_in_viper_worker() -> None:
    """Keep the project model valid under VIPER's isolated source loader."""
    path = PLAN_ROOT / "trial.py"
    raw = path.read_bytes()
    reference = ParameterModelRef(
        owner="project",
        path="trial.py",
        symbol="AgentTrialParameters",
        sha256=hashlib.sha256(raw).hexdigest(),
        bytes=len(raw),
    )
    value = trial.AgentTrialParameters(
        arm="ordinary",
        model="gpt-5.4-mini",
        timeout_seconds=480,
        fixture_sha256="a" * 64,
        graph_evidence_sha256="b" * 64,
        prompt_sha256="c" * 64,
        evaluator_sha256="d" * 64,
    )
    validated = validate_parameters(path, reference, value, Train)
    assert validated["arm"] == "ordinary"


def test_usage_counts_commands_searches_and_predicate_calls(tmp_path: Path) -> None:
    """Derive counters only from retained Codex JSONL events."""
    transcript = tmp_path / "transcript.jsonl"
    events = (
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "/bin/zsh -lc 'rg fetch src'",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "python .viper/unresolved.py",
            },
        },
        {"type": "item.completed", "item": {"type": "agent_message"}},
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 80,
                "output_tokens": 20,
                "reasoning_output_tokens": 7,
            },
        },
    )
    transcript.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    usage = trial._usage(transcript)
    assert usage == {
        "input_tokens": 100,
        "cached_input_tokens": 80,
        "output_tokens": 20,
        "reasoning_tokens": 7,
        "agent_messages": 1,
        "commands": 2,
        "repository_searches": 1,
        "predicate_calls": 1,
    }


def test_candidate_digest_covers_non_python_outputs(tmp_path: Path) -> None:
    """Bind evaluator custody to configuration and documentation too."""
    source = tmp_path / "src/example.py"
    config = tmp_path / "config/registry.json"
    source.parent.mkdir()
    config.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    config.write_text('{"value": 1}\n', encoding="utf-8")
    before = trial._candidate_digest(tmp_path)
    config.write_text('{"value": 2}\n', encoding="utf-8")
    assert trial._candidate_digest(tmp_path) != before


def test_trial_callable_is_a_viper_estimator_stage() -> None:
    """Keep agent execution inside VIPER's governed invocation boundary."""
    definition = trial.run_agent_trial.__viper_stage__
    assert definition.kind == "train"
    assert definition.parameter_model is trial.AgentTrialParameters
