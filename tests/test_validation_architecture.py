"""Tests for the repository's validation-tier manifest."""

from pathlib import Path

from tests.conftest import DOMAIN_BY_MODULE, TIER_BY_MODULE


def test_every_test_module_has_one_tier_and_domain() -> None:
    """Require every collected test module to declare both classifications."""
    tests_root = Path(__file__).parent
    modules = {path.stem for path in tests_root.glob("test_*.py")}

    assert TIER_BY_MODULE.keys() == DOMAIN_BY_MODULE.keys()
    assert set(TIER_BY_MODULE) == modules
    assert set(TIER_BY_MODULE.values()) <= {
        "unit",
        "contract",
        "integration",
        "release",
    }
