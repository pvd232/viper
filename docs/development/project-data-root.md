# Project data root

VIPER uses one project root for source, authored inputs, frozen plans, run
records, working artifacts, and local immutable evidence. The user selects that
root when creating the project. Later commands rediscover the same root instead
of treating the current working directory as an unrelated default.

## 1. Status

**Contract status:** draft after change-impact review; owner review pending.

These requirements bind the contract to the master checklist:

| ID | Implementation obligation |
| --- | --- |
| PDR-01 <!-- contract-requirement: PDR-01 phase=0 test=tests/test_project_init.py --> | Make `viper init ROOT` create the complete protocol tree and one root marker at the selected location. |
| PDR-02 <!-- contract-requirement: PDR-02 phase=0 test=tests/test_storage.py --> | Resolve explicit and discovered roots through one function and bind local immutable publication to `ROOT/.viper/store`. |
| PDR-03 <!-- contract-requirement: PDR-03 phase=0 test=tests/test_validation_architecture.py --> | Require every logical project path and resolved filesystem path to remain beneath the selected root. |
| PDR-04 <!-- contract-requirement: PDR-04 phase=0 test=tests/test_documentation.py --> | Publish one root vocabulary across the protocol, Python API, typed operations, CLI, generated project, and documentation. |

## 2. Required claim

After the user runs:

```bash
viper init /Volumes/research/weekend-models --package weekend_models
```

VIPER treats `/Volumes/research/weekend-models` as the root of that project.
The project source and the reserved protocol tree live beneath that root:

```text
/Volumes/research/weekend-models/
├── viper.toml
├── pyproject.toml
├── src/
├── tests/
├── inputs/
├── benchmarks/
├── experiments/
└── .viper/
    ├── store/
    ├── workspaces/
    ├── journals/
    ├── catalog.sqlite3
    └── knowledge/
```

VIPER stores source-controlled experiment records and user-visible artifacts in
the protocol tree. VIPER stores immutable local copies beneath `.viper/store`.
The two sets of files share one root and retain separate paths.

## 3. Current gap

### Inspected path

`viper init` already accepts a target path. `InitProjectRequest.path` reaches
`initialize_project(path, package)`, which writes the starter project under that
path. Runtime functions separately receive `repository_root` or default a
public `root` argument to `Path.cwd()`.

```text
viper init TARGET
-> InitProjectRequest.path
-> initialize_project(path, package)
-> starter files beneath TARGET

later command
-> explicit repository_root or Path.cwd()
-> execution and storage paths beneath that independently selected value
```

Current initialization leaves root discovery undefined. A later command chooses
its root independently through `repository_root` or `Path.cwd()`. The starter
project also creates only portions of the reserved protocol tree. The current
code therefore uses one conceptual root through several selection rules.

### Missing connector

The initialized target path must become the root selected by every later local
operation:

```text
viper init ROOT
-> write ROOT/viper.toml
-> write the reserved protocol directories
-> later operation receives ROOT explicitly or discovers ROOT/viper.toml
-> all RepoRelPath values resolve beneath ROOT
-> LocalArtifactStore publishes beneath ROOT/.viper/store
```

## 4. Contract models

### Root marker

`viper.toml` marks the root. It contains portable project settings and omits the
machine-specific absolute root path. The marker's parent directory is the root.

```toml
[project]
schema_version = 1
```

The `[project]` table uses this complete model:

```python
class ProjectSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1


class ViperConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project: ProjectSettings
    storage: StorageSettings = Field(default_factory=StorageSettings)
```

`StorageSettings` retains the exact model owned by
[`remote-storage.md`](remote-storage.md). The local configuration file owns one
`ViperConfig` outside the serialized protocol and run identity. Its filesystem
location binds the project to one machine-local absolute root.

### Initialization request and result

The public operation keeps its current serialized fields. `path` is the root
selected by the caller.

```python
class InitProjectRequest(APIModel):
    path: Path
    package: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class InitProjectSuccess(SuccessModel):
    operation: Literal["init_project"] = "init_project"
    project_root: Path
    files: tuple[Path, ...]
```

The CLI calls the same operation:

```text
viper init ROOT --package PACKAGE
```

