"""
Phase 3 - Graph Service
Entity extraction + relationship storage and querying.

Primary backend: Neo4j (bolt://localhost:7687) via the official neo4j Python driver.
Fallback backend: SQLite — used automatically if Neo4j is unreachable.

SOLID:
  - Single Responsibility: each backend class handles one storage technology.
  - Open/Closed: add new backends by subclassing _GraphBackend; never touch existing ones.
  - Liskov:  both backends satisfy the same _GraphBackend interface.
  - Dependency-Inversion: GraphService receives a backend; callers never touch the backend.
"""

import logging
import re
import sqlite3
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Abstract backend interface
# ─────────────────────────────────────────────────────────────────────────────

class _GraphBackend(ABC):
    @abstractmethod
    def create_relation(
        self,
        entity_a: str, relation: str, entity_b: str,
        source_doc: str,
        entity_a_type: str, entity_b_type: str,
    ) -> bool: ...

    @abstractmethod
    def query_entity(self, entity_name: str) -> List[Dict]: ...

    @abstractmethod
    def search_entities(self, keyword: str) -> List[Dict]: ...

    @abstractmethod
    def get_all_data(self, limit: int) -> Dict: ...

    @abstractmethod
    def multi_hop_query(self, entity_name: str, max_hops: int) -> List[Dict]: ...

    @abstractmethod
    def close(self) -> None: ...

    @property
    @abstractmethod
    def backend_name(self) -> str: ...


# ─────────────────────────────────────────────────────────────────────────────
# Neo4j backend
# ─────────────────────────────────────────────────────────────────────────────

