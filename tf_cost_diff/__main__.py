from __future__ import annotations

import argparse
import os
import sys

from .github import upsert_comment
from .plan import load_plan, parse_plan
from .pricing import PriceSheet
from .report import render


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
        type=float,
        default=None,
        help="Fail (exit 1) when the monthly delta exceeds this many dollars.",
    )
    p.add_argument("--repo", help="owner/name; defaults to $GITHUB_REPOSITORY.")
    p.add_argument("--pr", type=int, help="Pull request number to comment on.")
    p.add_argument(
        "--token", help="GitHub token; defaults to $GITHUB_TOKEN.", default=None
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    sheet = PriceSheet.load(args.price_sheet)
    summary = parse_plan(load_plan(args.plan), sheet)
    body = render(summary)
    print(body)

    repo = args.repo or os.environ.get("GITHUB_REPOSITORY")
    token = args.token or os.environ.get("GITHUB_TOKEN")
    if args.pr and repo and token:
        url = upsert_comment(repo, args.pr, token, body)
        if url:
            print(f"Comment: {url}", file=sys.stderr)

    if args.threshold is not None and summary.total_delta > args.threshold:
        print(
            f"::error::monthly cost delta ${summary.total_delta:.2f} "
            f"exceeds threshold ${args.threshold:.2f}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
