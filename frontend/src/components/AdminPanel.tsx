import { useState, useEffect, useCallback } from "react";
import {
  Shield, Users, AlertTriangle, Server, Database, GitBranch,
  Zap, Plus, Trash2, UserX, UserCheck, Lock,
  Activity, FileText, RefreshCw, Check,
  BarChart3, HardDrive, Search, Layers, ChevronDown, ChevronRight, FolderOpen, Folder,
  Key, X, Copy, Eye, EyeOff
} from "lucide-react";
import axios from "axios";

type Tab = "overview" | "users" | "security" | "rules" | "monitoring" | "chunks" | "storage" | "apikeys";
interface ApiKeyRecord { id: string; name: string; key_prefix: string; permissions: string; is_active: boolean; expires_at?: string; last_used_at?: string; total_requests: number; notes?: string }

interface Rule { id: string; name: string; pattern: string; action: string; role: string; active: boolean; created_at?: string }
interface SecurityEvent { id: string; user_email?: string; event_type: string; severity: string; description: string; query?: string; resolved: boolean; created_at: string }
interface SystemStatus { status: string; [key: string]: any }

const SEVERITY_STYLE: Record<string, string> = {
  high: "bg-red-500/10 border-red-500/20 text-red-400",
  medium: "bg-yellow-500/10 border-yellow-500/20 text-yellow-400",
  low: "bg-blue-500/10 border-blue-500/20 text-blue-400",
  critical: "bg-red-600/20 border-red-600/30 text-red-300",
};
const RISK_STYLE: Record<string, string> = {
  low: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
  medium: "text-yellow-400 bg-yellow-400/10 border-yellow-400/20",
  high: "text-orange-400 bg-orange-400/10 border-orange-400/20",
  critical: "text-red-400 bg-red-400/10 border-red-400/20",
};

