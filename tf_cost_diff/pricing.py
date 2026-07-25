"""Static monthly pricing for a small set of common AWS resources.

Prices are deliberately approximate on-demand list prices (us-east-1) and are
only meant to give an order-of-magnitude delta in a pull request. Override the
sheet with a JSON file via ``--price-sheet`` when you need accuracy.

Design rule: an estimator returns ``None`` -- meaning *unknown* -- whenever it
cannot honestly price a resource. It never falls back to a guessed rate and
never falls back to ``0.0``. A wrong number stated confidently in a PR comment
is worse than an admitted gap: an unrecognised ``m5.24xlarge`` priced at a
guessed $0.05/hr reads as $36/mo when the real figure is over $3,000/mo, and it
would sail through a ``--threshold`` gate.
"""
from __future__ import annotations

from typing import Any, Callable

from . import CostDiffError, finite, load_json_document

HOURS_PER_MONTH = 730

# An estimator maps a resource's attribute map to $/month, or None for unknown.
Estimator = Callable[[dict[str, Any]], "float | None"]


def _hourly_by_attribute(attribute: str, table: dict[str, float]) -> Estimator:
    """Price a resource from a lookup table keyed on one attribute.

    Returns None when the attribute is absent, is still unknown at plan time
    (Terraform writes null), or names a size we have no price for.
    """

    def estimate(attrs: dict[str, Any]) -> float | None:
        raw = attrs.get(attribute)
        if raw is None:
            return None
        hourly = table.get(str(raw))
        if hourly is None:
            return None
        return hourly * HOURS_PER_MONTH

    return estimate


def _per_unit(attribute: str, unit_price: float) -> Estimator:
    """Price a resource as ``quantity * unit_price`` (e.g. GB-month)."""

    def estimate(attrs: dict[str, Any]) -> float | None:
        quantity = finite(attrs.get(attribute))
        if quantity is None or quantity < 0:
            return None
        return quantity * unit_price

    return estimate


def _flat(hourly: float) -> Estimator:
    return lambda attrs: hourly * HOURS_PER_MONTH


# Minimal built-in sheet: resource_type -> estimator.
_BUILTIN: dict[str, Estimator] = {
    # EC2 on-demand, a few common sizes.
    "aws_instance": _hourly_by_attribute(
        "instance_type",
        {
            "t3.micro": 0.0104,
            "t3.small": 0.0208,
            "t3.medium": 0.0416,
            "t3.large": 0.0832,
            "m5.large": 0.096,
            "m5.xlarge": 0.192,
            "c5.large": 0.085,
        },
    ),
    # EBS gp3: $0.08 per GB-month.
    "aws_ebs_volume": _per_unit("size", 0.08),
    # Elastic IP: charged whenever allocated, ~$3.6/mo.
    "aws_eip": lambda attrs: 3.6,
    # NAT Gateway hourly component (data processing not modelled).
    "aws_nat_gateway": _flat(0.045),
    # RDS instance (rough, per-class hourly).
    "aws_db_instance": _hourly_by_attribute(
        "instance_class",
        {
            "db.t3.micro": 0.017,
            "db.t3.small": 0.034,
            "db.t3.medium": 0.068,
            "db.m5.large": 0.171,
        },
    ),
    # ALB/NLB hourly base (LCU charges not modelled).
    "aws_lb": _flat(0.0225),
}


class PriceSheet:
    def __init__(self, overrides: dict[str, float] | None = None) -> None:
        # overrides: resource_type -> flat monthly price (wins over builtin).
        self._overrides = overrides or {}

    @classmethod
    def load(cls, path: str | None) -> "PriceSheet":
        if not path:
            return cls()
        data = load_json_document(path, "price sheet")
        if not isinstance(data, dict):
            raise CostDiffError(
                f"price sheet {path} must be a JSON object mapping resource type "
                'to a monthly price, e.g. {"aws_nat_gateway": 32.85}'
            )
        overrides: dict[str, float] = {}
        for key, value in data.items():
            price = finite(value)
            if price is None:
                raise CostDiffError(
                    f"price sheet {path}: price for {key!r} must be a finite "
                    f"number, got {value!r}"
                )
            if price < 0:
                raise CostDiffError(
                    f"price sheet {path}: price for {key!r} is negative ({price})"
                )
            overrides[str(key)] = price
        return cls(overrides=overrides)

    def has_model(self, resource_type: str) -> bool:
        """True when this sheet claims to be able to price the resource type."""
        return resource_type in self._overrides or resource_type in _BUILTIN

    def monthly(self, resource_type: str, values: dict[str, Any]) -> float | None:
        """Monthly cost in dollars, or None when the cost is unknown."""
        if resource_type in self._overrides:
            return self._overrides[resource_type]
        estimator = _BUILTIN.get(resource_type)
        if estimator is None:
            return None
        try:
            result = estimator(values or {})
        except (TypeError, ValueError, AttributeError):
            return None
        return finite(result)
