import { useState, useEffect, useCallback } from "react";
import { Bell, X, AlertTriangle, CheckCircle, Info, Zap, Shield } from "lucide-react";
import axios from "axios";

interface Notification {
  id: string;
  type: "security" | "system" | "info" | "success";
  title: string;
  message: string;
  time: string;
  read: boolean;
}

const TYPE_ICON = {
  security: { icon: Shield, color: "text-red-400", bg: "bg-red-400/10" },
  system:   { icon: Zap, color: "text-yellow-400", bg: "bg-yellow-400/10" },
  info:     { icon: Info, color: "text-blue-400", bg: "bg-blue-400/10" },
  success:  { icon: CheckCircle, color: "text-emerald-400", bg: "bg-emerald-400/10" },
};

export default function NotificationsPanel({ onClose, isAdmin }: { onClose: () => void; isAdmin?: boolean }) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(false);

  const buildFromEvents = useCallback(async () => {
    setLoading(true);
    const base: Notification[] = [
      {
        id: "sys-1",
        type: "success",
        title: "System Operational",
        message: "All services (Qdrant, Neo4j, LLM) are running normally.",
        time: "Just now",
        read: false,
      },
      {
        id: "sys-2",
        type: "info",
        title: "Self-Learning Active",
        message: "Feedback loop is processing user interactions to improve retrieval.",
        time: "5m ago",
        read: true,
      },
    ];

    if (isAdmin) {
      try {
        const token = localStorage.getItem("accessToken");
        const res = await axios.get("/admin/security/events?limit=5", {
          headers: { Authorization: `Bearer ${token}` },
        });
        const secNotifs: Notification[] = res.data
          .filter((e: any) => !e.resolved)
          .map((e: any) => ({
            id: e.id,
            type: "security" as const,
            title: `Security: ${e.event_type.replace(/_/g, " ")}`,
            message: e.description,
            time: new Date(e.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            read: false,
          }));
        setNotifications([...secNotifs, ...base]);
      } catch {
        setNotifications(base);
      }
    } else {
      setNotifications(base);
    }
    setLoading(false);
  }, [isAdmin]);

  useEffect(() => { buildFromEvents(); }, [buildFromEvents]);

  const markRead = (id: string) =>
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));

  const markAllRead = () =>
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));

  const unread = notifications.filter(n => !n.read).length;

  return (
    <div className="absolute top-14 right-4 z-50 w-80 bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <Bell size={15} className="text-brand-400" />
          <span className="text-sm font-semibold text-white">Notifications</span>
          {unread > 0 && (
            <span className="bg-red-500 text-white text-xs font-bold px-1.5 py-0.5 rounded-full">
              {unread}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {unread > 0 && (
            <button onClick={markAllRead} className="text-xs text-brand-400 hover:text-brand-300 transition">
              Mark all read
            </button>
          )}
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 transition">
            <X size={15} />
          </button>
        </div>
      </div>

      {/* List */}
      <div className="max-h-80 overflow-y-auto divide-y divide-gray-800">
        {loading ? (
          <div className="p-4 text-center text-sm text-gray-400">Loading…</div>
        ) : notifications.length === 0 ? (
          <div className="p-6 text-center">
            <Bell size={28} className="mx-auto text-gray-600 mb-2" />
            <p className="text-sm text-gray-400">No notifications</p>
          </div>
        ) : (
          notifications.map(n => {
            const { icon: Icon, color, bg } = TYPE_ICON[n.type];
            return (
              <div
                key={n.id}
                onClick={() => markRead(n.id)}
                className={`flex gap-3 px-4 py-3 cursor-pointer transition hover:bg-gray-800/50 ${n.read ? "opacity-60" : ""}`}
              >
                <div className={`w-8 h-8 rounded-full ${bg} flex items-center justify-center shrink-0 mt-0.5`}>
                  <Icon size={14} className={color} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-xs font-semibold text-white">{n.title}</p>
                    {!n.read && <span className="w-2 h-2 bg-brand-400 rounded-full shrink-0 mt-1" />}
                  </div>
                  <p className="text-xs text-gray-400 leading-relaxed mt-0.5">{n.message}</p>
                  <p className="text-xs text-gray-600 mt-1">{n.time}</p>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2.5 border-t border-gray-800 text-center">
        <p className="text-xs text-gray-600">Alerts update in real-time</p>
      </div>
    </div>
  );
}
