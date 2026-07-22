"""Artifact persistence: workspace layout, briefs, reports, registry."""

from automation_miner.artifacts.briefs import render_brief, title_slug
from automation_miner.artifacts.registry import build_registry, reindex
from automation_miner.artifacts.reports import render_report, render_run_md
from automation_miner.artifacts.workspace import Workspace, default_workspace, read_json, write_json

__all__ = [
    "Workspace",
    "build_registry",
    "default_workspace",
    "read_json",
    "reindex",
    "render_brief",
    "render_report",
    "render_run_md",
    "title_slug",
    "write_json",
]
