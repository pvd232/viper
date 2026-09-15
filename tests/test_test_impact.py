"""Verify test selection from declaration relationships."""

from viper.test_impact import DeclarationId, TestRef, select_tests


def test_selects_explicit_direct_and_reachable_tests() -> None:
    """Combine explicit, direct, and dependency-reachable test references."""
    target = DeclarationId("src/package.py:target")
    dependent = DeclarationId("src/service.py:use_target")
    reachable_test = DeclarationId("tests/test_service.py:test_use_target")
    direct_test = DeclarationId("tests/test_direct.py:test_changed")

    selection = select_tests(
        (target, direct_test),
        dependents={
            target: (dependent,),
            dependent: (reachable_test,),
        },
        observers={
            target: (TestRef("tests/test_dynamic.py::test_target"),),
        },
        test_refs_by_declaration={
            reachable_test: TestRef("tests/test_service.py::test_use_target"),
            direct_test: TestRef("tests/test_direct.py::test_changed"),
        },
    )

    assert selection.tests == (
        TestRef("tests/test_direct.py::test_changed"),
        TestRef("tests/test_dynamic.py::test_target"),
        TestRef("tests/test_service.py::test_use_target"),
    )
    assert selection.unresolved == ()


def test_reports_unobserved_cycle_for_fallback() -> None:
    """Terminate a dependency cycle and report the unresolved declaration."""
    first = DeclarationId("src/first.py:first")
    second = DeclarationId("src/second.py:second")

    selection = select_tests(
        (first,),
        dependents={
            first: (second,),
            second: (first,),
        },
        observers={},
        test_refs_by_declaration={},
    )

    assert selection.tests == ()
    assert selection.unresolved == (first,)
