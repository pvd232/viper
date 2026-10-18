# Local store identity removal — 2026-10-18

The local address is now `workspace / store / commit / path`. The package removes
random store identity creation and checks. This removes 72 net production lines
across seven files.

## Inventory and preservation

Inspected 9,004 local and 4,649 VM metadata files, plus five large JSON files
checked separately. Historical local references occurred in 1,543 local records
or catalog columns and 112 VM records. The VM publication worker had completed
with exit status 0; its requests and journals are retained historical records.

Rechecked SHA-256 for 1,490 local and 136 VM original metadata files, including
108 model/benchmark files: none changed. Original GCS/Hugging Face publications,
model pointers, frozen experiments, and old store revisions remain unchanged.
Historical records retain their original schema and need their original reader.

## Migrated active records

Converted the five roots indexed by the RICO and MANTRA catalogs. The one-off
conversion reused graph promotion, wrote new metadata revisions, and hard-linked
unchanged payloads. MANTRA also required moving captured-input members to the
current canonical paths inside the new revisions; their bytes were unchanged.
Conversion reused the saved training, prediction, and metric artifacts.

The strict current reader verified all five complete run graphs, including
artifact loaders and reuse relationships, before building converted catalogs.
Catalog refresh accepted all four RICO runs and the one MANTRA run.
Both workspaces now install the reader built from commit
`4682e98cc1cf8bd5e0f7988b733e19f3813edec0` in their own virtual environments.
Each installed reader verified its converted graphs before atomic catalog
activation. Active graphs and catalog records omit the retired identity fields.
Original catalog backups remain available.

| Workspace | Run | New terminal revision |
| --- | --- | --- |
| rico-rebuild | `01M4J3YTTRYYH6XTYHCVJNPE8Q` | `30af3f300f199aae3bdf74e5e16a3267e7b16b12663b654fd59c1f41bee54caf` |
| rico-rebuild | `01M4J3Z5BDCGD7NMJEX4Y5AFQG` | `47de4820c33b92316169adbc957e82a1fe38b73639493e4fedaab645d2bd8aba` |
| rico-rebuild | `01M4J3ZB22KB5BEG4GWTTE4BY4` | `3ea782e7a25e68609551bed3f94fa6fdbe9d8541aabe517e2bb61a6db40ce95a` |
| rico-rebuild | `01M4J3ZGYM3606JPA10K8XK1VP` | `fcd544bac8f0b8df42f7c179e5dc683a9806731625ab70d045d43caf55f07b6a` |
| mantra-rebuild | `01M2Z3EZ6VBVTS9K05AFGSQPTK` | `1097f2cd5c28dba557e7e15bd949eda1b512ddbe2b24a89920899b81da0a1f7a` |

Full inventories, old-to-new file/revision maps, preservation checks, and the
one-off conversion scripts are retained locally with the catalog backups:

```text
.viper/migrations/store-id-removal-20261018/
```

The conversion-only reader stays outside the package. VIPER ships the strict
current reader and uses its existing content revision checks.

## Validation

- Pyrefly: 0 errors.
- `python -m pytest tests -q -m "unit or contract"`: 617 passed, 237 deselected,
  11 subtests passed (52.19 seconds).
- Documentation checks after adding this record: 39 passed.
- Final Ruff format/check and `git diff --check`: passed.
- Integration tests were excluded from local validation.
- Regression coverage checks identical-store reconstruction, missing revisions,
  workspace/path confinement, and rejection of corrupted bytes.

## Reader activation

Both environments installed the same wheel, SHA-256
`dd155dabff44e830769e7049a772c659f765a0458344337afd1a051072fe7660`.
Every installed Python module matched that wheel. Other installed packages kept
their existing versions; required missing dependencies and MANTRA's Pyrefly were added.
Reader changes are in [RICO #29](https://github.com/pvd232/rico-rebuild/pull/29)
and [MANTRA #28](https://github.com/pvd232/rico-rebuild/pull/28).

| Workspace | Verified runs | Indexed artifacts | Measurements | Reuse candidates |
| --- | ---: | ---: | ---: | ---: |
| RICO | 4 | 4 | 0 | 4 |
| MANTRA | 1 | 15 | 11 | 6 |

The installed readers queried these records after activation. SHA-256 checks
confirmed that 455 RICO and 634 MANTRA original metadata files were unchanged.
Cloud publications and model pointers were preserved. Integration was excluded.

RICO passed Pyrefly across active files, 45 affected tests, and active Ruff checks.
MANTRA passed Pyrefly on changed consumers, 103 affected tests, and changed-file
Ruff checks. Three MANTRA callers now use `RunFetcher.read()` for verified reads.

Broader scans retain failures outside the changed consumers: MANTRA has four
existing source/test type errors and 1,705 diagnostics from prose saved as
`docs/run.py`, plus 28 archived type errors. RICO's archived scan has 530 type
errors: 528 pre-existing findings and two retired-API errors in a preserved
publication script. Archived Ruff scans also fail: RICO has 37 format failures
and 629 lint findings; MANTRA has 14 format failures and 10 lint findings.
MANTRA's broader active Ruff scan finds the unchanged prose file and one
unformatted source file. Full reports, file lists, package inventories, and
activation receipts are retained alongside the catalog backups.
