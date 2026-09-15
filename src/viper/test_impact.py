"""Select tests from declaration relationships without repository conventions ."""

from __future__ import annotations

from collections import deque
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import NewType

DeclarationId = NewType("DeclarationId", str)
TestRef = NewType("TestRef", str)


@dataclass(frozen=True, slots=True)
class TestSelection:
    """Represent selected tests and declarations whose coverage remains unknown ."""

    tests: tuple[TestRef, ...]
    unresolved: tuple[DeclarationId, ...]


def select_tests(
    declarations: Iterable[DeclarationId],
    *,
    dependents: Mapping[DeclarationId, Collection[DeclarationId]],
    observers: Mapping[DeclarationId, Collection[TestRef]],
    test_refs_by_declaration: Mapping[DeclarationId, TestRef],
) -> TestSelection:
    """Select every known test that observers the supplied declarations.

    ``dependents`` maps each declaration to declarations that use it.
    ``observers`` records relationships that source analysis cannot prove.
    ``test_refs_by_declaration`` maps known test declarations to repo-specific refs.
    """
    selected: set[TestRef] = set()
    unresolved: list[DeclarationId] = []

    for declaration in sorted(set(declarations)):
        declared_tests = set(observers.get(declaration, ()))
        direct_test = test_refs_by_declaration.get(declaration)

        if direct_test is not None:
            declared_tests.add(direct_test)
        else:
            declared_tests.update(
                _reachable_tests(
                    declaration,
                    dependents=dependents,
                    test_refs_by_declaration=test_refs_by_declaration,
                )
            )

        if declared_tests:
            selected.update(declared_tests)
        else:
            unresolved.append(declaration)

    return TestSelection(tests=tuple(sorted(selected)), unresolved=tuple(unresolved))


def _reachable_tests(
    start: DeclarationId,
    *,
    dependents: Mapping[DeclarationId, Collection[DeclarationId]],
    test_refs_by_declaration: Mapping[DeclarationId, TestRef],
) -> set[TestRef]:
    """Find every test reachable through declarations that depend on `start` ."""
    pending = deque((start,))
    visited = {start}
    tests: set[TestRef] = set()

    while pending:
        declaration = pending.popleft()
        for dependent in dependents.get(declaration, ()):
            if dependent in visited:
                continue
            visited.add(dependent)

            test = test_refs_by_declaration.get(dependent)
            if test is None:
                pending.append(dependent)
            else:
                tests.add(test)

    return tests
