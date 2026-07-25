"""The rendered comment must survive hostile resource addresses and big plans."""
import re

from tf_cost_diff.plan import PlanSummary, ResourceDelta, UnpricedResource
from tf_cost_diff.report import COMMENT_LIMIT, MARKER, render


def _delta(address, after=10.0, action="create"):
    return ResourceDelta(
        address=address,
        resource_type="aws_eip",
        action=action,
        before_monthly=0.0,
        after_monthly=after,
    )


def _outside_code_spans(body):
    """The comment with every `code span` removed, i.e. what Markdown parses."""
    return re.sub(r"`[^`\n]*`", "", body.replace(MARKER, ""))


def test_backtick_in_for_each_key_cannot_close_the_code_span():
    # `for_each` keys are arbitrary strings. A backtick that closes the span
    # lets the rest be parsed as raw HTML, and a bare `<!--` would comment out
    # -- and therefore hide -- every table row below it.
    summary = PlanSummary(
        resources=[_delta('aws_eip.e["x`</code><!--"]'), _delta("aws_eip.visible")]
    )
    body = render(summary)
    rows = [line for line in body.splitlines() if line.startswith("| `")]
    assert len(rows) == 2
    assert "`aws_eip.visible`" in body
    # Nothing the attacker supplied escaped its code span, so no markup of
    # theirs reaches the Markdown parser.
    assert "<" not in _outside_code_spans(body)
    for row in rows:
        assert row.count("`") == 2


def test_pipe_in_address_cannot_forge_table_columns():
    body = render(PlanSummary(resources=[_delta("aws_eip.e[\"a | b\"]")]))
    row = next(line for line in body.splitlines() if line.startswith("| `"))
    assert row.count("|") - row.count("\\|") == 6  # 5 cells => 6 unescaped pipes
    assert "\\|" in row


def test_newline_in_address_cannot_split_the_table():
    body = render(PlanSummary(resources=[_delta('aws_eip.e["a\nb"]'), _delta("aws_eip.z")]))
    rows = [line for line in body.splitlines() if line.startswith("| `")]
    assert len(rows) == 2


def test_absurdly_long_address_is_truncated():
    body = render(PlanSummary(resources=[_delta("aws_eip.e" + "x" * 5000)]))
    row = next(line for line in body.splitlines() if line.startswith("| `"))
    assert len(row) < 300


def test_empty_address_still_renders_valid_markdown():
    body = render(PlanSummary(resources=[_delta("   ")]))
    assert "`(unnamed)`" in body


def test_huge_plan_is_truncated_to_fit_githubs_comment_limit():
    # Ordered biggest-delta-first, as parse_plan() sorts them.
    summary = PlanSummary(
        resources=[
            _delta(f"aws_eip.instance_number_{i}", after=float(i))
            for i in range(5999, -1, -1)
        ]
    )
    body = render(summary)
    # Previously this was posted whole, GitHub answered HTTP 422, and the run
    # ended with no comment at all.
    assert len(body) <= COMMENT_LIMIT
    assert "omitted to stay within GitHub's comment size limit" in body
    # The headline total still counts every resource, and the biggest rows are
    # the ones that survive.
    assert f"{summary.total_delta:,.2f}" in body
    assert "`aws_eip.instance_number_5999`" in body
    assert "`aws_eip.instance_number_0`" not in body


def test_small_plan_is_not_truncated():
    body = render(PlanSummary(resources=[_delta("aws_eip.a")]))
    assert "omitted" not in body


def test_no_changes_message():
    body = render(PlanSummary(resources=[]))
    assert "_No cost-relevant changes detected._" in body
    assert "(partial)" not in body


def test_unpriced_only_plan_does_not_claim_no_changes():
    summary = PlanSummary(
        resources=[],
        unpriced=[UnpricedResource("aws_instance.big", "aws_instance", "create", "why")],
    )
    body = render(summary)
    assert "_No cost-relevant changes detected._" not in body
    assert "could not be priced" in body
