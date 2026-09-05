from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import networkx as nx

from app.core.config import settings


class GraphStore:
    def upsert_job_node(self, job_id: str, props: dict[str, Any]) -> None:
        raise NotImplementedError

    def upsert_edge(self, src: str, dst: str, rel: str, props: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_vertical_path(self, job_id: str, max_hops: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_switch_paths(self, job_id: str, top_k: int = 5) -> list[list[dict[str, Any]]]:
        raise NotImplementedError


@dataclass
class InMemoryGraphStore(GraphStore):
    g: nx.DiGraph

    def __init__(self):
        self.g = nx.DiGraph()

    def upsert_job_node(self, job_id: str, props: dict[str, Any]) -> None:
        self.g.add_node(job_id, **props)

    def upsert_edge(self, src: str, dst: str, rel: str, props: dict[str, Any]) -> None:
        self.g.add_edge(src, dst, rel=rel, **props)

    def get_vertical_path(self, job_id: str, max_hops: int = 5) -> list[dict[str, Any]]:
        # follow NEXT_LEVEL edges forward
        path = []
        cur = job_id
        visited = set()
        for _ in range(max_hops):
            if cur in visited:
                break
            visited.add(cur)
            node = self.g.nodes.get(cur, {})
            path.append({"job_id": cur, "title": node.get("title"), "job_family": node.get("job_family")})
            # choose best next_level edge (highest weight)
            candidates = []
            for _, dst, data in self.g.out_edges(cur, data=True):
                if data.get("rel") == "NEXT_LEVEL":
                    candidates.append((data.get("weight", 1.0), dst))
            if not candidates:
                break
            candidates.sort(reverse=True)
            cur = candidates[0][1]
        return path

    def get_switch_paths(self, job_id: str, top_k: int = 5) -> list[list[dict[str, Any]]]:
        # return 1-hop paths for demo: job -> similar job
        paths: list[list[dict[str, Any]]] = []
        candidates = []
        for _, dst, data in self.g.out_edges(job_id, data=True):
            if data.get("rel") == "SWITCH_TO":
                candidates.append((data.get("weight", 0.0), dst, data))
        candidates.sort(reverse=True)
        for w, dst, data in candidates[:top_k]:
            src_node = self.g.nodes.get(job_id, {})
            dst_node = self.g.nodes.get(dst, {})
            paths.append([
                {"job_id": job_id, "title": src_node.get("title"), "note": "start"},
                {"job_id": dst, "title": dst_node.get("title"), "note": f"switch (similarity={w:.2f})"},
            ])
        return paths


_memory_store: GraphStore = InMemoryGraphStore()


def get_graph_store() -> GraphStore:
    """Factory: memory (default) or neo4j (optional).

    We keep this in a function so imports don't fail when neo4j driver is not installed.
    """
    if settings.graph_backend == "neo4j":
        try:
            from app.services.graph_store_neo4j import Neo4jGraphStore  # noqa: WPS433

            return Neo4jGraphStore(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
            )
        except Exception:
            # Fallback to memory if neo4j dependency/service isn't available.
            return _memory_store
    return _memory_store


# Public singleton used across the app
graph_store: GraphStore = get_graph_store()
