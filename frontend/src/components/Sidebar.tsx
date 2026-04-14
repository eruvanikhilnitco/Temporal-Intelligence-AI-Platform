import { useState } from "react";
import { MessageSquare, Upload, Shield, BarChart3, Settings, Activity, Network, Link2, ChevronLeft, ChevronRight } from "lucide-react";

type View = "chat" | "upload" | "admin" | "analytics" | "settings" | "graph" | "sharepoint";

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
  { id: "sharepoint" as View, label: "SharePoint", icon: Link2 },
  { id: "analytics" as View, label: "Analytics", icon: BarChart3 },
  { id: "settings" as View, label: "Settings", icon: Settings },
  { id: "admin" as View, label: "Admin Panel", icon: Shield },
  { id: "graph" as View, label: "Knowledge Graph", icon: Network },
];

export default function Sidebar({ activeView, onViewChange, isOnline, user, unreadAlerts = 0 }: SidebarProps) {
  const isAdmin = user?.role === "admin";
  const [collapsed, setCollapsed] = useState(false);

  const NavBtn = ({ id, label, icon: Icon }: { id: View; label: string; icon: React.ComponentType<any> }) => {
    const active = activeView === id;
    const isAdminPanel = id === "admin";
    return (
      <button
        key={id}
        onClick={() => onViewChange(id)}
        title={collapsed ? label : undefined}
        className={`w-full flex items-center rounded-lg text-sm font-medium transition-colors relative
          ${collapsed ? "justify-center px-2 py-2.5" : "gap-3 px-3 py-2.5"}
          ${active
            ? isAdminPanel ? "bg-red-600/80 text-white" : "bg-brand-600 text-white"
            : "text-gray-400 hover:bg-gray-800 hover:text-white"
          }`}
      >
        <Icon size={17} className="shrink-0" />
        {!collapsed && <span className="flex-1 text-left">{label}</span>}
        {!collapsed && isAdminPanel && unreadAlerts > 0 && (
          <span className="ml-auto bg-red-500 text-white text-xs font-bold px-1.5 py-0.5 rounded-full min-w-[20px] text-center">
            {unreadAlerts > 9 ? "9+" : unreadAlerts}
          </span>
        )}
        {collapsed && isAdminPanel && unreadAlerts > 0 && (
          <span className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 rounded-full" />
        )}
      </button>
    );
  };

  return (
    <aside className={`${collapsed ? "w-16" : "w-60"} bg-gray-900 border-r border-gray-800 flex flex-col shrink-0 transition-all duration-200`}>
      {/* Logo + collapse toggle */}
      <div className={`border-b border-gray-800 flex items-center ${collapsed ? "justify-center py-4 px-2" : "px-5 py-5 justify-between"}`}>
        {!collapsed && (
          <div className="flex items-center gap-2">
            <span className="text-2xl">🧠</span>
            <div>
              <p className="font-bold text-white leading-tight">CortexFlow</p>
              <p className="text-xs text-gray-400">Enterprise AI</p>
            </div>
          </div>
        )}
        {collapsed && <span className="text-xl">🧠</span>}
        <button
          onClick={() => setCollapsed(v => !v)}
          className={`p-1 rounded hover:bg-gray-800 text-gray-500 hover:text-gray-300 transition ${collapsed ? "mt-0" : ""}`}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-4 space-y-1">
        {/* Chat — available to everyone */}
        {USER_NAV.map(item => <NavBtn key={item.id} {...item} />)}

        {/* Admin-only section */}
        {isAdmin && (
          <>
            <div className="h-px bg-gray-800 my-2" />
            {!collapsed && <p className="text-xs text-gray-600 uppercase tracking-widest px-3 mb-1">Admin</p>}
            {ADMIN_NAV.map(item => <NavBtn key={item.id} {...item} />)}
          </>
        )}
      </nav>

      {/* Status */}
      <div className={`border-t border-gray-800 ${collapsed ? "px-2 py-4 flex justify-center" : "px-5 py-4 space-y-2"}`}>
        <div className="flex items-center gap-2 text-xs" title={isOnline ? "API Online" : "API Offline"}>
          <Activity size={13} className={isOnline ? "text-emerald-400" : "text-red-400"} />
          {!collapsed && (
            <span className={isOnline ? "text-emerald-400" : "text-red-400"}>
              {isOnline ? "API Online" : "API Offline"}
            </span>
          )}
        </div>
      </div>
    </aside>
  );
}
