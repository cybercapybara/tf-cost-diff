"""Create or update a single sticky comment on a pull request."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import CostDiffError
from .report import COMMENT_LIMIT, MARKER

_API = "https://api.github.com"
_TIMEOUT = 30  # seconds; without this a hung API call hangs the whole job
_PER_PAGE = 100
_MAX_PAGES = 20


def _request(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            return json.loads(resp.read() or "null")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (exc.read() or b"").decode("utf-8", "replace")[:400]
        except OSError:  # pragma: no cover - body already consumed
            pass
        hint = ""
        if exc.code in (401, 403):
            hint = (
                " (the token cannot write to this pull request; note that "
                "GITHUB_TOKEN is read-only on pull requests from forks, and the "
                "workflow needs `permissions: pull-requests: write`)"
            )
        raise CostDiffError(
            f"GitHub API {method} {url} failed: HTTP {exc.code}{hint}. {detail}"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CostDiffError(f"GitHub API {method} {url} failed: {exc}") from None
    except json.JSONDecodeError as exc:
        raise CostDiffError(f"GitHub API {method} {url} returned invalid JSON: {exc}") from None


def _find_sticky(repo: str, pr: int, token: str) -> int | None:
    """Find our previous comment, walking every page.

    Only checking the first page means that on a busy pull request the sticky
    comment is never found again and a fresh duplicate is posted on every run.
    """
    for page in range(1, _MAX_PAGES + 1):
        url = (
            f"{_API}/repos/{repo}/issues/{pr}/comments"
            f"?per_page={_PER_PAGE}&page={page}"
        )
        batch = _request("GET", url, token)
        if not isinstance(batch, list) or not batch:
            return None
        for comment in batch:
            if isinstance(comment, dict) and MARKER in (comment.get("body") or ""):
                return int(comment["id"])
        if len(batch) < _PER_PAGE:
            return None
    return None


def upsert_comment(repo: str, pr: int, token: str, body: str) -> str:
    """Post a new comment or edit the existing sticky one. Returns its URL."""
    if "/" not in repo:
        raise CostDiffError(f"repository must be in owner/name form, got {repo!r}")
    if len(body) > COMMENT_LIMIT:  # belt and braces; render() already fits it
        body = body[: COMMENT_LIMIT - 40].rstrip() + "\n\n_…comment truncated._\n"
    owner, name = repo.split("/", 1)
    safe_repo = f"{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}"

    existing = _find_sticky(safe_repo, pr, token)
    if existing is None:
        url = f"{_API}/repos/{safe_repo}/issues/{pr}/comments"
        result = _request("POST", url, token, {"body": body})
    else:
        url = f"{_API}/repos/{safe_repo}/issues/comments/{existing}"
        result = _request("PATCH", url, token, {"body": body})
    if not isinstance(result, dict):
        return ""
    return str(result.get("html_url", ""))
