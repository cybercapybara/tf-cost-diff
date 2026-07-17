"""Create or update a single sticky comment on a pull request."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .report import MARKER

_API = "https://api.github.com"


def _request(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req) as resp:  # noqa: S310 - api.github.com only
        return json.loads(resp.read() or "null")


def _find_sticky(repo: str, pr: int, token: str) -> int | None:
    url = f"{_API}/repos/{repo}/issues/{pr}/comments?per_page=100"
    for comment in _request("GET", url, token) or []:
        if MARKER in (comment.get("body") or ""):
            return int(comment["id"])
    return None


def upsert_comment(repo: str, pr: int, token: str, body: str) -> str:
    """Post a new comment or edit the existing sticky one. Returns its URL."""
    existing = _find_sticky(repo, pr, token)
    if existing is None:
        url = f"{_API}/repos/{repo}/issues/{pr}/comments"
        result = _request("POST", url, token, {"body": body})
    else:
        url = f"{_API}/repos/{repo}/issues/comments/{existing}"
        result = _request("PATCH", url, token, {"body": body})
    return str(result.get("html_url", ""))
