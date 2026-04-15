"""
WebsiteCrawler — Deep-crawl an organization's website and ingest content into Qdrant.

Architecture (enterprise-grade per spec):
  1. Admin pastes org URL → POST /website/connect
  2. Seed: sitemap.xml + base URL + navbar/footer links
  3. BFS crawl (depth-limited, domain-restricted, loop-safe)
  4. Per page: fetch → JS-render (Playwright if available, else requests) →
     full DOM extraction → interaction for hidden content → parse
  5. Extract: main text, headings, JSON-LD, stats, people/leadership, testimonials,
     contact info, navigation structure, metadata, links
  6. Classify page type + section type
  7. SHA-256 content hash → skip unchanged, version changed pages
  8. Chunk (500-800 chars, 100 overlap, heading-aware)
  9. Batch embed → upsert into Qdrant `phase1_documents`
     metadata: source_type="website", url, page_type, section, content_hash,
               version, timestamp, entities, stats, org_name, connection_id

Incremental: delete old URL vectors → insert updated chunks
Background: crawl runs in daemon thread; returns connection_id immediately
"""

from __future__ import annotations

import hashlib
import heapq
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests

try:
    from bs4 import BeautifulSoup as _BS4
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

logger = logging.getLogger(__name__)

# ── Config constants ──────────────────────────────────────────────────────────
MAX_PAGES        = 500
REQUEST_TIMEOUT  = 15
CRAWL_DELAY      = 0.25        # polite crawl delay (seconds)
MAX_DEPTH        = 6           # BFS depth limit
CHUNK_SIZE       = 800         # characters
CHUNK_OVERLAP    = 100
BATCH_EMBED_SIZE = 64

# URL priority scores — lower number = higher priority (heapq is min-heap)
_URL_PRIORITY: Dict[str, int] = {
    # Critical pages
    "home":        0,
    "about":       1,
    "services":    1,
    "solutions":   1,
    "products":    1,
    "contact":     1,
    "team":        2,
    "leadership":  2,
    "careers":     2,
    "pricing":     2,
    "faq":         2,
    "clients":     2,
    "portfolio":   2,
    "case-study":  2,
    "testimonials":2,
    # Medium
    "industry":    3,
    "resources":   3,
    "partners":    3,
    "technology":  3,
    "platform":    3,
    # Low
    "blog":        5,
    "news":        5,
    "events":      5,
    "press":       5,
    "legal":       6,
    "privacy":     6,
    "terms":       6,
    "cookie":      6,
    # Deprioritise / skip
    "tag":         9,
    "category":    9,
    "page":        8,
    "search":      9,
    "login":       9,
    "register":    9,
    "cart":        9,
    "checkout":    9,
    "wp-":         9,
}

# Patterns that should be skipped entirely
_SKIP_URL_PATTERNS = re.compile(
    r"(\.pdf$|\.jpg$|\.jpeg$|\.png$|\.gif$|\.svg$|\.ico$|\.css$|\.js$"
    r"|\.zip$|\.exe$|\.xml$|\?replytocom=|\?print=|\?lang=|/feed/?$"
    r"|/wp-json/|/xmlrpc\.php|/__utm|/amp/|/embed/)",
    re.IGNORECASE,
)

# ── Persistence ───────────────────────────────────────────────────────────────
# Connections are saved here so they survive server restarts.
_CONNECTIONS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "crawler_connections.json"
)


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class CrawlConnection:
    connection_id: str
    url: str
    org_name: str = ""
    status: str = "pending"       # pending | crawling | active | error | disconnected
    priority: str = "medium"      # high | medium | low  (used by scheduler)
    pages_found: int = 0
    pages_done: int = 0
    chunks_indexed: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    last_crawled: Optional[float] = None
    error: Optional[str] = None
    content_hashes: Dict[str, str] = field(default_factory=dict)  # url → sha256
    # Navigation graph: url → {title, parent, children, breadcrumb, page_type, depth}
    nav_graph: Dict[str, dict] = field(default_factory=dict)
    screenshots: Dict[str, str] = field(default_factory=dict)  # url → storage key


@dataclass
class PageData:
    url: str
    title: str
    description: str
    text: str
    headings: List[str]
    page_type: str
    section: str
    content_hash: str
    # Enriched extractions
    stats: List[dict]              # [{"label": "150+ Employees", "value": "150+"}]
    people: List[dict]             # [{"name": "...", "role": "...", "bio": "..."}]
    json_ld: List[dict]            # parsed JSON-LD objects
    contact_info: dict             # {phone, email, address, ...}
    og_tags: dict                  # og:title, og:description, og:image
    nav_links: List[str]           # navigation structure


# ── Main Crawler ───────────────────────────────────────────────────────────────

