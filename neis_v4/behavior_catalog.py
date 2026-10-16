from __future__ import annotations

import re
from uuid import uuid4

from neis_v4.models import BehaviorTraitDefinition
from neis_v4.storage import Storage


class BehaviorCatalog:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.groups: list[dict] = []
        self.traits: dict[str, BehaviorTraitDefinition] = {}
        self._load()

    def _load(self) -> None:
        raw = self.storage.load_behavior_catalog()
        self.groups = raw.get("groups", [])
        for group in self.groups:
            group_id = str(group["id"])
            for category in group.get("categories", []):
                category_id = str(category["id"])
                for index, label in enumerate(category.get("traits", [])):
                    slug = re.sub(r"[^a-z0-9]+", "_", f"{category_id}_{index}".lower()).strip("_")
                    trait_id = f"{group_id}.{slug}"
                    self.traits[trait_id] = BehaviorTraitDefinition(
                        trait_id=trait_id,
                        label=str(label),
                        group=group_id,
                        category=category_id,
                    )
        for item in self.storage.load_custom_traits():
            definition = BehaviorTraitDefinition(
                trait_id=item["trait_id"],
                label=item["label"],
                group=item["group"],
                category=item["category"],
                custom=True,
            )
            self.traits[definition.trait_id] = definition

    def category_definitions(self, group_id: str) -> list[tuple[str, str]]:
        group = next((item for item in self.groups if item.get("id") == group_id), None)
        if not group:
            return []
        return [(str(item["id"]), str(item["label"])) for item in group.get("categories", [])]

    def traits_for(self, group_id: str, category_id: str) -> list[BehaviorTraitDefinition]:
        return [
            item
            for item in self.traits.values()
            if item.group == group_id and item.category == category_id
        ]

    def get(self, trait_id: str) -> BehaviorTraitDefinition | None:
        return self.traits.get(trait_id)

    def add_custom(self, label: str, group: str, category: str) -> BehaviorTraitDefinition:
        definition = BehaviorTraitDefinition(
            trait_id=f"custom.{uuid4()}",
            label=label.strip(),
            group=group,
            category=category,
            custom=True,
        )
        self.traits[definition.trait_id] = definition
        self._save_custom()
        return definition

    def remove_custom(self, trait_id: str) -> None:
        definition = self.traits.get(trait_id)
        if definition and definition.custom:
            del self.traits[trait_id]
            self._save_custom()

    def _save_custom(self) -> None:
        self.storage.save_custom_traits(
            [
                {
                    "trait_id": item.trait_id,
                    "label": item.label,
                    "group": item.group,
                    "category": item.category,
                }
                for item in self.traits.values()
                if item.custom
            ]
        )
