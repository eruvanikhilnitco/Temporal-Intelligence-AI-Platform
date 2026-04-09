import { useState, useEffect } from "react";
import { Brain, Database, GitBranch, BarChart3, RefreshCw, Users, AlertCircle, Activity } from "lucide-react";
import axios from "axios";

// ── Area line chart ───────────────────────────────────────────────────────────
function AreaChart({ data, color }: { data: number[]; color: string }) {
  const max = Math.max(...data, 1);
  const min = Math.min(...data);
  const h = 64; const w = 400;
  const pts = data.map((v, i) => {
    const x = (i / Math.max(data.length - 1, 1)) * w;
    const y = h - ((v - min) / (max - min || 1)) * (h - 8) - 4;
    return `${x},${y}`;
  }).join(" ");
  const gradId = `ag${color.replace(/[^a-z0-9]/gi, "")}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-16" preserveAspectRatio="none">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,${h} ${pts} ${w},${h}`} fill={`url(#${gradId})`} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ── Sparkline mini bars ──────────────────────────────────────────────────────
function SparkBars({ data, color }: { data: number[]; color: string }) {
  const max = Math.max(...data, 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: "1px", height: "36px", width: "100%" }}>
      {data.map((v, i) => (
        <div
          key={i}
          style={{
            flex: 1,
            height: `${Math.max(8, (v / max) * 100)}%`,
            background: color,
            opacity: 0.5 + (i / data.length) * 0.5,
            borderRadius: "2px",
          }}
        />
      ))}
    </div>
  );
}

const PHASES = [
  { icon: Database,  label: "Phase 1",  name: "Vector RAG",            latency: "~80ms",  color: "#6366f1", tc: "text-indigo-400" },
  { icon: Brain,     label: "Phase 2",  name: "Classifier + Reranker", latency: "~120ms", color: "#8b5cf6", tc: "text-violet-400" },
  { icon: GitBranch, label: "Phase 3",  name: "Graph RAG + Cache",     latency: "~160ms", color: "#10b981", tc: "text-emerald-400" },
];

