"""
Phase 3 - Graph Service
Entity extraction + SQLite relationship storage and querying.
No Neo4j required — uses the same SQLite DB as the rest of the app.
"""

import logging
import re
import sqlite3
import uuid
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

# Path to the SQLite DB (same file the app uses)
_DB_PATH = str(Path(__file__).parent.parent / "cortexflow.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _init_graph_tables():
    """Create graph tables if they don't exist."""
    with _conn() as c:
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
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(from_node, relation, to_node)
            );
            CREATE INDEX IF NOT EXISTS idx_graph_edges_from ON graph_edges(from_node);
            CREATE INDEX IF NOT EXISTS idx_graph_edges_to   ON graph_edges(to_node);
        """)


# Initialise tables when the module loads
try:
    _init_graph_tables()
except Exception as _e:
    logger.warning(f"[GraphService] Could not create graph tables: {_e}")


class GraphService:
    """
    Drop-in replacement for the Neo4j GraphService.
    Stores entity relationships in SQLite for zero-dependency operation.
    """

    # Keep driver=None so existing callers that check `gs.driver` still work
    driver = None

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

    # ── Public API ────────────────────────────────────────────────────────────

    def close(self):
        pass  # No persistent connection to close

    def create_relation(
        self,
        entity_a: str,
        relation: str,
        entity_b: str,
        source_doc: str = "unknown",
        entity_a_type: str = "Entity",
        entity_b_type: str = "Entity",
    ) -> bool:
        rel_type = re.sub(r"[^A-Za-z0-9_]", "_", relation.upper())
        try:
            with _conn() as c:
                # Upsert nodes
                c.execute(
                    "INSERT OR IGNORE INTO graph_nodes(id, name, type, source) VALUES(?,?,?,?)",
                    (str(uuid.uuid4()), entity_a.strip(), entity_a_type, source_doc),
                )
                c.execute(
                    "INSERT OR IGNORE INTO graph_nodes(id, name, type, source) VALUES(?,?,?,?)",
                    (str(uuid.uuid4()), entity_b.strip(), entity_b_type, source_doc),
                )
                # Upsert edge
                c.execute(
                    """INSERT OR IGNORE INTO graph_edges(from_node, to_node, relation, source)
                       VALUES(?,?,?,?)""",
                    (entity_a.strip(), entity_b.strip(), rel_type, source_doc),
                )
            return True
        except Exception as e:
            logger.error(f"[GraphService] create_relation failed: {e}")
            return False

    def query_entity(self, entity_name: str, max_hops: int = 2) -> List[Dict]:
        results = []
        try:
            with _conn() as c:
                rows = c.execute(
                    """SELECT from_node, relation, to_node, source
                       FROM graph_edges
                       WHERE from_node = ? OR to_node = ?
                       LIMIT 50""",
                    (entity_name, entity_name),
                ).fetchall()
            for r in rows:
                results.append({
                    "from": r["from_node"],
                    "relation": r["relation"],
                    "to": r["to_node"],
                    "source": r["source"] or "unknown",
                })
        except Exception as e:
            logger.error(f"[GraphService] query_entity failed: {e}")
        return results

    def search_entities(self, keyword: str) -> List[Dict]:
        results = []
        try:
            with _conn() as c:
                rows = c.execute(
                    """SELECT n.name AS from_entity, n.type AS from_type,
                              e.relation, e.to_node AS to_entity, e.source
                       FROM graph_nodes n
                       LEFT JOIN graph_edges e ON e.from_node = n.name
                       WHERE LOWER(n.name) LIKE ?
                       LIMIT 30""",
                    (f"%{keyword.lower()}%",),
                ).fetchall()
            for r in rows:
                results.append({
                    "from": r["from_entity"],
                    "type": r["from_type"],
                    "relation": r["relation"],
                    "to": r["to_entity"],
                    "source": r["source"],
                })
        except Exception as e:
            logger.error(f"[GraphService] search_entities failed: {e}")
        return results

    def get_all_data(self, limit: int = 200) -> Dict:
        """Return all nodes and edges for graph visualisation."""
        try:
            with _conn() as c:
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
            }
        except Exception as e:
            logger.error(f"[GraphService] get_all_data failed: {e}")
            return {"nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0}

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
                self.create_relation(label, "starts_on", dates[0], source_doc,
                                     "Contract", "Date")
            if len(dates) > 1:
                self.create_relation(label, "ends_on", dates[-1], source_doc,
                                     "Contract", "Date")
            for org in orgs:
                self.create_relation(label, "issued_by", org, source_doc,
                                     "Contract", "Organization")
            for amount in amounts:
                self.create_relation(label, "has_amount", f"${amount}", source_doc,
                                     "Contract", "Amount")

        all_entities = (
            [("Contract", c) for c in contracts]
            + [("Date",     d) for d in dates]
            + [("Amount",   a) for a in amounts]
            + [("Organization", o) for o in orgs]
        )
        for etype, ename in all_entities:
            self.create_relation(source_doc, "mentions", ename, source_doc,
                                 "Document", etype)

        logger.info(
            f"[GraphService] {source_doc}: {len(contracts)} contracts, "
            f"{len(dates)} dates, {len(amounts)} amounts, {len(orgs)} orgs"
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
