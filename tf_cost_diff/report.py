"""Render a PlanSummary as a Markdown PR comment."""
from __future__ import annotations

from .plan import PlanSummary

MARKER = "<!-- tf-cost-diff -->"

_ARROW = {"create": "🟢 create", "update": "🟡 update", "delete": "🔴 delete"}


def _money(value: float) -> str:
    if value < 0:
        return f"-${abs(value):,.2f}"
    sign = "+" if value > 0 else ""
    return f"{sign}${value:,.2f}"


def render(summary: PlanSummary) -> str:
    total = summary.total_delta
    head = (
        f"{MARKER}\n"
        f"### 💸 Terraform monthly cost estimate: **{_money(total)}/mo**\n\n"
        f"`{summary.created} to create · {summary.updated} to change · "
        f"{summary.destroyed} to destroy`\n"
    )
    if not summary.resources:
        return head + "\n_No cost-relevant changes detected._\n"

    rows = [
        "| Resource | Action | Before | After | Δ/mo |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for r in summary.resources:
        rows.append(
            f"| `{r.address}` | {_ARROW.get(r.action, r.action)} | "
            f"${r.before_monthly:,.2f} | ${r.after_monthly:,.2f} | "
            f"**{_money(r.delta)}** |"
        )
    return head + "\n" + "\n".join(rows) + "\n"
