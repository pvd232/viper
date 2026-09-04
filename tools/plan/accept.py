"""Bind a passing plan check to its implementation commit."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from viper.system_impact.check import accept
from viper.system_impact.models import PlanCheck

ROOT = Path(__file__).parents[2]


def main(argv: Sequence[str] | None = None) -> int:
    """Accept a commit whose source and PairBlocks match a saved plan check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    result_path = args.result.resolve()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    check = PlanCheck.model_validate(result["check"])

    accepted = accept(
        root=args.root.resolve(),
        check=check,
        revision=args.revision,
    )

    output = (
        args.output.resolve()
        if args.output is not None
        else result_path.with_name("acceptance.json")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(accepted.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"accepted {accepted.revision}; saved {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