export default function AnalyticsDashboard() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState("");

  useEffect(() => { fetchAnalytics(); }, []);

  async function fetchAnalytics() {
    setLoading(true);
    setFetchError("");
    try {
      const token = localStorage.getItem("accessToken");
      if (!token) { setFetchError("Not authenticated."); setLoading(false); return; }
      const res = await axios.get("/admin/analytics", {
        headers: { Authorization: `Bearer ${token}` },
        timeout: 15000,
      });
      setData(res.data);
    } catch (e: any) {
      if (axios.isCancel(e) || e?.code === "ECONNABORTED") {
        setFetchError("Request timed out. The server may be restarting — click Refresh to retry.");
      } else {
        setFetchError(e?.response?.data?.detail || "Failed to load analytics. Click Refresh to retry.");
      }
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  const daily     = data?.daily_queries  ?? new Array(14).fill(0);
  const hourly    = data?.hourly_queries ?? new Array(24).fill(0);
  const graphRate  = Number(data?.graph_usage_rate ?? 0);
  const confidence = Number(data?.avg_confidence   ?? 0);

  const hourlyMax = Math.max(...hourly, 1);

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Activity size={20} className="text-brand-400" />
            Analytics Dashboard
          </h2>
          <p className="text-sm text-gray-400 mt-1">Live system performance, retrieval quality and usage</p>
        </div>
        <button onClick={fetchAnalytics} disabled={loading}
          className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs text-gray-400 hover:text-white transition disabled:opacity-50">
          <RefreshCw size={13} className={loading ? "animate-spin text-brand-400" : ""} />
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {loading && (
        <div className="flex items-center justify-center h-48 gap-3 text-gray-400">
          <RefreshCw size={22} className="animate-spin text-brand-400" />
          <span className="text-sm">Loading analytics…</span>
        </div>
      )}

      {!loading && fetchError && (
        <div className="flex gap-3 p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
          <AlertCircle size={16} className="shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Analytics unavailable</p>
            <p className="text-xs text-red-300 mt-0.5">{fetchError}</p>
            <button onClick={fetchAnalytics} className="mt-2 text-xs text-brand-400 hover:text-brand-300 underline">Retry</button>
          </div>
        </div>
      )}

      {!loading && !fetchError && (
        <>
          {/* ── Row 1: 4 KPI cards ── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">

            {/* Total Queries with sparkline */}
            <div className="rounded-2xl border border-brand-500/20 p-5 bg-gradient-to-br from-brand-900/40 to-gray-800/80 col-span-2 lg:col-span-1">
              <div className="flex items-start justify-between mb-3">
                <div className="w-9 h-9 rounded-xl bg-gray-800 flex items-center justify-center">
                  <BarChart3 size={16} className="text-brand-400" />
                </div>
                <span className="text-xs text-brand-400 bg-gray-800 px-2 py-0.5 rounded-full">all time</span>
              </div>
              <p className="text-3xl font-bold text-white leading-none mb-1">
                {(data?.total_queries ?? 0).toLocaleString()}
              </p>
              <p className="text-xs text-gray-400 mb-3">Total Queries</p>
              <SparkBars data={daily} color="#6366f1" />
              <p className="text-xs text-gray-600 mt-1">Last 14 days</p>
            </div>

            {/* Users + graph/confidence mini bars */}
            <div className="rounded-2xl border border-violet-500/20 p-5 bg-gradient-to-br from-violet-900/20 to-gray-800/80">
              <div className="flex items-start justify-between mb-3">
                <div className="w-9 h-9 rounded-xl bg-gray-800 flex items-center justify-center">
                  <Users size={16} className="text-violet-400" />
                </div>
              </div>
              <p className="text-3xl font-bold text-white leading-none mb-1">{data?.total_users ?? 0}</p>
              <p className="text-xs text-gray-400 mb-4">Total Users</p>
              <div className="space-y-2.5">
                {[
                  { label: "Graph Usage", val: graphRate, color: "bg-violet-500" },
                  { label: "Avg Confidence", val: confidence, color: "bg-blue-500" },
                ].map(({ label, val, color }) => (
                  <div key={label}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-gray-500">{label}</span>
                      <span className="text-gray-300 font-medium">{val.toFixed(1)}%</span>
                    </div>
                    <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${color} transition-all duration-700`} style={{ width: `${val}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ── Row 2: Daily queries area chart ── */}
          <div className="bg-gray-800 border border-gray-700 rounded-2xl p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-semibold text-white">Queries per Day</h3>
                <p className="text-xs text-gray-500 mt-0.5">Volume trend — last 14 days</p>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-brand-400">
                <span className="w-2 h-2 rounded-full bg-brand-400 inline-block" />
                Daily volume
              </div>
            </div>
            <AreaChart data={daily} color="#6366f1" />
            <div className="flex justify-between mt-2 text-xs text-gray-600">
              <span>14 days ago</span><span>Today</span>
            </div>
          </div>

          {/* ── Row 3: Hourly distribution (simple bars) ── */}
          <div className="bg-gray-800 border border-gray-700 rounded-2xl p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-semibold text-white">Hourly Query Distribution</h3>
                <p className="text-xs text-gray-500 mt-0.5">Queries per hour — today</p>
              </div>
              <span className="text-xs text-gray-500">
                Peak: {hourly.indexOf(Math.max(...hourly))}:00
              </span>
            </div>
            {/* Simple flex bar chart — no nested flex, just direct divs */}
            <div className="relative" style={{ height: 96 }}>
              <div className="absolute inset-0 flex items-end gap-px">
                {hourly.map((v: number, i: number) => {
                  const isPeak = v === Math.max(...hourly) && v > 0;
                  const h = Math.max(3, Math.round((v / hourlyMax) * 100));
                  return (
                    <div
                      key={i}
                      className="group flex-1 relative"
                      style={{ height: "100%", display: "flex", alignItems: "flex-end" }}
                      title={`${String(i).padStart(2, "0")}:00 — ${v} queries`}
                    >
                      <div
                        className={`w-full rounded-sm transition-colors ${isPeak ? "bg-brand-400" : "bg-brand-600/50 group-hover:bg-brand-500/70"}`}
                        style={{ height: `${h}%` }}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="flex justify-between mt-2 text-xs text-gray-600">
              <span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>23h</span>
            </div>
          </div>

          {/* ── Row 5: RAG pipeline ── */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {PHASES.map(({ icon: Icon, label, name, latency, color, tc }) => (
              <div key={label} className="bg-gray-800 border border-gray-700 rounded-2xl p-5">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: color + "22" }}>
                    <Icon size={16} style={{ color }} />
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">{label}</p>
                    <p className="text-sm font-bold text-white">{name}</p>
                  </div>
                </div>
                <div className="space-y-1.5 text-xs border-t border-gray-700 pt-3">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Status</span>
                    <span className="text-emerald-400 font-medium">● Active</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Added latency</span>
                    <span className={`${tc} font-medium`}>{latency}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>

        </>
      )}
    </div>
  );
}
