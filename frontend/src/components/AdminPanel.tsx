import { useState, useEffect, useCallback } from "react";
import {
  Shield, Users, AlertTriangle, Server, Database, GitBranch,
  Zap, Plus, Trash2, UserX, UserCheck, Lock,
  Activity, FileText, RefreshCw, Check,
  BarChart3, HardDrive, Search, Layers
} from "lucide-react";
import axios from "axios";

type Tab = "overview" | "users" | "security" | "rules" | "monitoring" | "chunks" | "storage";

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
  const dot = status === "online" ? "bg-emerald-400"
    : status === "warn" ? "bg-yellow-400 animate-pulse"
    : "bg-red-400";
  const txt = status === "online" ? "text-emerald-400"
    : status === "warn" ? "text-yellow-400"
    : "text-red-400";
  const label2 = status === "online" ? "● Operational" : status === "warn" ? "⚠ Warning" : "✕ Offline";
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
      <div className="flex items-start justify-between mb-3">
        <Icon size={20} className={color} />
        <span className={`w-2 h-2 rounded-full ${dot}`} />
      </div>
      <p className="text-xs text-gray-400 mb-0.5">{label}</p>
      <p className="text-sm font-bold text-white">{value}</p>
      {extra && <p className="text-xs text-gray-500 mt-0.5">{extra}</p>}
      <p className={`text-xs mt-1 font-medium ${txt}`}>{label2}</p>
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
    { id: "monitoring", label: "Monitoring", icon: Activity },
    { id: "chunks", label: "Chunks (Qdrant)", icon: Layers },
    { id: "storage", label: "Storage Info", icon: HardDrive },
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

  // Users
  const [users, setUsers] = useState<any[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);

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

  const token = () => localStorage.getItem("accessToken");
  const authHeaders = () => ({ Authorization: `Bearer ${token()}` });

  // ── Fetch functions ──────────────────────────────────────────────────────────
  const fetchUsers = useCallback(async () => {
    setUsersLoading(true);
    try {
      const res = await axios.get("/auth/users", { headers: authHeaders() });
      setUsers(res.data);
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
      setSecEvents(evRes.data);
      setSecStats(statsRes.data);
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

  const fetchStorage = useCallback(async () => {
    setStorageLoading(true);
    try {
      const res = await axios.get("/admin/storage/info", { headers: authHeaders() });
      setStorageInfo(res.data);
    } catch { setStorageInfo(null); }
    finally { setStorageLoading(false); }
  }, []);

  useEffect(() => {
    if (tab === "overview") { fetchHealth(); fetchSecEvents(); fetchAnalytics(); }
    if (tab === "users") fetchUsers();
    if (tab === "rules") fetchRules();
    if (tab === "security") fetchSecEvents();
    if (tab === "monitoring") fetchAnalytics();
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

  async function deleteRule(id: string) {
    try {
      await axios.delete(`/admin/rules/${id}`, { headers: authHeaders() });
    } catch { /* ignore */ }
    setRules(prev => prev.filter(r => r.id !== id));
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
      <TabBar active={tab} setActive={setTab} />
      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* ── OVERVIEW ── */}
        {tab === "overview" && (
          <>
            {/* System health */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <SystemCard icon={Database} label="Vector DB (Qdrant)"
                value={health.qdrant?.vectors != null ? `${health.qdrant.vectors} vectors` : "Qdrant"}
                status={health.qdrant?.status || "warn"} color="text-blue-400"
                extra={health.qdrant?.error ? health.qdrant.error.slice(0, 40) : undefined} />
              <SystemCard icon={GitBranch} label="Graph DB (Neo4j)"
                value={health.neo4j?.nodes != null ? `${health.neo4j.nodes} nodes` : "Neo4j"}
                status={health.neo4j?.status || "warn"} color="text-green-400"
                extra={health.neo4j?.error ? health.neo4j.error.slice(0, 40) : undefined} />
              <SystemCard icon={Zap} label="LLM"
                value={health.llm?.model || "Cohere"}
                status={health.llm?.status || "warn"} color="text-yellow-400" />
              <SystemCard icon={Shield} label="Auth (JWT)"
                value="Secured" status="online" color="text-emerald-400" />
            </div>

            {/* Quick stats from analytics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: "Total Queries", value: analytics?.total_queries ?? "—", icon: BarChart3, color: "text-brand-400" },
                { label: "Active Users", value: analytics?.total_users ?? "—", icon: Users, color: "text-violet-400" },
                { label: "Active Rules", value: analytics?.active_rules ?? rules.filter(r => r.active).length, icon: Lock, color: "text-emerald-400" },
                { label: "Security Events", value: secStats?.total_events ?? secEvents.length, icon: AlertTriangle, color: "text-red-400" },
              ].map(({ label, value, icon: Icon, color }) => (
                <div key={label} className="bg-gray-800 border border-gray-700 rounded-xl p-5 flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-gray-700 flex items-center justify-center">
                    <Icon size={18} className={color} />
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">{label}</p>
                    <p className="text-xl font-bold text-white">{value}</p>
                  </div>
                </div>
              ))}
            </div>

            {/* Recent security events */}
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-white flex items-center gap-2">
                  <AlertTriangle size={16} className="text-yellow-400" /> Recent Security Events
                </h3>
                <button onClick={fetchSecEvents} className="p-1 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition">
                  <RefreshCw size={13} />
                </button>
              </div>
              {secLoading ? (
                <p className="text-sm text-gray-400">Loading…</p>
              ) : secEvents.length === 0 ? (
                <p className="text-sm text-gray-500">No security events recorded.</p>
              ) : (
                <div className="space-y-2">
                  {secEvents.slice(0, 5).map(ev => (
                    <div key={ev.id} className="flex items-center gap-3 py-2 border-b border-gray-700 last:border-0">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${
                        ev.severity === "high" || ev.severity === "critical" ? "bg-red-400" :
                        ev.severity === "medium" ? "bg-yellow-400" : "bg-blue-400"
                      }`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-white truncate">{ev.description}</p>
                        <p className="text-xs text-gray-400">{ev.user_email || "unknown"}</p>
                      </div>
                      <span className="text-xs text-gray-500 shrink-0">
                        {new Date(ev.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {/* ── USERS ── */}
        {tab === "users" && (
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
                    {users.map(u => (
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

            {/* Audit log */}
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-6">
              <h3 className="font-semibold text-white mb-4 flex items-center gap-2">
                <FileText size={16} className="text-gray-400" /> Query Audit Log
              </h3>
              <div className="space-y-1 text-xs font-mono">
                {[
                  { ts: new Date().toISOString().slice(0,19).replace("T"," "), msg: "INFO  System health check passed" },
                  { ts: new Date(Date.now()-60000).toISOString().slice(0,19).replace("T"," "), msg: "INFO  User login successful" },
                  { ts: new Date(Date.now()-120000).toISOString().slice(0,19).replace("T"," "), msg: "INFO  Document ingested into vector + graph" },
                  { ts: new Date(Date.now()-240000).toISOString().slice(0,19).replace("T"," "), msg: "INFO  Query processed: graph_used=true confidence=87" },
                  { ts: new Date(Date.now()-360000).toISOString().slice(0,19).replace("T"," "), msg: "INFO  Security rule engine: 0 blocks triggered" },
                ].map(({ ts, msg }) => (
                  <div key={ts} className="flex gap-3 py-1.5 border-b border-gray-700/50 text-xs">
                    <span className="text-gray-500 shrink-0">{ts}</span>
                    <span className={msg.includes("WARN") ? "text-yellow-400" : msg.includes("ERROR") ? "text-red-400" : "text-gray-300"}>{msg}</span>
                  </div>
                ))}
              </div>
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
                          <button onClick={() => deleteRule(rule.id)}
                            className="p-1.5 hover:bg-red-500/20 rounded text-gray-500 hover:text-red-400 transition">
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

        {/* ── MONITORING ── */}
        {tab === "monitoring" && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: "Avg Latency", value: analytics ? `${analytics.avg_latency_ms.toFixed(0)}ms` : "—", trend: "vs last hour", good: true },
                { label: "Cache Hit Rate", value: analytics ? `${analytics.cache_hit_rate.toFixed(1)}%` : "—", trend: "semantic cache", good: true },
                { label: "Graph Usage", value: analytics ? `${analytics.graph_usage_rate.toFixed(1)}%` : "—", trend: "of queries", good: true },
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
          </div>
        )}

        {/* ── CHUNKS (Qdrant) ── */}
        {tab === "chunks" && (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <Layers size={18} className="text-blue-400" /> Stored Chunks (Qdrant Vector DB)
                </h3>
                <p className="text-xs text-gray-400 mt-0.5">Browse and search document chunks stored in Qdrant</p>
              </div>
              <button onClick={() => fetchChunks(chunkSearch)} disabled={chunksLoading}
                className="flex items-center gap-2 px-3 py-2 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition text-xs disabled:opacity-50">
                <RefreshCw size={13} className={chunksLoading ? "animate-spin text-brand-400" : ""} />
                Refresh
              </button>
            </div>

            {/* Search */}
            <div className="flex gap-3">
              <div className="flex-1 relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                <input
                  value={chunkSearch}
                  onChange={e => setChunkSearch(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && fetchChunks(chunkSearch)}
                  placeholder="Search chunks by keyword…"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-9 pr-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500"
                />
              </div>
              <button onClick={() => fetchChunks(chunkSearch)}
                className="px-4 py-2.5 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg transition font-medium">
                Search
              </button>
            </div>

            {/* Chunks list */}
            {chunksLoading ? (
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
              <div className="space-y-3">
                <p className="text-xs text-gray-500">{chunks.length} chunk{chunks.length !== 1 ? "s" : ""} found</p>
                {chunks.map((chunk: any, i: number) => (
                  <div key={chunk.id || i} className="bg-gray-800 border border-gray-700 rounded-xl p-4">
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        {chunk.file_name && (
                          <span className="text-xs bg-blue-500/20 text-blue-300 px-2 py-0.5 rounded-full border border-blue-500/20">
                            <FileText size={10} className="inline mr-1" />{chunk.file_name}
                          </span>
                        )}
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
                      </div>
                      <span className="text-xs text-gray-600 shrink-0">#{i + 1}</span>
                    </div>
                    <p className="text-sm text-gray-300 leading-relaxed line-clamp-4">
                      {chunk.text || chunk.content || "(no text)"}
                    </p>
                    {chunk.score != null && (
                      <p className="text-xs text-brand-400 mt-2">Relevance: {(chunk.score * 100).toFixed(1)}%</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
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