class WebsiteCrawler:
    """
    BFS website crawler that ingests pages into Qdrant.
    One singleton; each connection runs in its own daemon thread.
    """

    def __init__(self):
        self._connections: Dict[str, CrawlConnection] = {}
        self._lock = threading.Lock()
        self._threads: Dict[str, threading.Thread] = {}
        self._load_connections()   # restore from disk on startup

    # ── Persistence helpers ────────────────────────────────────────────────────

    def _save_connections(self):
        """Persist non-disconnected connections to JSON so they survive restarts."""
        try:
            data = []
            for c in self._connections.values():
                if c.status == "disconnected":
                    continue
                # Keep final statuses; reset transient states to "active" for persistence
                saved_status = c.status if c.status in ("active", "error") else "active"
                data.append({
                    "connection_id": c.connection_id,
                    "url":           c.url,
                    "org_name":      c.org_name,
                    "status":        saved_status,
                    "priority":      c.priority,
                    "pages_found":   c.pages_found,
                    "pages_done":    c.pages_done,
                    "chunks_indexed": c.chunks_indexed,
                    "started_at":    c.started_at,
                    "finished_at":   c.finished_at,
                    "last_crawled":  c.last_crawled,
                    "error":         c.error,
                    "content_hashes": c.content_hashes,
                    # Persist nav graph for navigation queries
                    "nav_graph":     c.nav_graph,
                })
            path = os.path.abspath(_CONNECTIONS_FILE)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("[Crawler] Could not save connections: %s", e)

    def _load_connections(self):
        """Restore connections from the JSON file on startup."""
        try:
            path = os.path.abspath(_CONNECTIONS_FILE)
            if not os.path.exists(path):
                return
            with open(path) as f:
                data = json.load(f)
            for item in data:
                cid = item.get("connection_id")
                if not cid:
                    continue
                conn = CrawlConnection(
                    connection_id=cid,
                    url=item.get("url", ""),
                    org_name=item.get("org_name", ""),
                    status=item.get("status", "active"),
                    priority=item.get("priority", "medium"),
                    pages_found=item.get("pages_found", 0),
                    pages_done=item.get("pages_done", 0),
                    chunks_indexed=item.get("chunks_indexed", 0),
                    started_at=item.get("started_at", time.time()),
                    finished_at=item.get("finished_at"),
                    last_crawled=item.get("last_crawled"),
                    error=item.get("error"),
                    content_hashes=item.get("content_hashes", {}),
                    nav_graph=item.get("nav_graph", {}),
                )
                self._connections[cid] = conn
            logger.info("[Crawler] Restored %d connection(s) from disk", len(self._connections))
        except Exception as e:
            logger.warning("[Crawler] Could not load connections: %s", e)

    # ── Public API ─────────────────────────────────────────────────────────────

    def connect(self, url: str, org_name: str = "", priority: str = "medium") -> str:
        """Start background crawl. Returns connection_id immediately."""
        url = url.strip().rstrip("/")
        if not url.startswith("http"):
            url = "https://" + url

        conn = CrawlConnection(
            connection_id=str(uuid.uuid4()),
            url=url,
            org_name=org_name or self._derive_org_name(url),
            priority=priority,
        )
        with self._lock:
            self._connections[conn.connection_id] = conn
        self._save_connections()

        self._spawn_crawl_thread(conn.connection_id)
        logger.info("[Crawler] Crawl started: %s (id=%s, priority=%s)", url, conn.connection_id, priority)
        return conn.connection_id

    def disconnect(self, connection_id: str, remove_vectors: bool = False):
        with self._lock:
            conn = self._connections.get(connection_id)
            if conn is None:
                raise ValueError(f"Connection {connection_id} not found")
            conn.status = "disconnected"
        self._save_connections()

        if remove_vectors:
            self._delete_connection_vectors(connection_id)
        logger.info("[Crawler] Disconnected %s (vectors_removed=%s)", connection_id, remove_vectors)

    def get_status(self, connection_id: str) -> Optional[dict]:
        with self._lock:
            conn = self._connections.get(connection_id)
            return self._conn_to_dict(conn) if conn else None

    def get_all_statuses(self) -> List[dict]:
        with self._lock:
            return [
                self._conn_to_dict(c) for c in self._connections.values()
                if c.status != "disconnected"
            ]

    def get_nav_graph(self, connection_id: str) -> Optional[dict]:
        """Return the navigation graph for a connection."""
        with self._lock:
            conn = self._connections.get(connection_id)
            return conn.nav_graph if conn else None

    def refresh_crawl(self, connection_id: str, force_reindex: bool = False) -> bool:
        """Trigger incremental re-crawl for an existing connection.

        force_reindex=True clears content_hashes so every page is re-indexed
        (use when chunks are missing despite pages having been crawled).
        """
        with self._lock:
            conn = self._connections.get(connection_id)
            if conn is None or conn.status == "crawling":
                return False
            # Clear hashes if forcing reindex OR if no chunks were ever indexed
            # (handles the case where previous crawl completed but embedding failed)
            needs_full_reindex = force_reindex or conn.chunks_indexed == 0
            conn.status = "pending"
            conn.pages_done = 0
            conn.pages_found = 0
            conn.chunks_indexed = 0
            conn.finished_at = None
            conn.error = None
            if needs_full_reindex:
                conn.content_hashes = {}

        self._spawn_crawl_thread(connection_id)
        return True

    def get_nav_graph(self, connection_id: str) -> Optional[dict]:
        """Return the navigation graph for a connection."""
        with self._lock:
            conn = self._connections.get(connection_id)
            return conn.nav_graph if conn else None

    def get_all_connections(self) -> List[CrawlConnection]:
        """Return all non-disconnected connections (for scheduler)."""
        with self._lock:
            return [c for c in self._connections.values() if c.status != "disconnected"]

    # ── Thread management ──────────────────────────────────────────────────────

    def _spawn_crawl_thread(self, connection_id: str):
        t = threading.Thread(
            target=self._crawl_worker,
            args=(connection_id,),
            name=f"crawler-{connection_id[:8]}",
            daemon=True,
        )
        self._threads[connection_id] = t
        t.start()

    # ── Worker ─────────────────────────────────────────────────────────────────

    def _score_url(self, url: str, depth: int) -> int:
        """Priority score for heapq min-heap. Lower = higher priority."""
        if _SKIP_URL_PATTERNS.search(url):
            return 999
        path = urlparse(url).path.lower()
        segments = [s for s in path.split("/") if s]
        for seg in segments:
            for kw, sc in _URL_PRIORITY.items():
                if kw in seg:
                    return sc + depth
        if not segments:
            return 0  # home page
        return 4 + depth

    def _update_nav_graph(
        self, conn: "CrawlConnection", url: str, page: "PageData",
        parent_url: str, depth: int
    ):
        """Build navigation graph entry for this page."""
        # Build breadcrumb from parent chain
        breadcrumb: List[str] = []
        cur = parent_url
        visited_bc: Set[str] = set()
        while cur and cur not in visited_bc and cur in conn.nav_graph:
            visited_bc.add(cur)
            parent_title = conn.nav_graph[cur].get("title", cur)
            breadcrumb.insert(0, parent_title)
            cur = conn.nav_graph[cur].get("parent", "")
        breadcrumb.append(page.title or url)

        entry = {
            "title":     page.title,
            "url":       url,
            "parent":    parent_url,
            "children":  [],
            "breadcrumb": " > ".join(breadcrumb),
            "page_type": page.page_type,
            "depth":     depth,
            "description": page.description,
        }
        conn.nav_graph[url] = entry

        # Register as child of parent
        if parent_url and parent_url in conn.nav_graph:
            if url not in conn.nav_graph[parent_url]["children"]:
                conn.nav_graph[parent_url]["children"].append(url)

    def _capture_screenshot(self, url: str, connection_id: str) -> Optional[str]:
        """
        Capture full-page screenshot with Playwright and store to MinIO/local.
        Returns storage key or None.
        """
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                page = context.new_page()
                page.goto(url, timeout=20000, wait_until="networkidle")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(800)
                screenshot_bytes = page.screenshot(full_page=True, type="jpeg", quality=70)
                browser.close()

            # Store to MinIO or local
            filename = f"screenshot_{connection_id}_{hashlib.md5(url.encode()).hexdigest()[:10]}.jpg"
            try:
                from services.storage_service import get_storage_service
                svc = get_storage_service()
                key = svc.store(screenshot_bytes, filename, content_type="image/jpeg", prefix="screenshots")
                return key
            except Exception as se:
                logger.debug("[Crawler] Screenshot storage failed: %s", se)
                return None
        except ImportError:
            return None
        except Exception as e:
            logger.debug("[Crawler] Screenshot failed for %s: %s", url, e)
            return None

    def _crawl_worker(self, connection_id: str):
        with self._lock:
            conn = self._connections.get(connection_id)
        if conn is None:
            return

        conn.status = "crawling"
        logger.info("[Crawler] Worker started for %s", conn.url)

        try:
            base_url = conn.url
            allowed_domain = urlparse(base_url).netloc

            # ── Priority queue: (score, counter, url, depth, parent_url) ──────
            pq: List[Tuple[int, int, str, int, str]] = []
            visited: Set[str] = set()
            _counter = 0

            def enqueue(u: str, depth: int, parent: str = ""):
                nonlocal _counter
                sc = self._score_url(u, depth)
                if sc < 999:
                    heapq.heappush(pq, (sc, _counter, u, depth, parent))
                    _counter += 1

            # 1. Sitemap — highest-value seeds
            sitemap_urls = self._parse_sitemap(base_url)
            for u in sitemap_urls[:MAX_PAGES]:
                enqueue(u, 1, base_url)
            if sitemap_urls:
                logger.info("[Crawler] %d URLs seeded from sitemap", len(sitemap_urls))

            # 2. Base URL (home)
            enqueue(base_url, 0, "")

            # ── Priority BFS ───────────────────────────────────────────────────
            while pq and conn.status == "crawling":
                if len(visited) >= MAX_PAGES:
                    break

                score, _, url, depth, parent_url = heapq.heappop(pq)
                url = self._normalize_url(url)

                if url in visited:
                    continue
                if not self._is_same_domain(url, allowed_domain):
                    continue
                if depth > MAX_DEPTH:
                    continue

                visited.add(url)
                with self._lock:
                    conn.pages_found = max(conn.pages_found, len(visited) + len(pq))

                # ── Fetch + parse ──────────────────────────────────────────────
                result = self._fetch_page(url)
                if result is None:
                    with self._lock:
                        conn.pages_done += 1
                    time.sleep(CRAWL_DELAY)
                    continue

                page, raw_html = result

                # ── Navigation graph ───────────────────────────────────────────
                self._update_nav_graph(conn, url, page, parent_url, depth)

                # ── Dedup via content hash ─────────────────────────────────────
                old_hash = conn.content_hashes.get(url)
                if old_hash and old_hash == page.content_hash:
                    with self._lock:
                        conn.pages_done += 1
                    for link in self._extract_links_from_html(url, raw_html, allowed_domain):
                        if link not in visited:
                            enqueue(link, depth + 1, url)
                    time.sleep(CRAWL_DELAY)
                    continue

                # ── Incremental update: delete old vectors ─────────────────────
                if old_hash:
                    self._delete_url_vectors(url)

                # ── Ingest page ────────────────────────────────────────────────
                chunks_added = self._ingest_page(page, conn)
                conn.content_hashes[url] = page.content_hash

                with self._lock:
                    conn.pages_done += 1
                    conn.chunks_indexed += chunks_added

                # ── Discover new links ─────────────────────────────────────────
                for link in self._extract_links_from_html(url, raw_html, allowed_domain):
                    if link not in visited:
                        enqueue(link, depth + 1, url)

                time.sleep(CRAWL_DELAY)

            # ── Crawl complete — status = "active" (stay connected, never auto-disconnect)
            if conn.status != "disconnected":
                conn.status = "active"
                conn.finished_at = time.time()
                conn.last_crawled = time.time()
                logger.info(
                    "[Crawler] Crawl complete %s: %d pages, %d chunks — staying active",
                    conn.url, conn.pages_done, conn.chunks_indexed,
                )
                self._save_connections()

        except Exception as exc:
            conn.status = "error"
            conn.error = str(exc)[:300]
            conn.finished_at = time.time()
            logger.error("[Crawler] Failed for %s: %s", conn.url, exc)
            self._save_connections()

    # ── Fetch & Parse ──────────────────────────────────────────────────────────

    def _fetch_page(self, url: str) -> Optional[Tuple[PageData, str]]:
        """
        Fetch page using Playwright (JS rendering) if available,
        fall back to requests. Returns (PageData, raw_html) or None.
        """
        html = self._fetch_playwright(url) or self._fetch_requests(url)
        if html is None:
            return None
        page = self._parse_html(url, html)
        return (page, html)

    def _fetch_playwright(self, url: str) -> Optional[str]:
        """
        Full JS render via Playwright with:
        - networkidle wait
        - incremental scroll for lazy-loaded content
        - interaction simulation (tabs, accordions, dropdowns, modals)
        """
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900},
                )
                page = context.new_page()
                page.goto(url, timeout=25000, wait_until="networkidle")

                # ── Incremental scroll to trigger lazy-loaded content ──────────
                page.evaluate("""
                    async () => {
                        const delay = ms => new Promise(r => setTimeout(r, ms));
                        const scrollHeight = () => document.body.scrollHeight;
                        let last = 0;
                        for (let i = 0; i < 8; i++) {
                            window.scrollTo(0, scrollHeight());
                            await delay(300);
                            if (scrollHeight() === last) break;
                            last = scrollHeight();
                        }
                        window.scrollTo(0, 0);
                    }
                """)
                page.wait_for_timeout(600)

                # ── Interact with expandable elements ─────────────────────────
                interaction_selectors = [
                    # Accordions
                    ".accordion-button:not(.active)",
                    "[data-toggle='collapse']",
                    "[data-bs-toggle='collapse']",
                    "details:not([open]) summary",
                    # Tabs
                    ".tab-link:not(.active)",
                    ".nav-tab:not(.active)",
                    "[role='tab']:not([aria-selected='true'])",
                    # Expand buttons
                    "[aria-expanded='false']",
                    ".expand-btn",
                    ".show-more",
                    ".read-more",
                    # Dropdown triggers (reveal hidden nav)
                    ".dropdown-toggle",
                    ".menu-item-has-children > a",
                ]
                for selector in interaction_selectors:
                    try:
                        elements = page.query_selector_all(selector)
                        for el in elements[:6]:
                            try:
                                el.scroll_into_view_if_needed()
                                el.click(timeout=1500)
                                page.wait_for_timeout(250)
                            except Exception:
                                pass
                    except Exception:
                        pass

                # Wait for any newly rendered content
                page.wait_for_timeout(500)
                html = page.content()
                browser.close()
                return html
        except ImportError:
            return None
        except Exception as e:
            logger.debug("[Crawler] Playwright failed for %s: %s", url, e)
            return None

    def _fetch_requests(self, url: str) -> Optional[str]:
        """Plain HTTP fetch fallback."""
        try:
            resp = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                allow_redirects=True,
            )
            if resp.status_code != 200:
                return None
            ct = resp.headers.get("content-type", "")
            if "html" not in ct and "text" not in ct:
                return None
            return resp.text
        except Exception as e:
            logger.debug("[Crawler] Requests failed for %s: %s", url, e)
            return None

    def _parse_html(self, url: str, html: str) -> PageData:
        """Full DOM extraction using BeautifulSoup when available, regex fallback."""

        if _HAS_BS4:
            return self._parse_html_bs4(url, html)
        return self._parse_html_regex(url, html)

    def _parse_html_bs4(self, url: str, html: str) -> PageData:
        """BS4-powered extraction for maximum coverage."""
        soup = _BS4(html, "html.parser")

        # ── Title ──────────────────────────────────────────────────────────────
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # ── Meta tags ──────────────────────────────────────────────────────────
        def get_meta(name: str, prop: bool = False) -> str:
            key = "property" if prop else "name"
            tag = soup.find("meta", {key: name}) or soup.find("meta", {key: name.lower()})
            return (tag.get("content") or "") if tag else ""

        desc = get_meta("description")
        og_tags = {
            "og:title":       get_meta("og:title", prop=True),
            "og:description": get_meta("og:description", prop=True),
            "og:image":       get_meta("og:image", prop=True),
        }

        # ── JSON-LD ────────────────────────────────────────────────────────────
        json_ld = self._extract_json_ld(html)

        # ── Remove noise elements ──────────────────────────────────────────────
        for tag in soup(["script", "style", "noscript", "iframe", "svg", "canvas", "template"]):
            tag.decompose()

        # ── Navigation links (from <nav> elements) ─────────────────────────────
        nav_links: List[str] = []
        for nav in soup.find_all("nav"):
            for a in nav.find_all("a", href=True):
                label = a.get_text(strip=True)
                href  = a["href"]
                if label and href and not href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    nav_links.append(f"{label} → {href}")
        nav_links = list(dict.fromkeys(nav_links))[:25]

        # ── Headings ───────────────────────────────────────────────────────────
        headings: List[str] = []
        for h in soup.find_all(["h1", "h2", "h3", "h4"]):
            txt = h.get_text(strip=True)
            if txt:
                headings.append(txt)
        headings = headings[:35]

        # ── Main text — exclude nav/header/footer/aside ────────────────────────
        for noisy in soup.find_all(["nav", "header", "footer", "aside", "form"]):
            noisy.decompose()

        # Extract text from content areas (article, main, .content, etc.)
        main_content = (
            soup.find("main") or
            soup.find("article") or
            soup.find(id=re.compile(r"content|main|body", re.I)) or
            soup.find(class_=re.compile(r"content|main|body|page", re.I)) or
            soup.find("body") or
            soup
        )
        text = main_content.get_text(separator=" ", strip=True) if main_content else soup.get_text(separator=" ", strip=True)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = self._decode_html_entities(text).strip()

        # ── Stats extraction ───────────────────────────────────────────────────
        stats = self._extract_stats(text)

        # ── People / leadership extraction ────────────────────────────────────
        people = self._extract_people(html, text)

        # ── Contact info ───────────────────────────────────────────────────────
        contact_info = self._extract_contact_info(text)

        # ── Page type & section classification ────────────────────────────────
        page_type = self._classify_page_type(url, title, headings, text)
        section   = self._classify_section(headings, text)

        content_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

        return PageData(
            url=url,
            title=title,
            description=desc,
            text=text,
            headings=headings,
            page_type=page_type,
            section=section,
            content_hash=content_hash,
            stats=stats,
            people=people,
            json_ld=json_ld,
            contact_info=contact_info,
            og_tags=og_tags,
            nav_links=nav_links,
        )

    def _parse_html_regex(self, url: str, html: str) -> PageData:
        """Regex-based fallback extractor (used when BS4 is unavailable)."""
        title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = self._clean_text(title_m.group(1)) if title_m else ""
        desc = self._extract_meta(html, "description")
        og_tags = {
            "og:title":       self._extract_meta(html, "og:title", prop=True),
            "og:description": self._extract_meta(html, "og:description", prop=True),
            "og:image":       self._extract_meta(html, "og:image", prop=True),
        }
        json_ld = self._extract_json_ld(html)
        clean_html = re.sub(
            r"<(script|style|noscript|iframe|svg|canvas)[^>]*>.*?</\1>",
            " ", html, flags=re.IGNORECASE | re.DOTALL,
        )
        headings = [
            self._clean_text(h)
            for h in re.findall(r"<h[1-6][^>]*>(.*?)</h[1-6]>", clean_html, re.IGNORECASE | re.DOTALL)
            if self._clean_text(h)
        ][:35]
        content_html = re.sub(
            r"<(nav|header|footer|aside)[^>]*>.*?</\1>",
            " ", clean_html, flags=re.IGNORECASE | re.DOTALL,
        )
        text = self._decode_html_entities(
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content_html))
        ).strip()
        nav_html_m = re.search(r"<nav[^>]*>(.*?)</nav>", html, re.IGNORECASE | re.DOTALL)
        nav_links = []
        if nav_html_m:
            links_raw = re.findall(
                r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                nav_html_m.group(1), re.IGNORECASE | re.DOTALL,
            )
            nav_links = [f"{self._clean_text(lbl)} → {href}"
                         for href, lbl in links_raw if self._clean_text(lbl)][:25]
        stats       = self._extract_stats(text)
        people      = self._extract_people(html, text)
        contact_info = self._extract_contact_info(text)
        page_type   = self._classify_page_type(url, title, headings, text)
        section     = self._classify_section(headings, text)
        content_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        return PageData(
            url=url, title=title, description=desc, text=text,
            headings=headings, page_type=page_type, section=section,
            content_hash=content_hash, stats=stats, people=people,
            json_ld=json_ld, contact_info=contact_info, og_tags=og_tags,
            nav_links=nav_links,
        )

    # ── Extraction helpers ─────────────────────────────────────────────────────

    def _extract_meta(self, html: str, name: str, prop: bool = False) -> str:
        attr = "property" if prop else "name"
        patterns = [
            rf'<meta[^>]+{attr}=["\'](?:twitter:|){re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+{attr}=["\'](?:twitter:|){re.escape(name)}["\']',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                return self._clean_text(m.group(1))
        return ""

    def _extract_json_ld(self, html: str) -> List[dict]:
        """Parse all application/ld+json blocks."""
        results = []
        for block in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.IGNORECASE | re.DOTALL,
        ):
            try:
                data = json.loads(block.strip())
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            except Exception:
                pass
        return results

    def _extract_stats(self, text: str) -> List[dict]:
        """
        Extract numeric stats like '150+ Employees', '200+ Clients', '$50M Revenue'.
        Pattern: number (with optional +/k/M/B) followed by descriptive words.
        """
        stats = []
        pattern = re.compile(
            r'\b(\$?[\d,]+(?:\.\d+)?(?:[kKmMbB]|\+|%)?(?:\+)?)\s+'
            r'([A-Za-z][A-Za-z\s+\-&]{2,30})',
            re.IGNORECASE,
        )
        seen = set()
        for m in pattern.finditer(text):
            value = m.group(1).strip()
            label = m.group(2).strip()
            key = f"{value} {label}".lower()
            if key not in seen and len(label) > 2:
                seen.add(key)
                stats.append({"value": value, "label": label, "full": f"{value} {label}"})
        return stats[:20]

    def _extract_people(self, html: str, text: str) -> List[dict]:
        """
        Extract people entries from leadership/team sections.
        Looks for patterns like Name + Title/Role combinations.
        """
        people = []
        seen_names = set()

        # JSON-LD Person schema
        for jld in self._extract_json_ld(html):
            items = jld if isinstance(jld, list) else [jld]
            for item in items:
                if item.get("@type") in ("Person", "Employee"):
                    name = item.get("name", "")
                    role = item.get("jobTitle", "")
                    if name and name not in seen_names:
                        seen_names.add(name)
                        people.append({
                            "name": name,
                            "role": role,
                            "bio": item.get("description", ""),
                            "url": item.get("url", ""),
                        })

        # Heuristic: find "Name\nTitle" patterns in leadership sections
        # Look for team/leadership HTML sections
        leadership_patterns = [
            r'(?:team|leadership|executive|management|founder|director|ceo|cto|cfo)',
        ]
        for pat in leadership_patterns:
            sections = re.findall(
                rf'<(?:div|section)[^>]*(?:class|id)[^>]*{pat}[^>]*>(.*?)</(?:div|section)>',
                html, re.IGNORECASE | re.DOTALL,
            )
            for sec in sections:
                # Extract names from h3/h4 + adjacent paragraph (role/title)
                names = re.findall(r'<h[34][^>]*>([^<]{3,60})</h[34]>', sec, re.IGNORECASE)
                roles = re.findall(r'<(?:p|span)[^>]*>([^<]{3,80})</(?:p|span)>', sec, re.IGNORECASE)
                for i, name in enumerate(names[:10]):
                    name = self._clean_text(name)
                    role = self._clean_text(roles[i]) if i < len(roles) else ""
                    # Filter out obvious non-names
                    if name and len(name.split()) >= 2 and name not in seen_names:
                        seen_names.add(name)
                        people.append({"name": name, "role": role, "bio": "", "url": ""})

        return people[:20]

    def _extract_contact_info(self, text: str) -> dict:
        """Extract phone, email, address from text."""
        info = {}

        # Phone
        phone_m = re.search(
            r'(?:tel:|phone:|call us:?)?\s*'
            r'(\+?[\d\s\-().]{8,20}\d)',
            text, re.IGNORECASE,
        )
        if phone_m:
            info["phone"] = phone_m.group(1).strip()

        # Email
        email_m = re.search(r'[\w.+-]+@[\w-]+\.[a-z]{2,}', text, re.IGNORECASE)
        if email_m:
            info["email"] = email_m.group(0)

        # Address (simple heuristic: number + street word)
        addr_m = re.search(
            r'\b\d{1,5}\s+[A-Z][a-z]+\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct)\b',
            text,
        )
        if addr_m:
            info["address"] = addr_m.group(0)

        return info

    # ── Ingestion ──────────────────────────────────────────────────────────────

    def _ingest_page(self, page: PageData, conn: CrawlConnection) -> int:
        """Chunk, embed, and upsert page into Qdrant. Returns chunks added."""
        try:
            from services.embedding_service import get_embedding_service
            embedder = get_embedding_service()
            if embedder is None:
                return 0

            chunks = self._chunk_text(page.text, page.headings)
            if not chunks:
                return 0

            timestamp = time.time()
            points = []
            texts_to_embed = []

            for i, chunk_text in enumerate(chunks):
                enriched = f"[{page.title}]\n{chunk_text}"
                texts_to_embed.append(enriched)

            # Batch embed (much faster than one-by-one)
            try:
                vectors = embedder.model.encode(
                    texts_to_embed,
                    normalize_embeddings=True,
                    batch_size=BATCH_EMBED_SIZE,
                    show_progress_bar=False,
                )
                vectors = [v.tolist() for v in vectors]
            except Exception:
                vectors = [embedder.embed(t) for t in texts_to_embed]

            from qdrant_client.models import PointStruct
            for i, (chunk_text, vector) in enumerate(zip(chunks, vectors)):
                if not vector:
                    continue

                # Build stat/people summaries for metadata
                stats_str = "; ".join(s["full"] for s in page.stats[:5]) if page.stats else ""
                people_str = "; ".join(f"{p['name']} ({p['role']})" for p in page.people[:5] if p.get("name")) if page.people else ""

                payload = {
                    "text":          chunk_text,
                    "title":         page.title,
                    "description":   page.description,
                    "url":           page.url,
                    "source_type":   "website",
                    "source_name":   conn.org_name,
                    "page_type":     page.page_type,
                    "section":       page.section,
                    "file_name":     f"web:{page.url}",
                    "content_hash":  page.content_hash,
                    "version":       1,
                    "timestamp":     timestamp,
                    "chunk_id":      i,
                    "org_name":      conn.org_name,
                    "connection_id": conn.connection_id,
                    # Enriched metadata
                    "stats":         stats_str,
                    "people":        people_str,
                    "contact_phone": page.contact_info.get("phone", ""),
                    "contact_email": page.contact_info.get("email", ""),
                    "nav_links":     "; ".join(page.nav_links[:10]),
                    "og_title":      page.og_tags.get("og:title", ""),
                }

                points.append(PointStruct(id=str(uuid.uuid4()), vector=vector, payload=payload))

            if not points:
                return 0

            # Batch upsert into Qdrant
            for start in range(0, len(points), 50):
                embedder.qdrant.upsert(
                    collection_name="phase1_documents",
                    points=points[start:start + 50],
                )

            return len(points)

        except Exception as e:
            logger.warning("[Crawler] Ingest failed for %s: %s", page.url, e)
            return 0

    def _delete_url_vectors(self, url: str):
        """Remove all Qdrant vectors for a given URL."""
        try:
            from services.embedding_service import get_embedding_service
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            embedder = get_embedding_service()
            if embedder is None:
                return
            embedder.qdrant.delete(
                collection_name="phase1_documents",
                points_selector=Filter(
                    must=[FieldCondition(key="url", match=MatchValue(value=url))]
                ),
            )
        except Exception as e:
            logger.debug("[Crawler] Delete URL vectors failed for %s: %s", url, e)

    def _delete_connection_vectors(self, connection_id: str):
        """Delete all vectors for a connection (on full disconnect)."""
        try:
            from services.embedding_service import get_embedding_service
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            embedder = get_embedding_service()
            if embedder is None:
                return
            embedder.qdrant.delete(
                collection_name="phase1_documents",
                points_selector=Filter(
                    must=[FieldCondition(key="connection_id", match=MatchValue(value=connection_id))]
                ),
            )
            logger.info("[Crawler] Removed all vectors for connection %s", connection_id)
        except Exception as e:
            logger.warning("[Crawler] Connection vector removal failed: %s", e)

    # ── Chunking ───────────────────────────────────────────────────────────────

    def _chunk_text(self, text: str, headings: List[str]) -> List[str]:
        """
        Structure-aware chunking: split on sentence boundaries,
        respecting heading boundaries when possible.
        """
        if not text.strip():
            return []

        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks: List[str] = []
        current = ""

        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(current) + len(sent) + 1 <= CHUNK_SIZE:
                current = (current + " " + sent).strip()
            else:
                if current and len(current) > 50:
                    chunks.append(current)
                # New chunk: start with overlap from previous
                words = current.split()[-int(CHUNK_OVERLAP / 5):]
                current = " ".join(words) + " " + sent
                current = current.strip()

        if current and len(current) > 50:
            chunks.append(current)

        return chunks

    # ── Sitemap ────────────────────────────────────────────────────────────────

    def _parse_sitemap(self, base_url: str) -> List[str]:
        """Parse sitemap.xml and return all URLs (follows sitemap index files)."""
        urls: List[str] = []
        candidates = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/sitemap-index.xml",
            f"{base_url}/robots.txt",
        ]

        for sm_url in candidates:
            try:
                resp = requests.get(
                    sm_url, timeout=10,
                    headers={"User-Agent": "CortexFlowBot/1.0 (+https://cortexflow.ai)"},
                )
                if resp.status_code != 200:
                    continue

                # robots.txt: look for Sitemap: directive
                if sm_url.endswith("robots.txt"):
                    for line in resp.text.splitlines():
                        if line.lower().startswith("sitemap:"):
                            sitemap_url = line.split(":", 1)[1].strip()
                            urls.extend(self._parse_sitemap_xml(sitemap_url))
                    if urls:
                        break
                    continue

                # XML sitemap
                found = self._parse_sitemap_xml_text(resp.text)
                urls.extend(found)
                if urls:
                    break

            except Exception:
                continue

        return list(dict.fromkeys(urls))  # preserve order, deduplicate

    def _parse_sitemap_xml(self, url: str) -> List[str]:
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "CortexFlowBot/1.0"})
            if resp.status_code == 200:
                return self._parse_sitemap_xml_text(resp.text)
        except Exception:
            pass
        return []

    def _parse_sitemap_xml_text(self, xml: str) -> List[str]:
        """Extract <loc> URLs; follow <sitemap> entries in index files."""
        urls = re.findall(r"<loc>\s*(https?://[^\s<]+)\s*</loc>", xml)
        # Sitemap index — recursively parse
        sub_sitemaps = re.findall(r"<sitemap>.*?<loc>(https?://[^\s<]+)</loc>.*?</sitemap>", xml, re.DOTALL)
        for sm in sub_sitemaps[:5]:
            urls.extend(self._parse_sitemap_xml(sm))
        return urls

    # ── Link extraction ────────────────────────────────────────────────────────

    def _extract_links_from_html(
        self, base_url: str, html: str, allowed_domain: str
    ) -> List[str]:
        hrefs = re.findall(r'<a[^>]+href=["\']([^"\'#][^"\']*)["\']', html, re.IGNORECASE)
        links = []
        seen = set()
        for href in hrefs:
            if href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
                continue
            full = urljoin(base_url, href)
            full = self._normalize_url(full)
            if full not in seen and self._is_same_domain(full, allowed_domain):
                seen.add(full)
                links.append(full)
        return links[:100]

    # ── Page classifiers ───────────────────────────────────────────────────────

    def _classify_page_type(self, url: str, title: str, headings: List[str], text: str) -> str:
        combined = (url + " " + title + " " + " ".join(headings[:5]) + " " + text[:500]).lower()

        mapping = [
            ("about",        ["about us", "who we are", "our story", "our mission", "company overview"]),
            ("service",      ["services", "solutions", "offerings", "what we do", "our services", "capabilities"]),
            ("contact",      ["contact us", "get in touch", "reach us", "our location", "contact page"]),
            ("blog",         ["blog", "news", "article", "insights", "press release", "latest posts"]),
            ("team",         ["team", "leadership", "our people", "executives", "management", "founders"]),
            ("careers",      ["careers", "jobs", "hiring", "join us", "open positions", "vacancies"]),
            ("testimonials", ["testimonials", "reviews", "client stories", "case studies", "success stories"]),
            ("product",      ["product", "platform", "software", "tool", "application", "features"]),
            ("pricing",      ["pricing", "plans", "packages", "cost", "subscription"]),
            ("faq",          ["faq", "frequently asked", "questions", "help", "support"]),
        ]

        for page_type, keywords in mapping:
            if any(kw in combined for kw in keywords):
                return page_type

        # Home: short path
        try:
            path = urlparse(url).path.strip("/")
            if path == "" or path == "index.html":
                return "home"
        except Exception:
            pass

        return "other"

    def _classify_section(self, headings: List[str], text: str) -> str:
        """Classify the primary section/topic of this page."""
        combined = (" ".join(headings[:3]) + " " + text[:200]).lower()
        sections = [
            ("leadership", ["ceo", "cto", "founder", "director", "executive", "leadership"]),
            ("stats",      ["employees", "clients", "projects", "solutions", "years", "deployed"]),
            ("contact",    ["address", "phone", "email", "location", "office"]),
            ("testimonial", ["said", "quote", "testimonial", "review", '"', "★"]),
            ("service",    ["service", "solution", "offering", "what we provide"]),
        ]
        for section, keywords in sections:
            if any(kw in combined for kw in keywords):
                return section
        return headings[0][:50] if headings else "general"

    # ── Utilities ──────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_url(url: str) -> str:
        try:
            p = urlparse(url)
            # Remove fragment; keep query params (different params = different page)
            return p._replace(fragment="").geturl().rstrip("/") or url
        except Exception:
            return url

    @staticmethod
    def _is_same_domain(url: str, domain: str) -> bool:
        try:
            netloc = urlparse(url).netloc
            # Allow www. and non-www variations
            return netloc == domain or netloc == f"www.{domain}" or f"www.{netloc}" == domain
        except Exception:
            return False

    @staticmethod
    def _derive_org_name(url: str) -> str:
        try:
            netloc = urlparse(url).netloc.replace("www.", "")
            return netloc.split(".")[0].capitalize()
        except Exception:
            return url

    @staticmethod
    def _decode_html_entities(text: str) -> str:
        return (
            text
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&nbsp;", " ").replace("&quot;", '"').replace("&#39;", "'")
            .replace("&apos;", "'").replace("&#8217;", "'").replace("&#8216;", "'")
            .replace("&#8220;", '"').replace("&#8221;", '"').replace("&mdash;", "—")
            .replace("&ndash;", "–").replace("&hellip;", "…")
        )

    @staticmethod
    def _clean_text(html_snippet: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html_snippet)
        return re.sub(r"\s+", " ", text).strip()

    def get_connections(self) -> List[dict]:
        """Return all non-disconnected connections as dicts (including nav_graph)."""
        with self._lock:
            result = []
            for c in self._connections.values():
                if c.status == "disconnected":
                    continue
                d = self._conn_to_dict(c)
                d["nav_graph"] = c.nav_graph  # include full nav_graph for lookups
                result.append(d)
            return result

    @staticmethod
    def _conn_to_dict(conn: CrawlConnection) -> dict:
        return {
            "connection_id":  conn.connection_id,
            "url":            conn.url,
            "org_name":       conn.org_name,
            "status":         conn.status,
            "priority":       conn.priority,
            "pages_found":    conn.pages_found,
            "pages_done":     conn.pages_done,
            "chunks_indexed": conn.chunks_indexed,
            "started_at":     conn.started_at,
            "finished_at":    conn.finished_at,
            "last_crawled":   conn.last_crawled,
            "error":          conn.error,
            "nav_pages":      len(conn.nav_graph),   # navigation graph size
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_crawler_instance: Optional[WebsiteCrawler] = None
_crawler_lock = threading.Lock()


def get_website_crawler() -> WebsiteCrawler:
    global _crawler_instance
    if _crawler_instance is None:
        with _crawler_lock:
            if _crawler_instance is None:
                _crawler_instance = WebsiteCrawler()
    return _crawler_instance
