import { useState, useEffect, useRef } from "react";
import { Globe, Link2Off, Loader2, CheckCircle2, AlertCircle, RefreshCw, RotateCcw, FileText, Layers, Activity, Map } from "lucide-react";
import axios from "axios";

interface CrawlConnection {
  connection_id: string;
  url: string;
  org_name: string;
  status: "pending" | "crawling" | "active" | "done" | "error" | "disconnected";
  priority: string;
  pages_found: number;
  pages_done: number;
  chunks_indexed: number;
  nav_pages: number;
  started_at: number;
  finished_at: number | null;
  last_crawled: number | null;
  error: string | null;
}

function StatusDot({ status }: { status: CrawlConnection["status"] }) {
  const map: Record<string, string> = {
    pending:  "bg-yellow-400",
    crawling: "bg-blue-400 animate-pulse",
    active:   "bg-emerald-400 animate-pulse",
    done:     "bg-emerald-400",
    error:    "bg-red-400",
  };
  return <span className={`w-2 h-2 rounded-full shrink-0 ${map[status] ?? "bg-gray-500"}`} />;
}

function StatusLabel({ status }: { status: CrawlConnection["status"] }) {
  const map: Record<string, { label: string; cls: string }> = {
    pending:  { label: "Pending",    cls: "text-yellow-400 bg-yellow-500/10 border-yellow-500/20" },
    crawling: { label: "Crawling…",  cls: "text-blue-400 bg-blue-500/10 border-blue-500/20" },
    active:   { label: "Live",       cls: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
    done:     { label: "Live",       cls: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
    error:    { label: "Error",      cls: "text-red-400 bg-red-500/10 border-red-500/20" },
  };
  const s = map[status] ?? { label: "Stopped", cls: "text-gray-500 bg-gray-800 border-gray-700" };
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border ${s.cls}`}>
      <StatusDot status={status} />
      {s.label}
    </span>
  );
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <div className="mt-2">
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>{done} / {total || "?"} pages</span>
        <span>{pct}%</span>
      </div>
      <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function elapsed(start: number, end: number | null) {
  const s = Math.round((end || Date.now() / 1000) - start);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

export default function WebsiteScraper() {
  const [url, setUrl] = useState("");
  const [orgName, setOrgName] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [connections, setConnections] = useState<CrawlConnection[]>([]);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const token = localStorage.getItem("accessToken");
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    fetchStatus();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  // Auto-poll every 4s while crawling or pending; slower 30s poll when all active (live)
  useEffect(() => {
    const isCrawling = connections.some(c => c.status === "crawling" || c.status === "pending");
    const hasLive = connections.some(c => c.status === "active" || c.status === "done");
    if (isCrawling && !pollRef.current) {
      pollRef.current = setInterval(fetchStatus, 4000);
    } else if (!isCrawling && hasLive && !pollRef.current) {
      pollRef.current = setInterval(fetchStatus, 30000);
    } else if (!isCrawling && !hasLive && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [connections]);

  async function fetchStatus() {
    try {
      const res = await axios.get("/website/status", { headers });
      setConnections(res.data.connections || []);
    } catch { /* silent */ }
    finally { setLoadingStatus(false); }
  }

  async function handleConnect() {
    const trimmed = url.trim();
    if (!trimmed) { setError("Please enter a website URL."); return; }
    setError(""); setSuccessMsg(""); setConnecting(true);
    try {
      const res = await axios.post("/website/connect", { url: trimmed, org_name: orgName.trim() }, { headers });
      setSuccessMsg(res.data.message || `Connected to ${trimmed}.`);
      setUrl(""); setOrgName("");
      await fetchStatus();
    } catch (err: any) {
      const d = err?.response?.data?.detail || err?.message || "Connection failed.";
      setError(typeof d === "string" ? d : JSON.stringify(d));
    } finally { setConnecting(false); }
  }

  async function handleDisconnect(id: string, removeVectors: boolean) {
    setActionLoading(id + "-disconnect"); setError("");
    try {
      await axios.post("/website/disconnect", { connection_id: id, remove_vectors: removeVectors }, { headers });
      setSuccessMsg(removeVectors ? "Disconnected and all indexed data removed." : "Disconnected successfully.");
      await fetchStatus();
    } catch (err: any) {
      const d = err?.response?.data?.detail || err?.message || "Failed.";
      setError(typeof d === "string" ? d : JSON.stringify(d));
    } finally { setActionLoading(null); }
  }

  async function handleRefresh(id: string) {
    setActionLoading(id + "-refresh"); setError("");
    try {
      await axios.post(`/website/refresh/${id}`, {}, { headers });
      setSuccessMsg("Re-crawl triggered — new/changed pages will be updated.");
      await fetchStatus();
    } catch (err: any) {
      const d = err?.response?.data?.detail || err?.message || "Failed.";
      setError(typeof d === "string" ? d : JSON.stringify(d));
    } finally { setActionLoading(null); }
  }

  const activeConns = connections.filter(c => c.status !== "disconnected");

  return (
    <div className="flex flex-col h-full bg-gray-950 p-8 overflow-y-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-1">
          <div className="w-9 h-9 rounded-xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center">
            <Globe size={18} className="text-indigo-400" />
          </div>
          <h1 className="text-xl font-bold text-white">Website Scraper</h1>
        </div>
        <p className="text-sm text-gray-500 ml-12">
          Connect any organization website — deep-crawled end to end, stays live, auto-updates when the site changes.
        </p>
      </div>

      {/* Connect form */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-6 max-w-2xl">
        <p className="text-xs text-gray-500 uppercase tracking-widest mb-4 font-semibold">Connect a website</p>

        <div className="space-y-3">
          <input
            type="url"
            value={url}
            onChange={e => { setUrl(e.target.value); setError(""); setSuccessMsg(""); }}
            onKeyDown={e => e.key === "Enter" && !connecting && handleConnect()}
            placeholder="https://example.com"
            className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-indigo-500 transition"
            disabled={connecting}
          />
          <div className="flex gap-3">
            <input
              type="text"
              value={orgName}
              onChange={e => setOrgName(e.target.value)}
              placeholder="Organization name (optional, e.g. Nitco Inc)"
              className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-indigo-500 transition"
              disabled={connecting}
            />
            <button
              onClick={handleConnect}
              disabled={connecting || !url.trim()}
              className="flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl transition shrink-0"
            >
              {connecting
                ? <><Loader2 size={15} className="animate-spin" /> Connecting…</>
                : <><Globe size={15} /> Connect</>}
            </button>
          </div>
        </div>

        {/* How it works */}
        <div className="mt-4 pt-4 border-t border-gray-800 grid grid-cols-3 gap-3 text-xs text-gray-500">
          <div><span className="text-indigo-400 font-medium">1. Crawl</span><br />BFS up to 500 pages, sitemap-seeded, depth-limited</div>
          <div><span className="text-indigo-400 font-medium">2. Extract</span><br />Text, JSON-LD, stats, people, contact, nav links</div>
          <div><span className="text-indigo-400 font-medium">3. Stay live</span><br />Auto re-crawls every 2h. Updates only changed pages.</div>
        </div>

        {error && (
          <div className="mt-3 flex items-start gap-2 text-red-400 text-sm bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
            <AlertCircle size={15} className="mt-0.5 shrink-0" /><span>{error}</span>
          </div>
        )}
        {successMsg && (
          <div className="mt-3 flex items-start gap-2 text-emerald-400 text-sm bg-emerald-500/10 border border-emerald-500/20 rounded-xl px-4 py-3">
            <CheckCircle2 size={15} className="mt-0.5 shrink-0" /><span>{successMsg}</span>
          </div>
        )}
      </div>

      {/* Connections list */}
      <div className="max-w-2xl">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs text-gray-500 uppercase tracking-widest font-semibold">Connected websites</p>
          <button onClick={fetchStatus} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition">
            <RefreshCw size={12} className={loadingStatus ? "animate-spin" : ""} />Refresh
          </button>
        </div>

        {loadingStatus ? (
          <div className="flex items-center gap-2 text-gray-600 text-sm py-6"><Loader2 size={15} className="animate-spin" />Loading…</div>
        ) : activeConns.length === 0 ? (
          <div className="text-gray-600 text-sm py-10 border border-dashed border-gray-800 rounded-2xl text-center">
            No websites connected yet.<br />Enter a URL above to connect an organization website.
          </div>
        ) : (
          <div className="space-y-3">
            {activeConns.map(conn => (
              <div key={conn.connection_id} className="bg-gray-900 border border-gray-800 rounded-2xl px-5 py-4">
                {/* Name + status */}
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <Globe size={14} className="text-indigo-400 shrink-0" />
                      <p className="text-sm font-semibold text-white truncate">
                        {conn.org_name || new URL(conn.url).hostname}
                      </p>
                    </div>
                    <p className="text-xs text-gray-600 truncate">{conn.url}</p>
                  </div>
                  <StatusLabel status={conn.status} />
                </div>

                {/* Progress bar while crawling */}
                {conn.status === "crawling" && (
                  <ProgressBar done={conn.pages_done} total={conn.pages_found} />
                )}

                {/* Stats */}
                <div className="flex items-center flex-wrap gap-4 text-xs text-gray-500 mt-3">
                  <span className="flex items-center gap-1"><FileText size={11} />{conn.pages_done} pages indexed</span>
                  <span className="flex items-center gap-1"><Layers size={11} />{conn.chunks_indexed} chunks</span>
                  {conn.nav_pages > 0 && (
                    <span className="flex items-center gap-1 text-indigo-400/80"><Map size={11} />{conn.nav_pages} nav pages</span>
                  )}
                  <span className="flex items-center gap-1"><Activity size={11} />{elapsed(conn.started_at, conn.finished_at)}</span>
                  {conn.last_crawled && (conn.status === "active" || conn.status === "done") && (
                    <span className="text-emerald-600/70">
                      Last crawled {new Date(conn.last_crawled * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  )}
                </div>

                {/* Scheduling info */}
                {(conn.status === "active" || conn.status === "done") && (
                  <p className="text-xs text-gray-700 mt-1.5">
                    Connected · Auto re-crawls every 2 hours · stays live until manually disconnected
                  </p>
                )}

                {/* Error */}
                {conn.error && (
                  <p className="mt-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-1.5">{conn.error}</p>
                )}

                {/* Actions */}
                <div className="flex items-center gap-2 mt-3 pt-3 border-t border-gray-800">
                  {/* Re-crawl now */}
                  {(conn.status === "active" || conn.status === "done" || conn.status === "error") && (
                    <button
                      onClick={() => handleRefresh(conn.connection_id)}
                      disabled={actionLoading === conn.connection_id + "-refresh"}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-400 hover:text-indigo-300 border border-indigo-500/20 hover:border-indigo-500/40 bg-indigo-500/5 rounded-xl transition disabled:opacity-50"
                    >
                      {actionLoading === conn.connection_id + "-refresh"
                        ? <Loader2 size={12} className="animate-spin" />
                        : <RotateCcw size={12} />}
                      Re-crawl now
                    </button>
                  )}

                  {/* Disconnect (keep vectors) */}
                  <button
                    onClick={() => handleDisconnect(conn.connection_id, false)}
                    disabled={!!actionLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-500 hover:text-gray-300 border border-gray-700 bg-gray-800/50 rounded-xl transition disabled:opacity-50"
                  >
                    {actionLoading === conn.connection_id + "-disconnect"
                      ? <Loader2 size={12} className="animate-spin" />
                      : <Link2Off size={12} />}
                    Disconnect
                  </button>

                  {/* Disconnect + remove all data */}
                  <button
                    onClick={() => handleDisconnect(conn.connection_id, true)}
                    disabled={!!actionLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-red-400 hover:text-red-300 border border-red-500/20 hover:border-red-500/40 bg-red-500/5 rounded-xl transition disabled:opacity-50"
                  >
                    {actionLoading === conn.connection_id + "-disconnect"
                      ? <Loader2 size={12} className="animate-spin" />
                      : <Link2Off size={12} />}
                    Disconnect + delete data
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
