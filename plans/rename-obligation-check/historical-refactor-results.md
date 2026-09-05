# Historical Refactor Check

## Case

- Dataset instance: `roboflow__supervision-1943`
- Repository: `roboflow/supervision`
- Base commit: `005cdbd37abec947301ed005d34d07a4c97f80bc`
- Candidate: dataset production patch plus `test_patch`
- Scope: the five Python files containing the renamed declarations or their
  baseline/candidate uses
- CodeQL: 2.26.4, Python `build-mode=none`, query pack 1.2.0

The complete repository could not be lowered because the existing graph schema
rejects repeated assignment targets in unrelated example and package files.
The focused scope preserves every Python occurrence of the three selected old
and replacement decorators.

## Closure result

| Rename | Baseline sites | Obligation groups | Gold patch |
|---|---:|---:|---|
| `ensure_cv2_image_for_annotation` to `ensure_cv2_image_for_class_method` | 26 | 26 | accepted |
| `ensure_cv2_image_for_processing` to `ensure_cv2_image_for_standalone_function` | 4 | 4 | accepted |
| `ensure_pil_image_for_annotation` to `ensure_pil_image_for_class_method` | 2 | 2 | accepted |

The first checker revision rejected all three gold transformations because it
required exact old/new count equality. The patch legitimately added new uses
of replacement decorators. Changing the rule to zero old uses and at least the
baseline replacement count accepted all 32 baseline sites.

The production patch alone left three old test references. Adding the
dataset's separate `test_patch` removed them. The checker rejected the
production-only state and accepted the complete gold state.

## Timing and parity

| Case | Overlay candidate | Full candidate | Full divided by overlay | Rename-reference parity |
|---|---:|---:|---:|---|
| Two-file toy | 15.69 s | 19.66 s | 1.25x | exact |
| Five-file historical scope, first candidate | 22.96 s | 24.82 s | 1.08x | exact |
| Five-file historical scope, complete gold candidate | 36.99 s | 26.76 s | 0.72x | exact |

These are single cold observations, not stable performance estimates. They
show correctness parity for the relation consumed by the rename checker. They
do not show a reliable end-to-end speedup: query compilation and evaluation
dominate small scopes, and one overlay run was slower.

The overlay did not reproduce the toy candidate's general `Dependencies.ql`
edges even though it reproduced `RenameTransitions.ql` exactly. Production
therefore confines overlays to rename checking; ordinary impact analysis keeps
full extraction.

A separate two-file live check used both `from sample import tools; tools.run()`
and `from sample.tools import run as execute; execute()`. The candidate overlay
emitted the expected `member_module_alias` row, compiled three obligations, and
accepted the complete rename. Baseline and candidate analysis each took about
11.5 seconds in that warm CodeQL process.
