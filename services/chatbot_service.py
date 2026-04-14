import json
import logging
import re
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from threading import Lock
from urllib import error as url_error
from urllib import request as url_request

from qdrant_client import QdrantClient

from core.config import get_settings
from core.database import get_neo4j_connection, get_neo4j_driver, get_qdrant_connection
from services.embedding_service import EmbeddingService
from services.lifecycle_service import LifecycleService
from services.prediction_service import PredictionService
from services.outcome_service import OutcomeService
from services.prediction_service import PredictionService

logger = logging.getLogger(__name__)


class ChatbotService:
    """
    Hybrid RAG (Retrieval Augmented Generation) chatbot:
    1) Semantic retrieval: Uses embeddings to find relevant documents from Qdrant
    2) Content retrieval: Fetches actual document text content from stored files
    3) Context augmentation: Includes retrieved document content in LLM prompts
    4) Deterministic tools: DB-backed answers for key metrics (lifecycles, counts, etc.)
    5) LLM synthesis: Uses OpenAI/Ollama to generate answers based on retrieved context
    6) Source citations: Returns document sources with snippets for transparency
    7) Session memory: Maintains short-term conversation context
    8) Guardrails: Safety checks for sensitive queries
    """
    _memory_lock = Lock()
    _session_memory: Dict[str, deque] = {}

    def __init__(self):
        self.settings = get_settings()
        self.lifecycle_service = LifecycleService()
        self.prediction_service = PredictionService()
        self.outcome_service = OutcomeService()
        self._embedder: Optional[EmbeddingService] = None
        
        # Log LLM configuration on initialization
        if self.settings.openai_api_key and self.settings.openai_api_key.strip():
            logger.info(f"Chatbot initialized with OpenAI: model={self.settings.openai_model}")
        elif self.settings.use_ollama:
            logger.info(f"Chatbot initialized with Ollama: model={self.settings.ollama_model}")
        else:
            logger.info("Chatbot initialized in deterministic mode (no LLM configured)")

    def answer_question(self, question: str, session_id: Optional[str] = None) -> Tuple[str, List[Dict[str, Any]]]:
        q = (question or "").strip()
        if not q:
            return "Please provide a question.", []
        sid = self._normalize_session_id(session_id)

        guardrail_result = self._apply_guardrails(q)
        if guardrail_result:
            return guardrail_result, []

        # Check for greetings and simple conversational queries first
        greeting_response = self._handle_greeting(q)
        if greeting_response:
            self._append_session_turn(sid, q, greeting_response)
            return greeting_response, []

        session_context = self._get_session_context(sid)
        sub_questions = self._decompose_question(q)
        context_chunks: List[str] = []
        sources: List[Dict[str, Any]] = []

        # Intelligent routing: Analyze question and route to appropriate services
        question_intent = self._analyze_question_intent(q)
        logger.info(f"Question intent detected: {question_intent}")

        # Check if this is a simple list/overview question (skip document retrieval for speed)
        q_lower = q.lower()
        is_list_question = any(term in q_lower for term in ["list", "show all", "all", "existing", "available", "what are the"])
        
        # Route to all relevant data sources based on intent
        routed_chunks, routed_sources = self._route_to_services(q, question_intent, is_list_question)
        context_chunks.extend(routed_chunks)
        sources.extend(routed_sources)

        # Always include deterministic tools for system metrics (only if not a simple list question)
        if not is_list_question or question_intent.get("statistics"):
            deterministic_chunks, deterministic_sources = self._run_deterministic_tools(q)
            context_chunks.extend(deterministic_chunks)
            sources.extend(deterministic_sources)

        # Retrieval for each sub-question (documents and tech stack) - skip for list questions
        if not is_list_question:
            for sub_q in sub_questions:
                doc_chunks, doc_sources = self._retrieve_documents(sub_q)
                context_chunks.extend(doc_chunks)
                sources.extend(doc_sources)

                stack_chunks, stack_sources = self._retrieve_tech_stack_context(sub_q)
                context_chunks.extend(stack_chunks)
                sources.extend(stack_sources)

        # Dedupe sources and trim context.
        sources = self._dedupe_sources(sources)[: self.settings.chatbot_max_sources]
        context = self._build_context(context_chunks)

        # Always try LLM first if API key is available (even for simple queries, it provides better responses)
        llm_answer = self._synthesize_with_llm(
            question=q,
            sub_questions=sub_questions,
            context=context,
            session_context=session_context,
        )
        if llm_answer:
            self._append_session_turn(sid, q, llm_answer)
            return llm_answer, sources

        # Deterministic fallback (works without API key).
        fallback = self._synthesize_without_llm(q, deterministic_chunks, context_chunks, session_context)
        self._append_session_turn(sid, q, fallback)
        return fallback, sources

    def _handle_greeting(self, question: str) -> Optional[str]:
        """Handle greetings and simple conversational queries with friendly responses."""
        q_lower = question.lower().strip()
        
        # Greeting patterns
        greetings = [
            r"^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening))[!.]?$",
            r"^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening))\s+there[!.]?$",
            r"^how\s+are\s+you[?]?$",
            r"^what\'?s\s+up[?]?$",
        ]
        
        for pattern in greetings:
            if re.match(pattern, q_lower, re.IGNORECASE):
                return (
                    "Hello! I'm here to help you explore your lifecycle data, documents, and system insights. "
                    "You can ask me about:\n"
                    "• Active lifecycles and their status\n"
                    "• Document counts and types\n"
                    "• Risk assessments and trends\n"
                    "• Technical stack details\n"
                    "• Specific lifecycle details (e.g., 'Tell me about lifecycle_procurement_001')\n\n"
                    "What would you like to know?"
                )
        
        return None

    def _apply_guardrails(self, question: str) -> Optional[str]:
        q_lower = question.lower()
        secret_terms = [
            "password",
            "api key",
            "secret",
            "access token",
            "private key",
            "jwt",
        ]
        if any(term in q_lower for term in secret_terms):
            return (
                "I can help with architecture, lifecycle data, and debugging guidance, "
                "but I can't reveal credentials, secrets, or security-sensitive values."
            )

        dangerous_terms = ["drop database", "delete all", "wipe data", "bypass auth"]
        if any(term in q_lower for term in dangerous_terms):
            return (
                "I can explain safe operational steps, but I can't assist with destructive "
                "or security-bypassing actions."
            )
        return None

    def _decompose_question(self, question: str) -> List[str]:
        # Lightweight decomposition for complex prompts.
        raw_parts = re.split(r"\?|\band\b|;|\n", question, flags=re.IGNORECASE)
        parts = [p.strip() for p in raw_parts if p and p.strip()]
        if not parts:
            return [question]
        return parts[:3]

    def _normalize_session_id(self, session_id: Optional[str]) -> str:
        sid = (session_id or "").strip()
        if not sid:
            return f"anon-{uuid.uuid4().hex[:12]}"
        return sid[:128]

    def _get_session_context(self, session_id: str) -> str:
        with self._memory_lock:
            turns = list(self._session_memory.get(session_id, deque()))
        if not turns:
            return ""
        formatted = []
        for item in turns:
            formatted.append(f"User: {item.get('question', '')}")
            formatted.append(f"Assistant: {item.get('answer', '')}")
        return "\n".join(formatted[-12:])

    def _append_session_turn(self, session_id: str, question: str, answer: str) -> None:
        max_turns = max(2, int(self.settings.chatbot_memory_turns))
        with self._memory_lock:
            if session_id not in self._session_memory:
                self._session_memory[session_id] = deque(maxlen=max_turns)
            self._session_memory[session_id].append(
                {
                    "question": question[:1000],
                    "answer": answer[:2000],
                }
            )

    def _analyze_question_intent(self, question: str) -> Dict[str, bool]:
        """Analyze question to determine which services/data sources to query."""
        q_lower = question.lower()
        
        intent = {
            "document": False,
            "lifecycle": False,
            "risk": False,
            "outcome": False,
            "event": False,
            "relationship": False,
            "statistics": False,
            "tech_stack": False,
        }
        
        # Document-related keywords
        doc_keywords = ["document", "file", "upload", "content", "text", "pdf", "invoice", "order", "report", "contract"]
        if any(kw in q_lower for kw in doc_keywords):
            intent["document"] = True
        
        # Lifecycle-related keywords
        lifecycle_keywords = ["lifecycle", "process", "workflow", "status", "stage", "phase"]
        if any(kw in q_lower for kw in lifecycle_keywords) or re.search(r"lifecycle[_-]?[a-z0-9]+", q_lower, re.IGNORECASE):
            intent["lifecycle"] = True
        
        # Risk-related keywords
        risk_keywords = ["risk", "danger", "alert", "warning", "threat", "vulnerability", "score", "prediction"]
        if any(kw in q_lower for kw in risk_keywords):
            intent["risk"] = True
        
        # Outcome-related keywords
        outcome_keywords = ["outcome", "result", "conclusion", "final", "end result", "achievement"]
        if any(kw in q_lower for kw in outcome_keywords):
            intent["outcome"] = True
        
        # Event-related keywords
        event_keywords = ["event", "activity", "action", "occurrence", "incident", "happened", "when"]
        if any(kw in q_lower for kw in event_keywords):
            intent["event"] = True
        
        # Relationship/graph keywords
        relationship_keywords = ["related", "connected", "linked", "relationship", "association", "graph", "network"]
        if any(kw in q_lower for kw in relationship_keywords):
            intent["relationship"] = True
        
        # Statistics/count keywords
        stats_keywords = ["how many", "count", "number", "total", "statistics", "stats", "summary", "overview"]
        if any(kw in q_lower for kw in stats_keywords):
            intent["statistics"] = True
        
        # Tech stack keywords
        tech_keywords = ["tech stack", "architecture", "database", "neo4j", "qdrant", "postgres", "system", "infrastructure"]
        if any(kw in q_lower for kw in tech_keywords):
            intent["tech_stack"] = True
        
        # If no specific intent detected, enable all for comprehensive search
        if not any(intent.values()):
            intent = {k: True for k in intent.keys()}
            logger.debug("No specific intent detected, enabling all data sources for comprehensive search")
        
        return intent

    def _route_to_services(self, question: str, intent: Dict[str, bool], is_list_question: bool = False) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Route question to appropriate services based on intent."""
        chunks: List[str] = []
        sources: List[Dict[str, Any]] = []
        q_lower = question.lower()
        
        # For list questions about lifecycles, get documents efficiently in one query
        if is_list_question and (intent.get("lifecycle") or "lifecycle" in q_lower):
            try:
                driver = get_neo4j_driver()
                try:
                    with driver.session() as session:
                        # Get lifecycles with document IDs from Neo4j
                        result = session.run("""
                            MATCH (l:Lifecycle)
                            OPTIONAL MATCH (l)-[:HAS_DOCUMENT]->(d:Document)
                            WITH l, 
                                 collect(DISTINCT {doc_id: d.document_id, filename: d.filename, type: d.document_type}) as docs
                            RETURN l.lifecycle_id as id, 
                                   l.status as status, 
                                   [doc IN docs WHERE doc.doc_id IS NOT NULL | doc.doc_id] as doc_ids,
                                   docs
                            ORDER BY l.lifecycle_id ASC
                            LIMIT 50
                        """)
                        
                        # Collect all document IDs first
                        all_doc_ids = set()
                        records_list = []
                        for record in result:
                            doc_ids = record.get("doc_ids", [])
                            all_doc_ids.update(doc_ids)
                            records_list.append(record)
                        
                        # Get filenames from Qdrant for collected document IDs
                        qdrant_filenames = {}
                        if all_doc_ids:
                            try:
                                qconf = get_qdrant_connection()
                                qclient = QdrantClient(host=qconf.host, port=qconf.port)
                                offset = None
                                found_count = 0
                                while found_count < len(all_doc_ids):
                                    points, next_offset = qclient.scroll(
                                        collection_name="documents",
                                        scroll_filter=None,
                                        limit=200,
                                        offset=offset,
                                        with_payload=True,
                                        with_vectors=False,
                                    )
                                    if not points:
                                        break
                                    for point in points:
                                        payload = point.payload or {}
                                        doc_id = payload.get("document_id")
                                        if doc_id in all_doc_ids:
                                            filename = payload.get("filename")
                                            if filename:
                                                qdrant_filenames[doc_id] = filename
                                                found_count += 1
                                    if next_offset is None:
                                        break
                                    offset = next_offset
                            except Exception as e:
                                logger.warning(f"Failed to get filenames from Qdrant: {e}")
                        
                        # Build lifecycle list with enriched document info
                        lifecycle_list = []
                        for record in records_list:
                            docs = record.get("docs", [])
                            # Filter out null documents and enrich with Qdrant filenames
                            enriched_docs = []
                            for doc in docs:
                                doc_id = doc.get("doc_id")
                                if doc_id:
                                    # Try Neo4j filename first, then Qdrant, then fallback
                                    filename = doc.get("filename")
                                    if not filename or filename == "None":
                                        filename = qdrant_filenames.get(doc_id)
                                    if not filename:
                                        # Last resort: try to get from stored file
                                        try:
                                            from core.config import get_settings
                                            settings = get_settings()
                                            upload_dir = Path(settings.upload_dir)
                                            file_pattern = f"{doc_id}_*"
                                            matching_files = list(upload_dir.glob(file_pattern))
                                            if matching_files:
                                                stored_name = matching_files[0].name
                                                if "_" in stored_name:
                                                    filename = stored_name.split("_", 1)[1]
                                                else:
                                                    filename = stored_name
                                        except:
                                            filename = None
                                    
                                    doc_type = doc.get("type") or "Document"
                                    if filename and filename != "None":
                                        enriched_docs.append({
                                            "filename": filename,
                                            "type": doc_type
                                        })
                            
                            lifecycle_list.append({
                                "id": record["id"],
                                "status": record["status"] or "unknown",
                                "doc_count": len(enriched_docs),
                                "documents": enriched_docs
                            })
                        
                        if lifecycle_list:
                            # Format in a clean, structured way for LLM
                            lifecycle_info = "### Existing Lifecycles\n\n"
                            for lc in lifecycle_list:
                                lifecycle_info += f"- **Lifecycle ID**: `{lc['id']}`\n"
                                lifecycle_info += f"  - **Status**: {lc['status'].title()}\n"
                                lifecycle_info += f"  - **Document Count**: {lc['doc_count']}\n"
                                
                                if lc['documents'] and len(lc['documents']) > 0:
                                    lifecycle_info += f"\n  ### Documents Associated with the Lifecycle\n"
                                    for idx, doc in enumerate(lc['documents'][:10], 1):  # Limit to 10 docs per lifecycle
                                        doc_type = doc.get('type', 'Document')
                                        doc_filename = doc.get('filename', '')
                                        # Clean up filename - remove None, empty strings, etc.
                                        if doc_filename and doc_filename.strip() and doc_filename.lower() != "none" and doc_filename.lower() != "unknown":
                                            lifecycle_info += f"  {idx}. **{doc_type}**: `{doc_filename}`\n"
                                        else:
                                            lifecycle_info += f"  {idx}. **{doc_type}**: (filename not available)\n"
                                lifecycle_info += "\n"
                            
                            chunks.append(lifecycle_info)
                            sources.append(self._make_source("neo4j", "lifecycles", "Lifecycle list", f"{len(lifecycle_list)} lifecycles found"))
                            # Return early for list questions to avoid other queries
                            return chunks, sources
                finally:
                    driver.close()
            except Exception as e:
                logger.warning(f"Failed to get lifecycle list: {e}")
        
        # Route to Neo4j (Lifecycle Service) for lifecycle, event, relationship queries
        if intent.get("lifecycle") or intent.get("event") or intent.get("relationship"):
            try:
                # Extract lifecycle IDs from question
                lifecycle_matches = re.findall(r"lifecycle[_-]?([a-z0-9_]+)", q_lower, re.IGNORECASE)
                lifecycle_ids = [m.replace("-", "_") for m in lifecycle_matches] if lifecycle_matches else []
                
                # If specific lifecycle mentioned, get details
                if lifecycle_ids:
                    for lc_id in lifecycle_ids[:3]:  # Limit to 3 lifecycles
                        lc_chunks, lc_sources = self._get_lifecycle_details(lc_id)
                        if lc_chunks:
                            chunks.append(lc_chunks)
                            sources.extend(lc_sources)
                else:
                    # Query all lifecycles efficiently with document counts
                    try:
                        driver = get_neo4j_driver()
                        try:
                            with driver.session() as session:
                                # Single efficient query to get lifecycles with document and event counts
                                result = session.run("""
                                    MATCH (l:Lifecycle)
                                    OPTIONAL MATCH (l)-[:HAS_DOCUMENT]->(d:Document)
                                    OPTIONAL MATCH (l)-[:HAS_EVENT]->(e:Event)
                                    WITH l, 
                                         count(DISTINCT d) as doc_count,
                                         count(DISTINCT e) as event_count
                                    RETURN l.lifecycle_id as id, 
                                           l.status as status, 
                                           doc_count,
                                           event_count
                                    ORDER BY l.lifecycle_id ASC
                                    LIMIT 50
                                """)
                                
                                lifecycle_list = []
                                for record in result:
                                    lifecycle_list.append({
                                        "id": record["id"],
                                        "status": record["status"] or "unknown",
                                        "doc_count": record["doc_count"] or 0,
                                        "event_count": record["event_count"] or 0
                                    })
                                
                                if lifecycle_list:
                                    # Format for LLM in a clean structure
                                    lifecycle_info = "### Existing Lifecycles\n\n"
                                    for lc in lifecycle_list:
                                        lifecycle_info += f"- **Lifecycle ID**: `{lc['id']}`\n"
                                        lifecycle_info += f"  - **Status**: {lc['status'].title()}\n"
                                        lifecycle_info += f"  - **Document Count**: {lc['doc_count']}\n"
                                        lifecycle_info += f"  - **Event Count**: {lc['event_count']}\n\n"
                                    
                                    chunks.append(lifecycle_info)
                                    sources.append(self._make_source("neo4j", "lifecycles", "Lifecycle list", f"{len(lifecycle_list)} lifecycles found"))
                        finally:
                            driver.close()
                    except Exception as e:
                        logger.warning(f"Failed to query Neo4j for lifecycle overview: {e}")
            except Exception as e:
                logger.warning(f"Failed to route to lifecycle service: {e}")
        
        # Route to Prediction Service for risk queries
        if intent.get("risk"):
            try:
                # Extract lifecycle IDs for risk queries
                lifecycle_matches = re.findall(r"lifecycle[_-]?([a-z0-9_]+)", q_lower, re.IGNORECASE)
                lifecycle_ids = [m.replace("-", "_") for m in lifecycle_matches] if lifecycle_matches else []
                
                if lifecycle_ids:
                    # Get risk for specific lifecycles
                    for lc_id in lifecycle_ids[:3]:
                        try:
                            prediction = self.prediction_service.predict_risk(lc_id)
                            risk_info = (
                                f"Risk assessment for {lc_id}:\n"
                                f"- Risk Score: {round(prediction.risk_score * 100)}%\n"
                                f"- Risk Label: {prediction.risk_label.upper()}\n"
                                f"- Drivers: {', '.join(prediction.drivers[:3]) if prediction.drivers else 'None'}\n"
                                f"- Explanation: {prediction.explanation[:200]}"
                            )
                            chunks.append(risk_info)
                            sources.append(self._make_source("prediction", lc_id, f"Risk for {lc_id}", f"Risk: {round(prediction.risk_score * 100)}%"))
                        except Exception as e:
                            logger.warning(f"Failed to get risk for {lc_id}: {e}")
                else:
                    # Get risk overview for all lifecycles
                    try:
                        driver = get_neo4j_driver()
                        try:
                            with driver.session() as session:
                                result = session.run("MATCH (l:Lifecycle) RETURN l.lifecycle_id as id LIMIT 10")
                                lifecycle_ids = [record["id"] for record in result]
                                
                                risk_summary = []
                                for lc_id in lifecycle_ids[:5]:  # Limit to 5
                                    try:
                                        pred = self.prediction_service.predict_risk(lc_id)
                                        risk_summary.append(f"{lc_id}: {round(pred.risk_score * 100)}% ({pred.risk_label})")
                                    except:
                                        continue
                                
                                if risk_summary:
                                    chunks.append("Risk overview:\n" + "\n".join(risk_summary))
                                    sources.append(self._make_source("prediction", "overview", "Risk overview", risk_summary[0]))
                        finally:
                            driver.close()
                    except Exception as e:
                        logger.warning(f"Failed to get risk overview: {e}")
            except Exception as e:
                logger.warning(f"Failed to route to prediction service: {e}")
        
        # Route to PostgreSQL (Outcome Service) for outcome queries
        if intent.get("outcome"):
            try:
                lifecycle_matches = re.findall(r"lifecycle[_-]?([a-z0-9_]+)", q_lower, re.IGNORECASE)
                lifecycle_ids = [m.replace("-", "_") for m in lifecycle_matches] if lifecycle_matches else []
                
                if lifecycle_ids:
                    for lc_id in lifecycle_ids[:3]:
                        try:
                            outcomes = self.outcome_service.list_outcomes(lifecycle_id=lc_id, limit=10)
                            if outcomes:
                                outcome_info = f"Outcomes for {lc_id}:\n"
                                for outcome in outcomes[:5]:
                                    outcome_info += f"- {outcome.outcome_type}: {outcome.value} (recorded: {outcome.recorded_at})\n"
                                
                                # Also get stats
                                stats = self.outcome_service.get_outcome_stats(lc_id)
                                if stats:
                                    outcome_info += "\nStatistics:\n"
                                    for outcome_type, stat in stats.items():
                                        outcome_info += f"- {outcome_type}: avg={stat['avg']:.2f}, total={stat['total']:.2f}, count={stat['count']}\n"
                                
                                chunks.append(outcome_info)
                                sources.append(self._make_source("outcome", lc_id, f"Outcomes for {lc_id}", f"{len(outcomes)} outcomes"))
                        except Exception as e:
                            logger.warning(f"Failed to get outcomes for {lc_id}: {e}")
                else:
                    # Get all outcomes overview
                    try:
                        all_outcomes = self.outcome_service.list_outcomes(limit=10)
                        if all_outcomes:
                            outcome_summary = []
                            for outcome in all_outcomes:
                                outcome_summary.append(f"{outcome.lifecycle_id}: {outcome.outcome_type}={outcome.value}")
                            chunks.append("Outcomes overview:\n" + "\n".join(outcome_summary))
                            sources.append(self._make_source("outcome", "all", "Outcomes overview", outcome_summary[0] if outcome_summary else ""))
                    except Exception as e:
                        logger.warning(f"Failed to get outcomes overview: {e}")
            except Exception as e:
                logger.warning(f"Failed to route to outcome service: {e}")
        
        # Route to Qdrant for document queries (handled separately in _retrieve_documents)
        # This is already done in the main flow, so we don't duplicate here
        
        return chunks, sources

    def _run_deterministic_tools(self, question: str) -> Tuple[List[str], List[Dict[str, Any]]]:
        chunks: List[str] = []
        sources: List[Dict[str, Any]] = []
        q = question.lower()

        # Always include baseline platform summary for stack-level questions.
        summary, summary_sources = self._get_platform_summary()
        if summary:
            chunks.append(summary)
            sources.extend(summary_sources)

        # Match lifecycle IDs like lifecycle_001, lifecycle-procurement-001, lifecycle001
        # But NOT "lifecycles" (plural) or just "lifecycle" alone
        lifecycle_match = re.search(r"lifecycle[_-][a-z0-9]+|lifecycle[a-z0-9]{2,}", q, flags=re.IGNORECASE)
        lifecycle_id = lifecycle_match.group(0).replace("-", "_") if lifecycle_match else None

        if lifecycle_id:
            lifecycle_chunk, lifecycle_sources = self._get_lifecycle_details(lifecycle_id)
            if lifecycle_chunk:
                chunks.append(lifecycle_chunk)
                sources.extend(lifecycle_sources)

        if any(k in q for k in ["how many", "count", "number", "active", "risk", "document", "lifecycle"]):
            stats_chunk, stats_sources = self._get_system_counts()
            if stats_chunk:
                chunks.append(stats_chunk)
                sources.extend(stats_sources)

        return chunks, sources

    def _get_platform_summary(self) -> Tuple[str, List[Dict[str, Any]]]:
        backend_root = Path(__file__).resolve().parents[1]
        repo_root = backend_root.parent
        requirements = backend_root / "requirements.txt"
        frontend_pkg = repo_root / "frontend" / "package.json"

        req_lines: List[str] = []
        if requirements.exists():
            req_lines = [line.strip() for line in requirements.read_text(encoding="utf-8").splitlines() if line.strip()]

        frontend_name = ""
        frontend_deps = 0
        try:
            if frontend_pkg.exists():
                pkg = json.loads(frontend_pkg.read_text(encoding="utf-8"))
                frontend_name = pkg.get("name", "frontend")
                frontend_deps = len(pkg.get("dependencies", {}) or {})
        except Exception:
            pass

        core_deps = [
            dep for dep in req_lines
            if dep.lower().startswith(("fastapi", "uvicorn", "neo4j", "qdrant-client", "sentence-transformers", "torch"))
        ]

        summary = (
            "Tech stack summary:\n"
            f"- Backend: FastAPI service with Neo4j + Qdrant + PostgreSQL integrations.\n"
            f"- Core backend deps: {', '.join(core_deps[:8]) if core_deps else 'unavailable'}.\n"
            f"- Frontend: {frontend_name or 'React/Vite app'} with {frontend_deps} dependencies.\n"
            "- Retrieval: embedding-based document indexing in Qdrant."
        )
        sources = [
            self._make_source(
                source_type="file",
                source_id="backend/requirements.txt",
                title="Backend dependencies",
                snippet=(core_deps[0] if core_deps else "requirements available"),
            ),
            self._make_source(
                source_type="file",
                source_id="frontend/package.json",
                title="Frontend package metadata",
                snippet=f"{frontend_name or 'frontend'} deps: {frontend_deps}",
            ),
            self._make_source(
                source_type="file",
                source_id="backend/main.py",
                title="Backend app entrypoint",
                snippet="FastAPI app with routers for chatbot/dashboard/documents/lifecycles/outcomes/predictions",
            ),
        ]
        return summary, sources

    def _get_lifecycle_details(self, lifecycle_id: str) -> Tuple[str, List[Dict[str, Any]]]:
        try:
            lifecycle = self.lifecycle_service.get_lifecycle(lifecycle_id)
            if lifecycle.status == "not_found":
                return f"Lifecycle {lifecycle_id} was not found.", [
                    self._make_source("lifecycle", lifecycle_id, "Lifecycle lookup", "Lifecycle not found")
                ]

            event_types = [e.event_type for e in lifecycle.events]
            prediction = self.prediction_service.predict_risk(lifecycle_id)
            detail = (
                f"Lifecycle detail for {lifecycle_id}:\n"
                f"- Status: {lifecycle.status}\n"
                f"- Events: {len(lifecycle.events)}\n"
                f"- Recent event types: {', '.join(event_types[-5:]) if event_types else 'none'}\n"
                f"- Risk: {round(prediction.risk_score * 100)}% ({prediction.risk_label})"
            )
            return detail, [
                self._make_source(
                    "lifecycle",
                    lifecycle_id,
                    "Lifecycle details",
                    f"status={lifecycle.status}, events={len(lifecycle.events)}",
                ),
                self._make_source(
                    "prediction",
                    lifecycle_id,
                    "Lifecycle risk",
                    f"risk={round(prediction.risk_score * 100)}% ({prediction.risk_label})",
                ),
            ]
        except Exception as exc:
            logger.warning("Failed to fetch lifecycle details for chatbot: %s", exc)
            return "", []

    def _get_system_counts(self) -> Tuple[str, List[Dict[str, Any]]]:
        chunks: List[str] = []
        sources: List[Dict[str, Any]] = []

        # Qdrant document count via scroll (avoids strict schema parsing issues).
        try:
            qconf = get_qdrant_connection()
            qclient = QdrantClient(host=qconf.host, port=qconf.port)
            total_docs = 0
            offset = None
            while True:
                points, next_offset = qclient.scroll(
                    collection_name="documents",
                    scroll_filter=None,
                    limit=200,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                total_docs += len(points or [])
                if next_offset is None:
                    break
                offset = next_offset
            chunks.append(f"Document index count: {total_docs}")
            sources.append(
                self._make_source(
                    "qdrant",
                    "documents",
                    "Qdrant documents collection",
                    f"document_count={total_docs}",
                )
            )
        except Exception as exc:
            logger.warning("Chatbot document count query failed: %s", exc)

        # Neo4j lifecycle/risk counts.
        try:
            driver = get_neo4j_driver()
            try:
                with driver.session() as session:
                    lc_count = session.run("MATCH (l:Lifecycle) RETURN count(l) as c").single()
                    active_count = session.run(
                        """
                        MATCH (l:Lifecycle)
                        WHERE l.status IN ['active', 'pending', 'in_progress']
                           OR EXISTS { MATCH (l)-[:HAS_EVENT]->(:Event) }
                        RETURN count(DISTINCT l) as c
                        """
                    ).single()
                    risk_count = session.run(
                        """
                        MATCH (l:Lifecycle)-[:HAS_EVENT]->(e:Event)
                        WHERE toUpper(e.event_type) CONTAINS 'RISK' OR toUpper(e.event_type) CONTAINS 'ALERT'
                        RETURN count(DISTINCT l) as c
                        """
                    ).single()
                chunks.append(
                    f"Lifecycle counts: total={int(lc_count['c']) if lc_count else 0}, "
                    f"active={int(active_count['c']) if active_count else 0}, "
                    f"with_risk_alerts={int(risk_count['c']) if risk_count else 0}"
                )
                sources.append(
                    self._make_source(
                        "neo4j",
                        "lifecycle_stats",
                        "Neo4j lifecycle aggregates",
                        chunks[-1],
                    )
                )
            finally:
                driver.close()
        except Exception as exc:
            logger.warning("Chatbot lifecycle stats query failed: %s", exc)

        return ("\n".join(chunks), sources) if chunks else ("", [])

    def _retrieve_documents(self, question: str) -> Tuple[List[str], List[Dict[str, Any]]]:
        chunks: List[str] = []
        sources: List[Dict[str, Any]] = []
        if len(question) < 3:
            return chunks, sources

        try:
            qconf = get_qdrant_connection()
            qclient = QdrantClient(host=qconf.host, port=qconf.port)
            embedder = self._get_embedder()
            query_vec = embedder.embed(question) if embedder else None

            # Get document parser to read file content
            from services.document_parser import DocumentParser
            from core.config import get_settings
            parser = DocumentParser()
            settings = get_settings()
            upload_dir = Path(settings.upload_dir)

            if query_vec:
                _resp = qclient.query_points(
                    collection_name="documents",
                    query=query_vec,
                    limit=5,
                    with_payload=True,
                    with_vectors=False,
                )
                hits = _resp.points if hasattr(_resp, "points") else _resp
                for hit in hits:
                    payload = hit.payload or {}
                    document_id = payload.get("document_id")
                    filename = payload.get("filename", "unknown")
                    doc_type = payload.get("document_type", "Document")
                    lifecycle_id = payload.get("lifecycle_id", "unknown")
                    entities = payload.get("entities", []) or []
                    
                    # Retrieve actual document content for RAG
                    doc_content = ""
                    if document_id:
                        try:
                            # Find the stored file
                            file_pattern = f"{document_id}_*"
                            matching_files = list(upload_dir.glob(file_pattern))
                            if matching_files:
                                file_path = matching_files[0]
                                parsed = parser.parse(str(file_path))
                                doc_content = parsed.get("text", "")[:2000]  # Limit to 2000 chars per doc
                        except Exception as e:
                            logger.warning(f"Failed to retrieve content for document {document_id}: {e}")
                    
                    # Build context chunk with actual content
                    if doc_content:
                        chunk = (
                            f"Document: {filename}\n"
                            f"Type: {doc_type}\n"
                            f"Lifecycle: {lifecycle_id}\n"
                            f"Content:\n{doc_content}\n"
                            f"Entities: {', '.join(str(e) for e in entities[:5])}"
                        )
                    else:
                        # Fallback to metadata only if content unavailable
                        chunk = (
                            f"Document: {filename} | type={doc_type} | lifecycle={lifecycle_id} | "
                            f"entities_sample={entities[:5]}"
                        )
                    
                    chunks.append(chunk)
                    sources.append(
                        self._make_source(
                            source_type="document",
                            source_id=document_id or filename,
                            title=filename,
                            snippet=doc_content[:200] if doc_content else f"type={doc_type}, lifecycle={lifecycle_id}",
                        )
                    )
            else:
                # Lightweight fallback metadata scan with content retrieval
                offset = None
                q_lower = question.lower()
                found = 0
                while found < 5:
                    points, next_offset = qclient.scroll(
                        collection_name="documents",
                        scroll_filter=None,
                        limit=100,
                        offset=offset,
                        with_payload=True,
                        with_vectors=False,
                    )
                    if not points:
                        break
                    for point in points:
                        payload = point.payload or {}
                        haystack = " ".join(
                            str(payload.get(k, "")) for k in ("filename", "document_type", "lifecycle_id")
                        ).lower()
                        if q_lower in haystack:
                            document_id = payload.get("document_id")
                            filename = payload.get("filename", "unknown")
                            doc_type = payload.get("document_type", "Document")
                            
                            # Retrieve document content for RAG
                            doc_content = ""
                            if document_id:
                                try:
                                    file_pattern = f"{document_id}_*"
                                    matching_files = list(upload_dir.glob(file_pattern))
                                    if matching_files:
                                        file_path = matching_files[0]
                                        parsed = parser.parse(str(file_path))
                                        doc_content = parsed.get("text", "")[:2000]
                                except Exception as e:
                                    logger.warning(f"Failed to retrieve content for document {document_id}: {e}")
                            
                            if doc_content:
                                chunk = (
                                    f"Document: {filename}\n"
                                    f"Type: {doc_type}\n"
                                    f"Content:\n{doc_content}"
                                )
                            else:
                                chunk = f"Document match: {filename} | type={doc_type}"
                            
                            chunks.append(chunk)
                            sources.append(
                                self._make_source(
                                    source_type="document",
                                    source_id=document_id or filename,
                                    title=filename,
                                    snippet=doc_content[:200] if doc_content else f"type={doc_type}",
                                )
                            )
                            found += 1
                            if found >= 5:
                                break
                    if next_offset is None:
                        break
                    offset = next_offset
        except Exception as exc:
            logger.warning("Chatbot document retrieval failed: %s", exc)

        return chunks, sources

    def _retrieve_tech_stack_context(self, question: str) -> Tuple[List[str], List[Dict[str, Any]]]:
        q = question.lower()
        chunks: List[str] = []
        sources: List[Dict[str, Any]] = []
        backend_root = Path(__file__).resolve().parents[1]
        repo_root = backend_root.parent

        interest_terms = ("tech stack", "architecture", "backend", "frontend", "database", "api", "model", "embedding")
        if not any(term in q for term in interest_terms):
            return chunks, sources

        file_map = {
            "backend/main.py": backend_root / "main.py",
            "backend/core/config.py": backend_root / "core" / "config.py",
            "backend/requirements.txt": backend_root / "requirements.txt",
            "frontend/package.json": repo_root / "frontend" / "package.json",
        }
        for source_id, file_path in file_map.items():
            if not file_path.exists():
                continue
            try:
                text = file_path.read_text(encoding="utf-8")
                snippet = text[:1200]
                chunks.append(f"{source_id} snippet:\n{snippet}")
                snippet_text = snippet[:240].replace("\n", " ").strip()
                sources.append(
                    self._make_source(
                        source_type="file",
                        source_id=source_id,
                        title=source_id,
                        snippet=snippet_text,
                    )
                )
            except Exception:
                continue

        return chunks, sources

    def _build_context(self, chunks: List[str]) -> str:
        if not chunks:
            return ""
        text = "\n\n".join(chunks)
        max_chars = max(2000, int(self.settings.chatbot_max_context_chars))
        return text[:max_chars]

    def _synthesize_with_llm(
        self,
        question: str,
        sub_questions: List[str],
        context: str,
        session_context: str = "",
    ) -> Optional[str]:
        # Check if we have OpenAI API key or Ollama configured
        has_openai = bool(self.settings.openai_api_key and self.settings.openai_api_key.strip())
        use_ollama = self.settings.use_ollama
        
        # Prioritize OpenAI if API key is available (unless explicitly using Ollama)
        if not has_openai and not use_ollama:
            logger.debug("No LLM configured: OpenAI API key not set and Ollama not enabled")
            return None
        
        # Log which LLM is being used
        if use_ollama:
            logger.info(f"Using Ollama model: {self.settings.ollama_model}")
        elif has_openai:
            logger.info(f"Using OpenAI model: {self.settings.openai_model} (API key configured)")
        
        # Allow LLM to handle even simple queries with minimal context for better conversational responses
        q_lower = question.lower().strip()
        is_simple_query = not context.strip() or len(context.strip()) < 50
        
        # For simple queries, provide a helpful system context
        if is_simple_query:
            system_context = (
                "You are a friendly and professional technical assistant for a lifecycle intelligence platform. "
                "The system tracks documents, lifecycles, risk assessments, and provides insights on business processes. "
                "Be conversational, helpful, and concise. If asked about capabilities, mention you can help with "
                "lifecycle data, document queries, risk analysis, and technical stack information."
            )
        else:
            system_context = (
                "You are a technical assistant for a lifecycle intelligence platform.\n"
                "Use ONLY provided context and be explicit about uncertainty.\n"
                "If context is missing for part of the question, say what is missing.\n"
                "Answer in concise, actionable language and include short bullet points when useful.\n"
                "IMPORTANT: When presenting lists or structured data, preserve the formatting from the context. "
                "If the context contains markdown formatting (like ### headers, **bold**, `code`, etc.), use it in your response. "
                "Do not add unnecessary 'Sources:' sections or extra formatting that wasn't in the context."
            )

        prompt = (
            f"{system_context}\n\n"
            f"Original question: {question}\n"
            f"Sub-questions: {sub_questions}\n\n"
            "Recent conversation (short-term memory):\n"
            f"{session_context or '[none]'}\n\n"
        )
        
        if context.strip():
            prompt += f"Context:\n{context}"
        else:
            prompt += "No specific context retrieved. Provide a helpful, friendly response based on your role as a lifecycle intelligence assistant."

        # Configure for Ollama or OpenAI
        if use_ollama:
            base_url = self.settings.ollama_base_url.rstrip('/')
            model = self.settings.ollama_model
            headers = {
                "Content-Type": "application/json",
            }
            # Ollama uses /api/chat endpoint
            url = f"{base_url}/api/chat"
        else:
            base_url = self.settings.openai_base_url.rstrip('/')
            model = self.settings.openai_model
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.openai_api_key}",
            }
            # OpenAI uses /chat/completions endpoint
            url = f"{base_url}/chat/completions"
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a precise technical analyst."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        
        # Ollama uses slightly different payload format
        if use_ollama:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a precise technical analyst."},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            }
        
        try:
            req = url_request.Request(
                url=url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with url_request.urlopen(req, timeout=30) as resp:  # Longer timeout for local Ollama
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            
            # Handle different response formats
            if use_ollama:
                # Ollama returns {"message": {"content": "..."}}
                return data.get("message", {}).get("content", "").strip()
            else:
                # OpenAI returns {"choices": [{"message": {"content": "..."}}]}
                return data["choices"][0]["message"]["content"].strip()
        except (url_error.URLError, KeyError, ValueError, TimeoutError) as exc:
            logger.warning("LLM synthesis failed, using fallback: %s", exc)
            return None

    def _synthesize_without_llm(self, question: str, deterministic_chunks: List[str], all_chunks: List[str], session_context: str = "") -> str:
        # Deterministic fallback with context transparency.
        q_lower = question.lower().strip()
        
        # For simple queries without context, provide a friendly response
        if not all_chunks:
            return (
                "I'm here to help! I can assist you with:\n"
                "• Finding information about specific lifecycles (e.g., 'Tell me about lifecycle_procurement_001')\n"
                "• Document counts and statistics\n"
                "• Risk assessments and trends\n"
                "• Technical stack details\n\n"
                "What would you like to explore?"
            )

        # Build a more conversational response
        lines = []
        
        # Start with a friendly intro if we have data
        if deterministic_chunks:
            lines.append("Here's what I found in the system:")
        else:
            lines.append("I found some relevant information:")
        
        if session_context:
            lines.append("(Using context from our recent conversation)")
        
        # Add key findings
        for chunk in deterministic_chunks[:4]:
            # Make chunks more readable
            if ":" in chunk:
                lines.append(f"• {chunk}")
            else:
                lines.append(f"• {chunk}")

        if not deterministic_chunks and all_chunks:
            lines.append("• Retrieved relevant context from the system")

        # Add helpful note about LLM if not configured
        if not self.settings.use_ollama and not self.settings.openai_api_key:
            lines.append(
                "\n💡 Tip: For more natural, synthesized answers, configure either:\n"
                "  • `USE_OLLAMA=true` and `OLLAMA_MODEL=llama3` (local, no API key needed)\n"
                "  • `OPENAI_API_KEY=...` (cloud-based)"
            )
        
        return "\n".join(lines)

    def _get_embedder(self) -> Optional[EmbeddingService]:
        if self._embedder is not None:
            return self._embedder
        try:
            self._embedder = EmbeddingService()
            return self._embedder
        except Exception as exc:
            logger.warning("Embedding model unavailable for chatbot retrieval: %s", exc)
            self._embedder = None
            return None

    @staticmethod
    def _dedupe_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        deduped = []
        for source in sources:
            src_type = source.get("type", "")
            src_id = source.get("id", "")
            key = f"{src_type}:{src_id}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(source)
        return deduped

    @staticmethod
    def _make_source(
        source_type: str,
        source_id: str,
        title: str = "",
        snippet: str = "",
    ) -> Dict[str, Any]:
        payload = {
            "type": source_type,
            "id": source_id,
        }
        if title:
            payload["title"] = title[:160]
        if snippet:
            payload["snippet"] = snippet[:500]
        return payload