// ── System status card ────────────────────────────────────────────────────────
function SystemCard({ icon: Icon, label, value, status, color, extra }: any) {
  const isOnline  = status === "online";
  const isWarn    = status === "warn";
  const isOffline = !isOnline && !isWarn;

  const borderGlow = isOnline  ? "border-emerald-500/30 shadow-emerald-500/5"
    : isWarn   ? "border-yellow-500/30 shadow-yellow-500/5"
    : "border-red-500/30 shadow-red-500/5";
  const gradFrom  = isOnline  ? "from-emerald-900/20"
    : isWarn   ? "from-yellow-900/20"
    : "from-red-900/20";
  const dotClass  = isOnline  ? "bg-emerald-400"
    : isWarn   ? "bg-yellow-400 animate-pulse"
    : "bg-red-400 animate-pulse";
  const statusTxt = isOnline  ? "Operational" : isWarn ? "Degraded" : "Offline";
  const statusColor = isOnline ? "text-emerald-400" : isWarn ? "text-yellow-400" : "text-red-400";

  return (
    <div className={`rounded-2xl border bg-gradient-to-br ${gradFrom} to-gray-800/80 ${borderGlow} shadow-lg p-5 transition-all hover:scale-[1.01]`}>
      <div className="flex items-start justify-between mb-4">
        <div className="w-10 h-10 rounded-xl bg-gray-800/80 flex items-center justify-center shadow-inner">
          <Icon size={19} className={color} />
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${dotClass}`} />
          <span className={`text-xs font-semibold ${statusColor}`}>{statusTxt}</span>
        </div>
      </div>
      <p className="text-xs text-gray-500 mb-0.5 uppercase tracking-wide">{label}</p>
      <p className="text-base font-bold text-white leading-tight">{value}</p>
      {extra && <p className="text-xs text-gray-500 mt-1.5">{extra}</p>}
    </div>
  );
}

// ── Chunks Tab — grouped by document ─────────────────────────────────────────
function ChunksTab({ chunks, loading, search, setSearch, onSearch, onRefresh }: {
  chunks: any[]; loading: boolean; search: string;
  setSearch: (s: string) => void; onSearch: () => void; onRefresh: () => void;
}) {
  const [openDocs, setOpenDocs] = useState<Set<string>>(new Set());
  const [deletingDoc, setDeletingDoc] = useState<string | null>(null);

  // Group chunks by file_name
  const grouped: Record<string, any[]> = {};
  for (const c of chunks) {
    const key = c.file_name || "Unknown";
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(c);
  }
  const docNames = Object.keys(grouped).sort();

  const toggle = (name: string) =>
    setOpenDocs(prev => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });

  const handleDeleteDoc = async (docName: string) => {
    if (!window.confirm(`Delete all chunks for "${docName}"? This cannot be undone.`)) return;
    setDeletingDoc(docName);
    try {
      const token = localStorage.getItem("accessToken");
      await axios.delete(`/admin/document/${encodeURIComponent(docName)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      onRefresh();
    } catch (e: any) {
      alert(`Delete failed: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setDeletingDoc(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            <Layers size={18} className="text-blue-400" /> Stored Chunks (Qdrant Vector DB)
          </h3>
          <p className="text-xs text-gray-400 mt-0.5">Chunks grouped by document — click a folder to expand</p>
        </div>
        <button onClick={onRefresh} disabled={loading}
          className="flex items-center gap-2 px-3 py-2 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition text-xs disabled:opacity-50">
          <RefreshCw size={13} className={loading ? "animate-spin text-brand-400" : ""} /> Refresh
        </button>
      </div>

      {/* Search */}
      <div className="flex gap-3">
        <div className="flex-1 relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === "Enter" && onSearch()}
            placeholder="Search chunks by keyword…"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-9 pr-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500" />
        </div>
        <button onClick={onSearch}
          className="px-4 py-2.5 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg transition font-medium">
          Search
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-32 gap-3 text-gray-400">
          <RefreshCw size={18} className="animate-spin text-brand-400" />
          <span className="text-sm">Loading chunks…</span>
        </div>
      ) : chunks.length === 0 ? (
        <div className="text-center py-16 text-gray-500">
          <Database size={40} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">No chunks found. Upload documents to populate the vector store.</p>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-gray-500">{chunks.length} chunk{chunks.length !== 1 ? "s" : ""} across {docNames.length} document{docNames.length !== 1 ? "s" : ""}</p>
          {docNames.map(docName => {
            const isOpen = openDocs.has(docName);
            const docChunks = grouped[docName];
            return (
              <div key={docName} className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
                {/* Folder header */}
                <div className="flex items-center gap-2 px-4 py-3.5 hover:bg-gray-700/30 transition">
                  <button onClick={() => toggle(docName)} className="flex items-center gap-3 flex-1 text-left min-w-0">
                  {isOpen
                    ? <FolderOpen size={16} className="text-brand-400 shrink-0" />
                    : <Folder size={16} className="text-gray-400 shrink-0" />}
                  <span className="flex-1 text-sm font-medium text-white truncate">{docName}</span>
                  <span className="text-xs text-gray-500 bg-gray-700 px-2 py-0.5 rounded-full shrink-0">
                    {docChunks.length} chunk{docChunks.length !== 1 ? "s" : ""}
                  </span>
                  {isOpen
                    ? <ChevronDown size={14} className="text-gray-400 shrink-0" />
                    : <ChevronRight size={14} className="text-gray-400 shrink-0" />}
                  </button>
                  {/* Delete document button */}
                  <button
                    onClick={() => handleDeleteDoc(docName)}
                    disabled={deletingDoc === docName}
                    className="shrink-0 p-1.5 hover:bg-red-500/20 rounded text-gray-500 hover:text-red-400 transition disabled:opacity-50"
                    title="Delete document and all its chunks">
                    {deletingDoc === docName
                      ? <RefreshCw size={13} className="animate-spin text-red-400" />
                      : <Trash2 size={13} />}
                  </button>
                </div>

                {/* Chunk list */}
                {isOpen && (
                  <div className="border-t border-gray-700 divide-y divide-gray-700/50">
                    {docChunks.map((chunk: any, i: number) => (
                      <div key={chunk.id || i} className="px-4 py-3.5 hover:bg-gray-700/20 transition">
                        <div className="flex items-center gap-2 mb-2">
                          {chunk.collection && (
                            <span className="text-xs bg-violet-500/20 text-violet-300 px-2 py-0.5 rounded-full border border-violet-500/20">
                              {chunk.collection}
                            </span>
                          )}
                          {chunk.access_roles && (
                            <span className="text-xs bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded-full border border-emerald-500/20">
                              {Array.isArray(chunk.access_roles) ? chunk.access_roles.join(", ") : chunk.access_roles}
                            </span>
                          )}
                          <span className="ml-auto text-xs text-gray-600">#{i + 1}</span>
                        </div>
                        <p className="text-xs text-gray-300 leading-relaxed line-clamp-3 font-mono">
                          {chunk.text || chunk.content || "(no text)"}
                        </p>
                        {chunk.score != null && (
                          <p className="text-xs text-brand-400 mt-1.5">Relevance: {(chunk.score * 100).toFixed(1)}%</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Ingest Queue Panel ────────────────────────────────────────────────────────
function IngestQueuePanel({ authHeaders }: { authHeaders: () => Record<string, string> }) {
  const [jobs, setJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await axios.get("/upload/status/all", { headers: authHeaders() });
      setJobs(Array.isArray(res.data) ? res.data.slice(0, 20) : []);
    } catch { setJobs([]); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const badge: Record<string, string> = {
    done: "bg-emerald-500/20 text-emerald-300",
    processing: "bg-yellow-500/20 text-yellow-300 animate-pulse",
    queued: "bg-blue-500/20 text-blue-300",
    error: "bg-red-500/20 text-red-300",
  };

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-white flex items-center gap-2">
          <Activity size={15} className="text-brand-400" /> Background Ingest Queue
        </h3>
        <button onClick={load} disabled={loading} className="p-1.5 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      {jobs.length === 0 ? (
        <p className="text-sm text-gray-500">No recent jobs. Upload a file to see activity here.</p>
      ) : (
        <div className="space-y-2 max-h-52 overflow-y-auto pr-1">
          {jobs.map((j: any) => (
            <div key={j.job_id} className="flex items-center gap-3 bg-gray-900/50 rounded-lg px-3 py-2">
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0 ${badge[j.status] || "bg-gray-600/30 text-gray-400"}`}>
                {j.status}
              </span>
              <span className="text-xs text-gray-300 flex-1 truncate">{j.file?.split("/").pop() || j.file || "—"}</span>
              {j.elapsed_s != null && <span className="text-xs text-gray-500 shrink-0">{j.elapsed_s}s</span>}
              {j.error && <span className="text-xs text-red-400 shrink-0 truncate max-w-[120px]" title={j.error}>{j.error}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Confirm Dialog ────────────────────────────────────────────────────────────
function ConfirmDialog({ message, onConfirm, onCancel }: { message: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
      <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 max-w-sm w-full shadow-2xl">
        <div className="flex items-start gap-3 mb-5">
          <AlertTriangle size={20} className="text-yellow-400 shrink-0 mt-0.5" />
          <p className="text-sm text-gray-200 leading-relaxed">{message}</p>
        </div>
        <div className="flex gap-3">
          <button onClick={onCancel}
            className="flex-1 px-4 py-2 text-sm text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg transition">
            Cancel
          </button>
          <button onClick={onConfirm}
            className="flex-1 px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-500 rounded-lg transition">
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Tab bar ───────────────────────────────────────────────────────────────────
function TabBar({ active, setActive }: { active: Tab; setActive: (t: Tab) => void }) {
  const tabs: { id: Tab; label: string; icon: React.ComponentType<any> }[] = [
    { id: "overview", label: "Overview", icon: Server },
    { id: "users", label: "Users", icon: Users },
    { id: "security", label: "Security", icon: Shield },
    { id: "rules", label: "Rule Engine", icon: Lock },
    { id: "apikeys", label: "API Keys", icon: Key },
    { id: "monitoring", label: "Monitoring", icon: Activity },
    { id: "chunks", label: "Chunks", icon: Layers },
    { id: "storage", label: "Storage", icon: HardDrive },
  ];
  return (
    <div className="flex gap-1 border-b border-gray-800 px-6 pt-1 shrink-0 overflow-x-auto">
      {tabs.map(({ id, label, icon: Icon }) => (
        <button key={id} onClick={() => setActive(id)}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition -mb-px whitespace-nowrap ${
            active === id ? "border-brand-500 text-brand-300" : "border-transparent text-gray-400 hover:text-white"
          }`}>
          <Icon size={14} />{label}
        </button>
      ))}
    </div>
  );
}

// ── Main AdminPanel ───────────────────────────────────────────────────────────
export default function AdminPanel({ user }: { user?: any }) {
  const [tab, setTab] = useState<Tab>("overview");

  // Confirm dialog
  const [confirm, setConfirm] = useState<{ message: string; onConfirm: () => void } | null>(null);
  const askConfirm = (message: string, onConfirm: () => void) => setConfirm({ message, onConfirm });

  // Users
  const [users, setUsers] = useState<any[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [userSearch, setUserSearch] = useState("");

  // API Keys
  const [apiKeys, setApiKeys] = useState<ApiKeyRecord[]>([]);
  const [apiKeysLoading, setApiKeysLoading] = useState(false);
  const [newKeyForm, setNewKeyForm] = useState({ name: "", permissions: "read", expires_days: 365, notes: "" });
  const [showNewKeyForm, setShowNewKeyForm] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [showRawKey, setShowRawKey] = useState(false);

  // Rules
  const [rules, setRules] = useState<Rule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(false);
  const [newRule, setNewRule] = useState({ name: "", pattern: "", action: "block", role: "public" });
  const [showNewRule, setShowNewRule] = useState(false);
  const [editingRule, setEditingRule] = useState<Rule | null>(null);

  // Security
  const [secEvents, setSecEvents] = useState<SecurityEvent[]>([]);
  const [secLoading, setSecLoading] = useState(false);
  const [secStats, setSecStats] = useState<any>(null);

  // System health
  const [health, setHealth] = useState<Record<string, SystemStatus>>({});
  const [healthLoading, setHealthLoading] = useState(false);
  const [serviceHealth, setServiceHealth] = useState<Record<string, any>>({});

  // Analytics
  const [analytics, setAnalytics] = useState<any>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);

  // Chunks
  const [chunks, setChunks] = useState<any[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunkSearch, setChunkSearch] = useState("");

  // Storage
  const [storageInfo, setStorageInfo] = useState<any>(null);
  const [storageLoading, setStorageLoading] = useState(false);

  // Cache stats
  const [cacheStats, setCacheStats] = useState<any>(null);

  // Error log
  const [errorLog, setErrorLog] = useState<any[]>([]);
  const [errorLogLoading, setErrorLogLoading] = useState(false);

  const token = () => localStorage.getItem("accessToken");
  const authHeaders = () => ({ Authorization: `Bearer ${token()}` });

  // ── Fetch functions ──────────────────────────────────────────────────────────
  const fetchUsers = useCallback(async () => {
    setUsersLoading(true);
    try {
      const res = await axios.get("/auth/users", { headers: authHeaders() });
      setUsers(Array.isArray(res.data) ? res.data : []);
    } catch { setUsers([]); }
    finally { setUsersLoading(false); }
  }, []);

  const fetchRules = useCallback(async () => {
    setRulesLoading(true);
    try {
      const res = await axios.get("/admin/rules", { headers: authHeaders() });
      setRules(res.data);
    } catch {
      // Fallback to default rules if API not ready
      setRules([
        { id: "1", name: "Block PII queries", pattern: "ssn|social security|passport", action: "block", role: "public", active: true },
        { id: "2", name: "Warn on financial terms", pattern: "salary|compensation|budget", action: "warn", role: "public", active: true },
        { id: "3", name: "Admin-only confidential", pattern: "confidential|restricted|internal only", action: "restrict", role: "user", active: true },
      ]);
    }
    finally { setRulesLoading(false); }
  }, []);

  const fetchSecEvents = useCallback(async () => {
    setSecLoading(true);
    try {
      const [evRes, statsRes] = await Promise.all([
        axios.get("/admin/security/events?limit=50", { headers: authHeaders() }),
        axios.get("/admin/security/stats", { headers: authHeaders() }),
      ]);
      setSecEvents(Array.isArray(evRes.data) ? evRes.data : []);
      setSecStats(statsRes.data && typeof statsRes.data === "object" ? statsRes.data : null);
    } catch { setSecEvents([]); }
    finally { setSecLoading(false); }
  }, []);

  const fetchHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const res = await axios.get("/admin/system/health", { headers: authHeaders() });
      setHealth(res.data);
    } catch { setHealth({}); }
    finally { setHealthLoading(false); }
  }, []);

  const fetchServiceHealth = useCallback(async () => {
    try {
      const res = await axios.get("/admin/health/services", { headers: authHeaders() });
      setServiceHealth(res.data);
    } catch { /* non-critical */ }
  }, []);

  const fetchAnalytics = useCallback(async () => {
    setAnalyticsLoading(true);
    try {
      const res = await axios.get("/admin/analytics", { headers: authHeaders() });
      setAnalytics(res.data);
    } catch { setAnalytics(null); }
    finally { setAnalyticsLoading(false); }
  }, []);

  const fetchChunks = useCallback(async (search = "") => {
    setChunksLoading(true);
    try {
      const url = search ? `/admin/chunks?search=${encodeURIComponent(search)}` : "/admin/chunks";
      const res = await axios.get(url, { headers: authHeaders() });
      setChunks(res.data.chunks || []);
    } catch { setChunks([]); }
    finally { setChunksLoading(false); }
  }, []);

  const fetchApiKeys = useCallback(async () => {
    setApiKeysLoading(true);
    try {
      const res = await axios.get("/admin/api-keys", { headers: authHeaders() });
      setApiKeys(Array.isArray(res.data) ? res.data : []);
    } catch { setApiKeys([]); }
    finally { setApiKeysLoading(false); }
  }, []);

  const createApiKey = async () => {
    if (!newKeyForm.name) return;
    try {
      const res = await axios.post("/admin/api-keys", newKeyForm, { headers: authHeaders() });
      setCreatedKey(res.data.raw_key || null);
      setShowNewKeyForm(false);
      setNewKeyForm({ name: "", permissions: "read", expires_days: 365, notes: "" });
      fetchApiKeys();
    } catch { /* ignore */ }
  };

  const revokeApiKey = (id: string, name: string) => {
    askConfirm(`Revoke API key "${name}"? All apps using it will lose access immediately.`, async () => {
      try { await axios.delete(`/admin/api-keys/${id}`, { headers: authHeaders() }); } catch { /* ignore */ }
      fetchApiKeys();
      setConfirm(null);
    });
  };

  const fetchStorage = useCallback(async () => {
    setStorageLoading(true);
    try {
      const res = await axios.get("/admin/storage/info", { headers: authHeaders() });
      setStorageInfo(res.data);
    } catch { setStorageInfo(null); }
    finally { setStorageLoading(false); }
  }, []);

  const fetchCacheStats = useCallback(async () => {
    try {
      const res = await axios.get("/admin/cache/stats", { headers: authHeaders() });
      setCacheStats(res.data);
    } catch { setCacheStats(null); }
  }, []);

  const fetchErrorLog = useCallback(async () => {
    setErrorLogLoading(true);
    try {
      const res = await axios.get("/admin/errors?limit=30", { headers: authHeaders() });
      setErrorLog(res.data.entries || []);
    } catch { setErrorLog([]); }
    finally { setErrorLogLoading(false); }
  }, []);

  useEffect(() => {
    if (tab === "overview") { fetchHealth(); fetchServiceHealth(); fetchSecEvents(); fetchAnalytics(); fetchCacheStats(); }
    if (tab === "users") fetchUsers();
    if (tab === "rules") fetchRules();
    if (tab === "security") { fetchSecEvents(); fetchErrorLog(); }
    if (tab === "apikeys") fetchApiKeys();
    if (tab === "monitoring") { fetchAnalytics(); fetchCacheStats(); }
    if (tab === "chunks") fetchChunks();
    if (tab === "storage") fetchStorage();
  }, [tab]);

  // ── Actions ──────────────────────────────────────────────────────────────────
  async function toggleBlock(userId: string, isActive: boolean) {
    const endpoint = isActive ? "block" : "unblock";
    await axios.post(`/auth/users/${userId}/${endpoint}`, {}, { headers: authHeaders() });
    fetchUsers();
  }

  async function addRule() {
    if (!newRule.name || !newRule.pattern) return;
    try {
      await axios.post("/admin/rules", newRule, { headers: authHeaders() });
      setNewRule({ name: "", pattern: "", action: "block", role: "public" });
      setShowNewRule(false);
      fetchRules();
    } catch {
      // Optimistic local add on API failure
      setRules(prev => [...prev, { ...newRule, id: Date.now().toString(), active: true }]);
      setShowNewRule(false);
    }
  }

  function deleteRule(id: string, name: string) {
    askConfirm(`Delete rule "${name}"? This cannot be undone.`, async () => {
      try { await axios.delete(`/admin/rules/${id}`, { headers: authHeaders() }); } catch { /* ignore */ }
      setRules(prev => prev.filter(r => r.id !== id));
      setConfirm(null);
    });
  }

  async function toggleRule(id: string) {
    try {
      await axios.patch(`/admin/rules/${id}/toggle`, {}, { headers: authHeaders() });
    } catch { /* ignore */ }
    setRules(prev => prev.map(r => r.id === id ? { ...r, active: !r.active } : r));
  }

  async function resolveEvent(id: string) {
    try {
      await axios.patch(`/admin/security/events/${id}/resolve`, {}, { headers: authHeaders() });
      setSecEvents(prev => prev.map(e => e.id === id ? { ...e, resolved: true } : e));
    } catch { /* ignore */ }
  }

  if (user?.role !== "admin") {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center p-8 bg-gray-900 border border-gray-800 rounded-2xl max-w-sm">
          <AlertTriangle size={48} className="mx-auto text-red-400 mb-4" />
          <p className="text-white font-bold text-lg mb-2">Access Denied</p>
          <p className="text-gray-400 text-sm">Administrator privileges required.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {confirm && (
        <ConfirmDialog
          message={confirm.message}
          onConfirm={confirm.onConfirm}
          onCancel={() => setConfirm(null)}
        />
      )}
      <TabBar active={tab} setActive={setTab} />
      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* ── OVERVIEW ── */}
        {tab === "overview" && (
          <>
            {/* ── Hero banner ── */}
            <div className="relative overflow-hidden rounded-2xl border border-brand-500/20 bg-gradient-to-br from-brand-900/40 via-gray-900 to-violet-900/20 p-6">
              <div className="absolute inset-0 opacity-5" style={{
                backgroundImage: "radial-gradient(circle at 20% 50%, #6366f1 0%, transparent 50%), radial-gradient(circle at 80% 20%, #8b5cf6 0%, transparent 40%)"
              }} />
              <div className="relative flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                    <span className="text-xs text-emerald-400 font-semibold uppercase tracking-widest">Platform Live</span>
                  </div>
                  <h2 className="text-2xl font-bold text-white">CortexFlow Admin</h2>
                  <p className="text-sm text-gray-400 mt-1">System is operational · All services monitored</p>
                </div>
                <div className="flex items-center gap-6 shrink-0">
                  {[
                    { label: "Queries", value: analytics?.total_queries ?? "—", color: "text-brand-400" },
                    { label: "Users", value: analytics?.total_users ?? "—", color: "text-violet-400" },
                    { label: "Cache Hit", value: cacheStats ? `${cacheStats.hit_rate_pct ?? 0}%` : "—", color: "text-emerald-400" },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="text-center">
                      <p className={`text-2xl font-bold ${color}`}>{value}</p>
                      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* ── System health cards ── */}
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-3">Service Health</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <SystemCard icon={Database} label="Vector DB (Qdrant)"
                  value={health.qdrant?.vectors != null ? `${health.qdrant.vectors} vectors` : "Qdrant"}
                  status={health.qdrant?.status || "warn"} color="text-blue-400"
                  extra={health.qdrant?.error ? "Error — check service" : "Real-time vector search"} />
                <SystemCard icon={GitBranch} label="Graph DB"
                  value={health.neo4j?.nodes != null ? `${health.neo4j.nodes} nodes` : "SQLite"}
                  status={health.neo4j?.status || "online"} color="text-emerald-400"
                  extra="SQLite (Neo4j fallback)" />
                <SystemCard icon={Zap} label="LLM Engine"
                  value={health.llm?.model || "command-r7b-12-2024"}
                  status={health.llm?.status || "online"} color="text-amber-400"
                  extra="Cohere API · RAG powered" />
                <SystemCard icon={Shield} label="Auth & Security"
                  value="JWT + API Keys"
                  status="online" color="text-violet-400"
                  extra={`${secStats?.total_events ?? secEvents.length} events logged`} />
              </div>

              {/* Fallback pills */}
              {Object.entries(serviceHealth).some(([, v]) => v.status === "down") && (
                <div className="flex flex-wrap gap-2 mt-3">
                  {Object.entries(serviceHealth).filter(([, v]) => v.status === "down").map(([name, v]) => (
                    <div key={name} className="flex items-center gap-2 rounded-lg border border-gray-700 bg-gray-800/80 px-3 py-1.5 text-xs">
                      <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
                      <span className="capitalize font-semibold text-gray-300">{name}</span>
                      <span className="text-gray-500">— using SQLite fallback</span>
                      {v.last_ok && <span className="text-gray-600">· last seen {new Date(v.last_ok).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* ── Recent security events — timeline style ── */}
            <div className="bg-gray-800/50 border border-gray-700 rounded-2xl overflow-hidden">
              <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700/50">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-red-500/15 flex items-center justify-center">
                    <AlertTriangle size={15} className="text-red-400" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white">Recent Security Events</h3>
                    <p className="text-xs text-gray-500">{secStats?.total_events ?? secEvents.length} total events logged</p>
                  </div>
                </div>
                <button onClick={fetchSecEvents} className="p-1.5 hover:bg-gray-700 rounded-lg text-gray-500 hover:text-white transition">
                  <RefreshCw size={13} className={secLoading ? "animate-spin" : ""} />
                </button>
              </div>

              {secLoading ? (
                <div className="px-6 py-8 text-center text-sm text-gray-500">Loading events…</div>
              ) : secEvents.length === 0 ? (
                <div className="px-6 py-8 text-center">
                  <Shield size={32} className="mx-auto text-gray-700 mb-2" />
                  <p className="text-sm text-gray-500">No security events — system is clean</p>
                </div>
              ) : (
                <div className="divide-y divide-gray-700/50">
                  {secEvents.slice(0, 6).map(ev => {
                    const sevStyles: Record<string, { dot: string; badge: string; bg: string }> = {
                      critical: { dot: "bg-red-400",    badge: "text-red-300 bg-red-500/15 border-red-500/30",    bg: "bg-red-900/5" },
                      high:     { dot: "bg-orange-400", badge: "text-orange-300 bg-orange-500/15 border-orange-500/30", bg: "bg-orange-900/5" },
                      medium:   { dot: "bg-yellow-400", badge: "text-yellow-300 bg-yellow-500/15 border-yellow-500/30", bg: "" },
                      low:      { dot: "bg-blue-400",   badge: "text-blue-300 bg-blue-500/15 border-blue-500/30",  bg: "" },
                    };
                    const sev = sevStyles[ev.severity] || sevStyles.low;
                    // Show event_type if description looks like a severity word (bad data)
                    const SWORDS = new Set(["medium", "high", "low", "critical", "info", "warn", "warning"]);
                    const displayDesc = SWORDS.has((ev.description || "").trim().toLowerCase())
                      ? (ev.event_type || ev.description).replace(/_/g, " ")
                      : (ev.description || ev.event_type || "—");
                    return (
                      <div key={ev.id} className={`flex items-start gap-4 px-6 py-4 ${sev.bg} hover:bg-gray-700/20 transition`}>
                        {/* Timeline dot */}
                        <div className="flex flex-col items-center gap-1 pt-0.5">
                          <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${sev.dot}`} />
                        </div>
                        {/* Content */}
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-gray-100 leading-snug line-clamp-2">{displayDesc}</p>
                          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                            <span className={`text-xs px-2 py-0.5 rounded-full border font-semibold capitalize ${sev.badge}`}>
                              {ev.severity}
                            </span>
                            {ev.event_type && (
                              <span className="text-xs text-gray-500 bg-gray-700/60 px-2 py-0.5 rounded-full">
                                {ev.event_type.replace(/_/g, " ")}
                              </span>
                            )}
                            <span className="text-xs text-gray-500">{ev.user_email || "system"}</span>
                          </div>
                        </div>
                        <div className="shrink-0 text-right">
                          <p className="text-xs text-gray-500">
                            {new Date(ev.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                          </p>
                          {ev.resolved && (
                            <span className="text-xs text-emerald-400 font-medium">✓ resolved</span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </>
        )}

        {/* ── USERS ── */}
        {tab === "users" && (
          <div className="space-y-4">
            {/* Search bar */}
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input value={userSearch} onChange={e => setUserSearch(e.target.value)}
                placeholder="Search by email or name…"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-9 pr-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500" />
            </div>
          <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
              <h3 className="font-semibold text-white flex items-center gap-2"><Users size={16} /> User Management</h3>
              <button onClick={fetchUsers} className="p-1.5 hover:bg-gray-700 rounded-lg text-gray-400 hover:text-white transition">
                <RefreshCw size={14} className={usersLoading ? "animate-spin" : ""} />
              </button>
            </div>
            {usersLoading ? (
              <div className="p-8 text-center text-gray-400 text-sm">Loading users…</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-900/50">
                    <tr>
                      {["Email", "Name", "Role", "Risk", "Status", "Queries", "Actions"].map(h => (
                        <th key={h} className="text-left py-3 px-4 text-xs font-medium text-gray-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-700/50">
                    {users.filter(u => !userSearch || u.email?.toLowerCase().includes(userSearch.toLowerCase()) || u.name?.toLowerCase().includes(userSearch.toLowerCase())).map(u => (
                      <tr key={u.id} className="hover:bg-gray-700/30 transition">
                        <td className="py-3.5 px-4 text-white">
                          <div className="flex items-center gap-2">
                            {(u.risk_level === "high" || u.risk_level === "critical") && (
                              <AlertTriangle size={13} className="text-red-400 shrink-0" />
                            )}
                            {u.email}
                          </div>
                        </td>
                        <td className="py-3.5 px-4 text-gray-300">{u.name}</td>
                        <td className="py-3.5 px-4">
                          <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${
                            u.role === "admin"
                              ? "bg-purple-600/20 text-purple-300 border border-purple-500/30"
                              : "bg-blue-600/20 text-blue-300 border border-blue-500/30"
                          }`}>{u.role}</span>
                        </td>
                        <td className="py-3.5 px-4">
                          <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${
                            RISK_STYLE[u.risk_level || "low"]
                          }`}>
                            {u.risk_level || "low"} {u.risk_score ? `(${u.risk_score})` : ""}
                          </span>
                        </td>
                        <td className="py-3.5 px-4">
                          <span className={`flex items-center gap-1.5 text-xs font-medium w-fit ${u.is_active ? "text-emerald-400" : "text-red-400"}`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${u.is_active ? "bg-emerald-400" : "bg-red-400"}`} />
                            {u.is_active ? "Active" : "Blocked"}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 text-gray-400 text-xs">{u.total_queries ?? 0}</td>
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => toggleBlock(u.id, u.is_active)}
                              className={`p-1 rounded transition ${
                                u.is_active
                                  ? "hover:bg-red-500/20 text-gray-400 hover:text-red-400"
                                  : "hover:bg-emerald-500/20 text-gray-400 hover:text-emerald-400"
                              }`}
                              title={u.is_active ? "Block user" : "Unblock user"}
                            >
                              {u.is_active ? <UserX size={14} /> : <UserCheck size={14} />}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {users.length === 0 && (
                      <tr><td colSpan={7} className="py-8 text-center text-gray-400 text-sm">No users found.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          </div>
        )}

        {/* ── SECURITY ── */}
        {tab === "security" && (
          <div className="space-y-6">
            {/* Stats row */}
            {secStats && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {[
                  { label: "Total Events", value: secStats.total_events, color: "text-gray-300" },
                  { label: "High Severity", value: secStats.high_severity, color: "text-red-400" },
                  { label: "Unresolved", value: secStats.unresolved, color: "text-yellow-400" },
                  { label: "Risky Users", value: secStats.risky_users, color: "text-orange-400" },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-gray-800 border border-gray-700 rounded-xl p-4">
                    <p className="text-xs text-gray-400 mb-1">{label}</p>
                    <p className={`text-2xl font-bold ${color}`}>{value ?? 0}</p>
                  </div>
                ))}
              </div>
            )}

            {/* Events list */}
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-white flex items-center gap-2">
                  <Shield size={16} className="text-red-400" /> Threat Detection Log
                </h3>
                <button onClick={fetchSecEvents} className="p-1 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition">
                  <RefreshCw size={13} className={secLoading ? "animate-spin" : ""} />
                </button>
              </div>
              {secLoading ? (
                <p className="text-sm text-gray-400">Loading…</p>
              ) : secEvents.length === 0 ? (
                <div className="text-center py-8">
                  <Shield size={32} className="mx-auto text-emerald-400 mb-2 opacity-50" />
                  <p className="text-sm text-gray-400">No threats detected. System is clean.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {secEvents.map(ev => (
                    <div key={ev.id} className={`flex items-start gap-3 p-4 rounded-xl border ${SEVERITY_STYLE[ev.severity] || SEVERITY_STYLE.low} ${ev.resolved ? "opacity-50" : ""}`}>
                      <AlertTriangle size={16} className="shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <div className="flex justify-between items-start gap-2">
                          <p className="text-sm font-medium text-white">{ev.description}</p>
                          <div className="flex items-center gap-2 shrink-0">
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                              ev.severity === "high" || ev.severity === "critical"
                                ? "bg-red-500/20 text-red-300"
                                : ev.severity === "medium"
                                ? "bg-yellow-500/20 text-yellow-300"
                                : "bg-blue-500/20 text-blue-300"
                            }`}>{ev.severity}</span>
                            {!ev.resolved && (
                              <button onClick={() => resolveEvent(ev.id)}
                                className="text-xs px-2 py-0.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition">
                                Resolve
                              </button>
                            )}
                            {ev.resolved && (
                              <span className="text-xs text-emerald-400 flex items-center gap-1">
                                <Check size={10} /> Resolved
                              </span>
                            )}
                          </div>
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {ev.user_email || "unknown"} · {new Date(ev.created_at).toLocaleString()} · {ev.event_type}
                        </p>
                        {ev.query && (
                          <code className="text-xs text-gray-500 bg-gray-900/50 px-2 py-0.5 rounded mt-1 block truncate">
                            {ev.query.slice(0, 120)}
                          </code>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Error / Audit log — live from backend */}
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-white flex items-center gap-2">
                  <FileText size={16} className="text-red-400" /> Error Log (live)
                </h3>
                <button onClick={fetchErrorLog} className="p-1 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition">
                  <RefreshCw size={13} className={errorLogLoading ? "animate-spin" : ""} />
                </button>
              </div>
              {errorLogLoading ? (
                <p className="text-sm text-gray-400">Loading…</p>
              ) : errorLog.length === 0 ? (
                <div className="text-center py-6">
                  <Check size={28} className="mx-auto text-emerald-400 mb-2 opacity-60" />
                  <p className="text-sm text-gray-400">No errors logged. System is healthy.</p>
                </div>
              ) : (
                <div className="space-y-1 text-xs font-mono max-h-64 overflow-y-auto">
                  {errorLog.map((entry: any, i: number) => (
                    <div key={i} className="flex gap-3 py-1.5 border-b border-gray-700/50">
                      <span className="text-gray-500 shrink-0">{(entry.timestamp || "").slice(0, 19).replace("T", " ")}</span>
                      <span className={entry.level === "ERROR" || entry.level === "CRITICAL" ? "text-red-400" : entry.level === "WARNING" ? "text-yellow-400" : "text-gray-300"}>
                        [{entry.level}] [{entry.source}] {entry.message}
                        {entry.exception ? ` | ${entry.exception}` : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── RULE ENGINE ── */}
        {tab === "rules" && (
          <div className="space-y-5">
            <div className="flex justify-between items-center">
              <div>
                <h3 className="font-semibold text-white">Dynamic Rule Engine</h3>
                <p className="text-xs text-gray-400 mt-0.5">Control access patterns and query filtering per role. Rules are stored persistently.</p>
              </div>
              <button onClick={() => setShowNewRule(!showNewRule)}
                className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg transition">
                <Plus size={14} /> Add Rule
              </button>
            </div>

            {showNewRule && (
              <div className="bg-gray-800 border border-brand-500/30 rounded-xl p-5 space-y-3">
                <h4 className="text-sm font-medium text-white">New Rule</h4>
                <div className="grid grid-cols-2 gap-3">
                  <input placeholder="Rule name" value={newRule.name}
                    onChange={e => setNewRule(p => ({ ...p, name: e.target.value }))}
                    className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500" />
                  <input placeholder="Pattern (regex)" value={newRule.pattern}
                    onChange={e => setNewRule(p => ({ ...p, pattern: e.target.value }))}
                    className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 font-mono focus:outline-none focus:border-brand-500" />
                  <select value={newRule.action} onChange={e => setNewRule(p => ({ ...p, action: e.target.value }))}
                    className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-500">
                    <option value="block">Block query</option>
                    <option value="warn">Warn user</option>
                    <option value="restrict">Restrict to role</option>
                    <option value="log">Log only</option>
                  </select>
                  <select value={newRule.role} onChange={e => setNewRule(p => ({ ...p, role: e.target.value }))}
                    className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-500">
                    <option value="public">Public</option>
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <div className="flex gap-2">
                  <button onClick={addRule} className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg transition">
                    <Check size={13} /> Save Rule
                  </button>
                  <button onClick={() => setShowNewRule(false)} className="px-4 py-2 text-gray-400 hover:text-white text-sm transition">Cancel</button>
                </div>
              </div>
            )}

            <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
              {rulesLoading ? (
                <div className="p-8 text-center text-gray-400 text-sm">Loading rules…</div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-gray-900/50">
                    <tr>
                      {["Rule Name", "Pattern", "Action", "Role", "Status", ""].map(h => (
                        <th key={h} className="text-left py-3 px-4 text-xs font-medium text-gray-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-700/50">
                    {rules.map(rule => (
                      <tr key={rule.id} className="hover:bg-gray-700/30 transition">
                        <td className="py-3.5 px-4 text-white font-medium">{rule.name}</td>
                        <td className="py-3.5 px-4">
                          <code className="text-xs bg-gray-900 text-emerald-300 px-2 py-0.5 rounded font-mono">{rule.pattern}</code>
                        </td>
                        <td className="py-3.5 px-4">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                            rule.action === "block" ? "bg-red-500/20 text-red-300" :
                            rule.action === "warn" ? "bg-yellow-500/20 text-yellow-300" :
                            rule.action === "restrict" ? "bg-purple-500/20 text-purple-300" :
                            "bg-gray-600/50 text-gray-300"
                          }`}>{rule.action}</span>
                        </td>
                        <td className="py-3.5 px-4 text-gray-400 text-xs capitalize">{rule.role}</td>
                        <td className="py-3.5 px-4">
                          <button onClick={() => toggleRule(rule.id)}
                            className={`text-xs px-2 py-0.5 rounded-full font-medium transition ${
                              rule.active
                                ? "bg-emerald-500/20 text-emerald-300 hover:bg-red-500/20 hover:text-red-300"
                                : "bg-gray-600/50 text-gray-400 hover:bg-emerald-500/20 hover:text-emerald-300"
                            }`}>{rule.active ? "Active" : "Disabled"}</button>
                        </td>
                        <td className="py-3.5 px-4">
                          <button onClick={() => deleteRule(rule.id, rule.name)}
                            className="p-1.5 hover:bg-red-500/20 rounded text-gray-500 hover:text-red-400 transition"
                            title="Delete rule">
                            <Trash2 size={13} />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {rules.length === 0 && (
                      <tr><td colSpan={6} className="py-8 text-center text-gray-400 text-sm">No rules configured.</td></tr>
                    )}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {/* ── API KEYS ── */}
        {tab === "apikeys" && (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2"><Key size={18} className="text-brand-400" /> API Key Management</h3>
                <p className="text-xs text-gray-400 mt-0.5">Generate keys so external apps or chatbots can integrate with CortexFlow without a login.</p>
              </div>
              <button onClick={() => { setShowNewKeyForm(!showNewKeyForm); setCreatedKey(null); }}
                className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg transition">
                <Plus size={14} /> Create Key
              </button>
            </div>

            {/* Create key form */}
            {showNewKeyForm && (
              <div className="bg-gray-800 border border-brand-500/30 rounded-xl p-5 space-y-4">
                <h4 className="text-sm font-semibold text-white">New API Key</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Key Name *</label>
                    <input placeholder="e.g. My Chatbot" value={newKeyForm.name}
                      onChange={e => setNewKeyForm(p => ({ ...p, name: e.target.value }))}
                      className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Permissions</label>
                    <select value={newKeyForm.permissions}
                      onChange={e => setNewKeyForm(p => ({ ...p, permissions: e.target.value }))}
                      className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-500">
                      <option value="read">Read — can only ask questions</option>
                      <option value="read_write">Read & Write — can also upload</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Expires In (days)</label>
                    <input type="number" min={1} max={3650} value={newKeyForm.expires_days}
                      onChange={e => setNewKeyForm(p => ({ ...p, expires_days: parseInt(e.target.value) || 365 }))}
                      className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-500" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Notes (optional)</label>
                    <input placeholder="e.g. Customer portal" value={newKeyForm.notes}
                      onChange={e => setNewKeyForm(p => ({ ...p, notes: e.target.value }))}
                      className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500" />
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={createApiKey} className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg transition">
                    <Check size={13} /> Generate Key
                  </button>
                  <button onClick={() => setShowNewKeyForm(false)} className="px-4 py-2 text-gray-400 hover:text-white text-sm transition">Cancel</button>
                </div>
              </div>
            )}

            {/* Raw key shown once */}
            {createdKey && (
              <div className="bg-emerald-900/20 border border-emerald-600/40 rounded-xl p-5 space-y-3">
                <div className="flex items-center gap-2">
                  <Check size={16} className="text-emerald-400" />
                  <p className="text-sm font-semibold text-emerald-300">API Key Created — copy it now, it won't be shown again</p>
                </div>
                <div className="flex items-center gap-2 bg-gray-900 rounded-lg px-3 py-2.5">
                  <code className="flex-1 text-sm text-emerald-300 font-mono break-all">
                    {showRawKey ? createdKey : "cf_live_" + "•".repeat(36)}
                  </code>
                  <button onClick={() => setShowRawKey(v => !v)} className="text-gray-500 hover:text-gray-300 transition shrink-0">
                    {showRawKey ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                  <button onClick={() => navigator.clipboard.writeText(createdKey)}
                    className="flex items-center gap-1 text-xs text-brand-400 hover:text-brand-300 transition shrink-0">
                    <Copy size={13} /> Copy
                  </button>
                </div>
                <p className="text-xs text-gray-400">Add this as an <code className="text-brand-300">X-API-Key</code> header in your HTTP requests.</p>
                <button onClick={() => setCreatedKey(null)} className="text-xs text-gray-500 hover:text-gray-300 transition">Dismiss</button>
              </div>
            )}

            {/* Keys table */}
            <div className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden">
              {apiKeysLoading ? (
                <div className="p-8 text-center text-gray-400 text-sm">Loading keys…</div>
              ) : apiKeys.length === 0 ? (
                <div className="p-8 text-center text-gray-500">
                  <Key size={36} className="mx-auto mb-3 opacity-30" />
                  <p className="text-sm">No API keys yet. Create one to let external apps connect.</p>
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-gray-900/50">
                    <tr>
                      {["Name", "Prefix", "Permissions", "Requests", "Last Used", "Expires", "Status", ""].map(h => (
                        <th key={h} className="text-left py-3 px-4 text-xs font-medium text-gray-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-700/50">
                    {apiKeys.map(k => (
                      <tr key={k.id} className="hover:bg-gray-700/30 transition">
                        <td className="py-3.5 px-4 text-white font-medium">{k.name}</td>
                        <td className="py-3.5 px-4"><code className="text-xs bg-gray-900 text-brand-300 px-2 py-0.5 rounded">{k.key_prefix}…</code></td>
                        <td className="py-3.5 px-4">
                          <span className={`text-xs px-2 py-0.5 rounded-full ${k.permissions === "read_write" ? "bg-purple-500/20 text-purple-300" : "bg-blue-500/20 text-blue-300"}`}>
                            {k.permissions === "read_write" ? "Read & Write" : "Read only"}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 text-gray-400 text-xs">{k.total_requests ?? 0}</td>
                        <td className="py-3.5 px-4 text-gray-400 text-xs">{k.last_used_at ? new Date(k.last_used_at).toLocaleDateString() : "Never"}</td>
                        <td className="py-3.5 px-4 text-gray-400 text-xs">{k.expires_at ? new Date(k.expires_at).toLocaleDateString() : "Never"}</td>
                        <td className="py-3.5 px-4">
                          <span className={`text-xs px-2 py-0.5 rounded-full ${k.is_active ? "bg-emerald-500/20 text-emerald-300" : "bg-red-500/20 text-red-300"}`}>
                            {k.is_active ? "Active" : "Revoked"}
                          </span>
                        </td>
                        <td className="py-3.5 px-4">
                          {k.is_active && (
                            <button onClick={() => revokeApiKey(k.id, k.name)}
                              className="p-1.5 hover:bg-red-500/20 rounded text-gray-500 hover:text-red-400 transition" title="Revoke key">
                              <X size={13} />
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* API Base URL */}
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-2">
              <p className="text-sm font-semibold text-white flex items-center gap-2">
                <Server size={14} className="text-brand-400" /> API Base URL
              </p>
              <div className="flex items-center gap-2 bg-gray-900 rounded-lg px-3 py-2">
                <code className="flex-1 text-sm text-brand-300 font-mono">{window.location.origin}</code>
                <button onClick={() => navigator.clipboard.writeText(window.location.origin)}
                  className="text-gray-500 hover:text-gray-300 transition shrink-0" title="Copy URL">
                  <Copy size={13} />
                </button>
              </div>
              <p className="text-xs text-gray-500">Use this as the base for all API requests when integrating from external apps.</p>
            </div>

            {/* API Documentation */}
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
              <p className="text-sm font-semibold text-white flex items-center gap-2">
                <FileText size={14} className="text-brand-400" /> API Documentation
              </p>
              {[
                {
                  method: "GET", path: "/api/verify", color: "text-emerald-400 bg-emerald-400/10",
                  desc: "Verify your API key is valid",
                  curl: `curl ${window.location.origin}/api/verify -H "X-API-Key: cf_live_…"`,
                },
                {
                  method: "POST", path: "/ask", color: "text-blue-400 bg-blue-400/10",
                  desc: "Ask a question — returns an AI answer based on your documents",
                  curl: `curl -X POST ${window.location.origin}/ask -H "X-API-Key: cf_live_…" -H "Content-Type: application/json" -d '{"question":"What is the contract value?"}'`,
                },
                {
                  method: "POST", path: "/upload", color: "text-blue-400 bg-blue-400/10",
                  desc: "Upload a document (PDF, DOCX, TXT, CSV…) — ingested into your private tenant",
                  curl: `curl -X POST ${window.location.origin}/upload -H "X-API-Key: cf_live_…" -F "file=@document.pdf"`,
                },
                {
                  method: "GET", path: "/chat/history", color: "text-emerald-400 bg-emerald-400/10",
                  desc: "Get your recent chat history",
                  curl: `curl ${window.location.origin}/chat/history -H "X-API-Key: cf_live_…"`,
                },
              ].map(({ method, path, color, desc, curl }) => (
                <div key={path} className="bg-gray-900 rounded-lg p-3 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${color}`}>{method}</span>
                    <code className="text-sm text-white font-mono">{path}</code>
                    <span className="text-xs text-gray-400 ml-1">{desc}</span>
                  </div>
                  <div className="flex items-center gap-2 bg-gray-800 rounded px-2 py-1.5">
                    <code className="flex-1 text-xs text-gray-400 font-mono truncate">{curl}</code>
                    <button onClick={() => navigator.clipboard.writeText(curl)}
                      className="text-gray-600 hover:text-gray-300 transition shrink-0" title="Copy">
                      <Copy size={11} />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* Usage Analytics per key */}
            {apiKeys.length > 0 && (
              <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 space-y-3">
                <p className="text-sm font-semibold text-white flex items-center gap-2">
                  <BarChart3 size={14} className="text-brand-400" /> Usage Analytics
                </p>
                <div className="space-y-2">
                  {apiKeys.filter(k => k.is_active).map(k => {
                    const maxReqs = Math.max(...apiKeys.map(x => x.total_requests || 0), 1);
                    const pct = Math.max(((k.total_requests || 0) / maxReqs) * 100, 2);
                    return (
                      <div key={k.id} className="space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-gray-300 font-medium truncate max-w-[180px]">{k.name}</span>
                          <span className="text-gray-400 shrink-0 ml-2">{k.total_requests ?? 0} req</span>
                        </div>
                        <div className="bg-gray-700 rounded-full h-1.5">
                          <div className="bg-brand-500 h-1.5 rounded-full transition-all" style={{ width: `${pct}%` }} />
                        </div>
                        <p className="text-xs text-gray-600">
                          Last used: {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "Never"} &bull; Permissions: {k.permissions}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── MONITORING ── */}
        {tab === "monitoring" && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: "Avg Latency", value: analytics ? `${analytics.avg_latency_ms.toFixed(0)}ms` : "—", trend: "vs last hour", good: true },
                { label: "Cache Hit Rate", value: cacheStats ? `${cacheStats.hit_rate_pct}%` : (analytics ? `${analytics.cache_hit_rate.toFixed(1)}%` : "—"), trend: `${cacheStats?.active_entries ?? 0} active entries`, good: true },
                { label: "Cache Memory", value: cacheStats ? `${cacheStats.memory_kb ?? 0} KB` : "—", trend: `${cacheStats?.total_requests ?? 0} total requests`, good: true },
                { label: "Avg Confidence", value: analytics ? `${analytics.avg_confidence.toFixed(1)}%` : "—", trend: "answer quality", good: true },
              ].map(({ label, value, trend, good }) => (
                <div key={label} className="bg-gray-800 border border-gray-700 rounded-xl p-5">
                  <p className="text-xs text-gray-400 mb-1">{label}</p>
                  <p className="text-2xl font-bold text-white">{value}</p>
                  <p className={`text-xs mt-1 font-medium ${good ? "text-emerald-400" : "text-red-400"}`}>{trend}</p>
                </div>
              ))}
            </div>

            {/* Hourly bar chart */}
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-6">
              <h3 className="font-semibold text-white mb-5">Queries per Hour (Today)</h3>
              <div className="flex items-end gap-1 h-32">
                {(analytics?.hourly_queries || Array(24).fill(0)).map((v: number, i: number) => (
                  <div key={i} className="flex-1 flex flex-col items-center gap-1">
                    <div className="w-full rounded-t bg-brand-600 hover:bg-brand-500 transition"
                      style={{ height: `${v > 0 ? Math.max((v / Math.max(...(analytics?.hourly_queries || [1]))) * 100, 4) : 4}%`, minHeight: "4px" }} />
                    {i % 6 === 0 && <span className="text-xs text-gray-600">{i}h</span>}
                  </div>
                ))}
              </div>
            </div>

            {/* Response quality by query type */}
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-6">
              <h3 className="font-semibold text-white mb-4">Response Quality by Query Type</h3>
              <div className="space-y-3">
                {(analytics?.retrieval_quality || [
                  { type: "Fact lookup", score: 94, queries: 342 },
                  { type: "Summary", score: 88, queries: 198 },
                  { type: "Multi-hop", score: 83, queries: 120 },
                  { type: "Analytical", score: 79, queries: 87 },
                  { type: "Comparison", score: 74, queries: 65 },
                ]).map(({ type, score, queries }: any) => (
                  <div key={type} className="flex items-center gap-3">
                    <span className="text-sm text-gray-300 w-28 shrink-0">{type}</span>
                    <div className="flex-1 bg-gray-700 rounded-full h-2">
                      <div className="bg-brand-500 h-2 rounded-full transition-all" style={{ width: `${score}%` }} />
                    </div>
                    <span className="text-xs text-brand-300 font-medium w-10 text-right">{score}%</span>
                    <span className="text-xs text-gray-500 w-14 text-right">{queries} q</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Live Ingest Queue */}
            <IngestQueuePanel authHeaders={authHeaders} />
          </div>
        )}

        {/* ── CHUNKS (Qdrant) ── */}
        {tab === "chunks" && (
          <ChunksTab
            chunks={chunks}
            loading={chunksLoading}
            search={chunkSearch}
            setSearch={setChunkSearch}
            onSearch={() => fetchChunks(chunkSearch)}
            onRefresh={() => fetchChunks(chunkSearch)}
          />
        )}

        {/* ── STORAGE INFO ── */}
        {tab === "storage" && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <HardDrive size={18} className="text-emerald-400" /> Storage Information
                </h3>
                <p className="text-xs text-gray-400 mt-0.5">Database and vector store details</p>
              </div>
              <button onClick={fetchStorage} disabled={storageLoading}
                className="flex items-center gap-2 px-3 py-2 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition text-xs disabled:opacity-50">
                <RefreshCw size={13} className={storageLoading ? "animate-spin text-brand-400" : ""} />
                Refresh
              </button>
            </div>

            {storageLoading ? (
              <div className="flex items-center justify-center h-32 gap-3 text-gray-400">
                <RefreshCw size={18} className="animate-spin text-brand-400" />
                <span className="text-sm">Loading storage info…</span>
              </div>
            ) : !storageInfo ? (
              <div className="text-center py-12 text-gray-500">
                <HardDrive size={40} className="mx-auto mb-3 opacity-30" />
                <p className="text-sm">Could not load storage info. Backend may be unavailable.</p>
                <button onClick={fetchStorage} className="mt-3 text-xs text-brand-400 hover:text-brand-300 underline">Retry</button>
              </div>
            ) : (
              <div className="grid md:grid-cols-2 gap-6">
                {/* SQLite / PostgreSQL */}
                <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 space-y-4">
                  <div className="flex items-center gap-3 mb-2">
                    <Database size={20} className="text-brand-400" />
                    <div>
                      <h4 className="font-semibold text-white">Relational Database</h4>
                      <p className="text-xs text-gray-400">{storageInfo.database?.type || "Unknown"}</p>
                    </div>
                    <span className="ml-auto text-xs bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded-full border border-emerald-500/20">● Online</span>
                  </div>
                  <div className="space-y-2.5 text-sm">
                    {[
                      { label: "Type", value: storageInfo.database?.type },
                      { label: "Location", value: storageInfo.database?.location, mono: true },
                      { label: "Size", value: storageInfo.database?.size_bytes != null ? `${(storageInfo.database.size_bytes / 1024).toFixed(1)} KB` : "—" },
                      { label: "Users", value: storageInfo.database?.users },
                      { label: "Chat Logs", value: storageInfo.database?.chat_logs },
                      { label: "Rules", value: storageInfo.database?.rules },
                    ].map(({ label, value, mono }) => (
                      <div key={label} className="flex justify-between items-center py-1.5 border-b border-gray-700/60 last:border-0">
                        <span className="text-gray-400">{label}</span>
                        <span className={`text-white font-medium ${mono ? "font-mono text-xs text-brand-300" : ""}`}>
                          {value ?? "—"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Qdrant */}
                <div className="bg-gray-800 border border-gray-700 rounded-xl p-6 space-y-4">
                  <div className="flex items-center gap-3 mb-2">
                    <Layers size={20} className="text-blue-400" />
                    <div>
                      <h4 className="font-semibold text-white">Vector Store (Qdrant)</h4>
                      <p className="text-xs text-gray-400">{storageInfo.vector_store?.host || "localhost:6333"}</p>
                    </div>
                    <span className={`ml-auto text-xs px-2 py-0.5 rounded-full border ${
                      storageInfo.vector_store?.status === "online"
                        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/20"
                        : "bg-red-500/20 text-red-300 border-red-500/20"
                    }`}>
                      {storageInfo.vector_store?.status === "online" ? "● Online" : "✕ Offline"}
                    </span>
                  </div>
                  <div className="space-y-2.5 text-sm">
                    {[
                      { label: "Status", value: storageInfo.vector_store?.status },
                      { label: "Total Vectors", value: storageInfo.vector_store?.total_vectors ?? 0 },
                      { label: "Collections", value: storageInfo.vector_store?.collections?.length ?? 0 },
                    ].map(({ label, value }) => (
                      <div key={label} className="flex justify-between items-center py-1.5 border-b border-gray-700/60 last:border-0">
                        <span className="text-gray-400">{label}</span>
                        <span className="text-white font-medium">{value ?? "—"}</span>
                      </div>
                    ))}
                    {(storageInfo.vector_store?.collections || []).length > 0 && (
                      <div className="pt-2">
                        <p className="text-xs text-gray-400 mb-2">Collections:</p>
                        <div className="flex flex-wrap gap-2">
                          {storageInfo.vector_store.collections.map((col: string) => (
                            <span key={col} className="text-xs bg-blue-500/20 text-blue-300 px-2 py-0.5 rounded-full border border-blue-500/20">
                              {col}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {storageInfo.vector_store?.error && (
                      <div className="mt-2 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                        <p className="text-xs text-red-400">{storageInfo.vector_store.error}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
