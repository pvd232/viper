# Select tests from declaration relationships

`viper.test_impact.select_tests()` accepts relationships supplied by a source
analyzer or by the application. It selects observing tests and reports changed
declarations whose observers remain unknown. It does not run those tests or
establish that the supplied graph covers every dependency.

This complete Python example shows a changed training function, a caller, and
the test that observes that caller:

```python
from viper.test_impact import DeclarationId, TestRef, select_tests

fit = DeclarationId("package/training.py:fit")
pipeline = DeclarationId("package/pipeline.py:run")
test_pipeline = DeclarationId("tests/test_pipeline.py:test_saved_model")
selection = select_tests(
    (fit,),
    dependents={fit: (pipeline,), pipeline: (test_pipeline,)},
    observers={},
    test_refs_by_declaration={
        test_pipeline: TestRef("tests/test_pipeline.py::test_saved_model"),
    },
)
assert selection.tests == ("tests/test_pipeline.py::test_saved_model",)
assert selection.unresolved == ()
print(selection.tests)

unknown = select_tests(
    (DeclarationId("package/native.py:unmapped"),),
    dependents={},
    observers={},
    test_refs_by_declaration={},
)
assert unknown.unresolved == ("package/native.py:unmapped",)
print("Run the owning suite when observers remain unresolved.")
```

These are declared graph relationships, not evidence extracted from your
repository. To analyze real Python source, the checkout's
[graph builder](../../tools/build_test_impact_graph.py) invokes CodeQL and binds
the result to the analyzed bytes. The
[pytest adapter](../../tools/select_impacted_tests.py) and
[unittest adapter](../../tools/select_unittest_tests.py) validate that identity,
translate test names, and return a declared fallback when selection is unresolved.
These tools require the VIPER checkout and CodeQL; they are not installed CLI
commands in the wheel. Inspect their `--help` for required analyzed roots and
fallbacks. The [testing guide](../development/testing.md) owns contributor gates.
