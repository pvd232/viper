"""Verify every VIPER arm and print the source-bound comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from viper.api import VerifyRunRequest, verify_run

SOURCE_REPOSITORY = "https://example.invalid/viper-agent-graph-memory"
ARMS = ("ordinary", "static_graph", "graph_predicate")


def compare(project: Path) -> dict[str, object]:
    """Reject unverified arms and compare accepted trials."""
    summary_path = project / "results/summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    arms = summary.get("arms")
    if not isinstance(arms, dict) or set(arms) != set(ARMS):
        raise ValueError("summary does not contain exactly the required arms")
    rows = []
    for arm in ARMS:
        record = arms[arm]
        verification_path = project / record["verification"]
        verification_sha256 = hashlib.sha256(verification_path.read_bytes()).hexdigest()
        if verification_sha256 != record["verification_sha256"]:
            raise ValueError(f"{arm} verification record digest differs")
        resolved = project / record["resolved_run"]
        verified = verify_run(
            VerifyRunRequest(
                path=resolved,
                root=project,
                trusted_source_repositories=frozenset({SOURCE_REPOSITORY}),
            )
        )
        if verified.run_status != "succeeded":
            raise ValueError(f"{arm} run is not successful")
        verdict = record["verdict"]
        usage = record["usage"]
        rows.append(
            {
                "arm": arm,
                "accepted": verdict["accepted"],
                "duration_seconds": verdict["duration_seconds"],
                "timed_out": verdict["timed_out"],
                "commands": usage["commands"],
                "repository_searches": usage["repository_searches"],
                "predicate_calls": usage["predicate_calls"],
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "reasoning_tokens": usage["reasoning_tokens"],
            }
        )
    successful = [row for row in rows if row["accepted"]]
    return {
        "schema_version": 1,
        "correct_arms": len(successful),
        "total_arms": len(rows),
        "arms": rows,
        "efficiency_comparison_arms": [row["arm"] for row in successful],
    }


def main() -> int:
    """Verify the selected experiment project and print compact JSON."""
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    arguments = parser.parse_args()
    result = compare(arguments.project.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
