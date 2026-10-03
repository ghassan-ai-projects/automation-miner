"""MCP tool dispatch tests — handlers called directly, no stdio."""

from __future__ import annotations

import json
from pathlib import Path

from automation_miner.mcp.tools import TOOL_SCHEMAS, dispatch


def _mine(workspace: Path) -> dict:
    resp = dispatch(
        "mine_domain",
        {"input": "MCP test domain", "dry_run": True},
        workspace,
    )
    assert resp.success, resp.error
    return resp.data  # type: ignore[return-value]


def test_all_tools_have_schemas() -> None:
    assert set(TOOL_SCHEMAS) == {
        "mine_domain",
        "list_runs",
        "list_domains",
        "get_opportunity",
        "query_registry",
        "get_run_report",
        "get_run_summary",
        "get_run_manifest",
        "get_run_error",
        "evaluate_run",
        "list_readers",
        "reindex",
        "server_info",
    }


def test_evaluate_run_lints_by_default_and_judges_on_request(workspace: Path) -> None:
    run_id = _mine(workspace)["run_id"]
    lint_only = dispatch("evaluate_run", {"run_id": run_id}, workspace)
    assert lint_only.success, lint_only.error
    assert lint_only.data["lint_errors"] == 0
    assert lint_only.data["briefs"] == []

    judged = dispatch(
        "evaluate_run", {"run_id": run_id, "judge": True, "dry_run": True}, workspace
    )
    assert judged.success, judged.error
    assert judged.data["means"]["overall"] == 4.0
    assert judged.data["portfolio"]["diversity"] == 4

    missing = dispatch("evaluate_run", {"run_id": "2026-01-01_none"}, workspace)
    assert not missing.success


def test_mine_domain_envelope(workspace: Path) -> None:
    data = _mine(workspace)
    assert data["run_id"]
    assert len(data["opportunities"]) == 5
    assert data["filtered"] == []
    assert Path(data["artifacts"]["report"]).is_file()
    assert Path(data["artifacts"]["summary_json"]).is_file()


def test_mine_domain_returns_the_summary_inline(workspace: Path) -> None:
    """An agent should not have to parse markdown or load every full draft."""
    summary = _mine(workspace)["summary"]
    assert summary["run_id"]
    assert summary["stats"]["published"] == 5
    assert summary["usage"]["calls"] > 0
    entry = summary["opportunities"][0]
    assert entry["am_id"] == "AM-001"
    assert entry["tier"] and entry["ice"] and entry["problem"]
    assert entry["eligibility"] == "published"
    assert Path(entry["brief_path"]).is_file()


def test_mine_domain_accepts_dynamic_constraint_params(workspace: Path) -> None:
    resp = dispatch(
        "mine_domain",
        {
            "input": "OpenClaw portfolio",
            "constraint_params": {"agent": "openclaw", "max_agents": 1},
            "mode": "strategy",
            "dry_run": True,
        },
        workspace,
    )
    assert resp.success, resp.error
    run = Path(resp.data["artifacts"]["run_dir"])
    manifest = json.loads((run / "run.json").read_text())
    assert manifest["constraint_params"] == {"agent": "openclaw", "max_agents": "1"}
    assert manifest["analysis_mode"] == "strategy"


def test_get_run_summary(workspace: Path) -> None:
    run_id = _mine(workspace)["run_id"]
    resp = dispatch("get_run_summary", {"run_id": run_id}, workspace)
    assert resp.success, resp.error
    assert resp.data["summary"]["run_id"] == run_id


def test_get_run_summary_rejects_traversal(workspace: Path) -> None:
    resp = dispatch("get_run_summary", {"run_id": "../../etc"}, workspace)
    assert not resp.success
    assert resp.error.code.value == "validation_error"


def test_get_run_manifest_and_error_are_directly_addressable(workspace: Path) -> None:
    data = _mine(workspace)
    manifest = dispatch("get_run_manifest", {"run_id": data["run_id"]}, workspace)
    assert manifest.success
    assert manifest.data["manifest"]["status"] == "completed"

    error = dispatch("get_run_error", {"run_id": data["run_id"]}, workspace)
    assert not error.success
    assert error.error.code == "not_found"


