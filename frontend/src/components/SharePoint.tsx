import { useState, useEffect } from "react";
import { Link2, Link2Off, Loader2, CheckCircle2, AlertCircle, RefreshCw } from "lucide-react";
import axios from "axios";

interface Connection {
  id: string;
  site_url: string;
  site_display_name: string;
  status: string;
  file_count: number;
  webhooks: number;
  last_sync_at: string | null;
  connected_at: string | null;
  last_error: string | null;
}

export default function SharePoint() {
  const [url, setUrl] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  const token = localStorage.getItem("accessToken");
  const headers = { Authorization: `Bearer ${token}` };

  // Load existing connections on mount
  useEffect(() => {
    fetchStatus();
  }, []);

  async function fetchStatus() {
    setLoadingStatus(true);
    try {
      const res = await axios.get("/sharepoint/status", { headers });
      setConnections(res.data.connections || []);
    } catch {
      // silently ignore — may be no connections yet
    } finally {
      setLoadingStatus(false);
    }
  }

  async function handleConnect() {
    const trimmed = url.trim();
    if (!trimmed) {
      setError("Please enter a SharePoint site URL.");
      return;
    }
    if (!trimmed.startsWith("https://")) {
      setError("URL must start with https://");
      return;
    }

    setError("");
    setSuccessMsg("");
    setConnecting(true);

    try {
      const res = await axios.post("/sharepoint/connect", { site_url: trimmed }, { headers });
      const data = res.data;

      if (data.status === "already_connected") {
        setSuccessMsg(`Already connected to ${data.site_display_name || trimmed}.`);
      } else {
        setSuccessMsg(data.message || `Connected to ${data.site_display_name || trimmed}.`);
        setUrl("");
      }
      await fetchStatus();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || "Connection failed.";
      setError(typeof detail === "string" ? detail : JSON.stringify(detail));
    } finally {
      setConnecting(false);
    }
  }

  async function handleDisconnect(connectionId: string) {
    setDisconnecting(connectionId);
    setError("");
    setSuccessMsg("");
    try {
      await axios.post("/sharepoint/disconnect", { connection_id: connectionId }, { headers });
      setSuccessMsg("SharePoint site disconnected.");
      await fetchStatus();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || "Disconnect failed.";
      setError(typeof detail === "string" ? detail : JSON.stringify(detail));
    } finally {
      setDisconnecting(null);
    }
  }

  const activeConnections = connections.filter(c => c.status === "connected");

  return (
    <div className="flex flex-col h-full bg-gray-950 p-8 overflow-y-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-1">
          <div className="w-9 h-9 rounded-xl bg-blue-600/20 border border-blue-500/30 flex items-center justify-center">
            <Link2 size={18} className="text-blue-400" />
          </div>
          <h1 className="text-xl font-bold text-white">SharePoint</h1>
        </div>
        <p className="text-sm text-gray-500 ml-12">
          Connect a SharePoint site — documents sync automatically and stay fresh.
        </p>
      </div>

      {/* Connect form */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-6 max-w-2xl">
        <p className="text-xs text-gray-500 uppercase tracking-widest mb-4 font-semibold">
          Connect a site
        </p>

        <div className="flex gap-3">
          <input
            type="url"
            value={url}
            onChange={e => { setUrl(e.target.value); setError(""); setSuccessMsg(""); }}
            onKeyDown={e => e.key === "Enter" && !connecting && handleConnect()}
            placeholder="https://yourcompany.sharepoint.com/sites/YourSite"
            className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500 transition"
            disabled={connecting}
          />
          <button
            onClick={handleConnect}
            disabled={connecting || !url.trim()}
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl transition"
          >
            {connecting ? (
              <><Loader2 size={15} className="animate-spin" /> Connecting…</>
            ) : (
              <><Link2 size={15} /> Connect</>
            )}
          </button>
        </div>

        {/* Feedback */}
        {error && (
          <div className="mt-3 flex items-start gap-2 text-red-400 text-sm bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
            <AlertCircle size={15} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {successMsg && (
          <div className="mt-3 flex items-start gap-2 text-emerald-400 text-sm bg-emerald-500/10 border border-emerald-500/20 rounded-xl px-4 py-3">
            <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}
      </div>

      {/* Active connections */}
      <div className="max-w-2xl">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs text-gray-500 uppercase tracking-widest font-semibold">
            Active connections
          </p>
          <button
            onClick={fetchStatus}
            disabled={loadingStatus}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition"
          >
            <RefreshCw size={12} className={loadingStatus ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>

        {loadingStatus ? (
          <div className="flex items-center gap-2 text-gray-600 text-sm py-6">
            <Loader2 size={15} className="animate-spin" /> Loading…
          </div>
        ) : activeConnections.length === 0 ? (
          <div className="text-gray-600 text-sm py-6 border border-dashed border-gray-800 rounded-2xl text-center">
            No active connections. Paste a SharePoint URL above to get started.
          </div>
        ) : (
          <div className="space-y-3">
            {activeConnections.map(conn => (
              <div
                key={conn.id}
                className="bg-gray-900 border border-gray-800 rounded-2xl px-5 py-4 flex items-start justify-between gap-4"
              >
                <div className="min-w-0">
                  {/* Site name + status dot */}
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
                    <p className="text-sm font-semibold text-white truncate">
                      {conn.site_display_name || conn.site_url}
                    </p>
                  </div>

                  {/* URL */}
                  <p className="text-xs text-gray-600 truncate mb-2">{conn.site_url}</p>

                  {/* Stats row */}
                  <div className="flex items-center gap-4 text-xs text-gray-500">
                    <span>{conn.file_count} file{conn.file_count !== 1 ? "s" : ""} indexed</span>
                    {conn.webhooks > 0 && (
                      <span className="text-emerald-600">
                        {conn.webhooks} webhook{conn.webhooks !== 1 ? "s" : ""}
                      </span>
                    )}
                    {conn.last_sync_at && (
                      <span>
                        Last sync {new Date(conn.last_sync_at).toLocaleTimeString([], {
                          hour: "2-digit", minute: "2-digit"
                        })}
                      </span>
                    )}
                  </div>

                  {/* Error banner if last sync errored */}
                  {conn.last_error && (
                    <p className="mt-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-1.5 truncate">
                      {conn.last_error}
                    </p>
                  )}
                </div>

                {/* Disconnect button */}
                <button
                  onClick={() => handleDisconnect(conn.id)}
                  disabled={disconnecting === conn.id}
                  className="shrink-0 flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-red-400 hover:text-red-300 border border-red-500/20 hover:border-red-500/40 bg-red-500/5 hover:bg-red-500/10 rounded-xl transition disabled:opacity-50"
                >
                  {disconnecting === conn.id ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <Link2Off size={13} />
                  )}
                  Disconnect
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
