"""MCP error types and response envelope (film-pipeline pattern, slimmed down)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MCPErrorCode(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    INTERNAL_ERROR = "internal_error"


@dataclass
class MCPError(Exception):
    """A structured MCP error."""

    code: MCPErrorCode
    message: str
    details: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, str]:
        out = {"code": self.code.value, "message": self.message}
        out.update(self.details)
        return out


@dataclass
class MCPResponse:
    """Structured MCP response envelope."""

    success: bool
    data: object = None
    error: MCPError | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error.to_dict() if self.error else None,
        }
