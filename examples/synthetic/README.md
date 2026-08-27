# VIPER synthetic project

This project shows how user code connects to VIPER. Each stage is an ordinary
decorated Python function under `src/sample_project/stages/`. The parameter
classes in `src/sample_project/parameters.py` validate the values delivered to
those functions.

Run the stage-definition test from this directory:

```bash
python -m pip install -e ".[test]"
python -m pytest -q
```

The complete release test copies this project into a temporary Git repository,
freezes its acquisition and candidate plans, executes all five stage kinds,
executes the benchmark confirmation, and verifies the terminal files:

```bash
python -m pytest tests/test_generated_project_acceptance.py -q -m release
```

The authored download specification at
`experiments/example/stages/download/spec.yaml` illustrates the frozen link
from one stage to its implementation, parameter class, HTTP request, and output
artifact.
