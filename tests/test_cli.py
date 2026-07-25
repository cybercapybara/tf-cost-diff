"""End-to-end CLI behaviour: exit codes, the threshold gate, Action outputs."""
import json

import pytest

from tf_cost_diff import CostDiffError
from tf_cost_diff.__main__ import EXIT_ERROR, EXIT_OK, EXIT_OVER_THRESHOLD, main
from tf_cost_diff.pricing import PriceSheet

PLAN = {
    "format_version": "1.2",
    "resource_changes": [
        {
            "address": "aws_instance.web",
            "type": "aws_instance",
            "change": {
                "actions": ["create"],
                "before": None,
                "after": {"instance_type": "m5.large"},
            },
        }
    ],
}


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return str(path)


def test_under_threshold_exits_zero(tmp_path, capsys):
    plan = _write(tmp_path, "plan.json", PLAN)
    assert main(["--plan", plan, "--threshold", "1000"]) == EXIT_OK


def test_over_threshold_exits_one(tmp_path, capsys):
    plan = _write(tmp_path, "plan.json", PLAN)
    assert main(["--plan", plan, "--threshold", "10"]) == EXIT_OVER_THRESHOLD
    assert "exceeds threshold" in capsys.readouterr().err


def test_state_output_fails_loudly_instead_of_reporting_no_changes(tmp_path, capsys):
    state = _write(
        tmp_path,
        "state.json",
        {"format_version": "1.0", "values": {"root_module": {"resources": []}}},
    )
    assert main(["--plan", state, "--threshold", "10"]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "::error::" in err and "state" in err


def test_truncated_plan_fails_with_a_message_not_a_traceback(tmp_path, capsys):
    plan = _write(tmp_path, "plan.json", '{"resource_changes":[{"addre')
    assert main(["--plan", plan]) == EXIT_ERROR
    assert "not valid JSON" in capsys.readouterr().err


def test_missing_plan_file_is_reported_cleanly(tmp_path, capsys):
    assert main(["--plan", str(tmp_path / "nope.json")]) == EXIT_ERROR
    assert "not found" in capsys.readouterr().err


def test_nan_price_sheet_is_rejected_rather_than_disabling_the_gate(tmp_path, capsys):
    plan = _write(tmp_path, "plan.json", PLAN)
    sheet = _write(tmp_path, "prices.json", '{"aws_instance": NaN}')
    # Previously this produced "$nan" and quietly returned 0 from the gate.
    assert main(["--plan", plan, "--price-sheet", sheet, "--threshold", "1"]) == EXIT_ERROR
    assert "non-finite" in capsys.readouterr().err


def test_nan_threshold_is_rejected(tmp_path):
    plan = _write(tmp_path, "plan.json", PLAN)
    with pytest.raises(SystemExit):
        main(["--plan", plan, "--threshold", "nan"])


def test_negative_price_in_sheet_is_rejected(tmp_path):
    sheet = _write(tmp_path, "prices.json", {"aws_instance": -5})
    with pytest.raises(CostDiffError, match="negative"):
        PriceSheet.load(sheet)


def test_non_numeric_price_is_rejected(tmp_path):
    sheet = _write(tmp_path, "prices.json", {"aws_instance": "cheap"})
    with pytest.raises(CostDiffError, match="finite number"):
        PriceSheet.load(sheet)


def test_github_output_is_written(tmp_path):
    plan = _write(tmp_path, "plan.json", PLAN)
    out = tmp_path / "gh-output"
    assert main(["--plan", plan, "--threshold", "10", "--github-output", str(out)]) == (
        EXIT_OVER_THRESHOLD
    )
    values = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert values == {
        "total-delta": "70.08",
        "created": "1",
        "updated": "0",
        "destroyed": "0",
        "unpriced": "0",
        "complete": "true",
        # Written even though the gate failed on this same run.
        "threshold-exceeded": "true",
        "comment-url": "",
    }


def test_github_output_reports_unpriced_resources(tmp_path):
    plan = _write(
        tmp_path,
        "plan.json",
        {
            "resource_changes": [
                {
                    "address": "aws_instance.big",
                    "type": "aws_instance",
                    "change": {
                        "actions": ["create"],
                        "after": {"instance_type": "m5.24xlarge"},
                    },
                }
            ]
        },
    )
    out = tmp_path / "gh-output"
    assert main(["--plan", plan, "--github-output", str(out)]) == EXIT_OK
    values = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert values["unpriced"] == "1"
    assert values["complete"] == "false"


def test_pr_without_token_warns_and_does_not_crash(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    plan = _write(tmp_path, "plan.json", PLAN)
    assert main(["--plan", plan, "--pr", "7"]) == EXIT_OK
    assert "::warning::" in capsys.readouterr().err


def test_failure_to_comment_does_not_mask_the_threshold_verdict(
    tmp_path, capsys, monkeypatch
):
    def boom(*_args, **_kwargs):
        raise CostDiffError("HTTP 403")

    monkeypatch.setattr("tf_cost_diff.__main__.upsert_comment", boom)
    plan = _write(tmp_path, "plan.json", PLAN)
    code = main(
        ["--plan", plan, "--pr", "7", "--repo", "o/n", "--token", "t", "--threshold", "10"]
    )
    assert code == EXIT_OVER_THRESHOLD
    err = capsys.readouterr().err
    assert "could not post the PR comment" in err
    assert "exceeds threshold" in err


def test_bundled_example_plan_parses(capsys):
    assert main(["--plan", "examples/plan.json"]) == EXIT_OK
    assert "Terraform monthly cost estimate" in capsys.readouterr().out