class _Neo4jBackend(_GraphBackend):
    """Stores graph data in Neo4j via bolt protocol."""

    def __init__(self, uri: str, user: str, password: str):
        from neo4j import GraphDatabase
        # Short connection timeout so we fall back to SQLite quickly when Neo4j is absent
        self._driver = GraphDatabase.driver(
            uri, auth=(user, password),
            connection_timeout=2.0,   # TCP connect timeout in seconds
            max_connection_lifetime=60,
        )
        # Verify connectivity — raises if unreachable (respects connection_timeout)
        self._driver.verify_connectivity()
        self._ensure_constraints()
        logger.info("[GraphService] Connected to Neo4j at %s", uri)

    def _ensure_constraints(self):
        with self._driver.session() as s:
            s.run(
                "CREATE CONSTRAINT entity_name IF NOT EXISTS "
                "FOR (n:Entity) REQUIRE n.name IS UNIQUE"
            )

    @property
    def backend_name(self) -> str:
        return "neo4j"

    def close(self) -> None:
        try:
            self._driver.close()
        except Exception:
            pass

    def create_relation(
        self,
        entity_a: str, relation: str, entity_b: str,
        source_doc: str,
        entity_a_type: str = "Entity", entity_b_type: str = "Entity",
    ) -> bool:
        rel_type = re.sub(r"[^A-Za-z0-9_]", "_", relation.upper())
        cypher = (
            f"MERGE (a:{entity_a_type} {{name: $a}}) "
            f"MERGE (b:{entity_b_type} {{name: $b}}) "
            f"MERGE (a)-[r:{rel_type} {{source: $src}}]->(b) "
            "RETURN r"
        )
        try:
            with self._driver.session() as s:
                s.run(cypher, a=entity_a.strip(), b=entity_b.strip(), src=source_doc)
            return True
        except Exception as e:
            logger.error("[Neo4j] create_relation failed: %s", e)
            return False

    def query_entity(self, entity_name: str) -> List[Dict]:
        cypher = (
            "MATCH (a)-[r]->(b) "
            "WHERE a.name = $name OR b.name = $name "
            "RETURN a.name AS from_node, type(r) AS relation, b.name AS to_node, "
            "       r.source AS source LIMIT 50"
        )
        try:
            with self._driver.session() as s:
                records = s.run(cypher, name=entity_name).data()
            return [
                {
                    "from": r["from_node"], "relation": r["relation"],
                    "to": r["to_node"], "source": r.get("source") or "unknown",
                }
                for r in records
            ]
        except Exception as e:
            logger.error("[Neo4j] query_entity failed: %s", e)
            return []

    def search_entities(self, keyword: str) -> List[Dict]:
        cypher = (
            "MATCH (n)-[r]->(m) "
            "WHERE toLower(n.name) CONTAINS toLower($kw) "
            "RETURN n.name AS from_entity, labels(n)[0] AS from_type, "
            "       type(r) AS relation, m.name AS to_entity, r.source AS source LIMIT 30"
        )
        try:
            with self._driver.session() as s:
                records = s.run(cypher, kw=keyword).data()
            return [
                {
                    "from": r["from_entity"], "type": r.get("from_type"),
                    "relation": r["relation"], "to": r["to_entity"],
                    "source": r.get("source"),
                }
                for r in records
            ]
        except Exception as e:
            logger.error("[Neo4j] search_entities failed: %s", e)
            return []

    def multi_hop_query(self, entity_name: str, max_hops: int = 2) -> List[Dict]:
        """
        Variable-length Cypher path query — finds all nodes reachable within
        max_hops relationships from entity_name.
        """
        cypher = (
            f"MATCH path = (start)-[*1..{max_hops}]->(end) "
            "WHERE start.name = $name "
            "RETURN "
            "  [n IN nodes(path) | n.name]   AS node_path, "
            "  [r IN relationships(path) | type(r)] AS rel_path, "
            "  end.name AS terminal "
            "LIMIT 30"
        )
        try:
            with self._driver.session() as s:
                records = s.run(cypher, name=entity_name).data()
            results = []
            for r in records:
                results.append({
                    "path": " → ".join(r.get("node_path") or []),
                    "relations": r.get("rel_path", []),
                    "terminal": r.get("terminal", ""),
                    "hops": len(r.get("rel_path", [])),
                })
            return results
        except Exception as e:
            logger.error("[Neo4j] multi_hop_query failed: %s", e)
            return []

    def get_all_data(self, limit: int = 200) -> Dict:
        try:
            with self._driver.session() as s:
                edges = s.run(
                    "MATCH (a)-[r]->(b) "
                    "RETURN a.name AS from_node, type(r) AS relation, "
                    "       b.name AS to_node, r.source AS source "
                    f"LIMIT {limit}"
                ).data()
                nodes_raw = s.run(
                    "MATCH (n) RETURN n.name AS name, labels(n)[0] AS type, "
                    f"n.source AS source LIMIT {limit * 2}"
                ).data()

            nodes = [
                {"id": r["name"], "name": r["name"],
                 "type": r.get("type") or "Entity", "source": r.get("source")}
                for r in nodes_raw
            ]
            edges_out = [
                {"from_node": r["from_node"], "relation": r["relation"],
                 "to_node": r["to_node"], "source": r.get("source")}
                for r in edges
            ]
            return {
                "nodes": nodes, "edges": edges_out,
                "total_nodes": len(nodes), "total_edges": len(edges_out),
                "backend": "neo4j",
            }
        except Exception as e:
            logger.error("[Neo4j] get_all_data failed: %s", e)
            return {"nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0, "backend": "neo4j"}


# ─────────────────────────────────────────────────────────────────────────────
# SQLite backend (zero-dependency fallback)
# ─────────────────────────────────────────────────────────────────────────────

_DB_PATH = str(Path(__file__).parent.parent / "cortexflow.db")


def _sqlite_conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    # WAL mode: concurrent reads don't block writes; essential for multi-worker ingestion
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")  # faster writes, still crash-safe
    c.execute("PRAGMA cache_size=-32000")   # 32 MB page cache
    c.execute("PRAGMA temp_store=MEMORY")
    return c


def _init_sqlite_tables():
    with _sqlite_conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id   TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT DEFAULT 'Entity',
                source TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_nodes_name ON graph_nodes(name);

            CREATE TABLE IF NOT EXISTS graph_edges (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                from_node  TEXT NOT NULL,
                to_node    TEXT NOT NULL,
                relation   TEXT NOT NULL,
                source     TEXT,
                weight     REAL DEFAULT 1.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(from_node, relation, to_node)
            );
            CREATE INDEX IF NOT EXISTS idx_graph_edges_from ON graph_edges(from_node);
            CREATE INDEX IF NOT EXISTS idx_graph_edges_to   ON graph_edges(to_node);
        """)


class _SQLiteBackend(_GraphBackend):
    """Stores graph data in a local SQLite database."""

    def __init__(self):
        _init_sqlite_tables()
        logger.info("[GraphService] Using SQLite backend at %s", _DB_PATH)

    @property
    def backend_name(self) -> str:
        return "sqlite"

    def close(self) -> None:
        pass  # SQLite connections are per-operation

    def create_relation(
        self,
        entity_a: str, relation: str, entity_b: str,
        source_doc: str,
        entity_a_type: str = "Entity", entity_b_type: str = "Entity",
    ) -> bool:
        rel_type = re.sub(r"[^A-Za-z0-9_]", "_", relation.upper())
        try:
            with _sqlite_conn() as c:
                c.execute(
                    "INSERT OR IGNORE INTO graph_nodes(id, name, type, source) VALUES(?,?,?,?)",
                    (str(uuid.uuid4()), entity_a.strip(), entity_a_type, source_doc),
                )
                c.execute(
                    "INSERT OR IGNORE INTO graph_nodes(id, name, type, source) VALUES(?,?,?,?)",
                    (str(uuid.uuid4()), entity_b.strip(), entity_b_type, source_doc),
                )
                c.execute(
                    "INSERT OR IGNORE INTO graph_edges(from_node, to_node, relation, source) "
                    "VALUES(?,?,?,?)",
                    (entity_a.strip(), entity_b.strip(), rel_type, source_doc),
                )
            return True
        except Exception as e:
            logger.error("[SQLite] create_relation failed: %s", e)
            return False

    def query_entity(self, entity_name: str) -> List[Dict]:
        try:
            with _sqlite_conn() as c:
                rows = c.execute(
                    "SELECT from_node, relation, to_node, source FROM graph_edges "
                    "WHERE from_node = ? OR to_node = ? LIMIT 50",
                    (entity_name, entity_name),
                ).fetchall()
            return [
                {"from": r["from_node"], "relation": r["relation"],
                 "to": r["to_node"], "source": r["source"] or "unknown"}
                for r in rows
            ]
        except Exception as e:
            logger.error("[SQLite] query_entity failed: %s", e)
            return []

    def search_entities(self, keyword: str) -> List[Dict]:
        try:
            with _sqlite_conn() as c:
                rows = c.execute(
                    "SELECT n.name AS from_entity, n.type AS from_type, "
                    "       e.relation, e.to_node AS to_entity, e.source "
                    "FROM graph_nodes n "
                    "LEFT JOIN graph_edges e ON e.from_node = n.name "
                    "WHERE LOWER(n.name) LIKE ? LIMIT 30",
                    (f"%{keyword.lower()}%",),
                ).fetchall()
            return [
                {"from": r["from_entity"], "type": r["from_type"],
                 "relation": r["relation"], "to": r["to_entity"],
                 "source": r["source"]}
                for r in rows
            ]
        except Exception as e:
            logger.error("[SQLite] search_entities failed: %s", e)
            return []

    def multi_hop_query(self, entity_name: str, max_hops: int = 2) -> List[Dict]:
        """BFS up to max_hops levels in SQLite graph."""
        visited: set = {entity_name}
        frontier: List[str] = [entity_name]
        results: List[Dict] = []
        for hop in range(1, max_hops + 1):
            next_frontier: List[str] = []
            for node in frontier:
                try:
                    with _sqlite_conn() as c:
                        rows = c.execute(
                            "SELECT from_node, relation, to_node FROM graph_edges "
                            "WHERE from_node = ? OR to_node = ? LIMIT 20",
                            (node, node),
                        ).fetchall()
                    for r in rows:
                        neighbor = r["to_node"] if r["from_node"] == node else r["from_node"]
                        if neighbor not in visited:
                            visited.add(neighbor)
                            next_frontier.append(neighbor)
                            results.append({
                                "path": f"{node} → {neighbor}",
                                "relations": [r["relation"]],
                                "terminal": neighbor,
                                "hops": hop,
                            })
                except Exception as e:
                    logger.error("[SQLite] multi_hop_query hop %d failed: %s", hop, e)
            frontier = next_frontier
            if not frontier:
                break
        return results[:30]

    def get_all_data(self, limit: int = 200) -> Dict:
        try:
            with _sqlite_conn() as c:
                edge_rows = c.execute(
                    "SELECT from_node, relation, to_node, source FROM graph_edges LIMIT ?",
                    (limit,),
                ).fetchall()
                node_rows = c.execute(
                    "SELECT name, type, source FROM graph_nodes LIMIT ?",
                    (limit * 2,),
                ).fetchall()
            nodes = [
                {"id": r["name"], "name": r["name"],
                 "type": r["type"] or "Entity", "source": r["source"]}
                for r in node_rows
            ]
            edges = [
                {"from_node": r["from_node"], "relation": r["relation"],
                 "to_node": r["to_node"], "source": r["source"]}
                for r in edge_rows
            ]
            return {
                "nodes": nodes, "edges": edges,
                "total_nodes": len(nodes), "total_edges": len(edges),
                "backend": "sqlite",
            }
        except Exception as e:
            logger.error("[SQLite] get_all_data failed: %s", e)
            return {"nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0, "backend": "sqlite"}


# ─────────────────────────────────────────────────────────────────────────────
# GraphService — public API, backend-agnostic
# ─────────────────────────────────────────────────────────────────────────────

def _build_backend() -> _GraphBackend:
    """Try Neo4j; fall back to SQLite on any error."""
    try:
        from core.config import get_settings
        s = get_settings()
        return _Neo4jBackend(s.neo4j_uri, s.neo4j_user, s.neo4j_password)
    except Exception as e:
        logger.warning("[GraphService] Neo4j unavailable (%s) — using SQLite fallback", e)
        return _SQLiteBackend()


class GraphService:
    """
    Drop-in graph store.  Uses Neo4j when available, falls back to SQLite.
    All callers use this class — they never touch the backend directly.
    """

    # Keep driver attribute for any callers that check gs.driver
    @property
    def driver(self):
        if isinstance(self._backend, _Neo4jBackend):
            return self._backend._driver
        return None

    def __init__(self, backend: Optional[_GraphBackend] = None):
        self._backend: _GraphBackend = backend or _build_backend()
        logger.info("[GraphService] Active backend: %s", self._backend.backend_name)

    # ── Entity extraction patterns ───────────────────────────────────────────

    CONTRACT_PATTERNS = [
        r"contract\s*(?:no\.?|number|#|num)?\s*[:\-]?\s*([A-Z0-9][\w\-/]{2,30})",
        r"agreement\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9][\w\-/]{2,30})",
        r"\bLC[-\s]?(\d{4,})\b",
    ]
    DATE_PATTERNS = [
        r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})\b",
        r"\b(\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})\b",
        r"\b((?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4})\b",
    ]
    AMOUNT_PATTERNS = [
        r"\$\s*([\d,]+(?:\.\d{2})?)",
        r"([\d,]+(?:\.\d{2})?)\s*(?:USD|EUR|GBP)",
        r"amount\s*[:\-]?\s*\$?([\d,]+(?:\.\d{2})?)",
    ]
    ORG_PATTERNS = [
        r"\b([A-Z][a-zA-Z&\s]{2,40}(?:LLC|Inc|Corp|Ltd|Company|Co\.|LLP|LP|PLC"
        r"|Association|Authority|Commission|Board))\b",
    ]

    # ── Delegation to backend ─────────────────────────────────────────────────

    def close(self) -> None:
        self._backend.close()

    def create_relation(
        self,
        entity_a: str,
        relation: str,
        entity_b: str,
        source_doc: str = "unknown",
        entity_a_type: str = "Entity",
        entity_b_type: str = "Entity",
    ) -> bool:
        return self._backend.create_relation(
            entity_a, relation, entity_b, source_doc, entity_a_type, entity_b_type
        )

    def query_entity(self, entity_name: str, max_hops: int = 2) -> List[Dict]:
        return self._backend.query_entity(entity_name)

    def search_entities(self, keyword: str) -> List[Dict]:
        return self._backend.search_entities(keyword)

    def get_all_data(self, limit: int = 200) -> Dict:
        return self._backend.get_all_data(limit)

    def backend_info(self) -> str:
        return self._backend.backend_name

    # ── Entity extraction ─────────────────────────────────────────────────────

    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        return {
            "contracts":     list(dict.fromkeys(self._extract_all(text, self.CONTRACT_PATTERNS))),
            "dates":         list(dict.fromkeys(self._extract_all(text, self.DATE_PATTERNS))),
            "amounts":       list(dict.fromkeys(self._extract_all(text, self.AMOUNT_PATTERNS))),
            "organizations": list(dict.fromkeys(self._extract_all(text, self.ORG_PATTERNS))),
        }

    def extract_and_store(self, text: str, source_doc: str) -> Dict[str, List[str]]:
        entities = self.extract_entities(text)
        contracts = entities["contracts"]
        dates     = entities["dates"]
        amounts   = entities["amounts"]
        orgs      = entities["organizations"]

        for contract in contracts:
            label = f"Contract {contract}" if not contract.startswith("Contract") else contract
            if dates:
                self.create_relation(label, "starts_on", dates[0], source_doc, "Contract", "Date")
            if len(dates) > 1:
                self.create_relation(label, "ends_on", dates[-1], source_doc, "Contract", "Date")
            for org in orgs:
                self.create_relation(label, "issued_by", org, source_doc, "Contract", "Organization")
            for amount in amounts:
                self.create_relation(label, "has_amount", f"${amount}", source_doc, "Contract", "Amount")

        all_entities = (
            [("Contract", c) for c in contracts]
            + [("Date",     d) for d in dates]
            + [("Amount",   a) for a in amounts]
            + [("Organization", o) for o in orgs]
        )
        for etype, ename in all_entities:
            self.create_relation(source_doc, "mentions", ename, source_doc, "Document", etype)

        logger.info(
            "[GraphService] %s: %d contracts, %d dates, %d amounts, %d orgs",
            source_doc, len(contracts), len(dates), len(amounts), len(orgs),
        )
        return entities

    def build_graph_context(self, entities: Dict[str, List[str]]) -> str:
        lines = []
        all_names = (
            [f"Contract {c}" for c in entities.get("contracts", [])]
            + entities.get("organizations", [])
        )
        seen: set = set()
        for name in all_names:
            if name in seen:
                continue
            seen.add(name)
            for rel in self.query_entity(name):
                line = f"{rel['from']} --[{rel['relation']}]--> {rel['to']}"
                if line not in lines:
                    lines.append(line)
        return "\n".join(lines)

    # ── Cross-document linking ────────────────────────────────────────────────

    def create_cross_document_links(self, source_doc: str, entities: Dict[str, List[str]]) -> int:
        """
        Find other documents sharing the same entities and create
        SHARES_ENTITY_WITH edges between them.
        """
        links_created = 0
        all_entity_names: List[str] = (
            [f"Contract {c}" for c in entities.get("contracts", [])]
            + entities.get("organizations", [])
            + entities.get("dates", [])
        )

        for entity_name in all_entity_names[:20]:
            for rel in self.query_entity(entity_name):
                other_doc = rel.get("source")
                if other_doc and other_doc != source_doc:
                    created = self.create_relation(
                        source_doc, "shares_entity_with", other_doc,
                        source_doc, "Document", "Document",
                    )
                    self.create_relation(
                        source_doc, "co_mentions", entity_name,
                        source_doc, "Document", "Entity",
                    )
                    if created:
                        links_created += 1

        if links_created:
            logger.info("[GraphService] %d cross-doc links created for %s", links_created, source_doc)
        return links_created

    def get_document_neighbors(self, doc_name: str) -> List[Dict]:
        """Return documents that share entities with the given document."""
        results = []
        for rel in self.query_entity(doc_name):
            if rel["relation"] in ("SHARES_ENTITY_WITH", "shares_entity_with"):
                other = rel["to"] if rel["from"] == doc_name else rel["from"]
                results.append({"document": other, "relation": rel["relation"], "source": rel["source"]})
        return results

    def multi_hop_query(self, entity_name: str, max_hops: int = 2) -> List[Dict]:
        """
        Traverse the graph up to `max_hops` away from `entity_name`.
        Neo4j: runs Cypher variable-length path query.
        SQLite: performs iterative BFS up to max_hops depth.
        Returns flat list of {path, relations, source} dicts.
        """
        return self._backend.multi_hop_query(entity_name, max_hops)

    def prune_graph(self, min_weight: float = 0.2, max_hops: int = 2) -> Dict:
        """
        Remove low-confidence edges and orphan nodes to keep the graph lean.
        - Deletes edges with weight < min_weight (defaults to 0.2)
        - Deletes nodes with no remaining edges (orphans)
        - Returns counts of pruned rows for admin visibility.
        Works for SQLite backend only; no-op for Neo4j (use Cypher pruning there).
        """
        if not isinstance(self._backend, _SQLiteBackend):
            return {"pruned_edges": 0, "pruned_nodes": 0, "backend": self._backend.backend_name}
        pruned_edges = 0
        pruned_nodes = 0
        try:
            with _sqlite_conn() as c:
                cur = c.execute(
                    "DELETE FROM graph_edges WHERE weight < ?", (min_weight,)
                )
                pruned_edges = cur.rowcount
                # Remove orphan nodes — nodes that no longer appear in any edge
                cur2 = c.execute(
                    "DELETE FROM graph_nodes WHERE name NOT IN ("
                    "  SELECT from_node FROM graph_edges"
                    "  UNION"
                    "  SELECT to_node   FROM graph_edges"
                    ")"
                )
                pruned_nodes = cur2.rowcount
            logger.info(
                "[GraphService] Pruned %d edges, %d orphan nodes", pruned_edges, pruned_nodes
            )
        except Exception as e:
            logger.error("[GraphService] prune_graph failed: %s", e)
        return {"pruned_edges": pruned_edges, "pruned_nodes": pruned_nodes, "backend": "sqlite"}

    def vacuum(self) -> bool:
        """Run VACUUM + ANALYZE to reclaim space and update query planner statistics."""
        if not isinstance(self._backend, _SQLiteBackend):
            return False
        try:
            with _sqlite_conn() as c:
                c.execute("ANALYZE")
                c.execute("VACUUM")
            logger.info("[GraphService] VACUUM + ANALYZE complete")
            return True
        except Exception as e:
            logger.error("[GraphService] vacuum failed: %s", e)
            return False

    def store_document_metadata(self, doc_name: str, metadata: Dict) -> bool:
        """Store extracted metadata as graph nodes connected to the document node."""
        try:
            domain = metadata.get("domain", "general")
            doc_type = metadata.get("doc_type", "document")
            sensitivity = metadata.get("sensitivity", "low")
            self.create_relation(doc_name, "has_domain", domain, doc_name, "Document", "Domain")
            self.create_relation(doc_name, "has_type", doc_type, doc_name, "Document", "DocType")
            self.create_relation(doc_name, "has_sensitivity", sensitivity, doc_name, "Document", "Sensitivity")
            return True
        except Exception as e:
            logger.error("[GraphService] store_document_metadata failed: %s", e)
            return False

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_all(text: str, patterns: List[str]) -> List[str]:
        results = []
        for pattern in patterns:
            try:
                matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
                results.extend([m.strip() for m in matches if m.strip()])
            except re.error:
                pass
        return results
