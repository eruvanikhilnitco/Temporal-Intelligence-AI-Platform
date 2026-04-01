import { useState, useEffect } from "react";
import { LogOut, Bell } from "lucide-react";
import Sidebar from "../components/Sidebar";
import ChatInterface from "../components/ChatInterface";
import DocumentUpload from "../components/DocumentUpload";
import AdminPanel from "../components/AdminPanel";
import AnalyticsDashboard from "../components/Analytics";
import SettingsPage from "../components/Settings";
import KnowledgeGraphUI from "../components/KnowledgeGraphUI";
import NotificationsPanel from "../components/NotificationsPanel";
import { NavigateFn } from "../App";
import axios from "axios";

type View = "chat" | "upload" | "admin" | "analytics" | "settings" | "graph";

const VIEW_LABELS: Record<View, string> = {
  chat: "Chat",
  upload: "Upload Documents",
  admin: "Admin Panel",
  analytics: "Analytics",
  settings: "Settings",
  graph: "Knowledge Graph",
};

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

  return (
    <div className="flex h-screen overflow-hidden bg-gray-950 relative">
      <Sidebar
        activeView={view}
        onViewChange={setView}
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
              {view === "chat" && "Hybrid RAG · Graph · Multi-hop · Agent Routing"}
              {view === "upload" && "Phase 1–3 ingestion pipeline"}
              {view === "admin" && "System administration & security"}
              {view === "analytics" && "Performance metrics & engagement"}
              {view === "settings" && "Configuration & API keys"}
              {view === "graph" && "Entity relationships from your documents"}
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

            {/* Notifications bell */}
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
                  isAdmin={user?.role === "admin"}
                />
              )}
            </div>

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
          {view === "chat"      && <ChatInterface />}
          {view === "upload"    && <DocumentUpload />}
          {view === "admin"     && <AdminPanel user={user} />}
          {view === "analytics" && <AnalyticsDashboard />}
          {view === "settings"  && <SettingsPage />}
          {view === "graph"     && <KnowledgeGraphUI />}
        </div>
      </main>
    </div>
  );
}
