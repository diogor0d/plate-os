"""Read-only search over versioned official generic-food catalogues."""

from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.llm_contracts import Per100Values

GenericFoodSource = Literal["ciqual", "swedish_food_agency"]
DATA_DIR = Path(__file__).parent.parent / "data"
CATALOG_FILES: dict[GenericFoodSource, str] = {
    "ciqual": "ciqual-2025.json",
    "swedish_food_agency": "swedish-food-agency-2026-07-01.json",
}


class FoodCatalogError(RuntimeError):
    pass


class CatalogFood(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    alternate_name: str | None = Field(default=None, max_length=255)
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float

    @property
    def per100(self) -> Per100Values:
        return Per100Values(
            calories=self.calories,
            protein_g=self.protein_g,
            carbs_g=self.carbs_g,
            fat_g=self.fat_g,
            fiber_g=self.fiber_g,
        )


class FoodCatalog(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: GenericFoodSource
    version: str = Field(min_length=1, max_length=32)
    attribution: str = Field(min_length=1, max_length=255)
    foods: list[CatalogFood]


def _search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in normalized if not unicodedata.combining(char)).split())


@lru_cache(maxsize=2)
def load_catalog(source: GenericFoodSource) -> FoodCatalog:
    path = DATA_DIR / CATALOG_FILES[source]
    try:
        catalog = FoodCatalog.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise FoodCatalogError(f"Invalid {source} food catalogue") from exc
    if catalog.source != source:
        raise FoodCatalogError(f"Invalid {source} food catalogue source")
    return catalog


def search_catalog(source: GenericFoodSource, query: str, limit: int) -> list[CatalogFood]:
    needle = _search_text(query)
    if not needle:
        return []

    matches: list[tuple[int, int, str, CatalogFood]] = []
    for food in load_catalog(source).foods:
        names = [_search_text(food.name)]
        if food.alternate_name:
            names.append(_search_text(food.alternate_name))
        ranks = []
        for name in names:
            if name == needle:
                ranks.append(0)
            elif name.startswith(needle):
                ranks.append(1)
            elif any(word.startswith(needle) for word in name.split()):
                ranks.append(2)
            elif needle in name:
                ranks.append(3)
        if ranks:
            matches.append((min(ranks), min(len(name) for name in names), food.name.casefold(), food))
    matches.sort(key=lambda match: match[:3])
    return [match[3] for match in matches[:limit]]
