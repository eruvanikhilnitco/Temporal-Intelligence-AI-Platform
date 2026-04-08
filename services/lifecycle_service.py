import logging
from datetime import datetime
from typing import List, Optional

from dateutil.parser import parse as parse_date

from core.config import get_settings
from core.database import get_neo4j_connection, get_neo4j_driver
from models.lifecycle import LifecycleEvent, LifecycleResponse

logger = logging.getLogger(__name__)


class LifecycleService:
    TERMINAL_EVENT_KEYWORDS = (
        "COMPLETE",
        "COMPLETED",
        "CLOSED",
        "DEAL_CLOSED",
        "ONBOARDING_COMPLETE",
        "PAID",
        "SIGNED",
        "ACCEPTED",
        "FULFILLED",
        "FINALIZED",
        "FINALISED",
        "RESOLVED",
    )

    TERMINAL_STATUS_KEYWORDS = {
        "completed",
        "complete",
        "closed",
        "paid",
        "signed",
        "accepted",
        "fulfilled",
        "finalized",
        "finalised",
        "done",
        "resolved",
    }
    CLOSED_STATUSES = {
        "completed",
        "closed",
        "cancelled",
        "canceled",
        "resolved",
        "archived",
        "done",
    }

    def __init__(self):
        try:
            self.driver = get_neo4j_driver()
            logger.info("Connected to Neo4j")
        except Exception as e:
            logger.warning(f"Neo4j unavailable, lifecycle service degraded: {e}")
            self.driver = None

    def close(self):
        """Close Neo4j driver connection."""
        if self.driver:
            self.driver.close()

    def get_lifecycle(self, lifecycle_id: str) -> LifecycleResponse:
        """Get lifecycle with events from Neo4j."""
        if not self.driver:
            logger.warning("Neo4j not available, returning empty lifecycle")
            return LifecycleResponse(
                lifecycle_id=lifecycle_id,
                status="unknown",
                events=[],
                lifecycle_type=None,
                domain=None
            )

        with self.driver.session() as session:
            # Get lifecycle node and events
            # Convert Neo4j DateTime to ISO string in the query
            result = session.run("""
                MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})
                OPTIONAL MATCH (l)-[:HAS_EVENT]->(e:Event)
                WITH l, e
                ORDER BY e.timestamp ASC
                RETURN l.status as status,
                       l.lifecycle_type as lifecycle_type,
                       l.domain as domain,
                       collect({
                           event_id: e.event_id,
                           event_type: e.event_type,
                           timestamp: CASE 
                               WHEN e.timestamp IS NOT NULL 
                               THEN toString(e.timestamp)
                               ELSE null
                           END,
                           summary: e.summary
                       }) as events
            """, lifecycle_id=lifecycle_id)

            record = result.single()
            if not record:
                # Lifecycle doesn't exist, return empty
                return LifecycleResponse(
                    lifecycle_id=lifecycle_id,
                    status="not_found",
                    events=[],
                    lifecycle_type=None,
                    domain=None
                )

            status = record["status"] or "unknown"
            lifecycle_type = record.get("lifecycle_type")
            domain = record.get("domain")
            events_data = record["events"] or []
            
            events = []
            for evt in events_data:
                if not evt.get("event_id"):
                    continue
                
                # Convert timestamp string to Python datetime
                timestamp = evt.get("timestamp")
                if timestamp:
                    try:
                        if isinstance(timestamp, str):
                            # Robust parsing for Neo4j timestamps with nanos and optional timezone.
                            timestamp = parse_date(timestamp)
                        elif isinstance(timestamp, datetime):
                            # Already a datetime object
                            pass
                        else:
                            # Try to convert Neo4j DateTime object
                            if hasattr(timestamp, 'to_native'):
                                timestamp = timestamp.to_native()
                            else:
                                timestamp = datetime.utcnow()
                    except Exception as e:
                        logger.warning(f"Failed to convert timestamp {timestamp}: {e}")
                        timestamp = datetime.utcnow()
                else:
                    timestamp = datetime.utcnow()
                
                events.append(
                    LifecycleEvent(
                        event_id=evt.get("event_id", ""),
                        event_type=evt.get("event_type", ""),
                        timestamp=timestamp,
                        summary=evt.get("summary", "")
                    )
                )

            return LifecycleResponse(
                lifecycle_id=lifecycle_id,
                status=status,
                events=events,
                lifecycle_type=lifecycle_type,
                domain=domain
            )

    def create_lifecycle(
        self, 
        lifecycle_id: str, 
        status: str = "active",
        lifecycle_type: Optional[str] = None,
        domain: Optional[str] = None
    ) -> bool:
        """Create a new lifecycle node in Neo4j."""
        if not self.driver:
            return False

        try:
            with self.driver.session() as session:
                session.run("""
                    MERGE (l:Lifecycle {lifecycle_id: $lifecycle_id})
                    ON CREATE SET l.status = $status,
                                  l.created_at = datetime()
                    SET l.status = COALESCE(l.status, $status),
                        l.lifecycle_type = COALESCE($lifecycle_type, l.lifecycle_type),
                        l.domain = COALESCE($domain, l.domain),
                        l.updated_at = datetime()
                """, 
                    lifecycle_id=lifecycle_id, 
                    status=status,
                    lifecycle_type=lifecycle_type,
                    domain=domain
                )
            return True
        except Exception as e:
            logger.error(f"Failed to create lifecycle: {e}")
            return False

    def add_event(
        self,
        lifecycle_id: str,
        event_type: str,
        summary: str,
        timestamp: Optional[datetime] = None,
        document_status: Optional[str] = None,
    ) -> Optional[str]:
        """Add an event to a lifecycle."""
        if not self.driver:
            return None

        if timestamp is None:
            timestamp = datetime.utcnow()

        event_id = f"evt-{timestamp.strftime('%Y%m%d%H%M%S')}-{hash(lifecycle_id) % 10000}"

        try:
            with self.driver.session() as session:
                # Ensure lifecycle exists
                session.run("""
                    MERGE (l:Lifecycle {lifecycle_id: $lifecycle_id})
                """, lifecycle_id=lifecycle_id)

                # Create event and link to lifecycle
                session.run("""
                    MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})
                    CREATE (e:Event {
                        event_id: $event_id,
                        event_type: $event_type,
                        summary: $summary,
                        timestamp: $timestamp
                    })
                    CREATE (l)-[:HAS_EVENT]->(e)
                """, 
                    lifecycle_id=lifecycle_id,
                    event_id=event_id,
                    event_type=event_type,
                    summary=summary,
                    timestamp=timestamp
                )
            # Reopen completed/closed lifecycle when a new non-terminal document/event is added.
            self.auto_reopen_lifecycle(
                lifecycle_id=lifecycle_id,
                event_type=event_type,
                summary=summary,
                document_status=document_status,
            )

            # Auto-complete lifecycle when terminal event signals are detected.
            self.auto_complete_lifecycle(
                lifecycle_id=lifecycle_id,
                event_type=event_type,
                summary=summary,
                document_status=document_status,
            )
            return event_id
        except Exception as e:
            logger.error(f"Failed to add event: {e}")
            return None

    def update_lifecycle_status(self, lifecycle_id: str, status: str) -> bool:
        """Update lifecycle status explicitly."""
        if not self.driver:
            return False

        try:
            with self.driver.session() as session:
                session.run(
                    """
                    MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})
                    SET l.status = $status,
                        l.updated_at = datetime(),
                        l.completed_at = CASE
                            WHEN $status = 'completed' THEN datetime()
                            ELSE l.completed_at
                        END
                    """,
                    lifecycle_id=lifecycle_id,
                    status=status,
                )
            return True
        except Exception as e:
            logger.error(f"Failed to update lifecycle status for {lifecycle_id}: {e}")
            return False

    def _is_terminal_signal(
        self,
        event_type: str = "",
        summary: str = "",
        document_status: Optional[str] = None,
    ) -> bool:
        event_upper = (event_type or "").upper()
        summary_lower = (summary or "").lower()
        status_lower = (document_status or "").strip().lower()

        terminal_from_event = any(k in event_upper for k in self.TERMINAL_EVENT_KEYWORDS)
        terminal_summary_terms = (
            "completed",
            "closed",
            "deal closed",
            "paid",
            "signed",
            "accepted",
            "fulfilled",
            "finalized",
            "finalised",
            "resolved",
            "cancelled",
            "canceled",
            "archived",
            "done",
        )
        terminal_from_summary = any(term in summary_lower for term in terminal_summary_terms)
        terminal_from_status = status_lower in self.TERMINAL_STATUS_KEYWORDS
        return terminal_from_event or terminal_from_summary or terminal_from_status

    def _is_reopen_signal(
        self,
        event_type: str = "",
        summary: str = "",
        document_status: Optional[str] = None,
    ) -> bool:
        # Reopen on new document/event activity only when it is not terminal.
        if self._is_terminal_signal(event_type, summary, document_status):
            return False
        event_upper = (event_type or "").upper()
        return (
            "_UPLOADED" in event_upper
            or "_CREATED" in event_upper
            or "_ADDED" in event_upper
            or "DOCUMENT" in event_upper
        )

    def auto_reopen_lifecycle(
        self,
        lifecycle_id: str,
        event_type: str = "",
        summary: str = "",
        document_status: Optional[str] = None,
    ) -> bool:
        """
        Reopen a lifecycle if new non-terminal activity arrives after closure.
        Enterprise-safe behavior:
        - only transitions from closed/completed-like states to active
        - never reopens on terminal signals
        - records audit fields (updated_at, reopened_at, reopen_count)
        """
        if not self.driver:
            return False
        if not self._is_reopen_signal(event_type, summary, document_status):
            return False

        try:
            with self.driver.session() as session:
                result = session.run(
                    """
                    MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})
                    WITH l, toLower(COALESCE(l.status, '')) as current_status
                    WHERE current_status IN $closed_statuses
                    SET l.status = 'active',
                        l.updated_at = datetime(),
                        l.reopened_at = datetime(),
                        l.reopen_count = COALESCE(l.reopen_count, 0) + 1
                    RETURN count(l) as reopened
                    """,
                    lifecycle_id=lifecycle_id,
                    closed_statuses=list(self.CLOSED_STATUSES),
                )
                record = result.single()
                reopened = int(record["reopened"]) if record and record.get("reopened") is not None else 0
                if reopened > 0:
                    logger.info(
                        f"Lifecycle {lifecycle_id} auto-reopened due to new activity "
                        f"(event_type={event_type}, document_status={document_status})"
                    )
                    return True
            return False
        except Exception as e:
            logger.error(f"Failed to auto-reopen lifecycle {lifecycle_id}: {e}")
            return False

    def auto_complete_lifecycle(
        self,
        lifecycle_id: str,
        event_type: str = "",
        summary: str = "",
        document_status: Optional[str] = None,
    ) -> bool:
        """
        Auto-mark lifecycle as completed based on terminal signals.
        Generic across industries: event types, summaries, and document status hints.
        """
        if not self.driver:
            return False

        if not self._is_terminal_signal(event_type, summary, document_status):
            return False

        try:
            with self.driver.session() as session:
                record = session.run(
                    """
                    MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})
                    RETURN l.status as status
                    """,
                    lifecycle_id=lifecycle_id,
                ).single()

                current_status = (record["status"] if record else None) or ""
                if str(current_status).strip().lower() == "completed":
                    return False

                session.run(
                    """
                    MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})
                    SET l.status = 'completed',
                        l.updated_at = datetime(),
                        l.completed_at = datetime()
                    """,
                    lifecycle_id=lifecycle_id,
                )

            logger.info(
                f"Lifecycle {lifecycle_id} auto-marked as completed "
                f"(event_type={event_type}, document_status={document_status})"
            )
            
            # Extract and create outcomes when lifecycle is completed
            try:
                from services.outcome_extractor import OutcomeExtractor
                extractor = OutcomeExtractor()
                created_count = extractor.create_outcomes_for_lifecycle(lifecycle_id)
                if created_count > 0:
                    logger.info(
                        f"Auto-created {created_count} outcome(s) for completed lifecycle {lifecycle_id}"
                    )
            except Exception as e:
                logger.warning(f"Failed to auto-extract outcomes for lifecycle {lifecycle_id}: {e}")
            
            return True
        except Exception as e:
            logger.error(f"Failed to auto-complete lifecycle {lifecycle_id}: {e}")
            return False

    def link_document(
        self,
        lifecycle_id: str,
        document_id: str,
        document_type: str,
        filename: Optional[str] = None,
        relationship: str = "HAS_DOCUMENT"
    ) -> bool:
        """Link a document to a lifecycle."""
        if not self.driver:
            return False

        try:
            with self.driver.session() as session:
                session.run("""
                    MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})
                    MERGE (d:Document {document_id: $document_id})
                    SET d.document_type = $document_type
                    SET d.filename = COALESCE($filename, d.filename)
                    MERGE (l)-[r:%s]->(d)
                """ % relationship,
                    lifecycle_id=lifecycle_id,
                    document_id=document_id,
                    document_type=document_type,
                    filename=filename
                )
            return True
        except Exception as e:
            logger.error(f"Failed to link document: {e}")
            return False

    def list_lifecycles(self, limit: int = 10) -> List[LifecycleResponse]:
        """List existing lifecycles."""
        if not self.driver:
            logger.warning("Neo4j driver not available for list_lifecycles")
            return []
        try:
            with self.driver.session() as session:
                # Order by created_at if it exists, otherwise by lifecycle_id
                result = session.run("""
                    MATCH (l:Lifecycle)
                    RETURN l.lifecycle_id as lifecycle_id, 
                           l.status as status,
                           l.lifecycle_type as lifecycle_type, 
                           l.domain as domain,
                           l.created_at as created_at
                    ORDER BY COALESCE(l.created_at, datetime()) DESC, l.lifecycle_id ASC
                    LIMIT $limit
                """, limit=limit)
                lifecycles = []
                for record in result:
                    lifecycle_id = record["lifecycle_id"]
                    if not lifecycle_id:
                        continue
                    
                    # Create a minimal LifecycleResponse
                    lifecycle = LifecycleResponse(
                        lifecycle_id=lifecycle_id,
                        status=record["status"] or "unknown",
                        events=[],  # Don't load events for list view
                        lifecycle_type=record.get("lifecycle_type"),
                        domain=record.get("domain")
                    )
                    lifecycles.append(lifecycle)
                
                logger.info(f"Found {len(lifecycles)} lifecycles")
                return lifecycles
        except Exception as e:
            logger.error(f"Failed to list lifecycles: {e}", exc_info=True)
            return []

    def get_graph_data(self, lifecycle_id: str) -> dict:
        """Get graph data (nodes and links) for visualization.
        
        Only returns nodes and relationships that are directly connected to the specified lifecycle.
        This ensures events and documents from other lifecycles are not included.
        """
        if not self.driver:
            return {"nodes": [], "links": []}

        try:
            with self.driver.session() as session:
                # SIMPLIFIED QUERY: Only get nodes and relationships directly connected to this lifecycle
                # This ensures NO cross-lifecycle contamination
                # Use elementId() for proper node comparison in Neo4j 5.x
                result = session.run("""
                    MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})
                    // Get ONLY events directly connected to this lifecycle
                    OPTIONAL MATCH (l)-[:HAS_EVENT]->(e:Event)
                    // Get ONLY documents directly connected to this lifecycle  
                    OPTIONAL MATCH (l)-[:HAS_DOCUMENT]->(d:Document)
                    // Collect node IDs for filtering
                    WITH l, 
                         collect(DISTINCT elementId(e)) as event_ids,
                         collect(DISTINCT elementId(d)) as doc_ids,
                         collect(DISTINCT e) as events,
                         collect(DISTINCT d) as documents
                    // Filter out nulls and combine
                    WITH l,
                         [n IN events + documents WHERE n IS NOT NULL] as all_nodes,
                         event_ids + doc_ids as all_node_ids
                    // Get relationships - lifecycle to events (only those we collected)
                    OPTIONAL MATCH (l)-[r1:HAS_EVENT]->(e:Event)
                    WHERE elementId(e) IN all_node_ids
                    // Get relationships - lifecycle to documents (only those we collected)
                    OPTIONAL MATCH (l)-[r2:HAS_DOCUMENT]->(d:Document)
                    WHERE elementId(d) IN all_node_ids
                    // Get relationships - documents to events (only if both belong to this lifecycle)
                    OPTIONAL MATCH (d)-[r3:RELATED_TO]->(e2:Event)
                    WHERE elementId(d) IN all_node_ids 
                      AND elementId(e2) IN all_node_ids
                      AND EXISTS {
                          MATCH (l)-[:HAS_EVENT]->(e2)
                      }
                    // Return results
                    WITH l, all_nodes,
                         [r IN collect(DISTINCT r1) + collect(DISTINCT r2) + collect(DISTINCT r3) WHERE r IS NOT NULL] as all_rels
                    RETURN l as lifecycle_node, all_nodes, all_rels
                """, lifecycle_id=lifecycle_id)

                record = result.single()
                if not record:
                    return {"nodes": [], "links": []}

                # Start with the lifecycle node
                lifecycle_node = record.get("lifecycle_node")
                nodes_data = record.get("all_nodes", [])  # Fixed: was all_related_nodes
                rels_data = record.get("all_rels", [])
                
                # Add lifecycle node to the list if it exists
                if lifecycle_node:
                    nodes_data = [lifecycle_node] + nodes_data

                # Extract unique nodes
                nodes = []
                seen_node_ids = set()
                for node in nodes_data:
                    if node is None:
                        continue
                    node_id = node.get("lifecycle_id") or node.get("document_id") or node.get("event_id")
                    if not node_id or node_id in seen_node_ids:
                        continue
                    seen_node_ids.add(node_id)
                    
                    labels = list(node.labels)
                    node_type = labels[0] if labels else "Unknown"
                    
                    # Extract better label based on node type
                    if node_type == "Document":
                        label = node.get("document_id", node_id)
                        # Try to get filename from properties if available
                        props = dict(node)
                        filename = props.get("filename") or props.get("document_id", node_id)
                        label = filename if filename else node_id
                    elif node_type == "Event":
                        label = node.get("event_type", node_id)
                    elif node_type == "Lifecycle":
                        label = node.get("lifecycle_id", node_id)
                    else:
                        label = node_id
                    
                    nodes.append({
                        "id": node_id,
                        "label": label,
                        "type": node_type,
                        "properties": dict(node),
                        "filename": dict(node).get("filename"),
                        "event_type": dict(node).get("event_type"),
                        "lifecycle_id": dict(node).get("lifecycle_id"),
                        "document_id": dict(node).get("document_id"),
                        "document_type": dict(node).get("document_type")
                    })

                # Extract relationships
                links = []
                seen_links = set()
                for rel in rels_data:
                    if rel is None:
                        continue
                    source_id = rel.start_node.get("lifecycle_id") or rel.start_node.get("document_id") or rel.start_node.get("event_id")
                    target_id = rel.end_node.get("lifecycle_id") or rel.end_node.get("document_id") or rel.end_node.get("event_id")
                    
                    if not source_id or not target_id:
                        continue
                    
                    link_key = f"{source_id}-{target_id}-{rel.type}"
                    if link_key in seen_links:
                        continue
                    seen_links.add(link_key)
                    
                    links.append({
                        "source": source_id,
                        "target": target_id,
                        "type": rel.type
                    })

                return {"nodes": nodes, "links": links}
        except Exception as e:
            logger.error(f"Failed to get graph data: {e}")
            return {"nodes": [], "links": []}

    def _extract_document_status_from_text(self, text: str) -> Optional[str]:
        """Extract a normalized status from document text when present.
        
        This is a helper method for retroactive evaluation.
        Duplicates the logic from api/routes/documents.py to avoid circular imports.
        """
        if not text:
            return None
        import re
        # Typical pattern in sample docs: "Status: PAID"
        match = re.search(r"^\s*status\s*:\s*([A-Za-z][A-Za-z _-]{0,40})\s*$", text, re.IGNORECASE | re.MULTILINE)
        if not match:
            return None
        value = match.group(1).strip().lower()
        value = re.sub(r"\s+", " ", value)
        return value or None

    def retroactively_evaluate_lifecycles(self) -> dict:
        """
        Retroactively evaluate all existing lifecycles and update their status
        based on existing events and documents.
        
        Returns:
            Dict with counts: {"evaluated": int, "completed": int, "reopened": int, "unchanged": int}
        """
        if not self.driver:
            logger.warning("Neo4j not available for retroactive evaluation")
            return {"evaluated": 0, "completed": 0, "reopened": 0, "unchanged": 0}
        
        from pathlib import Path
        from core.config import get_settings
        from services.document_parser import DocumentParser
        
        parser = DocumentParser()
        settings = get_settings()
        upload_dir = Path(settings.upload_dir)
        
        stats = {"evaluated": 0, "completed": 0, "reopened": 0, "unchanged": 0}
        
        try:
            with self.driver.session() as session:
                # Get all lifecycles with their events and documents
                result = session.run("""
                    MATCH (l:Lifecycle)
                    OPTIONAL MATCH (l)-[:HAS_EVENT]->(e:Event)
                    OPTIONAL MATCH (l)-[:HAS_DOCUMENT]->(d:Document)
                    WITH l, 
                         collect(DISTINCT {
                             event_id: e.event_id,
                             event_type: e.event_type,
                             summary: e.summary,
                             timestamp: CASE 
                                 WHEN e.timestamp IS NOT NULL 
                                 THEN toString(e.timestamp)
                                 ELSE null
                             END
                         }) as events,
                         collect(DISTINCT {
                             document_id: d.document_id,
                             filename: d.filename,
                             document_type: d.document_type
                         }) as documents
                    RETURN l.lifecycle_id as lifecycle_id,
                           l.status as current_status,
                           events,
                           documents
                    ORDER BY l.lifecycle_id
                """)
                
                for record in result:
                    lifecycle_id = record["lifecycle_id"]
                    if not lifecycle_id:
                        continue
                    
                    current_status = (record["current_status"] or "active").lower()
                    events_data = record["events"] or []
                    documents_data = record["documents"] or []
                    
                    # Filter out null events
                    events_data = [e for e in events_data if e.get("event_id")]
                    
                    stats["evaluated"] += 1
                    
                    # Check all events for terminal signals
                    found_terminal = False
                    found_reopen_signal = False
                    latest_doc_status = None
                    terminal_doc_status = None  # Track the terminal document status specifically
                    latest_terminal_event = None
                    latest_reopen_event = None
                    
                    # Evaluate events (sorted by timestamp if available)
                    sorted_events = sorted(
                        events_data,
                        key=lambda e: e.get("timestamp", "") or "",
                        reverse=True
                    )
                    
                    for event in sorted_events:
                        event_type = event.get("event_type", "")
                        summary = event.get("summary", "")
                        
                        # Check if this event is terminal
                        if self._is_terminal_signal(event_type, summary, None):
                            found_terminal = True
                            if not latest_terminal_event:
                                latest_terminal_event = event
                            logger.debug(f"Lifecycle {lifecycle_id}: Found terminal event {event_type}")
                        
                        # Check if this is a reopen signal (non-terminal upload/creation)
                        if self._is_reopen_signal(event_type, summary, None):
                            found_reopen_signal = True
                            if not latest_reopen_event:
                                latest_reopen_event = event
                    
                    # Evaluate documents for status hints
                    for doc in documents_data:
                        doc_id = doc.get("document_id")
                        filename = doc.get("filename")
                        
                        if not doc_id:
                            continue
                        
                        # Try to find and parse the document file
                        file_pattern = f"{doc_id}_*"
                        matching_files = list(upload_dir.glob(file_pattern))
                        
                        if matching_files:
                            try:
                                file_path = matching_files[0]
                                parsed = parser.parse(str(file_path))
                                text = parsed.get("text", "")
                                
                                # Extract document status
                                doc_status = self._extract_document_status_from_text(text)
                                
                                if doc_status:
                                    latest_doc_status = doc_status  # Keep latest for reference
                                    # Check if this is a terminal status
                                    if self._is_terminal_signal("", "", doc_status):
                                        found_terminal = True
                                        terminal_doc_status = doc_status  # Track terminal status specifically
                                        logger.debug(f"Lifecycle {lifecycle_id}: Found terminal document status {doc_status} in {filename}")
                            except Exception as e:
                                logger.warning(f"Failed to parse document {doc_id} for lifecycle {lifecycle_id}: {e}")
                    
                    # Use terminal document status if found, otherwise use latest
                    final_doc_status = terminal_doc_status or latest_doc_status
                    
                    # Determine action based on current status and signals
                    if current_status in self.CLOSED_STATUSES:
                        # Lifecycle is closed - check if it should be reopened
                        if found_reopen_signal and not found_terminal:
                            # Reopen with the latest reopen event info
                            event_to_use = latest_reopen_event or sorted_events[0] if sorted_events else {}
                            reopened = self.auto_reopen_lifecycle(
                                lifecycle_id=lifecycle_id,
                                event_type=event_to_use.get("event_type", ""),
                                summary=event_to_use.get("summary", ""),
                                document_status=final_doc_status
                            )
                            if reopened:
                                stats["reopened"] += 1
                            else:
                                stats["unchanged"] += 1
                        else:
                            stats["unchanged"] += 1
                    else:
                        # Lifecycle is active - check if it should be completed
                        if found_terminal:
                            # Use the most recent terminal event/document
                            # If we found terminal in documents but not events, use latest event with terminal doc status
                            event_to_use = latest_terminal_event or sorted_events[0] if sorted_events else {}
                            event_type = event_to_use.get("event_type", "")
                            summary = event_to_use.get("summary", "")
                            
                            # Log what we're passing to auto_complete_lifecycle
                            logger.info(
                                f"Attempting to complete lifecycle {lifecycle_id}: "
                                f"event_type={event_type}, summary={summary[:50]}, "
                                f"document_status={final_doc_status}"
                            )
                            
                            # Verify terminal signal detection
                            is_terminal = self._is_terminal_signal(event_type, summary, final_doc_status)
                            logger.info(
                                f"Terminal signal check for {lifecycle_id}: {is_terminal} "
                                f"(event_type has terminal: {any(k in event_type.upper() for k in self.TERMINAL_EVENT_KEYWORDS)}, "
                                f"summary has terminal: {any(term in summary.lower() for term in ['completed', 'closed', 'paid', 'signed', 'accepted'])}, "
                                f"doc_status is terminal: {final_doc_status and final_doc_status.lower() in self.TERMINAL_STATUS_KEYWORDS})"
                            )
                            
                            completed = self.auto_complete_lifecycle(
                                lifecycle_id=lifecycle_id,
                                event_type=event_type,
                                summary=summary,
                                document_status=final_doc_status
                            )
                            if completed:
                                logger.info(f"Successfully completed lifecycle {lifecycle_id}")
                                stats["completed"] += 1
                            else:
                                logger.warning(f"Failed to complete lifecycle {lifecycle_id} despite terminal signals")
                                stats["unchanged"] += 1
                        else:
                            stats["unchanged"] += 1
                
        except Exception as e:
            logger.error(f"Failed to retroactively evaluate lifecycles: {e}", exc_info=True)
        
        logger.info(f"Retroactive evaluation complete: {stats}")
        return stats