def test_failed_mine_returns_run_artifact_coordinates(workspace: Path, monkeypatch) -> None:
    from automation_miner.models.client import MinerModel

    original = MinerModel.call_json

    def fail(self, role, system, prompt, schema):  # type: ignore[no-untyped-def]
        if role == "mapper":
            raise RuntimeError("provider unavailable")
        return original(self, role, system, prompt, schema)

    monkeypatch.setattr(MinerModel, "call_json", fail)
    response = dispatch(
        "mine_domain",
        {"input": "MCP failing domain", "dry_run": True},
        workspace,
    )

    assert not response.success
    assert response.error.code == "internal_error"
    run_id = response.error.details["run_id"]
    error = dispatch("get_run_error", {"run_id": run_id}, workspace)
    assert error.success
    assert error.data["error"]["error"] == "provider unavailable"


def test_list_readers(workspace: Path) -> None:
    resp = dispatch("list_readers", {}, workspace)
    assert resp.success, resp.error
    names = {row["name"] for row in resp.data["readers"]}
    assert {"text", "json", "csv", "pdf"} <= names
    assert ".md" in resp.data["formats"]


def test_server_info(workspace: Path) -> None:
    resp = dispatch("server_info", {}, workspace)
    assert resp.success
    data = resp.data
    assert data["version"]
    assert data["workspace"] == str(workspace)
    assert "critic" in data["routing"]


def test_list_runs_and_domains(workspace: Path) -> None:
    _mine(workspace)
    runs = dispatch("list_runs", {}, workspace).data
    assert runs["runs"] == [r for r in runs["runs"] if "_" in r]
    assert len(runs["runs"]) == 1

    domains = dispatch("list_domains", {}, workspace).data
    assert domains["domains"][0]["id"] == "mcp-test-domain"
    assert domains["domains"][0]["total"] == 5


def test_get_opportunity(workspace: Path) -> None:
    _mine(workspace)
    resp = dispatch("get_opportunity", {"am_id": "AM-003"}, workspace)
    assert resp.success
    assert "# AM-003:" in resp.data["brief"]

    resp = dispatch("get_opportunity", {"am_id": "AM-999"}, workspace)
    assert not resp.success
    assert resp.error.code == "not_found"


def test_query_registry_filters(workspace: Path) -> None:
    _mine(workspace)
    resp = dispatch("query_registry", {"layer": "decision"}, workspace)
    assert resp.success
    assert resp.data["count"] == 1
    assert resp.data["entries"][0]["l"] == "decision"

    resp = dispatch("query_registry", {"min_ice": 100}, workspace)
    assert resp.data["count"] == 0


def test_get_run_report(workspace: Path) -> None:
    data = _mine(workspace)
    resp = dispatch("get_run_report", {"run_id": data["run_id"]}, workspace)
    assert resp.success
    assert "# Automation Mining Report" in resp.data["report"]

    resp = dispatch("get_run_report", {"run_id": "nope"}, workspace)
    assert not resp.success


def test_reindex(workspace: Path) -> None:
    _mine(workspace)
    resp = dispatch("reindex", {}, workspace)
    assert resp.success
    assert resp.data["stats"]["opps"] == 5


def test_unknown_tool(workspace: Path) -> None:
    resp = dispatch("hack_the_planet", {}, workspace)
    assert not resp.success
    assert resp.error.code == "unknown_tool"


def test_mine_domain_requires_input(workspace: Path) -> None:
    resp = dispatch("mine_domain", {"input": ""}, workspace)
    assert not resp.success
    assert resp.error.code == "validation_error"


def test_mine_domain_validates_iterations_and_paths(workspace: Path) -> None:
    malformed = dispatch(
        "mine_domain", {"input": "domain", "max_iterations": "many"}, workspace
    )
    assert not malformed.success
    assert malformed.error.code == "validation_error"

    zero = dispatch(
        "mine_domain",
        {"input": "domain", "max_iterations": 0, "dry_run": True},
        workspace,
    )
    assert not zero.success
    assert zero.error.code == "validation_error"

    missing = dispatch(
        "mine_domain",
        {"input": str(workspace / "missing.md"), "input_type": "file", "dry_run": True},
        workspace,
    )
    assert not missing.success
    assert missing.error.code == "validation_error"

    wrong_bool = dispatch(
        "mine_domain", {"input": "domain", "dry_run": "yes"}, workspace
    )
    assert not wrong_bool.success
    assert wrong_bool.error.code == "validation_error"


def test_lookup_tools_reject_pattern_and_traversal_input(workspace: Path) -> None:
    opportunity = dispatch("get_opportunity", {"am_id": "*"}, workspace)
    assert not opportunity.success
    assert opportunity.error.code == "validation_error"

    report = dispatch("get_run_report", {"run_id": "../../outside"}, workspace)
    assert not report.success
    assert report.error.code == "validation_error"

    query = dispatch("query_registry", {"min_ice": 126}, workspace)
    assert not query.success
    assert query.error.code == "validation_error"
