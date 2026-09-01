"""Open-ended constraint parameters remain dynamic and auditable."""

import pytest

from automation_miner.constraints import (
    normalize_constraint_params,
    parse_constraint_args,
    render_constraints,
)


def test_repeatable_constraint_args_render_as_binding_contract() -> None:
    params = parse_constraint_args(
        ["agent=openclaw", "deployment=local-only", "max_agents=1"]
    )
    rendered = render_constraints("budget:medium", params)

    assert params == {
        "agent": "openclaw",
        "deployment": "local-only",
        "max_agents": "1",
    }
    assert "budget:medium" in rendered
    assert "Unknown constraint parameters (advisory context only)" in rendered
    assert "- agent = openclaw" in rendered
    assert "- deployment = local-only" in rendered


@pytest.mark.parametrize(
    "values, message",
    [
        (["agent"], "key=value"),
        (["agent=openclaw", "agent=other"], "more than once"),
        (["bad key=value"], "invalid constraint parameter"),
        (["agent="], "must not be empty"),
    ],
)
def test_invalid_constraint_args_fail_clearly(values: list[str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_constraint_args(values)


def test_python_params_accept_non_string_scalar_values() -> None:
    assert normalize_constraint_params({"agent": "openclaw", "max_agents": 1}) == {
        "agent": "openclaw",
        "max_agents": "1",
    }


def test_constraint_keys_are_unique_case_insensitively() -> None:
    with pytest.raises(ValueError, match="case-insensitively"):
        normalize_constraint_params({"budget": "low", "BUDGET": "high"})
