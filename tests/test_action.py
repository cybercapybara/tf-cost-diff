"""Keep action.yml honest about what the CLI actually produces.

The failure mode this guards against is drift: the tool computes numbers, the
Action declares no `outputs:` for them, and the calling workflow silently has
nothing to read.
"""
import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ACTION = pathlib.Path(__file__).resolve().parent.parent / "action.yml"


@pytest.fixture(scope="module")
def action():
    return yaml.safe_load(ACTION.read_text(encoding="utf-8"))


def _cli_output_names(tmp_path):
    from tf_cost_diff.__main__ import write_github_output
    from tf_cost_diff.plan import PlanSummary

    out = tmp_path / "gh-output"
    write_github_output(str(out), PlanSummary(resources=[]), False, "")
    return {line.split("=", 1)[0] for line in out.read_text().splitlines()}


def test_action_declares_every_output_the_cli_writes(action, tmp_path):
    declared = set(action.get("outputs") or {})
    assert declared == _cli_output_names(tmp_path)


def test_every_declared_output_is_wired_to_the_step(action):
    step_ids = {s.get("id") for s in action["runs"]["steps"]}
    for name, spec in action["outputs"].items():
        assert spec.get("description"), f"output {name} has no description"
        value = spec["value"]
        step = value.split("steps.", 1)[1].split(".", 1)[0]
        assert step in step_ids, f"output {name} references unknown step {step}"
        assert value.endswith(f"outputs.{name} }}}}"), f"output {name} is mis-wired"


def test_inputs_are_passed_through_env_not_interpolated_into_the_script(action):
    """`run:` must not interpolate inputs, or a crafted value runs as shell."""
    for step in action["runs"]["steps"]:
        assert "${{" not in step.get("run", ""), "inputs must reach the script via env:"


def test_plan_path_is_resolved_against_the_workspace(action):
    # working-directory: ${{ github.action_path }} would make the documented
    # relative `plan: plan.json` resolve inside the action checkout instead.
    for step in action["runs"]["steps"]:
        assert "working-directory" not in step
    assert "PYTHONPATH" in action["runs"]["steps"][0]["env"]


def test_declared_inputs_are_all_consumed(action):
    script = "".join(s.get("run", "") for s in action["runs"]["steps"])
    env = {k: str(v) for s in action["runs"]["steps"] for k, v in (s.get("env") or {}).items()}
    for name in action["inputs"]:
        referenced = any(f"inputs.{name}" in value for value in env.values())
        assert referenced, f"input {name} is declared but never used"
    assert "--plan" in script
