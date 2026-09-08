"""Classify every test module by validation cost and owned domain."""

from pathlib import Path

import pytest

TIER_BY_MODULE = {
    "test_api": "contract",
    "test_api_json": "unit",
    "test_artifact_validation": "contract",
    "test_authoring": "contract",
    "test_benchmark_execution": "contract",
    "test_cli": "integration",
    "test_cloud_execution": "contract",
    "test_code_style": "unit",
    "test_config_contract": "contract",
    "test_documentation": "contract",
    "test_distribution_contents": "release",
    "test_execution_acceptance": "integration",
    "test_generated_project_acceptance": "release",
    "test_http_retrieval": "contract",
    "test_inspection": "contract",
    "test_live_process_startup": "integration",
    "test_storage": "unit",
    "test_metric_interface": "contract",
    "test_metric_provenance": "integration",
    "test_output_contract": "contract",
    "test_output_paths": "contract",
    "test_diagnostic_stage": "contract",
    "test_workspace_vocabulary": "contract",
    "test_dispatch_migration": "contract",
    "test_runtime_boundary": "contract",
    "test_public_inventory": "contract",
    "test_config_validation": "contract",
    "test_plan_execution": "contract",
    "test_prior_run_inputs": "contract",
    "test_preflight": "contract",
    "test_process_startup": "unit",
    "test_project_init": "contract",
    "test_protocol": "contract",
    "test_public_api": "contract",
    "test_public_authoring_test_plan": "contract",
    "test_readme_workflow": "integration",
    "test_release_tools": "unit",
    "test_resume": "integration",
    "test_run_execution": "integration",
    "test_execution_signals": "integration",
    "test_stage_invocation": "contract",
    "test_validation_architecture": "contract",
    "test_verification": "contract",
    "test_verification_acceptance": "integration",
    "test_worker": "integration",
    "test_workflow_documentation": "contract",
}

DOMAIN_BY_MODULE = {
    "test_api": "domain_application",
    "test_api_json": "domain_application",
    "test_artifact_validation": "domain_artifacts",
    "test_authoring": "domain_authoring",
    "test_benchmark_execution": "domain_execution",
    "test_cli": "domain_application",
    "test_cloud_execution": "domain_execution",
    "test_code_style": "domain_protocol",
    "test_config_contract": "domain_protocol",
    "test_documentation": "domain_protocol",
    "test_distribution_contents": "domain_release",
    "test_execution_acceptance": "domain_execution",
    "test_generated_project_acceptance": "domain_release",
    "test_http_retrieval": "domain_http",
    "test_inspection": "domain_verification",
    "test_live_process_startup": "domain_execution",
    "test_storage": "domain_storage",
    "test_metric_interface": "domain_metrics",
    "test_metric_provenance": "domain_metrics",
    "test_output_contract": "domain_authoring",
    "test_output_paths": "domain_storage",
    "test_diagnostic_stage": "domain_authoring",
    "test_workspace_vocabulary": "domain_application",
    "test_dispatch_migration": "domain_protocol",
    "test_runtime_boundary": "domain_execution",
    "test_public_inventory": "domain_release",
    "test_config_validation": "domain_parameters",
    "test_plan_execution": "domain_execution",
    "test_prior_run_inputs": "domain_authoring",
    "test_preflight": "domain_verification",
    "test_process_startup": "domain_execution",
    "test_project_init": "domain_application",
    "test_protocol": "domain_protocol",
    "test_public_api": "domain_application",
    "test_public_authoring_test_plan": "domain_protocol",
    "test_readme_workflow": "domain_application",
    "test_release_tools": "domain_release",
    "test_resume": "domain_execution",
    "test_run_execution": "domain_execution",
    "test_execution_signals": "domain_execution",
    "test_stage_invocation": "domain_execution",
    "test_validation_architecture": "domain_protocol",
    "test_verification": "domain_verification",
    "test_verification_acceptance": "domain_verification",
    "test_worker": "domain_execution",
    "test_workflow_documentation": "domain_release",
}

if TIER_BY_MODULE.keys() != DOMAIN_BY_MODULE.keys():
    raise RuntimeError("test tier and domain manifests must contain the same modules")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Attach one declared cost tier and one owned domain to every test."""
    for item in items:
        module = Path(str(item.path)).stem
        if not module.startswith("test_"):
            continue

        try:
            tier = TIER_BY_MODULE[module]
            domain = DOMAIN_BY_MODULE[module]
        except KeyError as error:
            raise pytest.UsageError(
                f"{module}.py needs one tier and one domain in tests/conftest.py"
            ) from error

        item.add_marker(getattr(pytest.mark, tier))
        item.add_marker(getattr(pytest.mark, domain))
