from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ItemType = Literal["hard_skill", "soft_skill", "certificate"]


class DictionaryItem(BaseModel):
    item_id: str
    item_type: ItemType
    name_zh: str
    name_en: str | None = None
    category_lv1: str | None = None
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    status: str = "active"
    merge_to: str | None = None


class BulkUpsertRequest(BaseModel):
    items: list[DictionaryItem]
