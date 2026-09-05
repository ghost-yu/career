from __future__ import annotations

"""Neo4j-backed GraphStore implementation.

This module is optional. If Neo4j is not available, the app falls back to the
in-memory NetworkX implementation.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class Neo4jGraphStore:
    uri: str
    user: str
    password: str

    def __post_init__(self) -> None:
        # Lazy import so the project still runs without neo4j installed.
        from neo4j import GraphDatabase  # type: ignore

        self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self._init_schema()

    def _init_schema(self) -> None:
        """Create constraints/indexes if not exist."""
        q1 = "CREATE CONSTRAINT job_id_unique IF NOT EXISTS FOR (j:Job) REQUIRE j.job_id IS UNIQUE"
        with self._driver.session() as s:
            s.run(q1)

    def close(self) -> None:
        try:
            self._driver.close()
        except Exception:
            pass

    # --- GraphStore API ---

    def upsert_job_node(self, job_id: str, props: dict[str, Any]) -> None:
        q = """
        MERGE (j:Job {job_id: $job_id})
        SET j += $props
        """
        with self._driver.session() as s:
            s.run(q, job_id=job_id, props=props)

    def upsert_edge(self, src: str, dst: str, rel: str, props: dict[str, Any]) -> None:
        # We store relationship type dynamically using APOC-free pattern by branching.
        # For this competition demo we only use NEXT_LEVEL and SWITCH_TO.
        if rel not in {"NEXT_LEVEL", "SWITCH_TO"}:
            rel = "RELATED"

        q = f"""
        MATCH (a:Job {{job_id: $src}}), (b:Job {{job_id: $dst}})
        MERGE (a)-[r:{rel}]->(b)
        SET r += $props
        """
        with self._driver.session() as s:
            s.run(q, src=src, dst=dst, props=props)

    def get_vertical_path(self, job_id: str, max_hops: int = 5) -> list[dict[str, Any]]:
        """Follow NEXT_LEVEL edges greedily by weight."""
        path: list[dict[str, Any]] = []
        cur = job_id
        visited = set()
        for _ in range(max_hops):
            if cur in visited:
                break
            visited.add(cur)
            node = self._get_job(cur)
            if not node:
                break
            path.append({"job_id": cur, "title": node.get("title"), "job_family": node.get("job_family")})
            nxt = self._get_best_next_level(cur)
            if not nxt:
                break
            cur = nxt
        return path

    def get_switch_paths(self, job_id: str, top_k: int = 5) -> list[list[dict[str, Any]]]:
        q = """
        MATCH (a:Job {job_id:$job_id})-[r:SWITCH_TO]->(b:Job)
        RETURN b.job_id as job_id, b.title as title, r.weight as weight
        ORDER BY weight DESC
        LIMIT $top_k
        """
        src = self._get_job(job_id) or {}
        out: list[list[dict[str, Any]]] = []
        with self._driver.session() as s:
            rows = list(s.run(q, job_id=job_id, top_k=top_k))
        for row in rows:
            out.append(
                [
                    {"job_id": job_id, "title": src.get("title"), "note": "start"},
                    {
                        "job_id": row.get("job_id"),
                        "title": row.get("title"),
                        "note": f"switch (similarity={float(row.get('weight') or 0):.2f})",
                    },
                ]
            )
        return out

    # --- helpers ---

    def _get_job(self, job_id: str) -> dict[str, Any] | None:
        q = "MATCH (j:Job {job_id:$job_id}) RETURN j LIMIT 1"
        with self._driver.session() as s:
            r = s.run(q, job_id=job_id).single()
            if not r:
                return None
            node = r.get("j")
            return dict(node)

    def _get_best_next_level(self, job_id: str) -> str | None:
        q = """
        MATCH (a:Job {job_id:$job_id})-[r:NEXT_LEVEL]->(b:Job)
        RETURN b.job_id as job_id, r.weight as weight
        ORDER BY weight DESC
        LIMIT 1
        """
        with self._driver.session() as s:
            r = s.run(q, job_id=job_id).single()
            if not r:
                return None
            return r.get("job_id")
