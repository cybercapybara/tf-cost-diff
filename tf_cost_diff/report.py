"""Render a PlanSummary as a Markdown PR comment."""
from __future__ import annotations

import re

from .plan import PlanSummary

MARKER = "<!-- tf-cost-diff -->"

# GitHub rejects an issue-comment body longer than this with HTTP 422, which
# would mean posting nothing at all on exactly the large plans people most want
# reviewed. Stay under it and say what was dropped.
COMMENT_LIMIT = 65536

_ARROW = {"create": "🟢 create", "update": "🟡 update", "delete": "🔴 delete"}

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_CELL_MAX = 200


def _code(text: str) -> str:
    """Render untrusted text as a Markdown code span that cannot break out.

    Resource addresses embed ``for_each`` keys, which are arbitrary attacker- or
    typo-supplied strings. A backtick would close the code span and let the rest
    of the key be interpreted as Markdown or raw HTML -- ``<!--`` alone hides
    every row below it in the rendered comment. A newline would end the table
    and a pipe would forge extra columns.
    """
    safe = _CONTROL.sub(" ", str(text))
    safe = safe.replace("`", "'").replace("|", "\\|")
    if len(safe) > _CELL_MAX:
        safe = safe[: _CELL_MAX - 1] + "…"
    safe = safe.strip()
    return f"`{safe}`" if safe else "`(unnamed)`"


def _money(value: float) -> str:
    if value < 0:
        return f"-${abs(value):,.2f}"
    sign = "+" if value > 0 else ""
    return f"{sign}${value:,.2f}"


def _assemble(head: str, blocks: list[list[str]], notes: list[str], dropped: int) -> str:
    # A block is a table: header row + separator + entries. Render it only while
    # it still has entries.
    parts = [head] + ["\n".join(b) for b in blocks if len(b) > 2]
    tail = list(notes)
    if dropped:
        tail.append(
            f"_{dropped} further row(s) omitted to stay within GitHub's comment "
            "size limit; the total above still counts them._"
        )
    return "\n\n".join(parts + tail) + "\n"


def _fit(head: str, blocks: list[list[str]], notes: list[str], limit: int) -> str:
    """Assemble the comment, dropping trailing rows until it fits ``limit``.

    ``blocks`` arrive ordered most-significant first, so the rows dropped are
    the least interesting ones.
    """
    dropped = 0
    while True:
        body = _assemble(head, blocks, notes, dropped)
        if len(body) <= limit:
            return body
        live = [b for b in blocks if len(b) > 2]
        if not live:
            return body[: max(0, limit - 1)].rstrip() + "…"
        # Estimate how many rows to drop in one go so this converges in a couple
        # of passes rather than one re-render per row.
        entries = [line for b in live for line in b[2:]]
        average = max(1, sum(len(line) + 1 for line in entries) // len(entries))
        drop_now = min(len(entries), max(1, (len(body) - limit) // average + 1))
        for _ in range(drop_now):
            candidates = [b for b in blocks if len(b) > 2]
            if not candidates:
                break
            max(candidates, key=len).pop()
            dropped += 1


def render(summary: PlanSummary, limit: int = COMMENT_LIMIT) -> str:
    total = summary.total_delta
    qualifier = " (partial)" if summary.unpriced else ""
    head = (
        f"{MARKER}\n"
        f"### 💸 Terraform monthly cost estimate: **{_money(total)}/mo**{qualifier}\n\n"
        f"`{summary.created} to create · {summary.updated} to change · "
        f"{summary.destroyed} to destroy`"
    )

    if not summary.resources and not summary.unpriced:
        return head + "\n\n_No cost-relevant changes detected._\n"

    blocks: list[list[str]] = []
    if summary.resources:
        rows = [
            "| Resource | Action | Before | After | Δ/mo |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
        for r in summary.resources:
            rows.append(
                f"| {_code(r.address)} | {_ARROW.get(r.action, _code(r.action))} | "
                f"${r.before_monthly:,.2f} | ${r.after_monthly:,.2f} | "
                f"**{_money(r.delta)}** |"
            )
        blocks.append(rows)

    notes: list[str] = []
    if summary.unpriced:
        unknown = [
            "**⚠️ Cost unknown — excluded from the total above**\n\n"
            "| Resource | Action | Why |",
            "| --- | --- | --- |",
        ]
        for u in summary.unpriced:
            # u.reason is our own static text, so it needs no sanitising.
            unknown.append(
                f"| {_code(u.address)} | {_ARROW.get(u.action, _code(u.action))} | "
                f"{u.reason} |"
            )
        blocks.append(unknown)
        notes.append(
            f"> ⚠️ **{len(summary.unpriced)} resource(s) could not be priced** and "
            "are *not* included in the total above, so the real delta differs. "
            "Add them to a `--price-sheet` override to get a complete figure."
        )

    notes.append(
        "_Estimate only: a small set of resource types is priced, and usage-based "
        "charges (data transfer, requests, storage growth) are never included._"
    )
    return _fit(head, blocks, notes, limit)
