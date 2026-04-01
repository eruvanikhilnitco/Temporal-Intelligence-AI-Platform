import { useState } from "react";
import { Key, Zap, Shield, Database, Bell, RefreshCw, Check, Eye, EyeOff } from "lucide-react";

type SettingTab = "api" | "model" | "cache" | "security" | "notifications";

function Section({ title, desc, icon: Icon, children }: any) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-6">
      <div className="flex items-center gap-2 mb-1">
        <Icon size={18} className="text-brand-400" />
        <h3 className="font-semibold text-white">{title}</h3>
      </div>
      <p className="text-xs text-gray-400 mb-5">{desc}</p>
      {children}
    </div>
  );
}

export default function SettingsPage() {
  const [tab, setTab] = useState<SettingTab>("api");
  const [showKey, setShowKey] = useState(false);
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);
  const [settings, setSettings] = useState({
    llmProvider: "cohere",
    temperature: "0.2",
    maxTokens: "1024",
    cacheEnabled: true,
    cacheTTL: "3600",
    rateLimit: "60",
    sessionTimeout: "24",
  });

  function handleSave() {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  function copyKey() {
    navigator.clipboard.writeText("sk_prod_Ud6FX8iIpKVtuAwu5MQ4TRzD5f60kQiKvywezVXI");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const tabs = [
    { id: "api", label: "API Keys", icon: Key },
    { id: "model", label: "Model", icon: Zap },
    { id: "cache", label: "Cache", icon: Database },
    { id: "security", label: "Security", icon: Shield },
    { id: "notifications", label: "Alerts", icon: Bell },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-800 px-6 pt-1 shrink-0">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id as SettingTab)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition -mb-px ${
              tab === id ? "border-brand-500 text-brand-300" : "border-transparent text-gray-400 hover:text-white"
            }`}
          >
            <Icon size={13} /> {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        {/* ── API KEYS ── */}
        {tab === "api" && (
          <>
            <Section icon={Key} title="API Keys" desc="Manage API keys for authenticating with CortexFlow and external services.">
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-2">Your API Key</label>
                  <div className="flex gap-2">
                    <div className="flex-1 flex items-center bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 gap-2">
                      <code className="text-sm text-gray-300 flex-1 font-mono">
                        {showKey ? "Ud6FX8iIpKVtuAwu5MQ4TRzD5f60kQiKvywezVXI" : "sk_prod_••••••••••••••••••••••••••••"}
                      </code>
                      <button onClick={() => setShowKey(!showKey)} className="text-gray-500 hover:text-gray-300 transition">
                        {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                    <button
                      onClick={copyKey}
                      className="px-4 py-2.5 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-xl transition flex items-center gap-1.5"
                    >
                      {copied ? <><Check size={13} /> Copied</> : "Copy"}
                    </button>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">This is your Cohere API key. Keep it secret.</p>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-2">OpenAI API Key (optional)</label>
                  <input
                    type="password"
                    placeholder="sk-..."
                    className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand-500 transition"
                  />
                </div>
              </div>
            </Section>
          </>
        )}

        {/* ── MODEL CONFIG ── */}
        {tab === "model" && (
          <Section icon={Zap} title="Model Configuration" desc="Configure LLM and embedding model settings.">
            <div className="space-y-5">
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-2">LLM Provider</label>
                <select
                  value={settings.llmProvider}
                  onChange={e => setSettings(p => ({ ...p, llmProvider: e.target.value }))}
                  className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:border-brand-500 transition"
                >
                  <option value="cohere">Cohere (command-r7b-12-2024)</option>
                  <option value="openai">OpenAI (gpt-4o-mini)</option>
                  <option value="ollama">Ollama (local)</option>
                </select>
              </div>

              <div>
                <div className="flex justify-between mb-2">
                  <label className="text-xs font-medium text-gray-400">Temperature</label>
                  <span className="text-xs text-brand-300 font-bold">{settings.temperature}</span>
                </div>
                <input
                  type="range" min="0" max="1" step="0.05"
                  value={settings.temperature}
                  onChange={e => setSettings(p => ({ ...p, temperature: e.target.value }))}
                  className="w-full accent-brand-500"
                />
                <div className="flex justify-between text-xs text-gray-500 mt-1">
                  <span>Deterministic (0.0)</span><span>Creative (1.0)</span>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-400 mb-2">Max Output Tokens</label>
                <input
                  type="number"
                  value={settings.maxTokens}
                  onChange={e => setSettings(p => ({ ...p, maxTokens: e.target.value }))}
                  className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:border-brand-500 transition"
                />
              </div>

              <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 text-xs space-y-1">
                <p className="text-gray-400 font-medium mb-2">Current Embedding Model</p>
                <div className="flex justify-between"><span className="text-gray-500">Model</span><span className="text-white">BAAI/bge-large-en-v1.5</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Dimensions</span><span className="text-white">1024</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Re-ranker</span><span className="text-white">cross-encoder/ms-marco-MiniLM-L-6-v2</span></div>
              </div>

              <button onClick={handleSave} className="w-full py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-sm font-medium transition flex items-center justify-center gap-2">
                {saved ? <><Check size={14} /> Saved!</> : "Save Changes"}
              </button>
            </div>
          </Section>
        )}

        {/* ── CACHE ── */}
        {tab === "cache" && (
          <Section icon={Database} title="Cache & Storage" desc="Manage semantic caching and vector store settings.">
            <div className="space-y-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-white">Semantic Cache</p>
                  <p className="text-xs text-gray-400">Cache identical queries to reduce latency</p>
                </div>
                <button
                  onClick={() => setSettings(p => ({ ...p, cacheEnabled: !p.cacheEnabled }))}
                  className={`w-12 h-6 rounded-full transition ${settings.cacheEnabled ? "bg-brand-600" : "bg-gray-700"} relative`}
                >
                  <span className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all ${settings.cacheEnabled ? "left-7" : "left-1"}`} />
                </button>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-400 mb-2">Cache TTL (seconds)</label>
                <input
                  type="number"
                  value={settings.cacheTTL}
                  onChange={e => setSettings(p => ({ ...p, cacheTTL: e.target.value }))}
                  className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:border-brand-500 transition"
                />
              </div>

              <div className="bg-gray-900 border border-gray-700 rounded-xl p-4">
                <div className="flex justify-between text-sm mb-3">
                  <span className="text-gray-400">Cache size</span>
                  <span className="text-white">2.4 GB / 10 GB</span>
                </div>
                <div className="h-2 bg-gray-700 rounded-full"><div className="h-2 bg-brand-500 rounded-full w-1/4" /></div>
              </div>

              <button className="w-full py-2.5 border border-red-500/30 hover:border-red-500/60 text-red-400 rounded-xl text-sm font-medium transition flex items-center justify-center gap-2">
                <RefreshCw size={14} /> Clear All Cache
              </button>
            </div>
          </Section>
        )}

        {/* ── SECURITY ── */}
        {tab === "security" && (
          <Section icon={Shield} title="Security Settings" desc="Authentication, rate limiting, and access control configuration.">
            <div className="space-y-5">
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-2">Rate Limit (requests/minute)</label>
                <input
                  type="number"
                  value={settings.rateLimit}
                  onChange={e => setSettings(p => ({ ...p, rateLimit: e.target.value }))}
                  className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:border-brand-500 transition"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-400 mb-2">Session Timeout (hours)</label>
                <input
                  type="number"
                  value={settings.sessionTimeout}
                  onChange={e => setSettings(p => ({ ...p, sessionTimeout: e.target.value }))}
                  className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:border-brand-500 transition"
                />
              </div>

              <div className="pt-2">
                <button className="w-full py-2.5 border border-yellow-500/30 hover:border-yellow-500/60 text-yellow-400 rounded-xl text-sm font-medium transition">
                  Change Password
                </button>
              </div>

              <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 text-xs space-y-1.5">
                {[
                  { k: "Auth method", v: "JWT (HS256)" },
                  { k: "Password hashing", v: "bcrypt (rounds: 12)" },
                  { k: "Token expiry", v: "24h access / 7d refresh" },
                  { k: "RBAC levels", v: "public, user, admin" },
                ].map(({ k, v }) => (
                  <div key={k} className="flex justify-between">
                    <span className="text-gray-500">{k}</span>
                    <span className="text-emerald-400 font-mono">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </Section>
        )}

        {/* ── NOTIFICATIONS ── */}
        {tab === "notifications" && (
          <Section icon={Bell} title="Alerts & Notifications" desc="Configure system alerts and notification preferences.">
            <div className="space-y-4">
              {[
                { label: "Security alerts", desc: "Prompt injection attempts, rate limit violations" },
                { label: "System health", desc: "Database disconnections, API failures" },
                { label: "Usage reports", desc: "Weekly query and performance summaries" },
                { label: "New documents", desc: "Notify when documents finish ingestion" },
              ].map(({ label, desc }, i) => (
                <div key={label} className="flex items-start gap-3">
                  <div className="flex-1">
                    <p className="text-sm font-medium text-white">{label}</p>
                    <p className="text-xs text-gray-400">{desc}</p>
                  </div>
                  <button className={`w-10 h-5 rounded-full transition relative ${i < 2 ? "bg-brand-600" : "bg-gray-700"}`}>
                    <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${i < 2 ? "left-5" : "left-0.5"}`} />
                  </button>
                </div>
              ))}
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}
