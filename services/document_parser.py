import logging
import re
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import spacy
from tika import parser as tika_parser

logger = logging.getLogger(__name__)


class DocumentParser:
    def __init__(self, spacy_model: str = "en_core_web_sm"):
        try:
            self.nlp = spacy.load(spacy_model)
        except OSError:
            logger.warning(f"spaCy model {spacy_model} not found. Install with: python -m spacy download {spacy_model}")
            self.nlp = None

    def _detect_document_type(self, text: str, filename: str) -> str:
        """Auto-detect document type from content and filename."""
        text_lower = text.lower()
        filename_lower = filename.lower()
        
        # Document type patterns (case-insensitive)
        # CRITICAL: Order matters - check specific types FIRST to avoid false matches
        # Use word boundaries (\b) and specific patterns to prevent partial matches
        patterns = {
            # Healthcare documents (check FIRST - highest priority)
            "Patient Record": [
                r"patient\s*record\b", r"medical\s*record\b", r"health\s*record\b", 
                r"patient\s*id\b", r"patient\s*information", r"vital\s*signs", 
                r"diagnosis\s*:", r"treatment\s*plan", r"blood\s*pressure", r"heart\s*rate",
                r"patientrecord", r"lab\s*result", r"labresult", r"blood\s*work"  # Filename patterns
            ],
            "Medical Report": [
                r"medical\s*report\b", r"diagnosis\s*report", r"clinical\s*report",
                r"lab\s*result", r"labresult"  # Lab results are medical reports
            ],
            "Prescription": [r"prescription\b", r"medication\s*order\b", r"rx\b"],
            
            # HR documents (check EARLY - high priority)
            "Resume": [
                r"resume\b", r"\bcv\b", r"curriculum\s*vitae", r"professional\s*summary", 
                r"resume\s*of", r"^resume_"  # Filename pattern
            ],
            "Application": [
                r"application\s*form\b", r"job\s*application\b", r"application\s*for\s*position", 
                r"application\s*id\b", r"candidate\s*application", r"candidate\s*:", r"position\s*:",
                r"^application_"  # Filename pattern (must be at start)
            ],
            "Offer Letter": [r"offer\s*letter\b", r"job\s*offer\b", r"employment\s*offer\b", r"offer\s*of\s*employment"],
            "Interview Feedback": [r"interview\s*feedback", r"interview\s*notes", r"interview\s*evaluation"],
            
            # Compliance and Financial Reports (check before generic "Report")
            "Financial Statement": [
                r"financial\s*statement\b", r"financial\s*report", r"financial.*statement",
                r"financialstatement", r"^financial_"  # Filename patterns
            ],
            "Compliance Report": [
                r"compliance\s*report\b", r"compliance\s*audit", r"data\s*privacy", 
                r"regulatory\s*compliance", r"compliance.*report"  # Filename pattern
            ],
            "Expense Report": [
                r"expense\s*report\b", r"expense\s*statement", r"expense.*report"  # Filename pattern
            ],
            
            # Sales documents (check before generic patterns)
            "Proposal": [
                r"proposal\b", r"quote\b", r"quotation\b", r"estimate\b",
                r"^proposal_"  # Filename pattern (must be at start, not "purchase proposal")
            ],
            "Lead": [r"lead\b", r"sales\s*lead", r"prospect", r"^lead_"],  # Filename pattern
            
            # Financial/Procurement documents (more specific patterns with word boundaries)
            # Check prefix patterns first (most reliable for filenames)
            "Invoice": [
                r"^inv_", r"^invoice",  # Filename prefix patterns (highest priority)
                r"invoice\b", r"\binv\s*#", r"invoice\s*number", r"bill\s*to\b", r"invoice\s*date"
            ],
            "Purchase Order": [
                r"^po_", r"^purchase.*order",  # Filename prefix patterns (highest priority)
                r"purchase\s*order\b", r"\bpo\s*#\b", r"\bpo\s*number\b", r"p\.o\.\s*#", 
                r"purchase\s*order\s*number", r"purchase\s*order\s*date"
            ],
            "Change Order": [
                r"^co_", r"^change.*order",  # Filename prefix patterns (highest priority)
                r"change\s*order\b", r"\bco\s*#\b", r"modification\s*order\b", 
                r"amendment\s*order\b", r"change\s*order\s*#"
            ],
            "Contract": [r"contract\b", r"agreement\b", r"terms\s*and\s*conditions", r"legal\s*agreement"],
            
            # General documents (check LAST - lowest priority)
            "Report": [
                r"report\b", r"summary\b", r"analysis\b", r"findings",
                r"^report_"  # Filename pattern (only if not compliance/expense report)
            ],
            "Receipt": [r"receipt\b", r"payment\s*received", r"acknowledgment"],
            "Certificate": [r"certificate\b", r"certification\b", r"certified\b"],
        }
        
        # Check filename first (more reliable)
        # Use ordered iteration to ensure specific types are checked first
        # Prefix patterns (^) are checked first as they're most reliable
        for doc_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                # Check if pattern matches filename (case-insensitive)
                match = re.search(pattern, filename_lower, re.IGNORECASE)
                if match:
                    # Additional validation for ambiguous filename matches
                    if doc_type == "Purchase Order":
                        # Don't match if filename suggests it's a proposal, application, or position
                        # But allow if it's a clear PO prefix
                        if pattern.startswith("^po_") or pattern.startswith("^purchase"):
                            # Prefix patterns are reliable, skip validation
                            pass
                        elif re.search(r"proposal|application|position", filename_lower, re.IGNORECASE):
                            logger.info(f"Skipping 'Purchase Order' match from filename - detected other document type")
                            continue
                    elif doc_type == "Change Order":
                        # Don't match if filename suggests it's a compliance report or patient record
                        # But allow if it's a clear CO prefix
                        if pattern.startswith("^co_") or pattern.startswith("^change"):
                            # Prefix patterns are reliable, skip validation
                            pass
                        elif re.search(r"compliance|patient|medical", filename_lower, re.IGNORECASE):
                            logger.info(f"Skipping 'Change Order' match from filename - detected other document type")
                            continue
                    elif doc_type == "Invoice":
                        # Prefix patterns are reliable, no validation needed
                        if pattern.startswith("^inv_") or pattern.startswith("^invoice"):
                            pass
                    elif doc_type == "Report":
                        # Don't match if it's a specific report type
                        if re.search(r"compliance|expense|financial|medical|patient", filename_lower, re.IGNORECASE):
                            logger.info(f"Skipping generic 'Report' match - detected specific report type")
                            continue
                    
                    logger.info(f"Detected document type '{doc_type}' from filename pattern: {pattern}")
                    return doc_type
        
        # Check content (less reliable, but needed if filename doesn't match)
        for doc_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    # Additional validation for ambiguous patterns to prevent false matches
                    if doc_type == "Change Order":
                        # Don't match if it's clearly a medical/healthcare document
                        if re.search(r"patient|medical|health|diagnosis|treatment|vital\s*signs|blood\s*pressure|heart\s*rate", text_lower, re.IGNORECASE):
                            logger.info(f"Skipping 'Change Order' match - detected healthcare document")
                            continue
                        # Require explicit "change order" phrase, not just "order"
                        if not re.search(r"change\s+order|modification\s+order|amendment\s+order|\bco\s*#", text_lower, re.IGNORECASE):
                            logger.info(f"Skipping 'Change Order' match - pattern too loose")
                            continue
                    elif doc_type == "Purchase Order":
                        # Don't match if it's an application, proposal, HR document, or report
                        if re.search(r"application\s+form|application\s+id|candidate|job\s+application|position\s*:|proposal|quote|compliance|expense|report", text_lower, re.IGNORECASE):
                            logger.info(f"Skipping 'Purchase Order' match - detected other document type")
                            continue
                        # Require explicit "purchase order" phrase or "PO #" pattern
                        if not re.search(r"purchase\s+order|\bpo\s*#|p\.o\.\s*#|purchase\s+order\s+number", text_lower, re.IGNORECASE):
                            logger.info(f"Skipping 'Purchase Order' match - pattern too loose")
                            continue
                    elif doc_type == "Proposal":
                        # Don't match if it's a purchase order
                        if re.search(r"purchase\s+order|\bpo\s*#", text_lower, re.IGNORECASE):
                            logger.info(f"Skipping 'Proposal' match - detected purchase order")
                            continue
                    elif doc_type == "Report":
                        # Don't match if it's a specific report type (compliance, expense, medical)
                        if re.search(r"compliance|expense|medical|patient", text_lower, re.IGNORECASE):
                            logger.info(f"Skipping generic 'Report' match - detected specific report type")
                            continue
                    elif doc_type == "Application":
                        # Don't match if it's a purchase order or invoice
                        if re.search(r"purchase\s+order|invoice|bill\s+to", text_lower, re.IGNORECASE):
                            logger.info(f"Skipping 'Application' match - detected financial document")
                            continue
                    
                    logger.info(f"Detected document type '{doc_type}' from content pattern: {pattern}")
                    return doc_type
        
        # Default based on file extension
        ext = Path(filename).suffix.lower()
        ext_map = {
            ".pdf": "PDF Document",
            ".docx": "Word Document",
            ".doc": "Word Document",
            ".txt": "Text Document",
            ".csv": "CSV Data",
            ".xlsx": "Excel Spreadsheet",
            ".xls": "Excel Spreadsheet",
            ".json": "JSON Data",
        }
        
        return ext_map.get(ext, "Document")
    
    def _extract_lifecycle_id(self, text: str) -> Optional[str]:
        """Extract lifecycle ID from document content."""
        # Common lifecycle ID patterns (order matters - more specific first)
        patterns = [
            # Most specific patterns first
            r"lifecycle[_\s-]?id[:\s]+([A-Za-z0-9_-]+)",  # "Lifecycle ID: lifecycle_001" or "Lifecycle ID: LC-001"
            r"lifecycle[:\s]+([A-Za-z0-9_-]+)",  # "Lifecycle: lifecycle_001"
            r"lc[_\s-]?id[:\s]+([A-Za-z0-9_-]+)",  # "LC ID: LC-001"
            # Standalone lifecycle IDs (with word boundaries)
            r"\b(lifecycle[_\s-]?[0-9]{3,})\b",  # "lifecycle_001" as standalone word
            r"\b(lc[_\s-]?[0-9]{3,})\b",  # "lc_001" as standalone word
            # Document reference patterns
            r"po[_\s-]?#?[:\s]+([A-Za-z0-9_-]+)",  # "PO #: PO-12345"
            r"purchase\s*order[:\s]+([A-Za-z0-9_-]+)",  # "Purchase Order: PO-12345"
            r"invoice[_\s-]?#?[:\s]+([A-Za-z0-9_-]+)",  # "Invoice #: INV-789"
            r"contract[_\s-]?#?[:\s]+([A-Za-z0-9_-]+)",  # "Contract #: CNT-456"
            r"order[_\s-]?#?[:\s]+([A-Za-z0-9_-]+)",  # "Order #: ORD-789"
            r"change\s*order[:\s]+([A-Za-z0-9_-]+)",  # "Change Order: CO-001"
            r"reference[_\s-]?number[:\s]+([A-Za-z0-9_-]+)",  # "Reference Number: REF-123"
            r"document[_\s-]?id[:\s]+([A-Za-z0-9_-]+)",  # "Document ID: DOC-456"
            # Generic ID patterns (less specific, check last)
            r"\bid[:\s]+([A-Za-z]{2,}[_\s-]?[0-9]{3,})\b",  # "ID: LC-001" or "ID: PO12345"
        ]
        
        text_lines = text.split('\n')[:50]  # Check first 50 lines
        text_sample = '\n'.join(text_lines)
        
        for pattern in patterns:
            matches = re.finditer(pattern, text_sample, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                lifecycle_id = match.group(1) if match.groups() else match.group(0)
                # Clean up the ID - preserve underscores and hyphens
                lifecycle_id = re.sub(r'[^\w_-]', '', lifecycle_id.strip())
                if len(lifecycle_id) >= 3:  # Minimum length
                    # Normalize format: ensure it starts with a prefix if it's just numbers
                    if lifecycle_id.replace('_', '').replace('-', '').isdigit():
                        lifecycle_id = f"lifecycle_{lifecycle_id}"
                    # Ensure lowercase for consistency (lifecycle_001 not Lifecycle_001)
                    lifecycle_id = lifecycle_id.lower()
                    return lifecycle_id
        
        return None
    
    def _parse_special_files(self, file_path: str) -> Optional[str]:
        """Parse special file types (CSV, JSON, XLSX) that Tika might not handle well."""
        path = Path(file_path)
        ext = path.suffix.lower()
        
        try:
            if ext == '.json':
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Convert JSON to readable text
                    text_parts = []
                    if isinstance(data, dict):
                        for key, value in data.items():
                            text_parts.append(f"{key}: {value}")
                    elif isinstance(data, list):
                        for item in data[:100]:  # Limit to first 100 items
                            if isinstance(item, dict):
                                text_parts.append(str(item))
                    return '\n'.join(text_parts)
            
            elif ext in ['.csv']:
                import csv
                with open(path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    rows = []
                    for i, row in enumerate(reader):
                        if i >= 100:  # Limit to first 100 rows
                            break
                        rows.append(' | '.join(row))
                    return '\n'.join(rows)
            
            elif ext in ['.xlsx', '.xls']:
                try:
                    import pandas as pd
                    df = pd.read_excel(path, nrows=100)  # Limit to first 100 rows
                    return df.to_string()
                except ImportError:
                    logger.warning("pandas not available for Excel parsing, using Tika fallback")
                    return None
                except Exception as e:
                    logger.warning(f"Failed to parse Excel with pandas: {e}, using Tika fallback")
                    return None
            
        except Exception as e:
            logger.warning(f"Failed to parse special file type {ext}: {e}")
            return None
        
        return None

    def parse(self, file_path: str, original_filename: Optional[str] = None) -> dict:
        """Parse document using Apache Tika and extract entities with spaCy."""
        path = Path(file_path)
        # Use original upload filename for type detection when available.
        # Stored files are UUID-prefixed, which can break prefix-based detectors.
        filename = original_filename or path.name
        
        # Try special file parsing first
        special_text = self._parse_special_files(file_path)
        
        # Extract text using Tika
        text = ""
        if special_text:
            text = special_text
        else:
            try:
                parsed = tika_parser.from_file(str(path))
                text = parsed.get("content", "") if parsed else ""
                if not text or not text.strip():
                    # Fallback: try to read as plain text
                    try:
                        text = path.read_text(encoding="utf-8")
                    except Exception:
                        text = f"Document: {filename}"
            except Exception as e:
                logger.error(f"Tika parsing failed for {path}: {e}")
                # Fallback: read as text
                try:
                    text = path.read_text(encoding="utf-8")
                except Exception:
                    text = f"Document: {filename}"

        # Auto-detect document type and lifecycle ID
        detected_doc_type = self._detect_document_type(text, filename)
        detected_lifecycle_id = self._extract_lifecycle_id(text)

        # Extract entities with spaCy
        entities: List[str] = []
        if self.nlp and text:
            try:
                doc = self.nlp(text[:100000])  # Limit to 100k chars for performance
                entities = [
                    ent.text
                    for ent in doc.ents
                    if ent.label_ in ["ORG", "PERSON", "MONEY", "DATE", "PRODUCT"]
                ]
                # Remove duplicates while preserving order
                seen = set()
                entities = [e for e in entities if not (e in seen or seen.add(e))]
            except Exception as e:
                logger.error(f"spaCy entity extraction failed: {e}")

        return {
            "text": text.strip() if text else "",
            "entities": entities[:50],  # Limit to 50 entities
            "detected_document_type": detected_doc_type,
            "detected_lifecycle_id": detected_lifecycle_id,
        }
