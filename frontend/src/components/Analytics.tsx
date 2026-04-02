import { useState, useEffect } from "react";
import { TrendingUp, Zap, Brain, Database, GitBranch, BarChart3, RefreshCw, Users, AlertCircle } from "lucide-react";
import axios from "axios";

function MiniLineChart({ data, color }: { data: number[]; color: string }) {
  const max = Math.max(...data, 1);
  const min = Math.min(...data);
  const h = 60; const w = 300;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / (max - min || 1)) * h;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-14" preserveAspectRatio="none">
      <defs>
        <linearGradient id={`g-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,${h} ${pts} ${w},${h}`} fill={`url(#g-${color.replace("#", "")})`} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function BarChart({ data, color }: { data: number[]; color: string }) {
  const max = Math.max(...data, 1);
  return (
    <div className="flex items-end gap-0.5 h-20">
      {data.map((v, i) => (
        <div key={i} className="flex-1 rounded-t transition-all hover:opacity-80"
          style={{ height: `${(v / max) * 100}%`, background: color, minHeight: "2px" }} />
      ))}
    </div>
  );
}

const PHASES = [
  { icon: Database, label: "Phase 1: RAG", desc: "Vector retrieval", latency: "80ms", color: "text-blue-400" },
  { icon: Brain, label: "Phase 2: Intelligence", desc: "Classifier + Reranker + Cache", latency: "120ms", color: "text-violet-400" },
  { icon: GitBranch, label: "Phase 3: Graph RAG", desc: "Hybrid + Knowledge Graph", latency: "160ms", color: "text-emerald-400" },
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
      });
      setData(res.data);
    } catch (e: any) {
      setFetchError(e?.response?.data?.detail || "Failed to load analytics. Backend may be unavailable.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  const daily = data?.daily_queries ?? [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
  const hourly = data?.hourly_queries ?? new Array(24).fill(0);
  const cacheData = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, data?.cache_hit_rate ?? 0];

  const kpi = [
    { label: "Total Queries", value: data ? data.total_queries.toLocaleString() : "0", icon: BarChart3 },
    { label: "Avg Latency", value: data ? `${data.avg_latency_ms.toFixed(0)}ms` : "—", icon: Zap },
    { label: "Cache Hit Rate", value: data ? `${data.cache_hit_rate.toFixed(1)}%` : "—", icon: Database },
    { label: "Graph Usage", value: data ? `${data.graph_usage_rate.toFixed(1)}%` : "—", icon: GitBranch },
    { label: "Avg Confidence", value: data ? `${data.avg_confidence.toFixed(1)}%` : "—", icon: TrendingUp },
    { label: "Total Users", value: data ? data.total_users.toString() : "0", icon: Users },
  ];

  const retrieval = data?.retrieval_quality ?? [
    { type: "Fact lookup", score: 0, queries: 0 },
    { type: "Summary", score: 0, queries: 0 },
    { type: "Multi-hop", score: 0, queries: 0 },
    { type: "Analytical", score: 0, queries: 0 },
    { type: "Comparison", score: 0, queries: 0 },
  ];

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">Analytics Dashboard</h2>
          <p className="text-sm text-gray-400 mt-1">System performance, retrieval quality, and user engagement</p>
        </div>
        <button onClick={fetchAnalytics} disabled={loading}
          className="flex items-center gap-2 px-3 py-2 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition text-xs disabled:opacity-50">
          <RefreshCw size={14} className={loading ? "animate-spin text-brand-400" : ""} />
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center h-40 gap-3 text-gray-400">
          <RefreshCw size={20} className="animate-spin text-brand-400" />
          <span className="text-sm">Loading analytics data…</span>
        </div>
      )}

      {/* Error */}
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

      {/* Content */}
      {!loading && !fetchError && (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            {kpi.map(({ label, value, icon: Icon }) => (
              <div key={label} className="bg-gray-800 border border-gray-700 rounded-xl p-4">
                <Icon size={16} className="text-brand-400 mb-2" />
                <p className="text-xs text-gray-400 mb-1 leading-tight">{label}</p>
                <p className="text-xl font-bold text-white">{value}</p>
              </div>
            ))}
          </div>

          {/* Line charts */}
          <div className="grid md:grid-cols-2 gap-5">
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-white mb-1">Queries per Day (Last 14 days)</h3>
              <p className="text-xs text-gray-500 mb-3">Daily query volume trend</p>
              <MiniLineChart data={daily} color="#6366f1" />
              <div className="flex justify-between mt-2 text-xs text-gray-600">
                <span>Day 1</span><span>Day 14</span>
              </div>
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-white mb-1">Cache Hit Rate (%)</h3>
              <p className="text-xs text-gray-500 mb-3">Semantic cache effectiveness over time</p>
              <MiniLineChart data={cacheData} color="#10b981" />
              <div className="flex justify-between mt-2 text-xs text-gray-600">
                <span>Day 1</span><span>Today</span>
              </div>
            </div>
          </div>

          {/* Hourly bar chart */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-white mb-1">Hourly Query Distribution</h3>
            <p className="text-xs text-gray-500 mb-4">Queries per hour across today</p>
            <BarChart data={hourly} color="#6366f1" />
            <div className="flex justify-between mt-2 text-xs text-gray-600">
              <span>00:00</span><span>12:00</span><span>23:59</span>
            </div>
          </div>

          {/* Retrieval quality */}
          <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-white mb-4">Retrieval Quality by Query Type</h3>
            <div className="space-y-3">
              {retrieval.map(({ type, score, queries }: any) => (
                <div key={type} className="flex items-center gap-3">
                  <span className="text-sm text-gray-300 w-28 shrink-0">{type}</span>
                  <div className="flex-1 bg-gray-700 rounded-full h-2">
                    <div className="h-2 rounded-full bg-gradient-to-r from-brand-600 to-violet-500 transition-all" style={{ width: `${score}%` }} />
                  </div>
                  <span className="text-xs text-brand-300 font-bold w-10 text-right">{score}%</span>
                  <span className="text-xs text-gray-500 w-14 text-right">{queries} q/day</span>
                </div>
              ))}
            </div>
          </div>

          {/* Phase performance */}
          <div className="grid md:grid-cols-3 gap-5">
            {PHASES.map(({ icon: Icon, label, desc, latency, color }) => (
              <div key={label} className="bg-gray-800 border border-gray-700 rounded-xl p-5">
                <Icon size={20} className={`${color} mb-3`} />
                <p className="text-xs text-gray-400 mb-0.5">{label}</p>
                <p className="text-sm font-bold text-white mb-3">{desc}</p>
                <div className="space-y-1 text-xs">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Status</span>
                    <span className="text-emerald-400">● Active</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Added latency</span>
                    <span className={color}>{latency}</span>
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
