import { useState } from "react";
import { Loader2, Check, Mail } from "lucide-react";
import { NavigateFn } from "../App";

export default function ForgotPassword({ navigate }: { navigate: NavigateFn }) {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    await new Promise(r => setTimeout(r, 1200));
    setSent(true);
    setLoading(false);
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center px-6">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-14 h-14 bg-brand-600/20 rounded-full flex items-center justify-center mx-auto mb-4">
            <Mail size={24} className="text-brand-400" />
          </div>
          <h1 className="text-2xl font-bold text-white">Reset your password</h1>
          <p className="text-gray-400 text-sm mt-2">We'll send a reset link to your email.</p>
        </div>

        {sent ? (
          <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-6 text-center">
            <Check size={32} className="text-emerald-400 mx-auto mb-3" />
            <p className="text-emerald-300 font-medium mb-2">Reset link sent!</p>
            <p className="text-sm text-gray-400 mb-4">Check your inbox at <strong className="text-gray-300">{email}</strong></p>
            <button onClick={() => navigate("login")} className="text-brand-400 hover:text-brand-300 text-sm">Back to sign in</button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">Email address</label>
              <input type="email" placeholder="you@company.com" value={email} onChange={e => setEmail(e.target.value)}
                className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-white placeholder-gray-600 text-sm focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/40 transition"
                required />
            </div>
            <button type="submit" disabled={loading}
              className="w-full bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white font-semibold py-2.5 rounded-xl transition flex items-center justify-center gap-2 text-sm">
              {loading ? <Loader2 size={16} className="animate-spin" /> : "Send Reset Link"}
            </button>
            <p className="text-center text-sm text-gray-400">
              <button type="button" onClick={() => navigate("login")} className="text-brand-400 hover:text-brand-300">Back to sign in</button>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
