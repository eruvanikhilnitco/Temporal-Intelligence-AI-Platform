import { useState, useEffect, Component, ReactNode } from "react";
import { LogOut, Bell, AlertTriangle, RefreshCw } from "lucide-react";
import Sidebar from "../components/Sidebar";
import ChatInterface from "../components/ChatInterface";
import DocumentUpload from "../components/DocumentUpload";
import AdminPanel from "../components/AdminPanel";
import AnalyticsDashboard from "../components/Analytics";
import SettingsPage from "../components/Settings";
import KnowledgeGraphUI from "../components/KnowledgeGraphUI";
import SharePoint from "../components/SharePoint";
import WebsiteScraper from "../components/WebsiteScraper";
import NotificationsPanel from "../components/NotificationsPanel";
import { NavigateFn } from "../App";
import axios from "axios";

// ── Error Boundary — prevents one broken view from blanking the entire app ──
class ErrorBoundary extends Component<
  { children: ReactNode; label: string },
  { error: string | null }
> {
  constructor(props: any) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(err: any) { return { error: err?.message || "Unknown error" }; }
  render() {
    if (this.state.error) {
      return (
        <div className="flex items-center justify-center h-full">
          <div className="text-center p-8 bg-gray-900 border border-red-800/40 rounded-2xl max-w-md">
            <AlertTriangle size={40} className="mx-auto text-red-400 mb-4" />
            <p className="text-white font-bold text-base mb-2">{this.props.label} encountered an error</p>
            <p className="text-gray-400 text-xs mb-4 font-mono break-all">{this.state.error}</p>
            <button onClick={() => this.setState({ error: null })}
              className="flex items-center gap-2 mx-auto px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg transition">
              <RefreshCw size={14} /> Retry
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

type View = "chat" | "upload" | "admin" | "analytics" | "settings" | "graph" | "sharepoint" | "website";

const VIEW_LABELS: Record<View, string> = {
  chat: "Chat",
  upload: "Upload Documents",
  admin: "Admin Panel",
  analytics: "Analytics",
  settings: "Settings",
  graph: "Knowledge Graph",
  sharepoint: "SharePoint",
  website: "Website Scraper",
};

// Views restricted to admin only
const ADMIN_ONLY_VIEWS: View[] = ["upload", "admin", "analytics", "settings", "graph", "sharepoint", "website"];

export default function Dashboard({ navigate }: { navigate: NavigateFn }) {
  const [view, setView] = useState<View>("chat");
  const [isOnline, setIsOnline] = useState(false);
  const [user, setUser] = useState<any>(null);
  const [showNotifications, setShowNotifications] = useState(false);
  const [unreadAlerts, setUnreadAlerts] = useState(0);

  useEffect(() => {
    const userData = localStorage.getItem("user");
    if (userData) setUser(JSON.parse(userData));

    fetch("/health")
      .then(r => r.ok && setIsOnline(true))
      .catch(() => setIsOnline(false));
  }, []);

  // Poll for unread security alerts (admin only)
  useEffect(() => {
    if (user?.role !== "admin") return;
    const poll = async () => {
      try {
        const token = localStorage.getItem("accessToken");
        const res = await axios.get("/admin/security/stats", {
          headers: { Authorization: `Bearer ${token}` },
        });
        setUnreadAlerts(res.data.unresolved || 0);
      } catch { /* ignore */ }
    };
    poll();
    const interval = setInterval(poll, 30000);
    return () => clearInterval(interval);
  }, [user]);

  function handleLogout() {
    localStorage.removeItem("accessToken");
    localStorage.removeItem("refreshToken");
    localStorage.removeItem("user");
    navigate("login");
  }

  // Enforce role-based view access — non-admins can only access chat
  function handleViewChange(requested: View) {
    const isAdmin = user?.role === "admin";
    if (!isAdmin && ADMIN_ONLY_VIEWS.includes(requested)) return;
    setView(requested);
  }

  const isAdmin = user?.role === "admin";

  return (
    <div className="flex h-screen overflow-hidden bg-gray-950 relative">
      <Sidebar
        activeView={view}
        onViewChange={handleViewChange}
        isOnline={isOnline}
        user={user}
        unreadAlerts={unreadAlerts}
      />

      <main className="flex-1 overflow-hidden flex flex-col">
        {/* Topbar */}
        <div className="border-b border-gray-800 bg-gray-900 px-6 py-4 flex justify-between items-center shrink-0">
          <div>
            <h1 className="text-base font-semibold text-white">{VIEW_LABELS[view]}</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              {view === "chat"      && (
                <span className="flex items-center gap-2">
                  <span className="inline-flex w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  {isAdmin ? "Neural retrieval · Knowledge graph · Live" : "Intelligent document assistant · Live"}
                </span>
              )}
              {view === "upload"      && "Phase 1–3 ingestion pipeline"}
              {view === "admin"       && "System administration & security"}
              {view === "analytics"   && "Performance metrics & engagement"}
              {view === "settings"    && "Configuration & API keys"}
              {view === "graph"       && "Entity relationships from your documents"}
              {view === "sharepoint"  && "Event-driven sync — stays connected until you disconnect"}
              {view === "website"     && "BFS deep-crawl with sitemap seeding and incremental updates"}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* User pill */}
            {user && (
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-full bg-brand-600 flex items-center justify-center text-xs font-bold text-white">
                  {user.name?.[0]?.toUpperCase() || "U"}
                </div>
                <span className="text-sm text-gray-400 hidden sm:block">{user.name}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  user.role === "admin"
                    ? "bg-red-500/20 text-red-400"
                    : "bg-brand-600/20 text-brand-300"
                }`}>
                  {user.role}
                </span>
              </div>
            )}

            {/* Notifications bell — admin only */}
            {isAdmin && (
              <div className="relative">
                <button
                  onClick={() => setShowNotifications(v => !v)}
                  className="relative p-2 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition"
                  title="Notifications"
                >
                  <Bell size={18} />
                  {unreadAlerts > 0 && (
                    <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full" />
                  )}
                </button>
                {showNotifications && (
                  <NotificationsPanel
                    onClose={() => setShowNotifications(false)}
                    isAdmin={true}
                  />
                )}
              </div>
            )}

            {/* Logout */}
            <button
              onClick={handleLogout}
              className="p-2 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition"
              title="Logout"
            >
              <LogOut size={18} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {/* Chat is always mounted — hidden via CSS so state (messages) persists when navigating away */}
          <div className={view === "chat" ? "h-full" : "hidden"}>
            <ErrorBoundary label="Chat"><ChatInterface userRole={user?.role} /></ErrorBoundary>
          </div>
          {view === "upload"      && isAdmin && <ErrorBoundary label="Upload"><DocumentUpload onNavigateToAdmin={() => setView("admin")} /></ErrorBoundary>}
          {view === "admin"       && isAdmin && <ErrorBoundary label="Admin Panel"><AdminPanel user={user} /></ErrorBoundary>}
          {view === "analytics"   && isAdmin && <ErrorBoundary label="Analytics"><AnalyticsDashboard /></ErrorBoundary>}
          {view === "settings"    && isAdmin && <ErrorBoundary label="Settings"><SettingsPage /></ErrorBoundary>}
          {view === "graph"       && isAdmin && <ErrorBoundary label="Knowledge Graph"><KnowledgeGraphUI /></ErrorBoundary>}
          {view === "sharepoint"  && isAdmin && <ErrorBoundary label="SharePoint"><SharePoint /></ErrorBoundary>}
          {view === "website"     && isAdmin && <ErrorBoundary label="Website Scraper"><WebsiteScraper /></ErrorBoundary>}
        </div>
      </main>
    </div>
  );
}
