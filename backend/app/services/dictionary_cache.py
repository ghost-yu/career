from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.db import sqlite as db
from app.utils.text import normalize_token


@dataclass
class DictionarySnapshot:
    ts: float
    items: list[dict[str, Any]]
    by_type: dict[str, list[dict[str, Any]]]
    alias_to_item: dict[str, dict[str, Any]]  # normalized alias -> item dict


class DictionaryCache:
    def __init__(self, ttl_seconds: int = 30):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._snapshot: DictionarySnapshot | None = None

    def get_snapshot(self, force: bool = False) -> DictionarySnapshot:
        with self._lock:
            if self._snapshot is None or force or (time.time() - self._snapshot.ts) > self.ttl_seconds:
                items = db.fetch_dictionary_items(limit=5000)
                by_type: dict[str, list[dict[str, Any]]] = {}
                alias_to_item: dict[str, dict[str, Any]] = {}
                by_id: dict[str, dict[str, Any]] = {it["item_id"]: it for it in items if it.get("item_id")}
                for it in items:
                    t = it["item_type"]
                    by_type.setdefault(t, []).append(it)
                    # add name + aliases as alias keys
                    keys = [it["name_zh"]]
                    if it.get("name_en"):
                        keys.append(it["name_en"])
                    keys.extend(it.get("aliases") or [])

                    # If an item is merged/deprecated, map its aliases to merge_to (if provided).
                    target = it
                    if (it.get("status") or "active") != "active":
                        mt = it.get("merge_to")
                        if mt and mt in by_id:
                            target = by_id[mt]
                        else:
                            continue

                    for k in keys:
                        nk = normalize_token(k)
                        if not nk:
                            continue
                        # keep first; if conflicts, you can resolve via admin merge later
                        alias_to_item.setdefault(nk, target)

                self._snapshot = DictionarySnapshot(ts=time.time(), items=items, by_type=by_type, alias_to_item=alias_to_item)
            return self._snapshot

    def lookup_by_alias(self, alias: str) -> dict[str, Any] | None:
        snap = self.get_snapshot()
        return snap.alias_to_item.get(normalize_token(alias))

    def list_by_type(self, item_type: str) -> list[dict[str, Any]]:
        snap = self.get_snapshot()
        return snap.by_type.get(item_type, [])


dictionary_cache = DictionaryCache()
