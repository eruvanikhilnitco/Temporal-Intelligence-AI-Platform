import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from dateutil.parser import parse as parse_date

from services.outcome_service import OutcomeService
from services.temporal_delta_engine import TemporalDeltaEngine
from services.lifecycle_service import LifecycleService
from models.outcome import OutcomeCreate

logger = logging.getLogger(__name__)


class OutcomeExtractor:
    """
    Automatically extract outcomes from lifecycle documents and events.
    
    Extracts:
    - Cost variance (from document revisions)
    - Time variance (from delivery date changes)
    - Revision frequency (from document change patterns)
    - Change order frequency (from event analysis)
    """
    
    def __init__(self):
        self.outcome_service = OutcomeService()
        self.delta_engine = TemporalDeltaEngine()
        self.lifecycle_service = LifecycleService()
    
    def extract_outcomes_from_lifecycle(
        self, 
        lifecycle_id: str,
        document_files: Optional[Dict[str, Dict]] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract outcomes by analyzing document revisions and events in a lifecycle.
        
        Args:
            lifecycle_id: The lifecycle to analyze
            document_files: Optional pre-loaded document files (for efficiency)
        
        Returns:
            List of outcome dictionaries ready for OutcomeCreate
        """
        try:
            lifecycle = self.lifecycle_service.get_lifecycle(lifecycle_id)
            
            if not lifecycle.events:
                logger.debug(f"No events found for lifecycle {lifecycle_id}, skipping outcome extraction")
                return []
            
            # Load document files if not provided
            if document_files is None:
                document_files = self._load_document_files(lifecycle_id)
            
            # Prepare events data for analysis
            events_data = [
                {
                    "event_type": e.event_type,
                    "timestamp": e.timestamp,
                    "summary": e.summary or ""
                }
                for e in lifecycle.events
            ]
            
            # Analyze document revisions
            revision_analysis = self.delta_engine.analyze_document_revisions(
                events_data, document_files
            )
            
            outcomes = []
            
            # Extract cost variance from revisions
            cost_outcomes = self._extract_cost_variance(
                lifecycle_id, revision_analysis, lifecycle.events
            )
            outcomes.extend(cost_outcomes)
            
            # Extract time variance from revisions
            time_outcomes = self._extract_time_variance(
                lifecycle_id, revision_analysis, lifecycle.events
            )
            outcomes.extend(time_outcomes)
            
            # Extract revision frequency metrics
            revision_outcomes = self._extract_revision_metrics(
                lifecycle_id, revision_analysis
            )
            outcomes.extend(revision_outcomes)
            
            # Extract change order frequency
            change_outcomes = self._extract_change_order_metrics(
                lifecycle_id, lifecycle.events
            )
            outcomes.extend(change_outcomes)
            
            logger.info(
                f"Extracted {len(outcomes)} outcomes for lifecycle {lifecycle_id}: "
                f"{[o['outcome_type'] for o in outcomes]}"
            )
            
            return outcomes
            
        except Exception as e:
            logger.error(f"Failed to extract outcomes for lifecycle {lifecycle_id}: {e}", exc_info=True)
            return []
    
    def _load_document_files(self, lifecycle_id: str) -> Dict[str, Dict]:
        """Load document files for a lifecycle."""
        from neo4j import GraphDatabase
        from core.database import get_neo4j_connection
        from core.config import get_settings
        from pathlib import Path
        from services.document_parser import DocumentParser
        
        document_files = {}
        try:
            neo4j_config = get_neo4j_connection()
            driver = GraphDatabase.driver(
                neo4j_config.uri,
                auth=(neo4j_config.user, neo4j_config.password)
            )
            try:
                with driver.session() as session:
                    result = session.run(
                        """
                        MATCH (l:Lifecycle {lifecycle_id: $lifecycle_id})-[:HAS_DOCUMENT]->(d:Document)
                        RETURN d.document_id as document_id, d.filename as filename
                        """,
                        lifecycle_id=lifecycle_id,
                    )
                    settings = get_settings()
                    upload_dir = Path(settings.upload_dir)
                    parser = DocumentParser()
                    
                    for record in result:
                        doc_id = record.get("document_id")
                        filename = record.get("filename")
                        if not doc_id:
                            continue
                        
                        file_pattern = f"{doc_id}_*"
                        matching_files = list(upload_dir.glob(file_pattern))
                        if not matching_files:
                            continue
                        
                        file_path = matching_files[0]
                        try:
                            parsed = parser.parse(str(file_path))
                            content = parsed.get("text", "")
                            key = filename or file_path.name
                            document_files[key] = {
                                "path": str(file_path),
                                "content": content,
                                "document_id": doc_id
                            }
                        except Exception as e:
                            logger.warning(f"Failed to parse document {doc_id}: {e}")
            finally:
                driver.close()
        except Exception as e:
            logger.warning(f"Failed to load document files: {e}")
        
        return document_files
    
    def _extract_cost_variance(
        self,
        lifecycle_id: str,
        revision_analysis: Dict[str, Any],
        events: List
    ) -> List[Dict[str, Any]]:
        """Extract cost variance outcomes from document revisions."""
        outcomes = []
        
        try:
            # Look for cost changes in revision analysis
            changes = revision_analysis.get("changes", [])
            
            for change in changes:
                detailed_changes = change.get("detailed_changes", [])
                
                for detail in detailed_changes:
                    # Pattern: "Total cost change: $X → $Y (+Z%)"
                    cost_pattern = r'Total\s+cost\s+change[:\s]+\$?([\d,]+\.?\d*)\s*→\s*\$?([\d,]+\.?\d*)\s*\(([+-]?\d+\.?\d*)%\)'
                    match = re.search(cost_pattern, detail, re.IGNORECASE)
                    
                    if match:
                        initial_cost = float(match.group(1).replace(',', ''))
                        final_cost = float(match.group(2).replace(',', ''))
                        variance_pct = float(match.group(3))
                        overrun = final_cost - initial_cost
                        
                        # Only record significant variances (>5%)
                        if abs(variance_pct) > 5:
                            outcome_type = "COST_OVERRUN" if overrun > 0 else "COST_UNDERRUN"
                            
                            # Use change timestamp or current time
                            recorded_at = change.get("timestamp")
                            if recorded_at:
                                if isinstance(recorded_at, str):
                                    recorded_at = parse_date(recorded_at)
                                if recorded_at.tzinfo is None:
                                    recorded_at = recorded_at.replace(tzinfo=timezone.utc)
                            else:
                                recorded_at = datetime.now(timezone.utc)
                            
                            outcomes.append({
                                "lifecycle_id": lifecycle_id,
                                "outcome_type": outcome_type,
                                "value": abs(overrun),
                                "recorded_at": recorded_at
                            })
                            
                            # Also record variance percentage as a separate outcome
                            outcomes.append({
                                "lifecycle_id": lifecycle_id,
                                "outcome_type": "VARIANCE",
                                "value": abs(variance_pct),
                                "recorded_at": recorded_at
                            })
                            
                            logger.debug(
                                f"Extracted cost variance: {outcome_type} ${abs(overrun):,.2f} "
                                f"({variance_pct:+.1f}%) for {lifecycle_id}"
                            )
            
            # Also try to extract from first vs last financial documents
            if not outcomes:
                outcomes.extend(self._extract_cost_from_document_comparison(
                    lifecycle_id, events
                ))
        
        except Exception as e:
            logger.warning(f"Failed to extract cost variance: {e}")
        
        return outcomes
    
    def _extract_cost_from_document_comparison(
        self,
        lifecycle_id: str,
        events: List
    ) -> List[Dict[str, Any]]:
        """Extract cost by comparing first and last financial documents."""
        outcomes = []
        
        try:
            # Find first PO and last Invoice
            po_events = [e for e in events if "PURCHASE_ORDER" in e.event_type.upper()]
            invoice_events = [e for e in events if "INVOICE" in e.event_type.upper()]
            
            if po_events and invoice_events:
                # Get document content for first PO and last Invoice
                first_po = po_events[0]
                last_invoice = invoice_events[-1]
                
                # Extract totals from summaries or document content
                # This is a simplified extraction - in production, parse actual documents
                po_total = self._extract_total_from_text(first_po.summary or "")
                inv_total = self._extract_total_from_text(last_invoice.summary or "")
                
                if po_total and inv_total and po_total > 0:
                    variance_pct = ((inv_total - po_total) / po_total) * 100
                    overrun = inv_total - po_total
                    
                    if abs(variance_pct) > 5:
                        outcome_type = "COST_OVERRUN" if overrun > 0 else "COST_UNDERRUN"
                        
                        recorded_at = last_invoice.timestamp
                        if recorded_at and recorded_at.tzinfo is None:
                            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
                        elif not recorded_at:
                            recorded_at = datetime.now(timezone.utc)
                        
                        outcomes.append({
                            "lifecycle_id": lifecycle_id,
                            "outcome_type": outcome_type,
                            "value": abs(overrun),
                            "recorded_at": recorded_at
                        })
        
        except Exception as e:
            logger.debug(f"Failed to extract cost from document comparison: {e}")
        
        return outcomes
    
    def _extract_total_from_text(self, text: str) -> Optional[float]:
        """Extract total cost from text."""
        if not text:
            return None
        
        # Pattern: "Total: $1,234.56" or "Total $1234.56"
        patterns = [
            r'total[:\s]+\$?([\d,]+\.?\d*)',
            r'amount[:\s]+\$?([\d,]+\.?\d*)',
            r'cost[:\s]+\$?([\d,]+\.?\d*)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(',', ''))
                except ValueError:
                    continue
        
        return None
    
    def _extract_time_variance(
        self,
        lifecycle_id: str,
        revision_analysis: Dict[str, Any],
        events: List
    ) -> List[Dict[str, Any]]:
        """Extract time variance outcomes from delivery date changes."""
        outcomes = []
        
        try:
            changes = revision_analysis.get("changes", [])
            
            for change in changes:
                detailed_changes = change.get("detailed_changes", [])
                
                for detail in detailed_changes:
                    # Pattern: "Delivery date changed: 2024-02-15 → 2024-02-20"
                    date_pattern = r'Delivery\s+date\s+changed[:\s]+(\d{4}-\d{2}-\d{2})\s*→\s*(\d{4}-\d{2}-\d{2})'
                    match = re.search(date_pattern, detail, re.IGNORECASE)
                    
                    if match:
                        planned_date_str = match.group(1)
                        actual_date_str = match.group(2)
                        
                        try:
                            planned_date = datetime.strptime(planned_date_str, "%Y-%m-%d")
                            actual_date = datetime.strptime(actual_date_str, "%Y-%m-%d")
                            
                            days_delay = (actual_date - planned_date).days
                            
                            # Only record significant delays (>1 day)
                            if abs(days_delay) > 1:
                                outcome_type = "TIME_OVERRUN" if days_delay > 0 else "TIME_UNDERRUN"
                                
                                recorded_at = change.get("timestamp")
                                if recorded_at:
                                    if isinstance(recorded_at, str):
                                        recorded_at = parse_date(recorded_at)
                                    if recorded_at.tzinfo is None:
                                        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
                                else:
                                    recorded_at = datetime.now(timezone.utc)
                                
                                outcomes.append({
                                    "lifecycle_id": lifecycle_id,
                                    "outcome_type": outcome_type,
                                    "value": abs(days_delay),
                                    "recorded_at": recorded_at
                                })
                                
                                logger.debug(
                                    f"Extracted time variance: {outcome_type} {abs(days_delay)} days "
                                    f"for {lifecycle_id}"
                                )
                        except ValueError:
                            continue
        
        except Exception as e:
            logger.warning(f"Failed to extract time variance: {e}")
        
        return outcomes
    
    def _extract_revision_metrics(
        self,
        lifecycle_id: str,
        revision_analysis: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract revision frequency metrics."""
        outcomes = []
        
        try:
            revisions = revision_analysis.get("revisions", [])
            total_revisions = sum(rev.get("revision_count", 0) for rev in revisions)
            
            if total_revisions > 0:
                # Record revision frequency as an outcome
                outcomes.append({
                    "lifecycle_id": lifecycle_id,
                    "outcome_type": "REVISION_FREQUENCY",
                    "value": float(total_revisions),
                    "recorded_at": datetime.now(timezone.utc)
                })
        
        except Exception as e:
            logger.warning(f"Failed to extract revision metrics: {e}")
        
        return outcomes
    
    def _extract_change_order_metrics(
        self,
        lifecycle_id: str,
        events: List
    ) -> List[Dict[str, Any]]:
        """Extract change order frequency metrics."""
        outcomes = []
        
        try:
            change_events = [
                e for e in events
                if "CHANGE" in e.event_type.upper() or
                   "MODIFY" in e.event_type.upper() or
                   "UPDATE" in e.event_type.upper()
            ]
            
            if change_events:
                outcomes.append({
                    "lifecycle_id": lifecycle_id,
                    "outcome_type": "CHANGE_ORDER_COUNT",
                    "value": float(len(change_events)),
                    "recorded_at": datetime.now(timezone.utc)
                })
        
        except Exception as e:
            logger.warning(f"Failed to extract change order metrics: {e}")
        
        return outcomes
    
    def create_outcomes_for_lifecycle(
        self,
        lifecycle_id: str,
        document_files: Optional[Dict[str, Dict]] = None
    ) -> int:
        """
        Extract and create outcomes for a lifecycle.
        
        Returns:
            Number of outcomes created
        """
        outcomes_data = self.extract_outcomes_from_lifecycle(lifecycle_id, document_files)
        
        created_count = 0
        for outcome_data in outcomes_data:
            try:
                outcome = self.outcome_service.create_outcome(OutcomeCreate(**outcome_data))
                created_count += 1
                logger.info(
                    f"Created outcome {outcome.outcome_id}: {outcome.outcome_type} = {outcome.value} "
                    f"for lifecycle {lifecycle_id}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to create outcome {outcome_data.get('outcome_type')} "
                    f"for {lifecycle_id}: {e}"
                )
        
        return created_count
    
    def extract_outcomes_for_all_completed_lifecycles(self) -> Dict[str, Any]:
        """
        Retroactively extract outcomes for all existing completed lifecycles.
        
        Returns:
            Dictionary with statistics:
            - processed: Number of lifecycles processed
            - outcomes_created: Total number of outcomes created
            - lifecycles_with_outcomes: Number of lifecycles that had outcomes extracted
            - errors: Number of errors encountered
        """
        stats = {
            "processed": 0,
            "outcomes_created": 0,
            "lifecycles_with_outcomes": 0,
            "errors": 0
        }
        
        try:
            # Get all completed lifecycles
            all_lifecycles = self.lifecycle_service.list_lifecycles(limit=1000)
            
            completed_lifecycles = [
                lc for lc in all_lifecycles
                if lc.status and lc.status.lower() in ["completed", "closed"]
            ]
            
            logger.info(f"Found {len(completed_lifecycles)} completed lifecycles to process")
            
            for lifecycle in completed_lifecycles:
                lifecycle_id = lifecycle.lifecycle_id
                if not lifecycle_id:
                    continue
                
                stats["processed"] += 1
                
                try:
                    # Extract outcomes for this lifecycle
                    created_count = self.create_outcomes_for_lifecycle(lifecycle_id)
                    
                    if created_count > 0:
                        stats["outcomes_created"] += created_count
                        stats["lifecycles_with_outcomes"] += 1
                        logger.info(
                            f"Extracted {created_count} outcome(s) for lifecycle {lifecycle_id}"
                        )
                    else:
                        logger.debug(f"No outcomes extracted for lifecycle {lifecycle_id}")
                
                except Exception as e:
                    stats["errors"] += 1
                    logger.warning(
                        f"Failed to extract outcomes for lifecycle {lifecycle_id}: {e}",
                        exc_info=True
                    )
            
            logger.info(
                f"Retroactive outcome extraction complete: "
                f"processed={stats['processed']}, "
                f"outcomes_created={stats['outcomes_created']}, "
                f"lifecycles_with_outcomes={stats['lifecycles_with_outcomes']}, "
                f"errors={stats['errors']}"
            )
            
        except Exception as e:
            logger.error(f"Failed to extract outcomes for all completed lifecycles: {e}", exc_info=True)
            stats["errors"] += 1
        
        return stats
