"""Parse ``terraform show -json <plan>`` output into cost-relevant changes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import CostDiffError, load_json_document
from .pricing import PriceSheet

# Terraform resource_changes[].change.actions values we care about.
_CREATE = "create"
_DELETE = "delete"
_UPDATE = "update"

# Money is rounded to whole cents everywhere, so the rows in the rendered table
# always add up to the headline total.
_CENTS = 2


@dataclass
class ResourceDelta:
    address: str
    resource_type: str
    action: str  # create | update | delete
    before_monthly: float
    after_monthly: float

    @property
    def delta(self) -> float:
        return round(self.after_monthly - self.before_monthly, _CENTS)


@dataclass
class UnpricedResource:
    """A resource of a modelled type whose cost we could not work out.

    Reported explicitly rather than counted as $0, so the reader can see that
    the headline total is incomplete.
    """

    address: str
    resource_type: str
    action: str
    reason: str


@dataclass
class PlanSummary:
    resources: list[ResourceDelta]
    unpriced: list[UnpricedResource] = field(default_factory=list)

    @property
    def total_delta(self) -> float:
        return round(sum(r.delta for r in self.resources), _CENTS)

    def _count(self, action: str) -> int:
        return sum(1 for r in self.resources if r.action == action) + sum(
            1 for r in self.unpriced if r.action == action
        )

    @property
    def created(self) -> int:
        return self._count(_CREATE)

    @property
    def updated(self) -> int:
        return self._count(_UPDATE)

    @property
    def destroyed(self) -> int:
        return self._count(_DELETE)

    @property
    def is_complete(self) -> bool:
        """True when every cost-relevant resource could be priced."""
        return not self.unpriced


def _classify(actions: list[str]) -> str | None:
    if actions == ["create"]:
        return _CREATE
    if actions == ["delete"]:
        return _DELETE
    if "create" in actions and "delete" in actions:
        return _UPDATE  # replace
    if actions == ["update"]:
        return _UPDATE
    return None


def validate_plan_document(doc: Any, source: str) -> dict[str, Any]:
    """Reject anything that is not Terraform plan JSON.

    Without this, *any* valid JSON parses to "no changes" and the Action posts a
    reassuring "$0.00/mo" comment. The two realistic ways to get there are
    passing ``terraform show -json`` of **state** instead of of a **plan file**,
    and a truncated or empty artifact download.
    """
    if not isinstance(doc, dict):
        raise CostDiffError(
            f"{source} is not a Terraform plan: expected a JSON object at the top "
            f"level, got {type(doc).__name__}."
        )
    if "resource_changes" in doc or "planned_values" in doc:
        changes = doc.get("resource_changes", [])
        if not isinstance(changes, list):
            raise CostDiffError(
                f"{source}: 'resource_changes' must be a list, got "
                f"{type(changes).__name__}."
            )
        return doc
    if "values" in doc and "planned_values" not in doc:
        raise CostDiffError(
            f"{source} looks like `terraform show -json` output for **state**, not "
            "for a plan: it has 'values' but no 'resource_changes'. Run "
            "`terraform plan -out tf.plan && terraform show -json tf.plan > plan.json`."
        )
    raise CostDiffError(
        f"{source} is not a Terraform plan: no 'resource_changes' or "
        "'planned_values' key. Check that the file is the full output of "
        "`terraform show -json <planfile>` and was not truncated."
    )


def parse_plan(plan_json: dict[str, Any], sheet: PriceSheet) -> PlanSummary:
    deltas: list[ResourceDelta] = []
    unpriced: list[UnpricedResource] = []

    for index, rc in enumerate(plan_json.get("resource_changes") or []):
        if not isinstance(rc, dict):
            raise CostDiffError(
                f"resource_changes[{index}] must be an object, got "
                f"{type(rc).__name__}."
            )
        change = rc.get("change")
        if not isinstance(change, dict):
            raise CostDiffError(
                f"resource_changes[{index}] has no usable 'change' object."
            )
        action = _classify(list(change.get("actions") or []))
        if action is None:
            continue

        rtype = str(rc.get("type", ""))
        address = str(rc.get("address") or rtype or f"resource_changes[{index}]")

        # Resource types we do not model at all (IAM roles, security groups,
        # and most usage-billed services) are excluded from the estimate; the
        # rendered report carries a standing caveat saying so.
        if not sheet.has_model(rtype):
            continue

        before = change.get("before") if isinstance(change.get("before"), dict) else {}
        after = change.get("after") if isinstance(change.get("after"), dict) else {}
        before_cost = 0.0 if action == _CREATE else sheet.monthly(rtype, before)
        after_cost = 0.0 if action == _DELETE else sheet.monthly(rtype, after)

        # A modelled type whose attributes we could not read: unknown, not zero.
        if before_cost is None or after_cost is None:
            side = "before" if before_cost is None else "after"
            unpriced.append(
                UnpricedResource(
                    address=address,
                    resource_type=rtype,
                    action=action,
                    reason=(
                        f"no price for the *{side}* configuration: an unmodelled "
                        "size/class, or a value not known until apply"
                    ),
                )
            )
            continue

        before_cost = round(before_cost, _CENTS)
        after_cost = round(after_cost, _CENTS)
        # Skip resources that carry no modelled cost on either side.
        if before_cost == 0.0 and after_cost == 0.0:
            continue
        deltas.append(
            ResourceDelta(
                address=address,
                resource_type=rtype,
                action=action,
                before_monthly=before_cost,
                after_monthly=after_cost,
            )
        )

    deltas.sort(key=lambda d: (-abs(d.delta), d.address))
    unpriced.sort(key=lambda u: u.address)
    return PlanSummary(resources=deltas, unpriced=unpriced)


def load_plan(path: str) -> dict[str, Any]:
    """Load and validate ``terraform show -json`` plan output."""
    return validate_plan_document(load_json_document(path, "plan file"), path)
