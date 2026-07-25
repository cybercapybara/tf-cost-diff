from __future__ import annotations

import argparse
import math
import os
import sys

from . import CostDiffError, __version__
from .github import upsert_comment
from .plan import PlanSummary, load_plan, parse_plan
from .pricing import PriceSheet
from .report import render

EXIT_OK = 0
EXIT_OVER_THRESHOLD = 1
EXIT_ERROR = 2


def _threshold(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a number") from None
    if not math.isfinite(value):
        # float("nan") parses happily, and every comparison against NaN is
        # False, so a NaN threshold would disable the gate without saying so.
        raise argparse.ArgumentTypeError(f"{raw!r} must be a finite number")
    return value


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tf-cost-diff",
        description="Estimate the monthly cost delta of a Terraform plan and "
        "post it to a pull request.",
    )
    p.add_argument("--plan", required=True, help="Path to `terraform show -json` output.")
    p.add_argument("--price-sheet", help="Optional JSON price-sheet override.")
    p.add_argument(
        "--threshold",
        type=_threshold,
        default=None,
        help="Fail (exit 1) when the monthly delta exceeds this many dollars.",
    )
    p.add_argument("--repo", help="owner/name; defaults to $GITHUB_REPOSITORY.")
    p.add_argument("--pr", type=int, help="Pull request number to comment on.")
    p.add_argument(
        "--token", help="GitHub token; defaults to $GITHUB_TOKEN.", default=None
    )
    p.add_argument(
        "--github-output",
        help="Append `name=value` result lines to this file (pass $GITHUB_OUTPUT).",
    )
    p.add_argument("--version", action="version", version=f"tf-cost-diff {__version__}")
    return p


def write_github_output(
    path: str, summary: PlanSummary, exceeded: bool, comment_url: str
) -> None:
    """Emit the results as GitHub Actions step outputs.

    Written before the threshold gate is applied, so a workflow can still read
    the numbers on the run where the gate fails -- which is the run that matters.
    """
    lines = [
        f"total-delta={summary.total_delta:.2f}",
        f"created={summary.created}",
        f"updated={summary.updated}",
        f"destroyed={summary.destroyed}",
        f"unpriced={len(summary.unpriced)}",
        f"complete={'true' if summary.is_complete else 'false'}",
        f"threshold-exceeded={'true' if exceeded else 'false'}",
        f"comment-url={comment_url.replace(chr(10), '').replace(chr(13), '')}",
    ]
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    sheet = PriceSheet.load(args.price_sheet)
    summary = parse_plan(load_plan(args.plan), sheet)
    body = render(summary)
    print(body)

    repo = args.repo or os.environ.get("GITHUB_REPOSITORY")
    token = args.token or os.environ.get("GITHUB_TOKEN")
    comment_url = ""
    if args.pr:
        if not repo or not token:
            missing = "repository" if not repo else "token"
            print(
                f"::warning::--pr {args.pr} was given but no {missing} is available; "
                "not posting a comment.",
                file=sys.stderr,
            )
        else:
            try:
                comment_url = upsert_comment(repo, args.pr, token, body)
            except CostDiffError as exc:
                # Posting is best effort: a fork PR has a read-only token, and
                # failing to comment must not mask the threshold verdict below.
                print(f"::warning::could not post the PR comment: {exc}", file=sys.stderr)
            else:
                if comment_url:
                    print(f"Comment: {comment_url}", file=sys.stderr)

    exceeded = args.threshold is not None and summary.total_delta > args.threshold

    if args.github_output:
        write_github_output(args.github_output, summary, exceeded, comment_url)

    if summary.unpriced:
        print(
            f"::warning::{len(summary.unpriced)} resource(s) could not be priced and "
            "are excluded from the total; the real delta differs.",
            file=sys.stderr,
        )

    if exceeded:
        print(
            f"::error::monthly cost delta ${summary.total_delta:.2f} "
            f"exceeds threshold ${args.threshold:.2f}",
            file=sys.stderr,
        )
        return EXIT_OVER_THRESHOLD
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except CostDiffError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
