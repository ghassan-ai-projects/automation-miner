"""MCP tool dispatch tests — handlers called directly, no stdio."""

from __future__ import annotations

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
        "reindex",
        "server_info",
    }


def test_mine_domain_envelope(workspace: Path) -> None:
    data = _mine(workspace)
    assert data["run_id"]
    assert len(data["opportunities"]) == 5
    assert Path(data["artifacts"]["report"]).is_file()


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
