from __future__ import annotations

from typing import Any

import networkx as nx

from app.db import sqlite as db
from app.services.career_taxonomy import LEVELS, level_rank, switch_targets
from app.services.dictionary_cache import dictionary_cache
from app.utils.text import normalize_token


class RoleGraph:
    def __init__(self) -> None:
        self.g = nx.DiGraph()

    def clear(self) -> None:
        self.g.clear()

    def _role_skills(self, role_id: str) -> dict[str, str]:
        rid = str(role_id or "").strip()
        if not rid:
            return {}
        try:
            rp = db.get_role_profile(rid)
        except Exception:
            return {}
        out: dict[str, str] = {}
        if rp:
            for item in (rp.get("profile") or {}).get("top_hard_skills") or []:
                sid = str(item.get("skill_id") or "").strip()
                name = str(item.get("name") or item.get("mention") or sid).strip()
                if sid:
                    out[f"sid:{sid}"] = name or sid
                token = normalize_token(name)
                if token:
                    out[f"kw:{token}"] = name or token
        return out

    def rebuild(self, limit_roles: int | None = None) -> dict[str, Any]:
        self.clear()
        roles = db.list_roles(limit=limit_roles or 5000, offset=0)
        family_level_to_id: dict[tuple[str, str], str] = {}
        for r in roles:
            self.g.add_node(
                r["role_id"],
                title=r.get("title_rep"),
                job_family=r.get("job_family"),
                base_role=r.get("base_role"),
                level_label=r.get("level_label"),
                role_key=r.get("role_key"),
            )
            family_level_to_id[(str(r.get("job_family") or "general"), str(r.get("level_label") or "mid"))] = r["role_id"]

        # vertical edges by taxonomy levels
        families = sorted({str(r.get("job_family") or "general") for r in roles})
        for family in families:
            chain = [family_level_to_id.get((family, lvl)) for lvl in LEVELS]
            chain = [rid for rid in chain if rid]
            for a, b in zip(chain, chain[1:]):
                self.g.add_edge(a, b, rel="NEXT_LEVEL", weight=1.0)

        skill_cache: dict[str, dict[str, str]] = {r["role_id"]: self._role_skills(r["role_id"]) for r in roles}
        # switch edges: taxonomy targets + skill overlap
        for r in roles:
            src = r["role_id"]
            src_family = str(r.get("job_family") or "general")
            src_sk = set((skill_cache.get(src) or {}).keys())
            src_level = str(r.get("level_label") or "mid")
            for target_family in switch_targets(src_family):
                dst = family_level_to_id.get((target_family, src_level)) or family_level_to_id.get((target_family, "mid"))
                if not dst or dst == src:
                    continue
                dst_sk = set((skill_cache.get(dst) or {}).keys())
                inter = len(src_sk & dst_sk)
                union = len(src_sk | dst_sk) or 1
                jacc = inter / union
                weight = 0.55 + min(0.35, jacc)
                self.g.add_edge(src, dst, rel="SWITCH_TO", weight=float(weight), rationale="taxonomy+skills")
            # add top skill-sim extras
            sims: list[tuple[float, str]] = []
            for dst in self.g.nodes:
                if dst == src:
                    continue
                if self.g.nodes[dst].get("job_family") == src_family:
                    continue
                dst_sk = set((skill_cache.get(dst) or {}).keys())
                if not src_sk or not dst_sk:
                    continue
                inter = len(src_sk & dst_sk)
                union = len(src_sk | dst_sk) or 1
                jacc = inter / union
                if inter >= 2 and jacc >= 0.18:
                    sims.append((jacc, dst))
            sims.sort(reverse=True)
            for sim, dst in sims[:4]:
                if not self.g.has_edge(src, dst):
                    self.g.add_edge(src, dst, rel="SWITCH_TO", weight=float(sim), rationale="skill_overlap")
        return {"roles": len(self.g.nodes), "edges": len(self.g.edges)}

    def get_vertical_path(self, role_id: str, max_hops: int = 6) -> list[dict[str, Any]]:
        if role_id not in self.g:
            return []
        path = []
        cur = role_id
        seen = set()
        for _ in range(max_hops):
            if cur in seen:
                break
            seen.add(cur)
            n = self.g.nodes[cur]
            path.append({
                "role_id": cur,
                "title": n.get("title"),
                "job_family": n.get("job_family"),
                "base_role": n.get("base_role"),
                "level_label": n.get("level_label"),
                "level_rank": level_rank(str(n.get("level_label") or "mid")),
            })
            cands = [(d.get("weight", 1.0), dst) for _, dst, d in self.g.out_edges(cur, data=True) if d.get("rel") == "NEXT_LEVEL"]
            if not cands:
                break
            cands.sort(reverse=True)
            cur = cands[0][1]
        return path

    def get_switch_paths(self, role_id: str, top_k: int = 5, max_hops: int = 2) -> list[list[dict[str, Any]]]:
        explained = self.get_switch_paths_explained(role_id, top_k=top_k, max_hops=max_hops)
        return [item.get("nodes") or [] for item in explained]

    def get_switch_paths_explained(self, role_id: str, top_k: int = 5, max_hops: int = 2, top_skill_k: int = 8) -> list[dict[str, Any]]:
        if role_id not in self.g:
            return []
        snap = dictionary_cache.get_snapshot(force=False)
        by_id = {it.get("item_id"): (it.get("name_zh") or it.get("name_en") or it.get("item_id")) for it in snap.items}
        skill_cache: dict[str, dict[str, str]] = {}

        def _skills_for(rid: str) -> dict[str, str]:
            if rid not in skill_cache:
                skill_cache[rid] = self._role_skills(rid)
            return skill_cache[rid]

        def skill_names(ids: set[str], role_hints: list[dict[str, str]] | None = None) -> list[str]:
            role_hints = role_hints or []
            role_hint_map: dict[str, str] = {}
            for hint in role_hints:
                role_hint_map.update(hint)
            out: list[str] = []
            seen: set[str] = set()
            for key in sorted(ids):
                name = ""
                if key.startswith("sid:"):
                    sid = key[4:]
                    name = str(by_id.get(sid) or role_hint_map.get(key) or sid)
                elif key.startswith("kw:"):
                    name = str(role_hint_map.get(key) or key[3:])
                else:
                    name = str(by_id.get(key) or role_hint_map.get(key) or key)
                clean = name.strip()
                if not clean:
                    continue
                lowered = clean.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                out.append(clean)
                if len(out) >= top_skill_k:
                    break
            return out
        candidates: list[tuple[float, list[str]]] = []
        one = []
        for _, dst, data in self.g.out_edges(role_id, data=True):
            if data.get("rel") == "SWITCH_TO":
                one.append((float(data.get("weight") or 0.0), dst))
        one.sort(reverse=True)
        for w, dst in one[:max(8, top_k)]:
            candidates.append((w, [role_id, dst]))
        if max_hops >= 2:
            for _, mid in one[:8]:
                w1 = float(self.g.get_edge_data(role_id, mid).get("weight") or 0.0)
                for _, dst, data in self.g.out_edges(mid, data=True):
                    if data.get("rel") != "SWITCH_TO" or dst == role_id:
                        continue
                    w2 = float(data.get("weight") or 0.0)
                    candidates.append((w1 * w2, [role_id, mid, dst]))
        uniq: list[tuple[float, list[str]]] = []
        seen = set()
        for score, path in sorted(candidates, key=lambda x: x[0], reverse=True):
            key = tuple(path)
            if key in seen:
                continue
            seen.add(key)
            uniq.append((score, path))
        out = []
        for score, path in uniq[:top_k]:
            nodes = []
            edges = []
            for rid in path:
                if rid not in self.g:
                    continue
                n = self.g.nodes[rid]
                nodes.append({
                    "role_id": rid,
                    "title": n.get("title"),
                    "job_family": n.get("job_family"),
                    "level_label": n.get("level_label"),
                })
            for a, b in zip(path, path[1:]):
                if not self.g.has_node(a) or not self.g.has_node(b):
                    continue
                sa_map = _skills_for(a)
                sb_map = _skills_for(b)
                sa = set(sa_map.keys())
                sb = set(sb_map.keys())
                shared = sa & sb
                gap = sb - sa
                edges.append({
                    "from": a,
                    "to": b,
                    "rel": "SWITCH_TO",
                    "sim": float((self.g.get_edge_data(a, b) or {}).get("weight") or 0.0),
                    "shared_skills": skill_names(shared, [sa_map, sb_map]),
                    "gap_skills": skill_names(gap, [sb_map]),
                    "reason": (self.g.get_edge_data(a, b) or {}).get("rationale") or "skills",
                })
            out.append({"score": score, "nodes": nodes, "edges": edges})
        return out


role_graph = RoleGraph()
