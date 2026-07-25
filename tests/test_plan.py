import pytest

from tf_cost_diff import CostDiffError
from tf_cost_diff.plan import parse_plan, validate_plan_document
from tf_cost_diff.pricing import PriceSheet
from tf_cost_diff.report import MARKER, render


def _plan(*changes):
    return {"resource_changes": list(changes)}


def _change(address, rtype, actions, before=None, after=None):
    return {
        "address": address,
        "type": rtype,
        "change": {"actions": actions, "before": before, "after": after},
    }


def test_create_instance_adds_cost():
    plan = _plan(
        _change(
            "aws_instance.web",
            "aws_instance",
            ["create"],
            after={"instance_type": "t3.medium"},
        )
    )
    summary = parse_plan(plan, PriceSheet())
    assert summary.created == 1
    assert summary.total_delta == round(0.0416 * 730, 2)


def test_delete_volume_is_negative():
    plan = _plan(
        _change(
            "aws_ebs_volume.data",
            "aws_ebs_volume",
            ["delete"],
            before={"size": 100},
        )
    )
    summary = parse_plan(plan, PriceSheet())
    assert summary.destroyed == 1
    assert summary.total_delta == -8.0


def test_replace_counts_as_update():
    plan = _plan(
        _change(
            "aws_instance.web",
            "aws_instance",
            ["create", "delete"],
            before={"instance_type": "t3.small"},
            after={"instance_type": "t3.large"},
        )
    )
    summary = parse_plan(plan, PriceSheet())
    assert summary.updated == 1
    assert summary.resources[0].delta > 0


def test_zero_cost_resources_are_skipped():
    plan = _plan(_change("aws_iam_role.r", "aws_iam_role", ["create"], after={}))
    summary = parse_plan(plan, PriceSheet())
    assert summary.resources == []
    assert summary.unpriced == []


def test_price_sheet_override_wins():
    sheet = PriceSheet(overrides={"aws_instance": 12.0})
    plan = _plan(
        _change("aws_instance.web", "aws_instance", ["create"], after={"instance_type": "m5.large"})
    )
    summary = parse_plan(plan, sheet)
    assert summary.total_delta == 12.0


def test_render_contains_marker_and_total():
    plan = _plan(
        _change("aws_eip.nat", "aws_eip", ["create"], after={})
    )
    summary = parse_plan(plan, PriceSheet())
    body = render(summary)
    assert MARKER in body
    assert "+$3.60/mo" in body
    assert "`aws_eip.nat`" in body


def test_no_op_and_read_actions_are_ignored():
    plan = _plan(
        _change("aws_eip.a", "aws_eip", ["no-op"], before={}, after={}),
        _change("aws_eip.b", "aws_eip", ["read"], after={}),
    )
    summary = parse_plan(plan, PriceSheet())
    assert summary.resources == []
    assert summary.created == 0


def test_rows_sum_to_the_headline_total():
    plan = _plan(
        _change("aws_eip.a", "aws_eip", ["create"], after={}),
        _change("aws_eip.b", "aws_eip", ["create"], after={}),
        _change("aws_ebs_volume.c", "aws_ebs_volume", ["create"], after={"size": 33}),
    )
    summary = parse_plan(plan, PriceSheet())
    assert summary.total_delta == round(sum(r.delta for r in summary.resources), 2)
    assert summary.total_delta == 9.84


# --- input validation: not every valid JSON document is a Terraform plan -----


def test_state_output_is_rejected_not_reported_as_no_changes():
    state = {
        "format_version": "1.0",
        "terraform_version": "1.9.0",
        "values": {"root_module": {"resources": []}},
    }
    with pytest.raises(CostDiffError, match="state"):
        validate_plan_document(state, "plan.json")


def test_arbitrary_json_is_rejected():
    with pytest.raises(CostDiffError, match="not a Terraform plan"):
        validate_plan_document({"hello": "world"}, "plan.json")


def test_non_object_json_is_rejected():
    with pytest.raises(CostDiffError, match="JSON object"):
        validate_plan_document([1, 2, 3], "plan.json")


def test_empty_plan_with_no_changes_is_accepted():
    doc = {"format_version": "1.2", "planned_values": {"root_module": {}}}
    assert validate_plan_document(doc, "plan.json") is doc
    assert parse_plan(doc, PriceSheet()).resources == []


def test_resource_changes_must_be_a_list():
    with pytest.raises(CostDiffError, match="must be a list"):
        validate_plan_document({"resource_changes": {}}, "plan.json")


def test_malformed_resource_change_raises_rather_than_costing_zero():
    with pytest.raises(CostDiffError, match="change"):
        parse_plan({"resource_changes": [{"address": "a", "type": "aws_eip"}]}, PriceSheet())


# --- unknown prices are reported, never silently turned into a number -------


def test_unknown_instance_type_is_unpriced_not_guessed():
    plan = _plan(
        _change(
            "aws_instance.big",
            "aws_instance",
            ["create"],
            after={"instance_type": "m5.24xlarge"},
        )
    )
    summary = parse_plan(plan, PriceSheet())
    assert summary.resources == []
    assert [u.address for u in summary.unpriced] == ["aws_instance.big"]
    assert summary.total_delta == 0.0
    assert summary.is_complete is False
    assert summary.created == 1


def test_attribute_unknown_until_apply_is_unpriced_not_zero():
    plan = _plan(
        _change("aws_ebs_volume.d", "aws_ebs_volume", ["create"], after={"size": None}),
        _change("aws_instance.w", "aws_instance", ["create"], after={"instance_type": None}),
    )
    summary = parse_plan(plan, PriceSheet())
    assert len(summary.unpriced) == 2
    assert summary.total_delta == 0.0


def test_unpriced_resources_are_flagged_in_the_report():
    plan = _plan(
        _change(
            "aws_db_instance.main",
            "aws_db_instance",
            ["create"],
            after={"instance_class": "db.r5.24xlarge"},
        )
    )
    body = render(parse_plan(plan, PriceSheet()))
    assert "could not be priced" in body
    assert "(partial)" in body
    assert "`aws_db_instance.main`" in body


def test_replace_with_unknown_after_side_is_unpriced():
    plan = _plan(
        _change(
            "aws_instance.web",
            "aws_instance",
            ["create", "delete"],
            before={"instance_type": "t3.small"},
            after={"instance_type": "x9.enormous"},
        )
    )
    summary = parse_plan(plan, PriceSheet())
    assert summary.resources == []
    assert len(summary.unpriced) == 1
    assert summary.updated == 1
