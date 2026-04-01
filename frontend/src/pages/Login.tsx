import { useState } from "react";
import { Loader2, AlertCircle, Eye, EyeOff } from "lucide-react";
import axios from "axios";
import { NavigateFn } from "../App";

export default function Login({ navigate, defaultEmail }: { navigate: NavigateFn; defaultEmail: string }) {
  const [formData, setFormData] = useState({ email: defaultEmail || "", password: "" });
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await axios.post("/auth/login", formData);
      if (res.data.status === "success") {
        localStorage.setItem("accessToken", res.data.access_token);
        localStorage.setItem("refreshToken", res.data.refresh_token);
        localStorage.setItem("user", JSON.stringify(res.data.user));
        navigate("dashboard");
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || "Invalid email or password.");
    } finally {
      setLoading(false);
    }
  }

  const change = (field: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setFormData(p => ({ ...p, [field]: e.target.value }));

  return (
    <div className="min-h-screen bg-gray-950 flex">
      {/* Left branding panel */}
      <div className="hidden lg:flex w-1/2 bg-gray-900 border-r border-gray-800 flex-col items-center justify-center p-12 relative overflow-hidden">
        <div className="absolute top-8 left-8 flex items-center gap-2 text-white font-bold text-xl cursor-pointer" onClick={() => navigate("landing")}>
          <span>🧠</span> CortexFlow
        </div>
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute top-1/3 left-1/4 w-72 h-72 bg-brand-600/15 rounded-full blur-3xl" />
          <div className="absolute bottom-1/3 right-1/4 w-60 h-60 bg-purple-600/10 rounded-full blur-3xl" />
        </div>
        <div className="relative text-center">
          <div className="text-6xl mb-6">🧠</div>
          <h2 className="text-3xl font-bold text-white mb-3">Welcome back</h2>
          <p className="text-gray-400 text-base max-w-xs leading-relaxed">
            Your intelligent knowledge platform is ready to answer your next question.
          </p>
          <div className="mt-8 grid grid-cols-3 gap-4 text-center">
            {[{ val: "20+", label: "Doc types" }, { val: "3", label: "AI phases" }, { val: "99%", label: "Uptime" }].map(({ val, label }) => (
              <div key={label} className="bg-gray-800/80 border border-gray-700 rounded-xl py-3 px-2">
                <p className="text-xl font-bold text-brand-300">{val}</p>
                <p className="text-xs text-gray-400 mt-0.5">{label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <div className="lg:hidden flex items-center gap-2 text-white font-bold text-xl mb-10 cursor-pointer" onClick={() => navigate("landing")}>
            <span>🧠</span> CortexFlow
          </div>

          <h1 className="text-2xl font-bold text-white mb-1">Sign in to your account</h1>
          <p className="text-gray-400 text-sm mb-8">
            Don't have one?{" "}
            <button onClick={() => navigate("signup")} className="text-brand-400 hover:text-brand-300">Create account</button>
          </p>

          {error && (
            <div className="flex gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-400 mb-4">
              <AlertCircle size={16} className="shrink-0 mt-0.5" /> {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">Email address</label>
              <input type="email" placeholder="you@company.com" value={formData.email} onChange={change("email")}
                className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-white placeholder-gray-600 text-sm focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/40 transition"
                required />
            </div>
            <div>
              <div className="flex justify-between mb-1.5">
                <label className="text-xs font-medium text-gray-400">Password</label>
                <button type="button" onClick={() => navigate("forgot-password")} className="text-xs text-brand-400 hover:text-brand-300">
                  Forgot password?
                </button>
              </div>
              <div className="relative">
                <input type={showPwd ? "text" : "password"} placeholder="Your password" value={formData.password} onChange={change("password")}
                  className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 pr-10 text-white placeholder-gray-600 text-sm focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/40 transition"
                  required />
                <button type="button" onClick={() => setShowPwd(!showPwd)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300">
                  {showPwd ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </div>
            <button type="submit" disabled={loading}
              className="w-full bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white font-semibold py-2.5 rounded-xl transition flex items-center justify-center gap-2 text-sm">
              {loading ? <Loader2 size={16} className="animate-spin" /> : "Sign In"}
            </button>
          </form>

          <div className="mt-8 pt-6 border-t border-gray-800 text-center text-xs text-gray-500">
            Protected by JWT + bcrypt · Zero-trust RBAC
          </div>
        </div>
      </div>
    </div>
  );
}
