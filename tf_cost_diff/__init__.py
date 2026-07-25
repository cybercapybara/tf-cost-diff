"""tf-cost-diff: estimate the monthly cost delta of a Terraform plan."""
from __future__ import annotations

import json
import math
from typing import Any

__version__ = "0.2.0"

__all__ = ["CostDiffError", "load_json_document", "finite", "__version__"]


class CostDiffError(Exception):
    """A user-facing error: bad input, unusable price sheet, failed API call.

    Raised instead of letting a raw traceback escape, so the Action shows an
    actionable message rather than a stack trace.
    """


def _reject_constant(token: str) -> float:
    # json.load() accepts NaN/Infinity/-Infinity by default. A NaN price makes
    # every comparison False, so the --threshold gate would silently pass while
    # the comment rendered "$nan". Refuse the document instead.
    raise CostDiffError(
        f"refusing {token!r}: cost inputs must be finite numbers, "
        "but this JSON contains a non-finite constant."
    )


def load_json_document(path: str, what: str) -> Any:
    """Load a JSON file, rejecting non-finite numbers and unreadable files."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh, parse_constant=_reject_constant)
    except FileNotFoundError:
        raise CostDiffError(f"{what} not found: {path}") from None
    except IsADirectoryError:
        raise CostDiffError(f"{what} is a directory, not a file: {path}") from None
    except UnicodeDecodeError:
        raise CostDiffError(
            f"{what} {path} is not UTF-8 text. Did you pass the binary plan file "
            "instead of `terraform show -json tf.plan > plan.json` output?"
        ) from None
    except json.JSONDecodeError as exc:
        raise CostDiffError(
            f"{what} {path} is not valid JSON ({exc}). A truncated download or an "
            "empty file will look like this."
        ) from None
    except OSError as exc:
        raise CostDiffError(f"could not read {what} {path}: {exc}") from None


def finite(value: Any) -> float | None:
    """Coerce to a finite float, or return None when that is not possible."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
