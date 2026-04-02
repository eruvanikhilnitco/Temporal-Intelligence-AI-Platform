import { useState } from "react";
import { ArrowRight, Brain, Zap, Lock, BarChart3, GitBranch, Shield, Network, ChevronRight, Check, Star, Send, Bot, Globe, LogIn, Loader2 } from "lucide-react";
import { NavigateFn } from "../App";

const FEATURES = [
  { icon: Brain, title: "Hybrid RAG", desc: "Combines dense vector search with sparse retrieval for maximum recall and precision across all document types.", color: "text-violet-400", bg: "bg-violet-400/10 border-violet-400/20" },
  { icon: GitBranch, title: "Knowledge Graph", desc: "Automatically extracts entities and relationships, building a semantic graph for multi-hop reasoning.", color: "text-blue-400", bg: "bg-blue-400/10 border-blue-400/20" },
  { icon: Zap, title: "Real-time Streaming", desc: "Token-by-token response streaming with confidence scores and source citations displayed live.", color: "text-yellow-400", bg: "bg-yellow-400/10 border-yellow-400/20" },
  { icon: Lock, title: "Zero-Trust Security", desc: "JWT authentication, document-level RBAC, and query-time enforcement with full audit logging.", color: "text-emerald-400", bg: "bg-emerald-400/10 border-emerald-400/20" },
  { icon: Network, title: "Multi-hop Reasoning", desc: "Decomposes complex queries into sub-questions and combines results for deeper, connected answers.", color: "text-pink-400", bg: "bg-pink-400/10 border-pink-400/20" },
  { icon: BarChart3, title: "Enterprise Analytics", desc: "Track accuracy, latency, cache hit rates, and per-user engagement with detailed dashboards.", color: "text-orange-400", bg: "bg-orange-400/10 border-orange-400/20" },
];