`ROOT` maps to `InitProjectRequest.path`.
`InitProjectSuccess.project_root` returns the resolved absolute root.

### Runtime root resolution

The root resolver returns one runtime path. Protocol serializers receive
relative paths only.

```python
def find_project_root(start: Path | None = None) -> Path:
    """Return the nearest parent containing viper.toml."""


def resolve_project_root(
    root: Path | None = None,
    *,
    start: Path | None = None,
) -> Path:
    """Validate an explicit root or discover one from start."""
```

`resolve_project_root()` applies this order:

1. An explicit `root` wins.
2. Otherwise, `find_project_root(start)` uses `Path.cwd()` when `start` is
   absent, then walks from the resolved starting path through its parents.
3. The selected directory must contain a valid `viper.toml`.
4. The selected directory must be a Git work tree before freezing, source
   verification, or execution begins.
5. Failure raises `ProjectRootError` before reading or writing experiment data.

### Local immutable store

The existing storage-reference fields remain unchanged:

```python
class LocalFileRef(ProtocolModel):
    kind: Literal["local"] = "local"
    store: RepoRelPath = ".viper/store"
    commit: SHA256
    path: RepoRelPath


class LocalStageResultSnapshotRef(ProtocolModel):
    kind: Literal["local"] = "local"
    store: RepoRelPath = ".viper/store"
    commit: SHA256
```

`LocalArtifactStore(project_root, store=".viper/store")` resolves the immutable
store beneath the selected root. The visible artifact and immutable publication
retain distinct files.

## 5. Execution

### Initialization

`initialize_project()` receives the selected root and performs one staged
write:

```python
def initialize_project(path: Path, package: str) -> tuple[Path, ...]: ...
```

The target operation is:

```text
validate package name
-> require ROOT to be absent or empty
-> write the complete scaffold to a sibling temporary directory
-> include viper.toml and the reserved protocol directories
-> atomically replace ROOT with the staged project
-> return every created file
```

The visible protocol directories contain a tracked `README.md` or `.gitkeep`
until the user creates their first record. Initialization creates the reserved
`.viper/` directories and keeps them ignored. State files such as
`.viper/catalog.sqlite3` appear when the owning operation first writes them.

### Later operations

Every local public entry point follows one root path:

```text
explicit root or current directory
-> resolve_project_root()
-> validated absolute project root
-> authoring, freezing, execution, verification, catalog, knowledge, or restore
```

Internal functions receive the resolved root explicitly. Only the public
operation boundary searches parent directories.

### File custody

A training stage that declares this working artifact:

```text
experiments/tiny/runs/baseline/<run-id>/artifacts/models/model/params.pt
```

produces two paths:

```text
ROOT/experiments/.../params.pt
-> user-visible working artifact

ROOT/.viper/store/<snapshot-sha256>/experiments/.../params.pt
-> immutable local publication
```

Editing the working artifact makes the working tree differ from the published
snapshot. Verification and restore use the immutable snapshot reference.
Editing `.viper/store` damages immutable evidence and causes retrieval or digest
verification to fail.

## 6. Persisted evidence

The selected absolute root is machine-local configuration. VIPER excludes it
from frozen run identity and scientific experiment identity.

Persisted protocol records retain `RepoRelPath` values. A local storage
reference records:

```text
store + commit + path
```

The runtime joins that reference with the selected root:

```text
ROOT
+ LocalFileRef.store
+ LocalFileRef.commit
+ LocalFileRef.path
-> local immutable file
```

Moving an unchanged project tree to another absolute root leaves its protocol
records and experiment identity unchanged.

## 7. Verification

The implementation adds these checks:

| Rule | Executable requirement |
| --- | --- |
| `project.root.marker` | The selected root contains one valid `viper.toml`. |
| `project.root.git` | Freeze, source verification, and execution use a root that belongs to one Git work tree. |
| `project.path.logical_boundary` | Every `RepoRelPath` rejects absolute paths and `..` traversal. |
| `project.path.resolved_boundary` | Every resolved path stays beneath `ROOT` after symlink resolution. |
| `project.store.boundary` | `LocalArtifactStore.store_root` stays beneath `ROOT`. |
| `project.root.stability` | One operation resolves the root once and passes that value to every internal consumer. |

