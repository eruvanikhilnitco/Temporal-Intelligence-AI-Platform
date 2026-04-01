"""
Phase 3 - Graph Service
Entity extraction + Neo4j relationship storage and querying.
"""

import logging
import re
from typing import List, Dict, Optional, Tuple

from neo4j import GraphDatabase

from core.database import get_neo4j_connection

logger = logging.getLogger(__name__)


class GraphService:
    """
    Handles entity extraction from text and stores/queries relationships in Neo4j.

    Supports:
      - Contract numbers, dates, companies, amounts, locations
      - create_relation(entity_a, relation, entity_b, source_doc)
      - query_entity(entity_name)
      - extract_and_store(text, source_doc)
    """

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
        r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
        r"\s+\d{4})\b",
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

    def __init__(self):
        self.driver = None
        try:
            neo4j_config = get_neo4j_connection()
            self.driver = GraphDatabase.driver(
                neo4j_config.uri,
                auth=(neo4j_config.user, neo4j_config.password),
            )
            self._ensure_constraints()
            logger.info("GraphService connected to Neo4j")
        except Exception as e:
            logger.warning(f"GraphService: Neo4j unavailable – {e}")

    def close(self):
        if self.driver:
            self.driver.close()

    # ── Schema setup ─────────────────────────────────────────────────────────

    def _ensure_constraints(self):
        """Create uniqueness constraints so nodes aren't duplicated."""
        if not self.driver:
            return
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.name IS UNIQUE",
        ]
        with self.driver.session() as session:
            for cql in constraints:
                try:
                    session.run(cql)
                except Exception as e:
                    logger.debug(f"Constraint (may already exist): {e}")

    # ── Public API ────────────────────────────────────────────────────────────

    def create_relation(
        self,
        entity_a: str,
        relation: str,
        entity_b: str,
        source_doc: str = "unknown",
        entity_a_type: str = "Entity",
        entity_b_type: str = "Entity",
    ) -> bool:
        """
        Merge two entity nodes and create / update a named relationship.

        Example:
            create_relation("Contract 511047", "starts_on", "2019-11-01", "data.xml",
                            entity_a_type="Contract", entity_b_type="Date")
        """
        if not self.driver:
            logger.warning("Neo4j unavailable – relation not stored")
            return False

        rel_type = re.sub(r"[^A-Z0-9_]", "_", relation.upper())

        cypher = f"""
        MERGE (a:Entity {{name: $name_a}})
          ON CREATE SET a.type = $type_a, a.source = $source
        MERGE (b:Entity {{name: $name_b}})
          ON CREATE SET b.type = $type_b, b.source = $source
        MERGE (a)-[r:{rel_type}]->(b)
          ON CREATE SET r.source = $source, r.created_at = timestamp()
        RETURN a.name, type(r), b.name
        """

        try:
            with self.driver.session() as session:
                session.run(
                    cypher,
                    name_a=str(entity_a).strip(),
                    type_a=entity_a_type,
                    name_b=str(entity_b).strip(),
                    type_b=entity_b_type,
                    source=source_doc,
                )
            return True
        except Exception as e:
            logger.error(f"create_relation failed: {e}")
            return False

    def query_entity(self, entity_name: str, max_hops: int = 2) -> List[Dict]:
        """
        Return all relationships connected to `entity_name` within `max_hops`.

        Returns list of dicts:
            {from: str, relation: str, to: str, source: str}
        """
        if not self.driver:
            return []

        cypher = f"""
        MATCH (a:Entity {{name: $name}})-[r*1..{max_hops}]-(b:Entity)
        RETURN a.name AS from_entity,
               [x IN r | type(x)] AS relations,
               b.name AS to_entity,
               [x IN r | x.source][0] AS source
        LIMIT 50
        """

        results = []
        try:
            with self.driver.session() as session:
                records = session.run(cypher, name=entity_name)
                for rec in records:
                    results.append(
                        {
                            "from": rec["from_entity"],
                            "relation": " -> ".join(rec["relations"]),
                            "to": rec["to_entity"],
                            "source": rec["source"] or "unknown",
                        }
                    )
        except Exception as e:
            logger.error(f"query_entity failed: {e}")

        return results

    def search_entities(self, keyword: str) -> List[Dict]:
        """
        Full-text style search: find entities whose name contains `keyword`.
        Returns relationships for each match.
        """
        if not self.driver:
            return []

        cypher = """
        MATCH (a:Entity)
        WHERE toLower(a.name) CONTAINS toLower($kw)
        OPTIONAL MATCH (a)-[r]->(b:Entity)
        RETURN a.name AS from_entity, a.type AS from_type,
               type(r) AS relation, b.name AS to_entity,
               r.source AS source
        LIMIT 30
        """

        results = []
        try:
            with self.driver.session() as session:
                records = session.run(cypher, kw=keyword)
                for rec in records:
                    results.append(
                        {
                            "from": rec["from_entity"],
                            "type": rec["from_type"],
                            "relation": rec["relation"],
                            "to": rec["to_entity"],
                            "source": rec["source"],
                        }
                    )
        except Exception as e:
            logger.error(f"search_entities failed: {e}")

        return results

    # ── Entity extraction ─────────────────────────────────────────────────────

    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extract named entities from raw text using regex patterns.

        Returns:
            {
                "contracts": [...],
                "dates": [...],
                "amounts": [...],
                "organizations": [...],
            }
        """
        contracts = self._extract_all(text, self.CONTRACT_PATTERNS)
        dates = self._extract_all(text, self.DATE_PATTERNS)
        amounts = self._extract_all(text, self.AMOUNT_PATTERNS)
        orgs = self._extract_all(text, self.ORG_PATTERNS)

        # De-duplicate preserving order
        return {
            "contracts": list(dict.fromkeys(contracts)),
            "dates": list(dict.fromkeys(dates)),
            "amounts": list(dict.fromkeys(amounts)),
            "organizations": list(dict.fromkeys(orgs)),
        }

    def extract_and_store(self, text: str, source_doc: str) -> Dict[str, List[str]]:
        """
        Extract all entities from `text` and persist relationships in Neo4j.

        Relationships stored:
          Contract  --[STARTS_ON]-->  Date
          Contract  --[ENDS_ON]-->    Date   (second date if present)
          Contract  --[ISSUED_BY]-->  Org
          Contract  --[HAS_AMOUNT]--> Amount
          Document  --[MENTIONS]-->   Entity  (all entities)

        Returns the extracted entity dict.
        """
        entities = self.extract_entities(text)

        contracts = entities["contracts"]
        dates = entities["dates"]
        amounts = entities["amounts"]
        orgs = entities["organizations"]

        # ── Document node ────────────────────────────────────────────────────
        if self.driver:
            try:
                with self.driver.session() as session:
                    session.run(
                        "MERGE (d:Document {name: $name})",
                        name=source_doc,
                    )
            except Exception as e:
                logger.debug(f"Document node creation: {e}")

        # ── Contract → Date relationships ────────────────────────────────────
        for contract in contracts:
            contract_label = f"Contract {contract}" if not contract.startswith("Contract") else contract

            if dates:
                self.create_relation(
                    contract_label, "starts_on", dates[0], source_doc,
                    entity_a_type="Contract", entity_b_type="Date",
                )
            if len(dates) > 1:
                self.create_relation(
                    contract_label, "ends_on", dates[-1], source_doc,
                    entity_a_type="Contract", entity_b_type="Date",
                )

            # Contract → Org
            for org in orgs:
                self.create_relation(
                    contract_label, "issued_by", org, source_doc,
                    entity_a_type="Contract", entity_b_type="Organization",
                )

            # Contract → Amount
            for amount in amounts:
                self.create_relation(
                    contract_label, "has_amount", f"${amount}", source_doc,
                    entity_a_type="Contract", entity_b_type="Amount",
                )

        # ── Document → all entities (MENTIONS) ───────────────────────────────
        all_entities = (
            [("Contract", c) for c in contracts]
            + [("Date", d) for d in dates]
            + [("Amount", a) for a in amounts]
            + [("Organization", o) for o in orgs]
        )
        for etype, ename in all_entities:
            self.create_relation(
                source_doc, "mentions", ename, source_doc,
                entity_a_type="Document", entity_b_type=etype,
            )

        logger.info(
            f"[GraphService] {source_doc}: {len(contracts)} contracts, "
            f"{len(dates)} dates, {len(amounts)} amounts, {len(orgs)} orgs"
        )

        return entities

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_all(text: str, patterns: List[str]) -> List[str]:
        results = []
        for pattern in patterns:
            try:
                matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
                results.extend([m.strip() for m in matches if m.strip()])
            except re.error as e:
                logger.debug(f"Regex error ({pattern}): {e}")
        return results

    def build_graph_context(self, entities: Dict[str, List[str]]) -> str:
        """
        Given extracted entities, query Neo4j and return a human-readable
        context string suitable for LLM injection.
        """
        if not self.driver:
            return ""

        lines = []
        all_names = (
            [f"Contract {c}" for c in entities.get("contracts", [])]
            + entities.get("organizations", [])
        )

        seen = set()
        for name in all_names:
            if name in seen:
                continue
            seen.add(name)
            relations = self.query_entity(name)
            for rel in relations:
                line = f"{rel['from']} --[{rel['relation']}]--> {rel['to']}"
                if line not in lines:
                    lines.append(line)

        return "\n".join(lines) if lines else ""
