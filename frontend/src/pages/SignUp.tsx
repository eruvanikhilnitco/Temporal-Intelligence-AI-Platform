import { useState } from "react";
import { Loader2, AlertCircle, Check, Eye, EyeOff } from "lucide-react";
import axios from "axios";
import { NavigateFn } from "../App";

function PasswordStrength({ password }: { password: string }) {
  const checks = [
    { label: "8+ characters", ok: password.length >= 8 },
    { label: "Uppercase letter", ok: /[A-Z]/.test(password) },
    { label: "Number", ok: /\d/.test(password) },
  ];
  if (!password) return null;
  return (
    <div className="mt-1 flex gap-3 flex-wrap">
      {checks.map(({ label, ok }) => (
        <span key={label} className={`flex items-center gap-1 text-xs ${ok ? "text-emerald-400" : "text-gray-500"}`}>
          <Check size={10} /> {label}
        </span>
      ))}
    </div>
  );
}

export default function SignUp({ navigate }: { navigate: NavigateFn }) {
  const [formData, setFormData] = useState({ email: "", password: "", name: "" });
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const payload = { ...formData, role: "client" };
      const res = await axios.post("/auth/signup", payload);
      if (res.data.status === "success") {
        setSuccess(true);
        setTimeout(() => navigate("login", { email: formData.email }), 1500);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || "Signup failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  const change = (field: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setFormData(p => ({ ...p, [field]: e.target.value }));

  return (
    <div className="min-h-screen bg-gray-950 flex">
      {/* Left panel */}
      <div className="hidden lg:flex w-1/2 bg-gray-900 border-r border-gray-800 flex-col justify-between p-12">
        <div className="flex items-center gap-2 text-white font-bold text-xl cursor-pointer" onClick={() => navigate("landing")}>
          <span>🧠</span> CortexFlow
        </div>
        <div>
          <blockquote className="text-2xl font-light text-gray-300 leading-relaxed mb-6">
            "CortexFlow transformed how our team extracts insights from thousands of contracts — what took days now takes seconds."
          </blockquote>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-brand-600 flex items-center justify-center font-bold text-white">A</div>
            <div>
              <p className="text-sm font-medium text-white">Aditya V.</p>
              <p className="text-xs text-gray-400">Lead Engineer, NITCO</p>
            </div>
          </div>
        </div>
        <div className="flex gap-6 text-xs text-gray-500">
          <span className="flex items-center gap-1"><Check size={11} className="text-emerald-400" /> SOC2-ready</span>
          <span className="flex items-center gap-1"><Check size={11} className="text-emerald-400" /> GDPR-compliant</span>
          <span className="flex items-center gap-1"><Check size={11} className="text-emerald-400" /> Zero-trust security</span>
        </div>
      </div>

      {/* Right panel */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <div className="lg:hidden flex items-center gap-2 text-white font-bold text-xl mb-10 cursor-pointer" onClick={() => navigate("landing")}>
            <span>🧠</span> CortexFlow
          </div>

          <h1 className="text-2xl font-bold text-white mb-1">Create your account</h1>
          <p className="text-gray-400 text-sm mb-8">Start with the free plan. No credit card required.</p>

          {success && (
            <div className="flex gap-2 p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-sm text-emerald-400 mb-4">
              <Check size={16} className="shrink-0 mt-0.5" /> Account created! Redirecting to login…
            </div>
          )}

          {error && (
            <div className="flex gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-400 mb-4">
              <AlertCircle size={16} className="shrink-0 mt-0.5" /> {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">Full name</label>
              <input type="text" placeholder="John Doe" value={formData.name} onChange={change("name")}
                className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-white placeholder-gray-600 text-sm focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/40 transition"
                required />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">Email address</label>
              <input type="email" placeholder="you@company.com" value={formData.email} onChange={change("email")}
                className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-white placeholder-gray-600 text-sm focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/40 transition"
                required />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">Password</label>
              <div className="relative">
                <input type={showPwd ? "text" : "password"} placeholder="Create a strong password" value={formData.password} onChange={change("password")}
                  className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 pr-10 text-white placeholder-gray-600 text-sm focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/40 transition"
                  required />
                <button type="button" onClick={() => setShowPwd(!showPwd)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300">
                  {showPwd ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
              <PasswordStrength password={formData.password} />
            </div>
            <button type="submit" disabled={loading || success}
              className="w-full bg-brand-600 hover:bg-brand-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-xl transition flex items-center justify-center gap-2 text-sm">
              {loading ? <Loader2 size={16} className="animate-spin" /> : "Create Account"}
            </button>
          </form>

          <p className="text-center text-xs text-gray-500 mt-6 leading-relaxed">
            By signing up, you agree to our{" "}
            <span className="text-brand-400 cursor-pointer hover:underline">Terms</span> and{" "}
            <span className="text-brand-400 cursor-pointer hover:underline">Privacy Policy</span>
          </p>

          <div className="mt-6 pt-6 border-t border-gray-800 text-center text-sm text-gray-400">
            Already have an account?{" "}
            <button onClick={() => navigate("login")} className="text-brand-400 hover:text-brand-300 font-medium">Sign in</button>
          </div>
        </div>
      </div>
    </div>
  );
}
