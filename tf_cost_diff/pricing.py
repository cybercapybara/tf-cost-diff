"""Static monthly pricing for a small set of common AWS resources.

Prices are deliberately approximate on-demand list prices (us-east-1) and are
only meant to give an order-of-magnitude delta in a pull request. Override the
sheet with a JSON file via ``--price-sheet`` when you need accuracy.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

HOURS_PER_MONTH = 730


@dataclass(frozen=True)
class Price:
    """A monthly-cost estimator for one resource type."""

    estimate: Callable[[dict[str, Any]], float]


def _instance(hourly: float) -> Price:
    return Price(lambda attrs: hourly * HOURS_PER_MONTH)


# Minimal built-in sheet: resource_type -> function(values) -> $/month.
_BUILTIN: dict[str, Callable[[dict[str, Any]], float]] = {
    # EC2 on-demand, a few common sizes.
    "aws_instance": lambda a: {
        "t3.micro": 0.0104,
        "t3.small": 0.0208,
        "t3.medium": 0.0416,
        "t3.large": 0.0832,
        "m5.large": 0.096,
        "m5.xlarge": 0.192,
        "c5.large": 0.085,
    }.get(str(a.get("instance_type", "t3.micro")), 0.05)
    * HOURS_PER_MONTH,
    # EBS gp3: $0.08 per GB-month.
    "aws_ebs_volume": lambda a: float(a.get("size", 0) or 0) * 0.08,
    # Elastic IP: charged when allocated, ~$3.6/mo.
    "aws_eip": lambda a: 3.6,
    # NAT Gateway hourly component.
    "aws_nat_gateway": lambda a: 0.045 * HOURS_PER_MONTH,
    # RDS instance (rough, per-class hourly).
    "aws_db_instance": lambda a: {
        "db.t3.micro": 0.017,
        "db.t3.small": 0.034,
        "db.t3.medium": 0.068,
        "db.m5.large": 0.171,
    }.get(str(a.get("instance_class", "db.t3.micro")), 0.05)
    * HOURS_PER_MONTH,
    # ALB/NLB hourly base.
    "aws_lb": lambda a: 0.0225 * HOURS_PER_MONTH,
}


class PriceSheet:
    def __init__(self, overrides: dict[str, float] | None = None) -> None:
        # overrides: resource_type -> flat monthly price (wins over builtin).
        self._overrides = overrides or {}

    @classmethod
    def load(cls, path: str | None) -> "PriceSheet":
        if not path:
            return cls()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return cls(overrides={str(k): float(v) for k, v in data.items()})

    def monthly(self, resource_type: str, values: dict[str, Any]) -> float:
        if resource_type in self._overrides:
            return self._overrides[resource_type]
        fn = _BUILTIN.get(resource_type)
        if fn is None:
            return 0.0
        try:
            return round(float(fn(values or {})), 4)
        except (TypeError, ValueError):
            return 0.0
