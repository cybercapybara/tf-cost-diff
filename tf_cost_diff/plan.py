"""Parse ``terraform show -json <plan>`` output into cost-relevant changes."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .pricing import PriceSheet

# Terraform resource_changes[].change.actions values we care about.
_CREATE = "create"
_DELETE = "delete"
_UPDATE = "update"


@dataclass
class ResourceDelta:
    address: str
    resource_type: str
    action: str  # create | update | delete
    before_monthly: float
    after_monthly: float

    @property
    def delta(self) -> float:
        return round(self.after_monthly - self.before_monthly, 4)


@dataclass
class PlanSummary:
    resources: list[ResourceDelta]

    @property
    def total_delta(self) -> float:
        return round(sum(r.delta for r in self.resources), 2)

    @property
    def created(self) -> int:
        return sum(1 for r in self.resources if r.action == _CREATE)

    @property
    def updated(self) -> int:
        return sum(1 for r in self.resources if r.action == _UPDATE)

    @property
    def destroyed(self) -> int:
        return sum(1 for r in self.resources if r.action == _DELETE)


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


def parse_plan(plan_json: dict[str, Any], sheet: PriceSheet) -> PlanSummary:
    deltas: list[ResourceDelta] = []
    for rc in plan_json.get("resource_changes", []):
        change = rc.get("change", {})
        action = _classify(list(change.get("actions", [])))
        if action is None:
            continue
        rtype = rc.get("type", "")
        before = change.get("before") or {}
        after = change.get("after") or {}
        before_cost = sheet.monthly(rtype, before) if action != _CREATE else 0.0
        after_cost = sheet.monthly(rtype, after) if action != _DELETE else 0.0
        # Skip resources that carry no modelled cost on either side.
        if before_cost == 0.0 and after_cost == 0.0:
            continue
        deltas.append(
            ResourceDelta(
                address=rc.get("address", rtype),
                resource_type=rtype,
                action=action,
                before_monthly=round(before_cost, 4),
                after_monthly=round(after_cost, 4),
            )
        )
    deltas.sort(key=lambda d: abs(d.delta), reverse=True)
    return PlanSummary(resources=deltas)


def load_plan(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
