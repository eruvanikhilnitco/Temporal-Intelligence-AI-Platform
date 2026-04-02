import { MessageSquare, Upload, Shield, BarChart3, Settings, Activity, Network } from "lucide-react";

type View = "chat" | "upload" | "admin" | "analytics" | "settings" | "graph";

interface SidebarProps {
  activeView: View;
  onViewChange: (v: View) => void;
  isOnline: boolean;
  user?: any;
  unreadAlerts?: number;
}

// Shown to all authenticated users
const USER_NAV = [
  { id: "chat" as View, label: "Chat", icon: MessageSquare },
];

// Shown only to admins
const ADMIN_NAV = [
  { id: "upload" as View, label: "Upload", icon: Upload },
  { id: "analytics" as View, label: "Analytics", icon: BarChart3 },
  { id: "settings" as View, label: "Settings", icon: Settings },
  { id: "admin" as View, label: "Admin Panel", icon: Shield },
  { id: "graph" as View, label: "Knowledge Graph", icon: Network },
];

export default function Sidebar({ activeView, onViewChange, isOnline, user, unreadAlerts = 0 }: SidebarProps) {
  const isAdmin = user?.role === "admin";

  return (
    <aside className="w-60 bg-gray-900 border-r border-gray-800 flex flex-col shrink-0">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <span className="text-2xl">🧠</span>
          <div>
            <p className="font-bold text-white leading-tight">CortexFlow</p>
            <p className="text-xs text-gray-400">Enterprise v3 · AI</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {/* Chat — available to everyone */}
        {USER_NAV.map(({ id, label, icon: Icon }) => {
          const active = activeView === id;
          return (
            <button
              key={id}
              onClick={() => onViewChange(id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                active ? "bg-brand-600 text-white" : "text-gray-400 hover:bg-gray-800 hover:text-white"
              }`}
            >
              <Icon size={17} />
              {label}
            </button>
          );
        })}

        {/* Admin-only section */}
        {isAdmin && (
          <>
            <div className="h-px bg-gray-800 my-2" />
            <p className="text-xs text-gray-600 uppercase tracking-widest px-3 mb-1">Admin</p>
            {ADMIN_NAV.map(({ id, label, icon: Icon }) => {
              const active = activeView === id;
              const isAdminPanel = id === "admin";
              return (
                <button
                  key={id}
                  onClick={() => onViewChange(id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors relative ${
                    active
                      ? isAdminPanel ? "bg-red-600/80 text-white" : "bg-brand-600 text-white"
                      : "text-gray-400 hover:bg-gray-800 hover:text-white"
                  }`}
                >
                  <Icon size={17} />
                  <span className="flex-1 text-left">{label}</span>
                  {isAdminPanel && unreadAlerts > 0 && (
                    <span className="ml-auto bg-red-500 text-white text-xs font-bold px-1.5 py-0.5 rounded-full min-w-[20px] text-center">
                      {unreadAlerts > 9 ? "9+" : unreadAlerts}
                    </span>
                  )}
                </button>
              );
            })}
          </>
        )}
      </nav>

      {/* Status */}
      <div className="px-5 py-4 border-t border-gray-800 space-y-2">
        <div className="flex items-center gap-2 text-xs">
          <Activity size={13} className={isOnline ? "text-emerald-400" : "text-red-400"} />
          <span className={isOnline ? "text-emerald-400" : "text-red-400"}>
            {isOnline ? "API Online" : "API Offline"}
          </span>
        </div>
        <p className="text-xs text-gray-600 italic leading-relaxed">
          {isAdmin
            ? '"Intelligence is the ability to adapt to change." — S. Hawking'
            : '"Knowledge is power." — F. Bacon'}
        </p>
      </div>
    </aside>
  );
}
