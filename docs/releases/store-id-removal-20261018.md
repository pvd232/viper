# Local store identity removal — 2026-10-18

The local address is now `workspace / store / commit / path`. The package no
longer creates or checks a random store identity. This removes 72 net production
lines across seven files; it adds no replacement storage abstraction.

## Inventory and preservation

Inspected 9,004 local and 4,649 VM metadata files, plus five large JSON files
checked separately. Historical local references occurred in 1,543 local records
or catalog columns and 112 VM records. The VM publication worker had completed
with exit status 0; its requests and journals are retained historical records.

Rechecked SHA-256 for 1,490 local and 136 VM original metadata files, including
108 model/benchmark files: none changed. Original GCS/Hugging Face publications,
model pointers, frozen experiments, and old store revisions were not rewritten.
Historical records retain their original schema and need their original reader.

## Migrated active records

Converted the five roots indexed by the RICO and MANTRA catalogs. The one-off
conversion reused graph promotion, wrote new metadata revisions, and hard-linked
unchanged payloads. MANTRA also required moving captured-input members to the
current canonical paths inside the new revisions; their bytes were unchanged.
No training, prediction, or metric recomputation ran.

The strict current reader verified all five complete run graphs, including
artifact loaders and reuse relationships, before building converted catalogs. Catalog refresh accepted four RICO runs and
one MANTRA run with no rejections. Converted graphs and catalog records contain
no retired identity fields. The installed RICO reader is pinned to
`a6bc9452a04796fa17397896903bdc13e8afd8bb`; MANTRA uses the older main checkout.
Both still require the retired field. Their original active catalogs therefore
remain installed; `catalog.converted.sqlite3` is ready to replace each catalog
when that workspace upgrades to this reader.

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

The conversion-only reader is outside the package. No compatibility field,
legacy parser, identity-file reader, or migration command was added to VIPER.

## Validation

- Pyrefly: 0 errors.
- `python -m pytest tests -q -m "unit or contract"`: 617 passed, 237 deselected,
  11 subtests passed (52.19 seconds).
- Documentation checks after adding this record: 39 passed.
- Final Ruff format/check and `git diff --check`: passed.
- Integration tests were excluded from local validation.
- Regression coverage checks identical-store reconstruction, missing revisions,
  workspace/path confinement, and rejection of corrupted bytes.
