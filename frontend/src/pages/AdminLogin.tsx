import { useState } from "react";
import { Loader2, AlertCircle, Eye, EyeOff, Shield } from "lucide-react";
import axios from "axios";
import { NavigateFn } from "../App";

const ORG_DOMAIN = "nitcoinc.com";

export default function AdminLogin({
  navigate,
  defaultEmail,
}: {
  navigate: NavigateFn;
  defaultEmail: string;
}) {
  const [formData, setFormData] = useState({ email: defaultEmail || "", password: "" });
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const domainOk =
    !formData.email ||
    formData.email.toLowerCase().endsWith(`@${ORG_DOMAIN}`);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!domainOk) {
      setError(`Admin login requires an organisation email (@${ORG_DOMAIN}).`);
      return;
    }
    setLoading(true);
    try {
      const res = await axios.post("/auth/login/admin", formData);
      if (res.data.status === "success") {
        localStorage.setItem("accessToken", res.data.access_token);
        localStorage.setItem("refreshToken", res.data.refresh_token);
        localStorage.setItem("user", JSON.stringify(res.data.user));
        navigate("dashboard");
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || "Invalid credentials or access denied.");
    } finally {
      setLoading(false);
    }
  }

  const change = (field: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setFormData((p) => ({ ...p, [field]: e.target.value }));

  return (
    <div className="min-h-screen bg-gray-950 flex">
      {/* Left branding panel */}
      <div className="hidden lg:flex w-1/2 bg-gray-900 border-r border-gray-800 flex-col items-center justify-center p-12 relative overflow-hidden">
        <div
          className="absolute top-8 left-8 flex items-center gap-2 text-white font-bold text-xl cursor-pointer"
          onClick={() => navigate("landing")}
        >
          <span>🧠</span> CortexFlow
        </div>
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute top-1/3 left-1/4 w-72 h-72 bg-red-600/15 rounded-full blur-3xl" />
          <div className="absolute bottom-1/3 right-1/4 w-60 h-60 bg-orange-600/10 rounded-full blur-3xl" />
        </div>
        <div className="relative text-center">
          <div className="w-16 h-16 rounded-2xl bg-red-600/20 border border-red-500/30 flex items-center justify-center mx-auto mb-6">
            <Shield size={32} className="text-red-400" />
          </div>
          <h2 className="text-3xl font-bold text-white mb-3">Admin Portal</h2>
          <p className="text-gray-400 text-base max-w-xs leading-relaxed">
            Restricted to organisation staff. Use your <span className="text-red-400 font-medium">@{ORG_DOMAIN}</span> email to continue.
          </p>
          <div className="mt-8 bg-red-500/10 border border-red-500/20 rounded-xl px-5 py-4 text-left max-w-xs mx-auto">
            <p className="text-xs text-red-400 font-semibold uppercase tracking-widest mb-2">Access Level</p>
            <ul className="text-sm text-gray-400 space-y-1">
              <li>• Full document management</li>
              <li>• User administration</li>
              <li>• Knowledge base control</li>
              <li>• System analytics</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <div
            className="lg:hidden flex items-center gap-2 text-white font-bold text-xl mb-10 cursor-pointer"
            onClick={() => navigate("landing")}
          >
            <span>🧠</span> CortexFlow
          </div>

          {/* Role badge */}
          <div className="inline-flex items-center gap-2 text-xs font-medium px-3 py-1.5 rounded-full mb-5 bg-red-500/10 border border-red-500/20 text-red-400">
            <Shield size={12} /> Admin Portal
          </div>

          <h1 className="text-2xl font-bold text-white mb-1">Admin Sign In</h1>
          <p className="text-gray-400 text-sm mb-8">
            Not an admin?{" "}
            <button
              onClick={() => navigate("login")}
              className="text-brand-400 hover:text-brand-300"
            >
              User login
            </button>
          </p>

          {error && (
            <div className="flex gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-400 mb-4">
              <AlertCircle size={16} className="shrink-0 mt-0.5" /> {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">
                Organisation email
              </label>
              <input
                type="email"
                placeholder={`you@${ORG_DOMAIN}`}
                value={formData.email}
                onChange={change("email")}
                className={`w-full bg-gray-900 border rounded-xl px-4 py-2.5 text-white placeholder-gray-600 text-sm focus:outline-none transition
                  ${
                    formData.email && !domainOk
                      ? "border-red-500/60 focus:border-red-500 focus:ring-1 focus:ring-red-500/40"
                      : "border-gray-700 focus:border-red-500 focus:ring-1 focus:ring-red-500/40"
                  }`}
                required
              />
              {formData.email && !domainOk && (
                <p className="mt-1 text-xs text-red-400">
                  Must be an @{ORG_DOMAIN} address
                </p>
              )}
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">
                Password
              </label>
              <div className="relative">
                <input
                  type={showPwd ? "text" : "password"}
                  placeholder="Your password"
                  value={formData.password}
                  onChange={change("password")}
                  className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 pr-10 text-white placeholder-gray-600 text-sm focus:outline-none focus:border-red-500 focus:ring-1 focus:ring-red-500/40 transition"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPwd(!showPwd)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                >
                  {showPwd ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading || !domainOk}
              className="w-full bg-red-600 hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-xl transition flex items-center justify-center gap-2 text-sm"
            >
              {loading ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <>
                  <Shield size={15} /> Admin Sign In
                </>
              )}
            </button>
          </form>

          <div className="mt-8 pt-6 border-t border-gray-800 text-center text-xs text-gray-500">
            Organisation-restricted · JWT + bcrypt · Zero-trust RBAC
          </div>
        </div>
      </div>
    </div>
  );
}
