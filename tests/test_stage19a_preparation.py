from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PRODUCTION_ROOT = ROOT / "infra" / "environments" / "production"
BOOTSTRAP_ROOT = ROOT / "infra" / "bootstrap"


def test_github_actions_are_pinned_to_immutable_shas() -> None:
    workflow_text = "\n".join(path.read_text(encoding="utf-8") for path in WORKFLOWS.glob("*.yml"))

    mutable_uses = [
        line.strip()
        for line in workflow_text.splitlines()
        if "uses:" in line and not re.search(r"@[0-9a-f]{40}\b", line)
    ]

    assert mutable_uses == []
    assert "@main" not in workflow_text


def test_production_plan_workflow_is_plan_only() -> None:
    workflow = (WORKFLOWS / "production-plan.yml").read_text(encoding="utf-8")

    assert "tofu apply" not in workflow
    assert "workflow_dispatch" in workflow
    assert "id-token: write" in workflow
    assert "google-github-actions/auth@" in workflow
    assert "service_account_key" not in workflow
    assert "credentials_json" not in workflow


def test_normal_ci_is_cloud_independent() -> None:
    workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    assert "id-token: write" not in workflow
    assert "google-github-actions/auth" not in workflow
    assert "GEMINI_API_KEY" not in workflow
    assert "SUPPLYCHAIN_AGENT_POSTGRES_DSN" not in workflow
    assert "uv run python -m supplychain.agent.evaluation" in workflow


def test_bootstrap_deployer_account_id_uses_valid_safe_default() -> None:
    variables = (BOOTSTRAP_ROOT / "variables.tf").read_text(encoding="utf-8")
    match = re.search(
        r'variable\s+"deployer_service_account_id"\s+\{[\s\S]*?default\s+=\s+"([^"]+)"',
        variables,
    )
    assert match is not None

    account_id = match.group(1)
    assert account_id == "supplychain-prod-deployer"
    assert account_id[0].isalpha()
    assert account_id == account_id.lower()
    assert re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", account_id)
    assert 6 <= len(account_id) <= 30


def test_bootstrap_deployer_roles_match_initial_dashboard_first_scope() -> None:
    main = (BOOTSTRAP_ROOT / "main.tf").read_text(encoding="utf-8")
    roles = set(_resource_role_list(main, "google_project_iam_member", "deployer_roles"))

    assert roles == {
        "roles/artifactregistry.admin",
        "roles/iam.serviceAccountAdmin",
        "roles/iam.serviceAccountUser",
        "roles/pubsub.admin",
        "roles/run.admin",
        "roles/secretmanager.admin",
        "roles/serviceusage.serviceUsageAdmin",
    }
    assert "roles/cloudsql.admin" not in roles
    assert "roles/bigquery.jobUser" not in roles
    assert "roles/owner" not in roles
    assert "roles/editor" not in roles


def test_public_cloud_run_access_is_disabled_by_default() -> None:
    variables = (PRODUCTION_ROOT / "variables.tf").read_text(encoding="utf-8")
    main = (PRODUCTION_ROOT / "main.tf").read_text(encoding="utf-8")

    assert re.search(
        r'variable\s+"allow_unauthenticated"\s+\{[\s\S]*?default\s+=\s+false',
        variables,
    )
    assert "var.enable_cloud_run_service && var.allow_unauthenticated ? 1 : 0" in main


def test_cloud_run_deployment_and_min_instances_are_safe_by_default() -> None:
    variables = (PRODUCTION_ROOT / "variables.tf").read_text(encoding="utf-8")

    assert re.search(
        r'variable\s+"enable_cloud_run_service"\s+\{[\s\S]*?default\s+=\s+false',
        variables,
    )
    assert re.search(
        r'variable\s+"cloud_run_min_instances"\s+\{[\s\S]*?default\s+=\s+0',
        variables,
    )


def test_cloud_sql_admin_api_is_gated_by_managed_postgres_flag() -> None:
    main = (PRODUCTION_ROOT / "main.tf").read_text(encoding="utf-8")
    base_services = _local_list(main, "base_production_services")
    managed_postgres_services = _local_list(main, "managed_postgres_services")

    assert "sqladmin.googleapis.com" not in base_services
    assert managed_postgres_services == ["sqladmin.googleapis.com"]
    assert "var.enable_managed_postgres ? [" in main
    assert "local.managed_postgres_services" in main


def test_cloud_sql_resources_remain_gated_by_managed_postgres_flag() -> None:
    main = (PRODUCTION_ROOT / "main.tf").read_text(encoding="utf-8")

    assert 'resource "google_sql_database_instance" "agent"' in main
    assert "count = var.enable_managed_postgres ? 1 : 0" in main
    assert "cloud_sql_instances = var.enable_managed_postgres ?" in main
    assert 'resource "google_project_iam_member" "runtime_cloudsql_client"' in main


def test_runtime_bigquery_iam_excludes_raw_dataset() -> None:
    production_text = "\n".join(
        path.read_text(encoding="utf-8") for path in PRODUCTION_ROOT.glob("*.tf")
    )

    assert "supplychain_raw" not in production_text
    assert "bigquery_core_dataset_id" in production_text
    assert "bigquery_mart_dataset_id" in production_text
    assert "runtime_core_viewer" in production_text
    assert "runtime_mart_viewer" in production_text


def test_tracked_production_tfvars_contain_placeholders_not_secret_values() -> None:
    tfvars_text = "\n".join(
        path.read_text(encoding="utf-8") for path in ROOT.glob("infra/**/terraform.tfvars.example")
    )

    forbidden = (
        "BEGIN PRIVATE KEY",
        "GEMINI_API_KEY=",
        "postgresql://",
        "service_account_key",
        "credentials_json",
    )
    for token in forbidden:
        assert token not in tfvars_text
    assert "REPLACE_" in tfvars_text


def test_dockerignore_excludes_credentials_state_and_non_runtime_content() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    required_patterns = (
        ".git/",
        ".env",
        "**/.terraform/",
        "*.tfstate",
        "terraform.tfvars",
        "*service-account*.json",
        "tests/",
        "docs/",
        "infra/",
    )
    for pattern in required_patterns:
        assert pattern in dockerignore


def _local_list(text: str, name: str) -> list[str]:
    match = re.search(rf"{name}\s+=\s+(?:var\.[^\n]+\?\s+)?\[(.*?)\]", text, re.DOTALL)
    assert match is not None
    return re.findall(r'"([^"]+)"', match.group(1))


def _resource_role_list(text: str, resource_type: str, resource_name: str) -> list[str]:
    match = re.search(
        rf'resource\s+"{resource_type}"\s+"{resource_name}"\s+\{{[\s\S]*?for_each\s+=\s+toset\(\[(.*?)\]\)',
        text,
        re.DOTALL,
    )
    assert match is not None
    return re.findall(r'"([^"]+)"', match.group(1))
