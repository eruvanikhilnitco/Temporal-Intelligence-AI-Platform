from datetime import datetime, timezone
from dateutil.parser import parse as parse_date
from typing import List, Dict, Any, Optional
from collections import defaultdict
import re
import logging

logger = logging.getLogger(__name__)


def normalize_datetime(dt):
    """Normalize datetime to timezone-aware UTC."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = parse_date(dt)
    if isinstance(dt, datetime):
        # If timezone-naive, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # Convert to UTC
        return dt.astimezone(timezone.utc)
    return dt


class TemporalDeltaEngine:
    def compute_deltas(self, events: list[dict]) -> dict:
        if not events:
            return {"delta_count": 0, "last_updated": None}
        
        # Normalize all timestamps before comparison
        normalized_events = []
        for event in events:
            normalized_ts = normalize_datetime(event["timestamp"])
            normalized_events.append({**event, "timestamp": normalized_ts})
        
        last_event = max(normalized_events, key=lambda event: event["timestamp"])
        return {
            "delta_count": len(events),
            "last_updated": last_event["timestamp"],
        }

    def summarize(self, events: list[dict]) -> str:
        if not events:
            return "No lifecycle activity detected."
        
        # Calculate time span if we have multiple events
        if len(events) > 1:
            # Normalize all timestamps
            normalized_timestamps = [normalize_datetime(e["timestamp"]) for e in events if e.get("timestamp")]
            if normalized_timestamps and len(normalized_timestamps) > 1:
                sorted_timestamps = sorted(normalized_timestamps)
                first_event_time = sorted_timestamps[0]
                last_event_time = sorted_timestamps[-1]
                
                # Calculate time span
                time_span_days = (last_event_time - first_event_time).days
                if time_span_days > 0:
                    return f"{len(events)} events recorded over {time_span_days} days. Last activity: {last_event_time.strftime('%Y-%m-%d')}."
        
        return f"{len(events)} lifecycle events recorded as of {datetime.now(timezone.utc).strftime('%Y-%m-%d')}."

    def analyze_document_revisions(self, events: List[Dict[str, Any]], document_files: Dict[str, Dict] = None) -> Dict[str, Any]:
        """Analyze document revisions and changes between versions.
        
        Returns:
            Dictionary with revision analysis including:
            - revisions: List of revision groups (same document type, multiple versions)
            - changes: List of detected changes between revisions
            - summary: Text summary of changes
        """
        if not events:
            return {
                "revisions": [],
                "changes": [],
                "summary": "No document revisions detected."
            }
        
        # Group events by document base name (to track revisions of the same document)
        # Extract base filename (without version) to group revisions together
        events_by_document = defaultdict(list)
        for event in events:
            # Extract document type from event type (e.g., "PURCHASE_ORDER_UPLOADED" -> "Purchase Order")
            event_type = event.get("event_type", "")
            if "_UPLOADED" in event_type:
                doc_type = event_type.replace("_UPLOADED", "").replace("_", " ").title()
                summary = event.get("summary", "")
                filename = self._extract_filename(summary)
                
                if filename:
                    # Extract base filename and entity ID for better grouping
                    base_filename = self._extract_base_filename(filename)
                    entity_id = self._extract_entity_id(filename, doc_type)
                    
                    # Generic grouping strategy: Try entity ID first, then base filename
                    # This works for all document types:
                    # - Procurement: PO_2024_Project_Alpha_v1/v2 -> base_filename groups them
                    # - HR: OfferLetter_Sarah_Johnson_Position001/Revised -> entity_id groups them
                    # - Healthcare: Prescription_PAT01001_v1/v2 -> entity_id groups them
                    
                    # Normalize document type and base filename to ensure consistent grouping
                    # Normalize doc_type to lowercase for consistent keys
                    doc_type_normalized = doc_type.strip().lower()
                    base_filename_normalized = base_filename.strip().lower()
                    
                    if entity_id:
                        # Use entity ID for documents with clear entity identifiers
                        doc_key = f"{doc_type_normalized}::{entity_id}"
                        logger.info(f"Grouping by entity_id: filename={filename}, doc_type={doc_type}, entity_id={entity_id}, doc_key={doc_key}")
                    else:
                        # Use normalized base filename as fallback (works for procurement, etc.)
                        doc_key = f"{doc_type_normalized}::{base_filename_normalized}"
                        logger.info(f"Grouping by base_filename: filename={filename}, doc_type={doc_type}, base_filename={base_filename} -> normalized={base_filename_normalized}, doc_key={doc_key}")
                    
                    events_by_document[doc_key].append({
                        **event,
                        "doc_type": doc_type,
                        "filename": filename,
                        "entity_id": entity_id,
                        "base_filename": base_filename
                    })
                else:
                    logger.warning(f"Could not extract filename from summary: {summary}")
        
        revisions = []
        changes = []
        
        # Analyze each document group for revisions
        logger.info(f"Analyzing {len(events_by_document)} document groups for revisions")
        for doc_key, doc_events in events_by_document.items():
            logger.info(f"Document group '{doc_key}': {len(doc_events)} event(s) - filenames: {[e.get('filename', 'unknown') for e in doc_events]}")
            if len(doc_events) > 1:
                # Multiple versions detected - this is a revision
                # Sort by timestamp first, then by version number if available
                def sort_key(e):
                    ts = normalize_datetime(e.get("timestamp"))
                    filename = e.get("filename", "")
                    version = self._extract_version(filename)
                    version_num = int(version) if version else 999  # Put files without version at end
                    return (ts, version_num)
                
                sorted_events = sorted(doc_events, key=sort_key)
                doc_type = doc_events[0].get("doc_type", "Document")
                
                # Extract dates for revision info
                first_date = normalize_datetime(sorted_events[0].get("timestamp"))
                last_date = normalize_datetime(sorted_events[-1].get("timestamp"))
                
                revision_info = {
                    "document_type": doc_type,
                    "versions": len(sorted_events),
                    "revision_count": len(sorted_events) - 1,
                    "first_upload": first_date.strftime('%Y-%m-%d') if first_date else None,
                    "last_upload": last_date.strftime('%Y-%m-%d') if last_date else None,
                    "first_version": {
                        "event_type": sorted_events[0].get("event_type"),
                        "timestamp": sorted_events[0].get("timestamp"),
                        "summary": sorted_events[0].get("summary", "")
                    },
                    "latest_version": {
                        "event_type": sorted_events[-1].get("event_type"),
                        "timestamp": sorted_events[-1].get("timestamp"),
                        "summary": sorted_events[-1].get("summary", "")
                    }
                }
                revisions.append(revision_info)
                
                # Extract change information from filenames and summaries
                for i in range(1, len(sorted_events)):
                    prev_event = sorted_events[i-1]
                    curr_event = sorted_events[i]
                    
                    # Use filename from event if available, otherwise extract from summary
                    prev_filename = prev_event.get("filename") or self._extract_filename(prev_event.get("summary", ""))
                    curr_filename = curr_event.get("filename") or self._extract_filename(curr_event.get("summary", ""))
                    
                    # Detect version indicators in filenames (v1, v2, etc.)
                    prev_version = self._extract_version(prev_filename)
                    curr_version = self._extract_version(curr_filename)
                    
                    # Ensure correct order: prev should have lower version number than curr
                    if prev_version and curr_version:
                        prev_v_num = int(prev_version)
                        curr_v_num = int(curr_version)
                        if prev_v_num > curr_v_num:
                            # Swap if order is wrong (shouldn't happen with proper sorting, but safety check)
                            prev_filename, curr_filename = curr_filename, prev_filename
                            prev_version, curr_version = curr_version, prev_version
                            prev_event, curr_event = curr_event, prev_event
                    
                    if prev_filename and curr_filename:
                        # Start with empty list - prioritize content-based changes
                        detailed_changes = []
                        
                        # If document files are available, extract content-based changes FIRST
                        if document_files:
                            content_changes = self._extract_content_changes(
                                prev_filename, curr_filename, doc_type, document_files
                            )
                            if content_changes:
                                detailed_changes.extend(content_changes)
                        
                        # If no content changes found, add filename-based changes as fallback
                        if not detailed_changes:
                            filename_changes = self._extract_detailed_changes(prev_filename, curr_filename, doc_type)
                            detailed_changes.extend(filename_changes)
                        else:
                            # Add version info if content changes exist
                            filename_changes = self._extract_detailed_changes(prev_filename, curr_filename, doc_type)
                            detailed_changes = filename_changes + detailed_changes  # Version info first, then content
                        
                        change_info = {
                            "type": "revision",
                            "document_type": doc_type,
                            "from_version": prev_filename,
                            "to_version": curr_filename,
                            "from_version_num": prev_version,
                            "to_version_num": curr_version,
                            "timestamp": curr_event.get("timestamp"),
                            "description": f"{doc_type} revised from {prev_filename} to {curr_filename}",
                            "detailed_changes": detailed_changes
                        }
                        changes.append(change_info)
        
        # Generate summary with dates
        if revisions:
            summary_parts = []
            for rev in revisions:
                if rev["revision_count"] > 0:
                    date_range = ""
                    if rev.get("first_upload") and rev.get("last_upload"):
                        date_range = f" ({rev['first_upload']} - {rev['last_upload']})"
                    summary_parts.append(
                        f"{rev['document_type']}: {rev['revision_count']} revision(s){date_range}"
                    )
            summary = "; ".join(summary_parts) if summary_parts else "No significant changes detected."
        else:
            summary = "No document revisions detected."
        
        return {
            "revisions": revisions,
            "changes": changes,
            "summary": summary
        }
    
    def _extract_version(self, filename: str) -> Optional[str]:
        """Extract version number from filename (e.g., v1, v2, _v2, etc.)."""
        if not filename:
            return None
        # Match patterns like v1, v2, _v2, -v3, etc.
        match = re.search(r'[_-]?v(\d+)', filename, re.IGNORECASE)
        return match.group(1) if match else None
    
    def _extract_base_filename(self, filename: str) -> str:
        """Extract base filename by removing version suffixes, revision markers, and date variations.
        
        This is a generic method that works for all document types:
        - Procurement: PO_2024_Project_Alpha_v1 -> PO_2024_Project_Alpha
        - HR: OfferLetter_Sarah_Johnson_Position001_Revised -> OfferLetter_Sarah_Johnson_Position001
        - Healthcare: Prescription_PAT01001_Medication_v2 -> Prescription_PAT01001_Medication
        """
        if not filename:
            return ""
        
        base = filename
        
        # Remove file extension first
        base = re.sub(r'\.[^.]+$', '', base)
        
        # Remove version suffixes (_v1, _v2, -v3, etc.) - must be at the end
        # Pattern: _v1, _v2, -v3, v1, v2 (with optional underscore/dash before)
        base = re.sub(r'[_-]?v\d+$', '', base, flags=re.IGNORECASE)
        
        # Remove revision markers (_Revised, _FollowUp, _Final, etc.) - must be at the end
        base = re.sub(r'[_-](?:revised|followup|follow-up|final|updated|modified)$', '', base, flags=re.IGNORECASE)
        
        # Remove round numbers for interviews (_Round1, _Round2, etc.) - must be at the end
        base = re.sub(r'[_-]round\d+$', '', base, flags=re.IGNORECASE)
        
        # Remove common suffixes that indicate revisions but keep the core identifier
        # Pattern: _PriceAdjustment, _DeliveryDelay, etc. (for change orders)
        base = re.sub(r'[_-](?:priceadjustment|deliverydelay|adjustment|delay)$', '', base, flags=re.IGNORECASE)
        
        # Remove date patterns at the end (2024_03, 2024-03-15, etc.) but keep entity IDs
        # Only remove if it's clearly a date pattern, not part of an ID
        # Pattern: _YYYY_MM or _YYYY-MM-DD at the end
        # But be careful: don't remove if it's part of a project ID like "Project_2024"
        # So only remove if it's a standalone date pattern at the very end
        base = re.sub(r'[_-]\d{4}[_-]\d{2}(?:[_-]\d{2})?$', '', base, flags=re.IGNORECASE)
        
        result = base.strip()
        logger.debug(f"Base filename extraction: {filename} -> {result}")
        return result
    
    def _extract_entity_id(self, filename: str, doc_type: str) -> Optional[str]:
        """Extract entity ID from filename to help group related documents.
        
        Examples:
        - Prescription_PAT01001_Medication_v1.txt -> PAT01001
        - OfferLetter_Sarah_Johnson_Position001.txt -> Sarah_Johnson_Position001
        - PatientRecord_PAT01001_2024_03.txt -> PAT01001
        - ExpenseReport_Employee001_2024_Q1.txt -> Employee001
        """
        if not filename:
            return None
        
        # Remove file extension
        name = re.sub(r'\.[^.]+$', '', filename)
        
        # Extract entity IDs based on document type patterns
        # Healthcare: PAT01001, PAT-01001, etc.
        if "patient" in doc_type.lower() or "prescription" in doc_type.lower() or "lab" in doc_type.lower():
            match = re.search(r'(?:patient|pat|prescription|lab)[_-]?([A-Z0-9]{6,})', name, re.IGNORECASE)
            if match:
                return match.group(1)
            # Try PAT pattern
            match = re.search(r'PAT[_-]?(\d+)', name, re.IGNORECASE)
            if match:
                return f"PAT{match.group(1)}"
        
        # HR: Extract name and position
        if "application" in doc_type.lower() or "offer" in doc_type.lower() or "interview" in doc_type.lower():
            # Pattern: Application_Sarah_Johnson_Position001 or OfferLetter_Sarah_Johnson_Position001
            # Match full words like "Application", "OfferLetter", "InterviewFeedback" followed by underscore
            match = re.search(r'(?:application|offerletter|interviewfeedback|interview)[_-]([A-Za-z_]+(?:_[A-Za-z]+)*)[_-](position|pos)[_-]?(\d+)', name, re.IGNORECASE)
            if match:
                return f"{match.group(1)}_{match.group(3)}"
            # Pattern without position: Application_Sarah_Johnson or OfferLetter_Sarah_Johnson
            match = re.search(r'(?:application|offerletter|interviewfeedback|interview)[_-]([A-Za-z_]+(?:_[A-Za-z]+)*)', name, re.IGNORECASE)
            if match:
                entity = match.group(1)
                # Remove common suffixes like "Revised", "FollowUp", etc.
                entity = re.sub(r'[_-](?:revised|followup|follow-up|final|updated|modified|round\d+)$', '', entity, flags=re.IGNORECASE)
                return entity
        
        # Finance: Employee001, EMP001, etc.
        if "expense" in doc_type.lower() or "financial" in doc_type.lower():
            match = re.search(r'(?:employee|emp)[_-]?(\d+)', name, re.IGNORECASE)
            if match:
                return f"Employee{match.group(1)}"
        
        # Sales: Company name or Lead ID
        if "lead" in doc_type.lower() or "proposal" in doc_type.lower() or "contract" in doc_type.lower():
            # Extract company name or project ID
            match = re.search(r'(?:lead|proposal|contract)[_-]([A-Za-z_]+(?:_[A-Za-z]+)*)', name, re.IGNORECASE)
            if match:
                return match.group(1)
            # Try project pattern
            match = re.search(r'project[_-]?(\d+)', name, re.IGNORECASE)
            if match:
                return f"Project{match.group(1)}"
        
        # Legal: Client name or Contract ID
        if "contract" in doc_type.lower() or "compliance" in doc_type.lower():
            match = re.search(r'(?:client|contract)[_-]([A-Za-z_]+(?:_[A-Za-z]+)*)', name, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # Procurement: PO number or project name
        if "purchase" in doc_type.lower() or "po" in doc_type.lower() or "change" in doc_type.lower():
            match = re.search(r'(?:po|purchase|change)[_-](\d{4}[_-][A-Za-z0-9_]+)', name, re.IGNORECASE)
            if match:
                entity = match.group(1)
                # Normalize procurement IDs so v1/v2/revised forms map to one revision group.
                entity = re.sub(r'[_-]?v\d+$', '', entity, flags=re.IGNORECASE)
                entity = re.sub(r'[_-](?:revised|followup|follow-up|final|updated|modified)$', '', entity, flags=re.IGNORECASE)
                return entity
            # Try project pattern
            match = re.search(r'project[_-]([A-Za-z_]+)', name, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # Generic: Try to extract any ID pattern (alphanumeric with underscores)
        match = re.search(r'[_-]([A-Z0-9]{4,}(?:[_-][A-Z0-9]+)*)', name, re.IGNORECASE)
        if match:
            return match.group(1)
        
        return None
    
    def _extract_detailed_changes(self, prev_filename: str, curr_filename: str, doc_type: str) -> List[str]:
        """Extract detailed changes from filename patterns and document type."""
        changes = []
        if not prev_filename or not curr_filename:
            return changes
        
        # For Purchase/Change Orders, detect common change patterns.
        # Use explicit type checks; avoid matching "proposal" via substring "po".
        doc_type_lower = (doc_type or "").strip().lower()
        if doc_type_lower in {"purchase order", "change order"}:
            # Check for version changes
            prev_v = self._extract_version(prev_filename)
            curr_v = self._extract_version(curr_filename)
            if prev_v and curr_v and prev_v != curr_v:
                changes.append(f"Version updated: v{prev_v} → v{curr_v}")
        
        # Don't add generic message here - let content-based extraction provide details
        return changes
    
    def _extract_content_changes(self, prev_filename: str, curr_filename: str, doc_type: str, document_files: Dict[str, Dict]) -> List[str]:
        """Extract detailed changes by comparing document content."""
        changes = []
        if not document_files:
            logger.debug(f"No document_files provided for content extraction")
            return changes
        
        # Try exact match first
        prev_file_data = document_files.get(prev_filename)
        curr_file_data = document_files.get(curr_filename)
        
        # If exact match fails, try partial match (filename might be truncated in summary)
        # Also try case-insensitive matching and base filename matching
        if not prev_file_data or not curr_file_data:
            prev_filename_lower = prev_filename.lower() if prev_filename else ""
            curr_filename_lower = curr_filename.lower() if curr_filename else ""
            prev_base = self._extract_base_filename(prev_filename).lower() if prev_filename else ""
            curr_base = self._extract_base_filename(curr_filename).lower() if curr_filename else ""
            
            for key in document_files.keys():
                key_lower = key.lower()
                key_base = self._extract_base_filename(key).lower()
                
                # Match by exact filename (case-insensitive)
                if not prev_file_data and (prev_filename_lower == key_lower or prev_filename in key or key in prev_filename):
                    prev_file_data = document_files[key]
                    logger.debug(f"Matched prev file: {prev_filename} -> {key}")
                
                # Match by base filename
                if not prev_file_data and prev_base and prev_base == key_base:
                    prev_file_data = document_files[key]
                    logger.debug(f"Matched prev file by base: {prev_base} -> {key}")
                
                # Same for current file
                if not curr_file_data and (curr_filename_lower == key_lower or curr_filename in key or key in curr_filename):
                    curr_file_data = document_files[key]
                    logger.debug(f"Matched curr file: {curr_filename} -> {key}")
                
                if not curr_file_data and curr_base and curr_base == key_base:
                    curr_file_data = document_files[key]
                    logger.debug(f"Matched curr file by base: {curr_base} -> {key}")
        
        if not prev_file_data or not curr_file_data:
            logger.warning(f"Could not find files in document_files: prev={prev_filename}, curr={curr_filename}, available={list(document_files.keys())}")
            return changes
        
        logger.info(f"Extracting content changes: prev={prev_filename} ({len(prev_file_data.get('content', ''))} chars), curr={curr_filename} ({len(curr_file_data.get('content', ''))} chars)")
        
        try:
            prev_content = prev_file_data.get("content", "").lower()
            curr_content = curr_file_data.get("content", "").lower()
            
            if not prev_content or not curr_content:
                return changes
            
            # Route to appropriate content extraction based on document type
            doc_type_lower = doc_type.lower()
            
            # Purchase Orders / Change Orders
            # Use explicit checks; avoid routing "proposal" to PO parser.
            if doc_type_lower in {"purchase order", "change order"}:
                changes.extend(self._extract_po_changes(prev_content, curr_content))
            
            # Prescriptions
            elif "prescription" in doc_type_lower:
                changes.extend(self._extract_prescription_changes(prev_content, curr_content))
            
            # Offer Letters
            elif "offer" in doc_type_lower:
                changes.extend(self._extract_offer_letter_changes(prev_content, curr_content))
            
            # Proposals
            elif "proposal" in doc_type_lower:
                changes.extend(self._extract_proposal_changes(prev_content, curr_content))
            
            # Expense Reports
            elif "expense" in doc_type_lower:
                changes.extend(self._extract_expense_report_changes(prev_content, curr_content))
            
            # Contracts
            elif "contract" in doc_type_lower:
                changes.extend(self._extract_contract_changes(prev_content, curr_content))
            
            # Patient Records
            elif "patient" in doc_type_lower or "record" in doc_type_lower:
                changes.extend(self._extract_patient_record_changes(prev_content, curr_content))
            
            # Lab Results
            elif "lab" in doc_type_lower:
                changes.extend(self._extract_lab_results_changes(prev_content, curr_content))
            
            # Generic document comparison (fallback)
            else:
                changes.extend(self._extract_generic_changes(prev_content, curr_content, doc_type))
            
            # Remove duplicate changes while preserving order.
            deduped_changes = list(dict.fromkeys(changes))
            return deduped_changes
        
        except Exception as e:
            logger.warning(f"Failed to extract content changes: {e}")

        # Remove duplicate changes while preserving order.
        deduped_changes = list(dict.fromkeys(changes))
        return deduped_changes
    
    def _extract_po_changes(self, prev_content: str, curr_content: str) -> List[str]:
        """Extract changes from Purchase Order documents."""
        changes = []
        
        # Extract items with their names and quantities (e.g., "Component A - Quantity: 50 units")
        # Pattern: Item name followed by quantity
        prev_items = {}
        curr_items = {}
        
        # Try to extract structured item data: "Item Name - Quantity: X - Unit Price: $Y"
        # Pattern matches: "1. Component A - Quantity: 50 units - Unit Price: $500.00"
        # Note: content is already lowercased, so we need to match case-insensitively
        prev_item_pattern = r'(\d+)\.\s*([^-]+?)\s*-\s*quantity[:\s]+(\d+)\s*(?:units?)?\s*(?:-\s*unit\s*price[:\s]+\$?([\d,]+\.?\d*))?'
        curr_item_pattern = r'(\d+)\.\s*([^-]+?)\s*-\s*quantity[:\s]+(\d+)\s*(?:units?)?\s*(?:-\s*unit\s*price[:\s]+\$?([\d,]+\.?\d*))?'
        
        prev_matches = list(re.finditer(prev_item_pattern, prev_content, re.MULTILINE))
        curr_matches = list(re.finditer(curr_item_pattern, curr_content, re.MULTILINE))
        
        logger.info(f"Regex found {len(prev_matches)} items in prev document, {len(curr_matches)} items in curr document")
        
        for match in prev_matches:
            item_num = match.group(1)
            item_name = match.group(2).strip()
            quantity = match.group(3)
            price = match.group(4) if match.group(4) else None
            prev_items[item_num] = {
                "name": item_name,
                "quantity": int(quantity),
                "price": float(price.replace(',', '')) if price else None
            }
        
        for match in curr_matches:
            item_num = match.group(1)
            item_name = match.group(2).strip()
            quantity = match.group(3)
            price = match.group(4) if match.group(4) else None
            curr_items[item_num] = {
                "name": item_name,
                "quantity": int(quantity),
                "price": float(price.replace(',', '')) if price else None
            }
        
        # Compare items by number
        all_item_nums = set(prev_items.keys()) | set(curr_items.keys())
        logger.info(f"Parsed {len(prev_items)} items in prev document, {len(curr_items)} items in curr document, {len(all_item_nums)} total unique items")
        
        # If no items found, log content preview for debugging
        if not prev_items and not curr_items:
            logger.warning(f"No items extracted! Prev content sample: {prev_content[:400]}... Curr content sample: {curr_content[:400]}...")
        
        for item_num in sorted(all_item_nums):
            prev_item = prev_items.get(item_num)
            curr_item = curr_items.get(item_num)
            
            if prev_item and curr_item:
                # Item exists in both versions - check for changes
                item_name = prev_item["name"] or curr_item["name"] or f"Item {item_num}"
                item_name = item_name.strip()
                
                if prev_item["quantity"] != curr_item["quantity"]:
                    changes.append(f"Quantity increase: {item_name} ({prev_item['quantity']} → {curr_item['quantity']} units)")
                
                if prev_item["price"] and curr_item["price"] and prev_item["price"] != curr_item["price"]:
                    changes.append(f"Price adjustment: {item_name} (${prev_item['price']:,.2f} → ${curr_item['price']:,.2f})")
            elif not prev_item and curr_item:
                # New item added
                item_name = curr_item["name"] or f"Item {item_num}"
                item_name = item_name.strip()
                if curr_item["price"]:
                    changes.append(f"New item added: {item_name} (Quantity: {curr_item['quantity']} units, Price: ${curr_item['price']:,.2f})")
                else:
                    changes.append(f"New item added: {item_name} (Quantity: {curr_item['quantity']} units)")
        
        logger.info(f"Extracted {len(changes)} content changes from item comparison")
        
        # Also check for rush delivery fee and timeline compression
        if "rush" in curr_content and "rush" not in prev_content:
            # Prefer extracting an actual dollar amount from the rush line (not quantity "1").
            rush_fee_match = re.search(
                r'rush[^\n]*?(?:unit\s*price|price)\s*[:\-]?\s*\$?([\d,]+(?:\.\d+)?)',
                curr_content,
                re.IGNORECASE
            )
            if not rush_fee_match:
                rush_fee_match = re.search(
                    r'rush[^\n]*?\$([\d,]+(?:\.\d+)?)',
                    curr_content,
                    re.IGNORECASE
                )
            if rush_fee_match:
                fee = rush_fee_match.group(1).replace(',', '')
                # Avoid duplicate rush messages if we already captured rush as a new item.
                if not any("rush delivery fee" in c.lower() for c in changes):
                    changes.append(f"Rush delivery fee added: ${float(fee):,.2f}")
            else:
                if not any("rush delivery fee" in c.lower() for c in changes):
                    changes.append("Rush delivery fee added")
        
        # Check for timeline compression
        prev_timeline_match = re.search(r'(?:timeline|delivery|duration)[:\s]+(\d+)\s*(?:days?|weeks?)', prev_content, re.IGNORECASE)
        curr_timeline_match = re.search(r'(?:timeline|delivery|duration)[:\s]+(\d+)\s*(?:days?|weeks?)', curr_content, re.IGNORECASE)
        if prev_timeline_match and curr_timeline_match:
            prev_days = int(prev_timeline_match.group(1))
            curr_days = int(curr_timeline_match.group(1))
            if curr_days < prev_days:
                changes.append(f"Timeline compressed: {prev_days} days → {curr_days} days")
        
        # Fallback: If structured parsing didn't work, try simple quantity/price extraction
        if not prev_items and not curr_items:
            prev_quantities = re.findall(r'quantity[:\s]+(\d+)', prev_content, re.IGNORECASE)
            curr_quantities = re.findall(r'quantity[:\s]+(\d+)', curr_content, re.IGNORECASE)
            
            if prev_quantities and curr_quantities and len(prev_quantities) == len(curr_quantities):
                for idx, (prev_qty, curr_qty) in enumerate(zip(prev_quantities, curr_quantities)):
                    if prev_qty != curr_qty:
                        item_name = f"Item {idx + 1}" if idx < 2 else "Additional items"
                        changes.append(f"Quantity change: {item_name} ({prev_qty} → {curr_qty} units)")
            
            prev_prices = re.findall(r'unit\s*price[:\s]+\$?(\d+(?:\.\d+)?)', prev_content, re.IGNORECASE)
            curr_prices = re.findall(r'unit\s*price[:\s]+\$?(\d+(?:\.\d+)?)', curr_content, re.IGNORECASE)
            
            if prev_prices and curr_prices and len(prev_prices) == len(curr_prices):
                for idx, (prev_price, curr_price) in enumerate(zip(prev_prices, curr_prices)):
                    if prev_price != curr_price:
                        item_name = f"Item {idx + 1}" if idx < 2 else "Additional items"
                        changes.append(f"Price adjustment: {item_name} (${prev_price} → ${curr_price})")
        
        # Extract totals
        prev_total_match = re.search(r'total[:\s]+\$?(\d+(?:,\d+)?(?:\.\d+)?)', prev_content, re.IGNORECASE)
        curr_total_match = re.search(r'total[:\s]+\$?(\d+(?:,\d+)?(?:\.\d+)?)', curr_content, re.IGNORECASE)
        
        if prev_total_match and curr_total_match:
            prev_total = prev_total_match.group(1).replace(',', '')
            curr_total = curr_total_match.group(1).replace(',', '')
            try:
                prev_val = float(prev_total)
                curr_val = float(curr_total)
                if prev_val != curr_val:
                    variance = ((curr_val - prev_val) / prev_val) * 100
                    changes.append(f"Total cost change: ${prev_val:,.2f} → ${curr_val:,.2f} ({variance:+.1f}%)")
            except ValueError:
                pass
        
        # Extract delivery dates
        prev_delivery = re.search(r'delivery\s*date[:\s]+(\d{4}-\d{2}-\d{2})', prev_content, re.IGNORECASE)
        curr_delivery = re.search(r'delivery\s*date[:\s]+(\d{4}-\d{2}-\d{2})', curr_content, re.IGNORECASE)
        
        if prev_delivery and curr_delivery:
            prev_date = prev_delivery.group(1)
            curr_date = curr_delivery.group(1)
            if prev_date != curr_date:
                changes.append(f"Delivery date changed: {prev_date} → {curr_date}")
        
        return changes
    
    def _extract_prescription_changes(self, prev_content: str, curr_content: str) -> List[str]:
        """Extract changes from Prescription documents."""
        changes = []
        
        # Extract medications
        prev_meds = {}
        curr_meds = {}
        
        # Pattern: "1. Medication Name - Quantity: X - Dosage"
        med_pattern = r'(\d+)\.\s*([^-]+?)\s*-\s*quantity[:\s]+(\d+)\s*(?:tablets?|units?)?\s*(?:-\s*take\s+([^-]+))?'
        
        for match in re.finditer(med_pattern, prev_content, re.IGNORECASE | re.MULTILINE):
            med_num = match.group(1)
            med_name = match.group(2).strip()
            quantity = match.group(3)
            dosage = match.group(4) if match.group(4) else ""
            prev_meds[med_num] = {"name": med_name, "quantity": int(quantity), "dosage": dosage}
        
        for match in re.finditer(med_pattern, curr_content, re.IGNORECASE | re.MULTILINE):
            med_num = match.group(1)
            med_name = match.group(2).strip()
            quantity = match.group(3)
            dosage = match.group(4) if match.group(4) else ""
            curr_meds[med_num] = {"name": med_name, "quantity": int(quantity), "dosage": dosage}
        
        # Check for dosage changes (e.g., 500mg -> 1000mg)
        for med_num in set(prev_meds.keys()) | set(curr_meds.keys()):
            prev_med = prev_meds.get(med_num)
            curr_med = curr_meds.get(med_num)
            
            if prev_med and curr_med:
                med_name = prev_med["name"] or curr_med["name"]
                # Check for dosage increase
                prev_dosage_match = re.search(r'(\d+)\s*mg', prev_med["name"], re.IGNORECASE)
                curr_dosage_match = re.search(r'(\d+)\s*mg', curr_med["name"], re.IGNORECASE)
                if prev_dosage_match and curr_dosage_match:
                    prev_dose = int(prev_dosage_match.group(1))
                    curr_dose = int(curr_dosage_match.group(1))
                    if curr_dose > prev_dose:
                        changes.append(f"Dosage increased: {med_name} ({prev_dose}mg → {curr_dose}mg)")
                    elif curr_dose < prev_dose:
                        changes.append(f"Dosage decreased: {med_name} ({prev_dose}mg → {curr_dose}mg)")
                
                if prev_med["quantity"] != curr_med["quantity"]:
                    changes.append(f"Quantity change: {med_name} ({prev_med['quantity']} → {curr_med['quantity']} tablets)")
            elif not prev_med and curr_med:
                med_name = curr_med["name"]
                changes.append(f"New medication added: {med_name} (Quantity: {curr_med['quantity']} tablets)")
        
        # Check for refills change
        prev_refills = re.search(r'refills?[:\s]+(\d+)', prev_content, re.IGNORECASE)
        curr_refills = re.search(r'refills?[:\s]+(\d+)', curr_content, re.IGNORECASE)
        if prev_refills and curr_refills:
            prev_r = int(prev_refills.group(1))
            curr_r = int(curr_refills.group(1))
            if prev_r != curr_r:
                changes.append(f"Refills changed: {prev_r} → {curr_r}")
        
        # Check for reason/status changes
        if "[changed:" in curr_content.lower() or "[new medication]" in curr_content.lower():
            reason_match = re.search(r'reason[:\s]+([^\n]+)', curr_content, re.IGNORECASE)
            if reason_match:
                changes.append(f"Reason for change: {reason_match.group(1).strip()}")
        
        return changes
    
    def _extract_offer_letter_changes(self, prev_content: str, curr_content: str) -> List[str]:
        """Extract changes from Offer Letter documents."""
        changes = []
        
        # Extract salary
        prev_salary = re.search(r'(?:base\s*)?salary[:\s]+\$?([\d,]+)', prev_content, re.IGNORECASE)
        curr_salary = re.search(r'(?:base\s*)?salary[:\s]+\$?([\d,]+)', curr_content, re.IGNORECASE)
        if prev_salary and curr_salary:
            prev_s = float(prev_salary.group(1).replace(',', ''))
            curr_s = float(curr_salary.group(1).replace(',', ''))
            if prev_s != curr_s:
                changes.append(f"Base salary changed: ${prev_s:,.0f} → ${curr_s:,.0f} (+${curr_s - prev_s:,.0f})")
        
        # Extract signing bonus
        prev_bonus = re.search(r'signing\s*bonus[:\s]+\$?([\d,]+)', prev_content, re.IGNORECASE)
        curr_bonus = re.search(r'signing\s*bonus[:\s]+\$?([\d,]+)', curr_content, re.IGNORECASE)
        if prev_bonus and curr_bonus:
            prev_b = float(prev_bonus.group(1).replace(',', ''))
            curr_b = float(curr_bonus.group(1).replace(',', ''))
            if prev_b != curr_b:
                changes.append(f"Signing bonus changed: ${prev_b:,.0f} → ${curr_b:,.0f} (+${curr_b - prev_b:,.0f})")
        
        # Extract stock options
        prev_stock = re.search(r'stock\s*options?[:\s]+(\d+)', prev_content, re.IGNORECASE)
        curr_stock = re.search(r'stock\s*options?[:\s]+(\d+)', curr_content, re.IGNORECASE)
        if prev_stock and curr_stock:
            prev_st = int(prev_stock.group(1))
            curr_st = int(curr_stock.group(1))
            if prev_st != curr_st:
                changes.append(f"Stock options changed: {prev_st} → {curr_st} shares (+{curr_st - prev_st})")
        
        # Check for new benefits
        if "remote work" in curr_content.lower() and "remote work" not in prev_content.lower():
            remote_match = re.search(r'remote\s*work[:\s]+([^\n]+)', curr_content, re.IGNORECASE)
            if remote_match:
                changes.append(f"New benefit added: Remote Work ({remote_match.group(1).strip()})")
        
        # Check status change
        prev_status = re.search(r'status[:\s]+(\w+)', prev_content, re.IGNORECASE)
        curr_status = re.search(r'status[:\s]+(\w+)', curr_content, re.IGNORECASE)
        if prev_status and curr_status:
            prev_st = prev_status.group(1).upper()
            curr_st = curr_status.group(1).upper()
            if prev_st != curr_st:
                changes.append(f"Status changed: {prev_st} → {curr_st}")
        
        return changes
    
    def _extract_proposal_changes(self, prev_content: str, curr_content: str) -> List[str]:
        """Extract changes from Proposal documents."""
        changes = []
        
        # Parse numbered scope lines: "3. Training: 8 days onsite [INCREASED: +3 days]"
        scope_pattern = r'^\s*\d+\.\s*([^:]+):\s*([^\n]+)$'
        prev_scope = {}
        curr_scope = {}
        for m in re.finditer(scope_pattern, prev_content, re.IGNORECASE | re.MULTILINE):
            key = m.group(1).strip().lower()
            prev_scope[key] = m.group(2).strip()
        for m in re.finditer(scope_pattern, curr_content, re.IGNORECASE | re.MULTILINE):
            key = m.group(1).strip().lower()
            curr_scope[key] = m.group(2).strip()

        # New scope entries
        for key, value in curr_scope.items():
            if key not in prev_scope:
                clean_value = re.sub(r'\[.*?\]', '', value).strip()
                changes.append(f"New scope item added: {key.title()} ({clean_value})")
            elif prev_scope[key] != value:
                prev_clean = re.sub(r'\[.*?\]', '', prev_scope[key]).strip()
                curr_clean = re.sub(r'\[.*?\]', '', value).strip()
                if prev_clean != curr_clean:
                    changes.append(f"Scope updated: {key.title()} ({prev_clean} → {curr_clean})")

        # Parse pricing lines: "- Training: $20,000 [INCREASED: +$5k]"
        price_pattern = r'^\s*-\s*([^:]+):\s*\$?([\d,]+(?:\.\d+)?)'
        prev_prices = {}
        curr_prices = {}
        for m in re.finditer(price_pattern, prev_content, re.IGNORECASE | re.MULTILINE):
            prev_prices[m.group(1).strip().lower()] = float(m.group(2).replace(',', ''))
        for m in re.finditer(price_pattern, curr_content, re.IGNORECASE | re.MULTILINE):
            curr_prices[m.group(1).strip().lower()] = float(m.group(2).replace(',', ''))

        all_price_keys = set(prev_prices.keys()) | set(curr_prices.keys())
        for key in sorted(all_price_keys):
            p = prev_prices.get(key)
            c = curr_prices.get(key)
            label = key.title()
            if p is None and c is not None:
                changes.append(f"New cost item added: {label} (${c:,.0f})")
            elif p is not None and c is not None and p != c:
                delta = c - p
                sign = "+" if delta >= 0 else "-"
                changes.append(f"Cost updated: {label} (${p:,.0f} → ${c:,.0f}, {sign}${abs(delta):,.0f})")

        # Total value
        prev_total = re.search(r'total[:\s]+\$?([\d,]+(?:\.\d+)?)', prev_content, re.IGNORECASE)
        curr_total = re.search(r'total[:\s]+\$?([\d,]+(?:\.\d+)?)', curr_content, re.IGNORECASE)
        if prev_total and curr_total:
            prev_t = float(prev_total.group(1).replace(',', ''))
            curr_t = float(curr_total.group(1).replace(',', ''))
            if prev_t != curr_t and prev_t != 0:
                variance = ((curr_t - prev_t) / prev_t) * 100
                changes.append(f"Total value changed: ${prev_t:,.0f} → ${curr_t:,.0f} ({variance:+.1f}%)")

        # Timeline
        prev_timeline = re.search(r'timeline[:\s]+(\d+)\s*(?:days?|weeks?)', prev_content, re.IGNORECASE)
        curr_timeline = re.search(r'timeline[:\s]+(\d+)\s*(?:days?|weeks?)', curr_content, re.IGNORECASE)
        if prev_timeline and curr_timeline:
            prev_days = int(prev_timeline.group(1))
            curr_days = int(curr_timeline.group(1))
            if prev_days != curr_days:
                if curr_days > prev_days:
                    changes.append(f"Timeline extended: {prev_days} → {curr_days} days (+{curr_days - prev_days} days)")
                else:
                    changes.append(f"Timeline compressed: {prev_days} → {curr_days} days (-{prev_days - curr_days} days)")

        # Payment terms
        prev_terms = re.search(r'payment\s*terms[:\s]+([^\n]+)', prev_content, re.IGNORECASE)
        curr_terms = re.search(r'payment\s*terms[:\s]+([^\n]+)', curr_content, re.IGNORECASE)
        if prev_terms and curr_terms:
            p_terms = prev_terms.group(1).strip()
            c_terms = curr_terms.group(1).strip()
            if p_terms != c_terms:
                changes.append(f"Payment terms changed: {p_terms} → {c_terms}")

        return changes
    
    def _extract_expense_report_changes(self, prev_content: str, curr_content: str) -> List[str]:
        """Extract changes from Expense Report documents."""
        changes = []
        
        # Extract subtotal
        prev_subtotal = re.search(r'subtotal[:\s]+\$?([\d,]+\.?\d*)', prev_content, re.IGNORECASE)
        curr_subtotal = re.search(r'subtotal[:\s]+\$?([\d,]+\.?\d*)', curr_content, re.IGNORECASE)
        if prev_subtotal and curr_subtotal:
            prev_st = float(prev_subtotal.group(1).replace(',', ''))
            curr_st = float(curr_subtotal.group(1).replace(',', ''))
            if prev_st != curr_st:
                changes.append(f"Subtotal changed: ${prev_st:,.2f} → ${curr_st:,.2f} (+${curr_st - prev_st:,.2f})")
        
        # Check for new expenses
        prev_expenses = re.findall(r'\d+\.\s*([^-]+?)\s*-\s*\$?([\d,]+\.?\d*)', prev_content, re.IGNORECASE)
        curr_expenses = re.findall(r'\d+\.\s*([^-]+?)\s*-\s*\$?([\d,]+\.?\d*)', curr_content, re.IGNORECASE)
        
        prev_expense_dict = {exp[0].strip(): float(exp[1].replace(',', '')) for exp in prev_expenses}
        curr_expense_dict = {exp[0].strip(): float(exp[1].replace(',', '')) for exp in curr_expenses}
        
        new_expenses = set(curr_expense_dict.keys()) - set(prev_expense_dict.keys())
        for expense in new_expenses:
            if "[added" in expense.lower() or "missing" in expense.lower():
                expense_name = re.sub(r'\[.*?\]', '', expense, flags=re.IGNORECASE).strip()
                amount = curr_expense_dict[expense]
                changes.append(f"New expense added: {expense_name} (${amount:,.2f})")
        
        # Check status change
        prev_status = re.search(r'status[:\s]+(\w+)', prev_content, re.IGNORECASE)
        curr_status = re.search(r'status[:\s]+(\w+)', curr_content, re.IGNORECASE)
        if prev_status and curr_status:
            prev_st = prev_status.group(1).upper()
            curr_st = curr_status.group(1).upper()
            if prev_st != curr_st:
                changes.append(f"Status changed: {prev_st} → {curr_st}")
        
        return changes
    
    def _extract_contract_changes(self, prev_content: str, curr_content: str) -> List[str]:
        """Extract changes from Contract documents."""
        changes = []
        
        # Extract service period
        prev_period = re.search(r'service\s*period[:\s]+(\d+)\s*(?:months?|years?)', prev_content, re.IGNORECASE)
        curr_period = re.search(r'service\s*period[:\s]+(\d+)\s*(?:months?|years?)', curr_content, re.IGNORECASE)
        if prev_period and curr_period:
            prev_p = int(prev_period.group(1))
            curr_p = int(curr_period.group(1))
            if prev_p != curr_p:
                changes.append(f"Service period changed: {prev_p} → {curr_p} months ({'+' if curr_p > prev_p else ''}{curr_p - prev_p} months)")
        
        # Extract monthly fee
        prev_fee = re.search(r'monthly\s*fee[:\s]+\$?([\d,]+)', prev_content, re.IGNORECASE)
        curr_fee = re.search(r'monthly\s*fee[:\s]+\$?([\d,]+)', curr_content, re.IGNORECASE)
        if prev_fee and curr_fee:
            prev_f = float(prev_fee.group(1).replace(',', ''))
            curr_f = float(curr_fee.group(1).replace(',', ''))
            if prev_f != curr_f:
                changes.append(f"Monthly fee changed: ${prev_f:,.0f} → ${curr_f:,.0f} (+${curr_f - prev_f:,.0f})")
        
        # Extract total contract value
        prev_total = re.search(r'total\s*contract\s*value[:\s]+\$?([\d,]+)', prev_content, re.IGNORECASE)
        curr_total = re.search(r'total\s*contract\s*value[:\s]+\$?([\d,]+)', curr_content, re.IGNORECASE)
        if prev_total and curr_total:
            prev_t = float(prev_total.group(1).replace(',', ''))
            curr_t = float(curr_total.group(1).replace(',', ''))
            if prev_t != curr_t:
                variance = ((curr_t - prev_t) / prev_t) * 100
                changes.append(f"Total contract value changed: ${prev_t:,.0f} → ${curr_t:,.0f} ({variance:+.1f}%)")
        
        # Check for new provisions
        if "[new]" in curr_content.lower():
            new_provision_match = re.search(r'\[new\][^\n]*?([^\n]+)', curr_content, re.IGNORECASE)
            if new_provision_match:
                changes.append(f"New provision added: {new_provision_match.group(1).strip()}")
        
        return changes
    
    def _extract_patient_record_changes(self, prev_content: str, curr_content: str) -> List[str]:
        """Extract changes from Patient Record documents."""
        changes = []
        
        # Extract vital signs
        vital_patterns = {
            "blood_pressure": r'blood\s*pressure[:\s]+(\d+/\d+)',
            "heart_rate": r'heart\s*rate[:\s]+(\d+)\s*bpm',
            "blood_glucose": r'blood\s*glucose[:\s]+(\d+)\s*mg/dl',
        }
        
        for vital_name, pattern in vital_patterns.items():
            prev_match = re.search(pattern, prev_content, re.IGNORECASE)
            curr_match = re.search(pattern, curr_content, re.IGNORECASE)
            if prev_match and curr_match:
                prev_val = prev_match.group(1)
                curr_val = curr_match.group(1)
                if prev_val != curr_val:
                    vital_display = vital_name.replace('_', ' ').title()
                    if "[improved]" in curr_content.lower() or "improved" in curr_match.group(0).lower():
                        changes.append(f"{vital_display} improved: {prev_val} → {curr_val}")
                    else:
                        changes.append(f"{vital_display} changed: {prev_val} → {curr_val}")
        
        # Check diagnosis change
        prev_diagnosis = re.search(r'diagnosis[:\s]+([^\n]+)', prev_content, re.IGNORECASE)
        curr_diagnosis = re.search(r'diagnosis[:\s]+([^\n]+)', curr_content, re.IGNORECASE)
        if prev_diagnosis and curr_diagnosis:
            prev_d = prev_diagnosis.group(1).strip()
            curr_d = curr_diagnosis.group(1).strip()
            if prev_d.lower() != curr_d.lower():
                changes.append(f"Diagnosis updated: {prev_d} → {curr_d}")
        
        return changes
    
    def _extract_lab_results_changes(self, prev_content: str, curr_content: str) -> List[str]:
        """Extract changes from Lab Results documents."""
        changes = []
        
        # Extract test results
        test_pattern = r'-\s*([^:]+?)[:\s]+([\d.]+%?)\s*(?:mg/dl|%)?\s*(?:\(([^)]+)\))?'
        
        prev_tests = {}
        curr_tests = {}
        
        for match in re.finditer(test_pattern, prev_content, re.IGNORECASE):
            test_name = match.group(1).strip()
            test_value = match.group(2)
            test_status = match.group(3) if match.group(3) else ""
            prev_tests[test_name] = {"value": test_value, "status": test_status}
        
        for match in re.finditer(test_pattern, curr_content, re.IGNORECASE):
            test_name = match.group(1).strip()
            test_value = match.group(2)
            test_status = match.group(3) if match.group(3) else ""
            curr_tests[test_name] = {"value": test_value, "status": test_status}
        
        # Compare test results
        for test_name in set(prev_tests.keys()) | set(curr_tests.keys()):
            prev_test = prev_tests.get(test_name)
            curr_test = curr_tests.get(test_name)
            
            if prev_test and curr_test:
                if prev_test["value"] != curr_test["value"]:
                    changes.append(f"{test_name} changed: {prev_test['value']} → {curr_test['value']}")
                if prev_test["status"] != curr_test["status"]:
                    changes.append(f"{test_name} status: {prev_test['status']} → {curr_test['status']}")
        
        return changes
    
    def _extract_generic_changes(self, prev_content: str, curr_content: str, doc_type: str) -> List[str]:
        """Generic change extraction for unknown document types."""
        changes = []
        
        # Check for common change indicators
        if "[changed" in curr_content.lower() or "[increased" in curr_content.lower():
            change_matches = re.findall(r'\[(?:changed|increased|decreased|new)[^\]]*\]', curr_content, re.IGNORECASE)
            for match in change_matches:
                change_text = match.replace('[', '').replace(']', '').strip()
                changes.append(f"Change noted: {change_text}")
        
        # Check for version indicators
        if "version" in curr_content.lower() or "revision" in curr_content.lower():
            version_match = re.search(r'(?:version|revision)[:\s]+(\w+)', curr_content, re.IGNORECASE)
            if version_match:
                changes.append(f"Document version: {version_match.group(1)}")
        
        return changes
    
    def _extract_filename(self, summary: str) -> Optional[str]:
        """Extract filename from event summary.
        
        Handles formats like:
        - "Document filename.txt uploaded and processed"
        - "Document filename... uploaded and processed" (truncated)
        """
        if not summary:
            return None
        # Summary format: "Document {filename} uploaded and processed"
        if "Document" in summary and "uploaded" in summary:
            parts = summary.split("Document")
            if len(parts) > 1:
                filename_part = parts[1].split("uploaded")[0].strip()
                # Remove trailing ellipsis if truncated
                filename_part = filename_part.rstrip("...")
                # Remove trailing dots/spaces
                filename_part = filename_part.rstrip(". ")
                return filename_part if filename_part else None
        return None
