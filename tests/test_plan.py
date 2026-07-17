from tf_cost_diff.plan import parse_plan
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
