"""Preserve the existing import boundary for portable test selection."""

from source_impact.selection import DeclarationId, TestRef, TestSelection, select_tests

__all__ = ["DeclarationId", "TestRef", "TestSelection", "select_tests"]
