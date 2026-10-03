"""Derived figures, checked in code instead of argued about by models.

A real run's best email-triage brief said 38% of the shared mailbox's emails
are follow-ups, "392/week". That was right: the metrics count 640 claim emails
a week, so follow-ups are 640 / 0.62 * 0.38. The critic computed 640 * 0.38 =
243 and blocked the brief; the repair role obediently wrote the wrong 243; the
verifier caught that, and the brief never published.

Arithmetic is not judgment. A draft now records each derived number with its
formula; code evaluates the formula and compares it with the figure. The critic
sees which derivations code verified, so it argues only about whether the
inputs are the right figures, and a wrong sum is caught without a model.
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from typing import Any, Callable

from automation_miner.schemas import Derivation, OpportunityDraft

# Relative tolerance for rounding in prose ("~392" for 392.3), with an absolute floor.
TOLERANCE = 0.03
_ABS_TOLERANCE = 0.5

_OPS: dict[type, Callable[..., float]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SYMBOLS = str.maketrans({"×": "*", "·": "*", "÷": "/", "−": "-", "~": " ", "≈": " "})


def _value(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_value(node.left), _value(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_value(node.operand))
    raise ValueError(f"unsupported expression element {type(node).__name__}")


def evaluate(formula: str) -> float | None:
    """The value of a plain arithmetic formula, or None if it is not one."""
    text = _THOUSANDS.sub("", formula.translate(_SYMBOLS))
    text = _PERCENT.sub(r"(\1/100)", text)
    try:
        return _value(ast.parse(text.strip(), mode="eval").body)
    except (SyntaxError, ValueError, ZeroDivisionError, RecursionError):
        return None


def figure_value(figure: str) -> float | None:
    match = _NUMBER.search(figure)
    return float(match.group(0).replace(",", "")) if match else None


@dataclass(frozen=True)
class Check:
    derivation: Derivation
    computed: float | None
    stated: float | None

    @property
    def ok(self) -> bool:
        if self.computed is None or self.stated is None:
            return False
        margin = max(_ABS_TOLERANCE, TOLERANCE * abs(self.computed))
        return abs(self.computed - self.stated) <= margin


def check_derivations(draft: OpportunityDraft) -> list[Check]:
    return [
        Check(d, evaluate(d.formula), figure_value(d.figure)) for d in draft.derivations
    ]


def _fmt(value: float | None) -> str:
    return "not computable" if value is None else f"{value:,.4g}"


def verified_notes(checks: list[Check]) -> str:
    """Prompt block: the derivations code verified, for critic and verifier."""
    lines = [
        f"- {c.derivation.figure} = {c.derivation.formula} (computes to {_fmt(c.computed)})"
        + (f" [{', '.join(c.derivation.evidence_refs)}]" if c.derivation.evidence_refs else "")
        for c in checks if c.ok
    ]
    return "\n".join(lines)


def arithmetic_issues(checks: list[Check]) -> list[str]:
    """Writing issues for derivations whose formula does not give the stated figure."""
    return [
        f'arithmetic check failed: "{c.derivation.figure}" but "{c.derivation.formula}" '
        f"computes to {_fmt(c.computed)}; fix the figure or the formula"
        for c in checks if not c.ok
    ]


def derivation_record(checks: list[Check]) -> list[dict[str, Any]]:
    return [
        {"figure": c.derivation.figure, "formula": c.derivation.formula,
         "computed": c.computed, "ok": c.ok}
        for c in checks
    ]


__all__ = [
    "Check", "arithmetic_issues", "check_derivations", "derivation_record", "evaluate",
    "figure_value", "verified_notes",
]
