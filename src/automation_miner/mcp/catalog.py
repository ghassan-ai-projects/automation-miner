"""MCP tool catalog: JSON input schemas and descriptions for every tool."""

from __future__ import annotations

from typing import Any

from automation_miner.mcp.lifecycle import LIFECYCLE_DESCRIPTIONS, LIFECYCLE_SCHEMAS

INPUT_TYPES = ("auto", "idea", "file", "kb")

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "mine_domain": {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Idea text, file path, or KB folder."},
            "input_type": {"type": "string", "enum": list(INPUT_TYPES), "default": "auto"},
            "constraints": {"type": "string", "default": ""},
            "constraint_params": {
                "type": "object",
                "additionalProperties": {
                    "type": ["string", "number", "boolean"]
                },
                "default": {},
                "description": (
                    "Open-ended binding parameters, e.g. "
                    '{"agent":"openclaw","deployment":"local-only"}.'
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["auto", "operational", "strategy"],
                "default": "auto",
            },
            "profile": {"type": "string", "default": "default"},
            "max_iterations": {"type": "integer", "minimum": 1, "maximum": 10, "default": 2},
            "dry_run": {
                "type": "boolean",
                "default": False,
                "description": "Force the deterministic mock provider.",
            },
        },
        "required": ["input"],
    },
    "list_runs": {"type": "object", "properties": {}},
    "list_domains": {"type": "object", "properties": {}},
    "get_opportunity": {
        "type": "object",
        "properties": {"am_id": {"type": "string", "description": "e.g. AM-001"}},
        "required": ["am_id"],
    },
    "query_registry": {
        "type": "object",
        "properties": {
            "layer": {"type": "string"},
            "min_ice": {"type": "integer", "minimum": 0, "maximum": 125},
            "status": {"type": "string"},
            "domain": {"type": "string"},
        },
    },
    "get_run_report": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    },
    "get_run_summary": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    },
    "get_run_manifest": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    },
    "get_run_error": {
        "type": "object",
        "properties": {"run_id": {"type": "string"}},
        "required": ["run_id"],
    },
    "evaluate_run": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "judge": {
                "type": "boolean",
                "default": False,
                "description": "Also grade briefs with the configured judge model (costs credit).",
            },
            "profile": {"type": "string", "default": "default"},
            "dry_run": {"type": "boolean", "default": False},
        },
        "required": ["run_id"],
    },
    "list_readers": {"type": "object", "properties": {}},
    "reindex": {"type": "object", "properties": {}},
    "server_info": {"type": "object", "properties": {}},
    **LIFECYCLE_SCHEMAS,
}

TOOL_DESCRIPTIONS = {
    "mine_domain": (
        "Run the full mining pipeline over a domain. Returns the compact run summary "
        "inline (per-opportunity ICE, tier, filters, eligibility) plus artifact paths."
    ),
    "list_runs": "List all mining run ids in the workspace.",
    "list_domains": "List all domains in the registry with totals and top ICE.",
    "get_opportunity": "Return the full AM-XXX opportunity brief markdown.",
    "query_registry": "Query registry entries filtered by layer, min ICE, status, or domain.",
    "get_run_report": "Return the report.md content of one run.",
    "get_run_summary": (
        "Return the compact summary.json of one run: portfolio stats, context stats, "
        "token usage, and one row per opportunity. Prefer this over get_run_report "
        "when deciding what to act on."
    ),
    "get_run_manifest": "Return the terminal manifest for one run, including status, budget, and usage.",
    "get_run_error": "Return the structured failure artifact for one failed run.",
    "evaluate_run": (
        "Grade a completed run: deterministic brief lint (hedging, numbering, empty "
        "sections) and, with judge=true, an independent judge model's 1-5 scores per "
        "brief plus portfolio diversity and coverage."
    ),
    "list_readers": (
        "List document readers, the file formats each handles, and whether its "
        "dependencies are installed."
    ),
    "reindex": "Rebuild registry.json from the opps/ tree.",
    "server_info": "Server version, active model routing, workspace path.",
    **LIFECYCLE_DESCRIPTIONS,
}
