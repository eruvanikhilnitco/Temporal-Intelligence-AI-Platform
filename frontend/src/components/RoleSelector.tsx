import { ChevronDown, Globe, User, ShieldCheck } from "lucide-react";

type Role = "public" | "user" | "admin";

interface RoleSelectorProps {
  role: Role;
  onChange: (r: Role) => void;
}

import type { LucideIcon } from "lucide-react";
const ROLES: { value: Role; label: string; icon: LucideIcon }[] = [
  { value: "public", label: "Public", icon: Globe },
  { value: "user",   label: "User",   icon: User },
  { value: "admin",  label: "Admin",  icon: ShieldCheck },
];

export default function RoleSelector({ role, onChange }: RoleSelectorProps) {
  const current = ROLES.find((r) => r.value === role)!;
  const Icon = current.icon;

  return (
    <div className="relative inline-block">
      <label className="text-xs text-gray-400 block mb-1">Access Role</label>
      <div className="relative">
        <select
          value={role}
          onChange={(e) => onChange(e.target.value as Role)}
          className="
            appearance-none bg-gray-800 border border-gray-700 text-white
            rounded-lg pl-8 pr-8 py-2 text-sm cursor-pointer
            focus:outline-none focus:ring-2 focus:ring-brand-500
          "
        >
          {ROLES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
        <Icon size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <ChevronDown size={14} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
      </div>
    </div>
  );
}
