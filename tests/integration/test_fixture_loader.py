from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "shipyard"
ENTITY_FILES = {
    "ships.json": 2,
    "ship_systems.json": 2,
    "drawings.json": 2,
    "equipment.json": 2,
    "materials.json": 2,
    "bom_items.json": 2,
    "suppliers.json": 2,
    "purchase_orders.json": 4,
    "project_tasks.json": 4,
    "aliases.json": 5,
    "security_scopes.json": 2,
}


def _json(name: str) -> Any:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_checked_in_dataset_has_stable_synthetic_manifest_and_counts() -> None:
    manifest = _json("manifest.json")
    assert manifest == {
        "dataset_id": "synthetic-shipyard-v1",
        "dataset_version": 1,
        "synthetic": True,
        "as_of_date": "2026-08-18",
        "purchase_order_cases": {
            "overdue_ids": ["80000000-0000-0000-0000-000000000071"],
            "non_overdue_ids": [
                "80000000-0000-0000-0000-000000000073",
                "80000000-0000-0000-0000-000000000074",
            ],
            "delivered_ids": ["80000000-0000-0000-0000-000000000072"],
        },
        "security_scope_ships": {
            "ship-alpha-only": "80000000-0000-0000-0000-000000000001",
            "ship-beta-only": "80000000-0000-0000-0000-000000000002",
        },
    }
    assert {name: len(_json(name)) for name in ENTITY_FILES} == ENTITY_FILES