// ── Public Demo Chat ──────────────────────────────────────────────────────────
function PublicDemoChat() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<{ role: "user" | "ai"; text: string; conf?: number }[]>([
    { role: "ai", text: "Hi! I'm CortexFlow AI in public demo mode. Ask me anything about the platform or try a sample question below.", conf: 100 },
  ]);
  const [loading, setLoading] = useState(false);

  const SAMPLES = [
    "What is contract number 511047?",
    "Summarize all high-risk agreements",
  ];

  async function send(q?: string) {
    const question = (q ?? input).trim();
    if (!question || loading) return;
    setMessages(prev => [...prev, { role: "user", text: question }]);
    setInput("");
    setLoading(true);
    try {
      const res = await fetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, role: "public" }),
      });
      const data = await res.json();
      setMessages(prev => [...prev, { role: "ai", text: data.answer || "No response.", conf: Math.round(data.confidence || 75) }]);
    } catch {
      setMessages(prev => [...prev, { role: "ai", text: "Demo is limited — please sign in for full access." }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
      {/* Terminal bar */}
      <div className="flex items-center gap-2 px-5 py-3.5 border-b border-gray-800 bg-gray-800/50">
        <span className="w-3 h-3 rounded-full bg-red-500" />
        <span className="w-3 h-3 rounded-full bg-yellow-500" />
        <span className="w-3 h-3 rounded-full bg-green-500" />
        <span className="ml-4 text-xs text-gray-500">CortexFlow Chat — Public Demo</span>
        <span className="ml-auto text-xs bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full flex items-center gap-1">
          <Globe size={10} /> Limited Access
        </span>
      </div>

      {/* Messages */}
      <div className="p-5 space-y-4 min-h-[200px] max-h-72 overflow-y-auto">
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
            {m.role === "ai" && (
              <div className="w-7 h-7 rounded-full bg-gradient-to-br from-brand-600 to-violet-600 flex items-center justify-center shrink-0">
                <Bot size={13} className="text-white" />
              </div>
            )}
            <div className={`max-w-sm rounded-2xl px-4 py-2.5 text-sm ${m.role === "user" ? "bg-brand-600 text-white rounded-tr-sm" : "bg-gray-800 border border-gray-700 text-gray-100 rounded-tl-sm"}`}>
              {m.text}
              {m.conf !== undefined && m.role === "ai" && (
                <div className="mt-1.5 flex items-center gap-1 text-xs text-yellow-400">
                  <Star size={10} /> {m.conf}% confidence
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-brand-600 to-violet-600 flex items-center justify-center">
              <Bot size={13} className="text-white" />
            </div>
            <div className="bg-gray-800 border border-gray-700 rounded-2xl rounded-tl-sm px-4 py-3">
              <div className="flex gap-1">
                {[0,1,2].map(i => <span key={i} className="w-2 h-2 bg-brand-400 rounded-full animate-bounce" style={{ animationDelay: `${i*120}ms` }} />)}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Sample questions */}
      <div className="px-5 pb-3 flex gap-2 flex-wrap">
        {SAMPLES.map(s => (
          <button key={s} onClick={() => send(s)} className="text-xs text-gray-400 hover:text-gray-200 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg px-3 py-1.5 transition">
            {s}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="px-5 pb-5 flex gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()}
          placeholder="Ask a question in demo mode…"
          className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition"
        />
        <button onClick={() => send()} disabled={!input.trim() || loading}
          className="bg-brand-600 hover:bg-brand-500 disabled:opacity-40 text-white rounded-xl px-4 py-2.5 transition">
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
        </button>
      </div>
    </div>
  );
}

export default function Landing({ navigate }: { navigate: NavigateFn }) {
  const [accessMode, setAccessMode] = useState<"public" | "login">("public");

  return (
    <div className="bg-gray-950 text-white min-h-screen overflow-x-hidden">

      {/* NAV */}
      <header className="fixed top-0 inset-x-0 z-50 bg-gray-950/80 backdrop-blur-md border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">🧠</span>
            <span className="font-bold text-white text-lg tracking-tight">CortexFlow</span>
            <span className="hidden sm:inline text-xs bg-brand-600/30 text-brand-300 px-2 py-0.5 rounded-full font-medium">v3</span>
          </div>
          <nav className="hidden md:flex items-center gap-8 text-sm text-gray-400">
            <a href="#features" className="hover:text-white transition">Features</a>
            <a href="#demo" className="hover:text-white transition">Demo</a>
          </nav>
          <div className="flex items-center gap-3">
            <button onClick={() => navigate("login")} className="text-sm text-gray-300 hover:text-white px-4 py-2 transition">Sign in</button>
            <button onClick={() => navigate("signup-user")} className="text-sm font-medium bg-brand-600 hover:bg-brand-500 text-white px-4 py-2 rounded-lg transition">
              Get Started
            </button>
          </div>
        </div>
      </header>

      {/* HERO */}
      <section className="relative pt-32 pb-20 px-6 text-center overflow-hidden">
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute top-20 left-1/4 w-96 h-96 bg-brand-600/20 rounded-full blur-3xl" />
          <div className="absolute top-40 right-1/4 w-80 h-80 bg-purple-600/15 rounded-full blur-3xl" />
        </div>
        <div className="relative max-w-4xl mx-auto">
          <div className="inline-flex items-center gap-2 bg-brand-600/15 border border-brand-500/30 text-brand-300 text-xs font-medium px-4 py-1.5 rounded-full mb-6">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            Phase 3 — Graph RAG is live
          </div>
          <h1 className="text-5xl md:text-7xl font-extrabold leading-tight tracking-tight mb-6">
            <span className="text-white">Enterprise AI for</span><br />
            <span className="bg-gradient-to-r from-brand-400 via-violet-400 to-pink-400 bg-clip-text text-transparent">
              Intelligent Knowledge
            </span>
          </h1>
          <p className="text-lg md:text-xl text-gray-400 max-w-2xl mx-auto mb-10 leading-relaxed">
            CortexFlow combines hybrid vector + graph retrieval, multi-hop reasoning, and enterprise security to deliver precise answers from your documents — at scale.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center mb-16">
            <button onClick={() => navigate("signup-user")} className="group flex items-center justify-center gap-2 px-8 py-3.5 bg-brand-600 hover:bg-brand-500 text-white font-semibold rounded-xl transition shadow-lg shadow-brand-600/25">
              Start for Free <ArrowRight size={18} className="group-hover:translate-x-0.5 transition-transform" />
            </button>
            <button onClick={() => { const el = document.getElementById("demo"); el?.scrollIntoView({ behavior: "smooth" }); }}
              className="flex items-center justify-center gap-2 px-8 py-3.5 bg-white/5 hover:bg-white/10 text-white border border-white/10 font-semibold rounded-xl transition">
              Try Demo
            </button>
          </div>
          <div className="flex items-center justify-center gap-6 text-sm text-gray-500 flex-wrap">
            {["No credit card required", "SOC2-ready architecture", "GDPR-compliant"].map(t => (
              <span key={t} className="flex items-center gap-1.5"><Check size={13} className="text-emerald-400" />{t}</span>
            ))}
          </div>
        </div>
      </section>

      {/* FEATURES */}
      <section id="features" className="py-24 px-6">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-sm font-medium text-brand-400 uppercase tracking-widest mb-3">Capabilities</p>
            <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">Powered by advanced AI infrastructure</h2>
            <p className="text-gray-400 max-w-xl mx-auto">Every component is production-grade and designed for enterprise reliability.</p>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map(({ icon: Icon, title, desc, color, bg }) => (
              <div key={title} className="bg-gray-900 border border-gray-800 hover:border-gray-700 rounded-2xl p-6 transition">
                <div className={`inline-flex p-2.5 rounded-xl ${bg} border mb-4`}>
                  <Icon size={22} className={color} />
                </div>
                <h3 className="font-semibold text-white mb-2">{title}</h3>
                <p className="text-sm text-gray-400 leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* DEMO — with Access Mode toggle */}
      <section id="demo" className="py-24 px-6 bg-gray-900/50">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-sm font-medium text-brand-400 uppercase tracking-widest mb-3">Interactive Demo</p>
            <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">See CortexFlow in action</h2>
            <p className="text-gray-400 mb-8">Try the AI assistant directly — no account required in Public Demo mode.</p>

            {/* Access Mode Toggle */}
            <div className="inline-flex items-center gap-1 bg-gray-800 border border-gray-700 rounded-xl p-1">
              <button
                onClick={() => setAccessMode("public")}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition ${accessMode === "public" ? "bg-brand-600 text-white shadow" : "text-gray-400 hover:text-white"}`}
              >
                <Globe size={14} /> Public Demo
              </button>
              <button
                onClick={() => setAccessMode("login")}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition ${accessMode === "login" ? "bg-brand-600 text-white shadow" : "text-gray-400 hover:text-white"}`}
              >
                <LogIn size={14} /> Login Required
              </button>
            </div>
          </div>

          {accessMode === "public" ? (
            <PublicDemoChat />
          ) : (
            <div className="bg-gray-900 border border-gray-700 rounded-2xl p-12 text-center">
              <div className="w-16 h-16 rounded-full bg-brand-600/20 border border-brand-500/30 flex items-center justify-center mx-auto mb-6">
                <Shield size={28} className="text-brand-400" />
              </div>
              <h3 className="text-xl font-bold text-white mb-3">Full Access Requires Login</h3>
              <p className="text-gray-400 mb-8 max-w-sm mx-auto">
                Sign in to unlock document uploads, full retrieval, analytics, and admin controls.
              </p>
              <div className="flex gap-3 justify-center">
                <button onClick={() => navigate("login")} className="flex items-center gap-2 px-6 py-2.5 bg-brand-600 hover:bg-brand-500 text-white font-semibold rounded-xl transition">
                  <LogIn size={16} /> Sign In
                </button>
                <button onClick={() => navigate("signup-user")} className="flex items-center gap-2 px-6 py-2.5 bg-white/5 hover:bg-white/10 text-white border border-white/10 font-semibold rounded-xl transition">
                  Create Account
                </button>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ARCHITECTURE */}
      <section className="py-24 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-sm font-medium text-brand-400 uppercase tracking-widest mb-3">Architecture</p>
            <h2 className="text-3xl md:text-4xl font-bold text-white">Three phases of intelligence</h2>
          </div>
          <div className="grid md:grid-cols-3 gap-6">
            {[
              { phase: "Phase 1", label: "Baseline RAG", desc: "Document ingestion, chunking, BAAI embeddings, Qdrant vector search, Cohere LLM generation.", icon: "📄" },
              { phase: "Phase 2", label: "Intelligence Layer", desc: "Query classification, cross-encoder re-ranking, multi-hop decomposition, semantic caching.", icon: "🧠" },
              { phase: "Phase 3", label: "Graph RAG", desc: "Named entity recognition, relationship extraction, Neo4j graph storage, hybrid retrieval.", icon: "🔗" },
            ].map(({ phase, label, desc, icon }) => (
              <div key={phase} className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
                <div className="text-3xl mb-4">{icon}</div>
                <div className="text-xs text-brand-400 font-medium uppercase tracking-widest mb-2">{phase}</div>
                <h3 className="font-bold text-white mb-3">{label}</h3>
                <p className="text-sm text-gray-400 leading-relaxed">{desc}</p>
                <div className="mt-4 flex items-center gap-1.5 text-xs text-emerald-400 font-medium">
                  <Check size={12} /> Deployed
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-6 bg-gray-900/50">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">Ready to transform your knowledge system?</h2>
          <p className="text-gray-400 mb-8">Join teams using CortexFlow to extract intelligence from their documents in minutes.</p>
          <div className="flex gap-4 justify-center flex-wrap">
            <button onClick={() => navigate("signup-user")} className="inline-flex items-center gap-2 px-8 py-3.5 bg-brand-600 hover:bg-brand-500 text-white font-semibold rounded-xl transition">
              Get started for free <ChevronRight size={18} />
            </button>
            <button onClick={() => navigate("signup-admin")} className="inline-flex items-center gap-2 px-8 py-3.5 bg-white/5 hover:bg-white/10 text-white border border-white/10 font-semibold rounded-xl transition">
              <Shield size={16} /> Register as Admin
            </button>
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="border-t border-gray-800 py-10 px-6">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-4">
          <div className="flex items-center gap-2 text-gray-400 text-sm">
            <span>🧠</span><span>CortexFlow AI</span>
            <span className="text-gray-600">·</span>
            <span>Enterprise AI Platform v3.0</span>
          </div>
          <div className="flex items-center gap-6 text-sm text-gray-500">
            <a href="#" className="hover:text-gray-300 transition">Docs</a>
            <a href="#" className="hover:text-gray-300 transition">GitHub</a>
            <a href="#" className="hover:text-gray-300 transition">Privacy</a>
            <a href="#" className="hover:text-gray-300 transition">Contact</a>
          </div>
          <p className="text-xs text-gray-600">&copy; 2026 CortexFlow. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}