The verifier reconstructs local paths from the explicit root supplied for
verification and the persisted relative reference. The verifier compares file
digests and byte counts through the existing storage rules.

## 8. Propagation

| Surface | Required statement |
| --- | --- |
| `src/viper/project_init.py` | Add `viper.toml`, complete the reserved protocol tree, and preserve staged atomic initialization. |
| `src/viper/project.py` | Add `ProjectSettings`, `ProjectRootError`, `find_project_root()`, and `resolve_project_root()`. |
| `src/viper/api.py` | Keep `InitProjectRequest.path` and `InitProjectSuccess.project_root`; route optional public roots through the shared resolver. |
| `src/viper/_api/handlers.py` | Resolve one root at each operation boundary and pass it to internal functions. |
| `src/viper/cli.py` | Document the `init` positional argument as `ROOT`; use `--root` on commands that need an explicit override. |
| `src/viper/storage.py` | Construct `LocalArtifactStore` from the resolved project root and preserve `.viper/store` as a separate subtree. |
| `src/viper/_verification/storage.py` | Replace `Path.cwd()` reconstruction with the explicit verified root. |
| `src/viper/authoring.py` | Resolve default roots through `resolve_project_root()` before freezing. |
| `src/viper/execution/_attempt.py` | Pass one resolved root through attempt execution and every stage boundary. |
| `src/viper/execution/_run.py` | Resolve the public run and restore root once before attempt execution. |
| `src/viper/execution/_metric.py` | Use the attempt's resolved root for metric inputs and implementations. |
| `src/viper/inspection.py` | Resolve catalog, lineage, comparison, and plan-diff paths from the selected root. |
| `tests/test_project_init.py` | Cover explicit-root initialization, root marker discovery, complete tree creation, and occupied-target rollback. |
| `tests/test_storage.py` | Publish and retrieve beneath a non-current project root; reject an escaping store. |
| `tests/test_validation_architecture.py` | Require public operation boundaries to use the shared root resolver and internal functions to receive resolved roots. |
| `tests/test_documentation.py` | Compare the protocol tree, CLI vocabulary, contract requirements, and checklist coverage. |
| Public documentation | Explain that `ROOT` contains both the visible protocol tree and the separate `.viper/store` subtree. |

### Legacy cleanup

| Current occurrence | Disposition |
| --- | --- |
| Public `Path.cwd()` defaults that bypass root discovery | Replace with `root: Path | None = None` and `resolve_project_root()`. |
| CLI `--repository-root` spelling | Replace with `--root`; delete the old spelling during this alpha migration. |
| `_verification/storage.py` use of `Path.cwd()` | Delete and require the verifier's resolved root. |
| Internal `repository_root` parameters | Retain where the name distinguishes the resolved Git/project root from another runtime path. |
| `LocalFileRef.store=".viper/store"` | Retain; the configured root supplies its absolute parent. |
| `.viper/` in generated `.gitignore` | Retain; immutable local evidence and attempt state remain local by default. |

## 9. Acceptance case

### Success

1. Initialize `/tmp/weekend-models` while the shell is elsewhere.
2. Require `viper.toml`, `inputs/`, `benchmarks/`, `experiments/`, `src/`, and
   `tests/` beneath that root.
3. Run a command from `/tmp/weekend-models/src/weekend_models` and let root
   discovery select the project.
4. Require root discovery to return `/tmp/weekend-models`.
5. Publish one working artifact and require its immutable copy beneath
   `/tmp/weekend-models/.viper/store`.
6. Change the working artifact and require retrieval of the original published
   bytes through its `LocalFileRef`.

### Rejection

Create `ROOT/inputs/link` as a symbolic link to a file outside `ROOT`. A plan
selects `inputs/link`. `project.path.resolved_boundary` rejects the source
before capture or publication.

## 10. Implementation order

1. Add the root marker, `ProjectSettings`, and root resolver with unit tests.
2. Complete the generated protocol tree and acceptance test.
3. Route initialization, authoring, execution, verification, inspection, and
   storage through one resolved root.
4. Replace public `--repository-root` spelling with `--root`.
5. Add boundary and relocation tests.
6. Update the protocol tree and public documentation.
7. Run the Phase 0 gate from the master execution checklist.

**Commit boundary:** `Bind every local operation to one project root`
