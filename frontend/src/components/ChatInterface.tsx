import { useState, useRef, useEffect, useCallback } from "react";
import {
  Send, Bot, User, Network, FileText, ChevronDown, ChevronUp,
  Copy, ThumbsUp, ThumbsDown, Sparkles, CheckCircle, Square,
  Plus, Zap, MessageSquare, Clock, MoreHorizontal, Loader2
} from "lucide-react";
import RoleSelector from "./RoleSelector";
import axios from "axios";

type Role = "public" | "user" | "admin";

interface Source { name: string; relevance: number; chunk: string }
interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  graphUsed?: boolean;
  confidence?: number;
  sources?: Source[];
  queryType?: string;
  streaming?: boolean;
  chatLogId?: string;
  feedback?: "positive" | "negative" | null;
  groundingScore?: number | null;
  groundingWarning?: string | null;
  providerUsed?: string;
  fallbackUsed?: boolean;
}

interface ChatSession {
  session_id: string;
  title: string;
  message_count: number;
  last_activity: string | null;
  avg_confidence: number;
  created_at: string | null;
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
function SimpleMarkdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  lines.forEach((line, i) => {
    if (line.startsWith("### "))
      elements.push(<h3 key={i} className="text-sm font-bold text-white mt-3 mb-1">{line.slice(4)}</h3>);
    else if (line.startsWith("## "))
      elements.push(<h2 key={i} className="text-base font-bold text-white mt-4 mb-1">{line.slice(3)}</h2>);
    else if (line.match(/^[-*•]\s/))
      elements.push(
        <li key={i} className="flex items-start gap-2 text-sm leading-relaxed my-0.5">
          <span className="w-1.5 h-1.5 rounded-full bg-violet-400/70 mt-2 shrink-0" />
          <span dangerouslySetInnerHTML={{ __html: inlineFmt(line.replace(/^[-*•]\s/, "")) }} />
        </li>
      );
    else if (line.startsWith("    ") || line.startsWith("\t"))
      elements.push(
        <code key={i} className="block bg-black/40 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-emerald-300 font-mono my-1.5">
          {line.trim()}
        </code>
      );
    else if (line.trim())
      elements.push(<p key={i} className="text-sm leading-relaxed" dangerouslySetInnerHTML={{ __html: inlineFmt(line) }} />);
    else
      elements.push(<div key={i} className="h-2" />);
  });
  return <div className="space-y-0.5">{elements}</div>;
}

function inlineFmt(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-white">$1</strong>')
    .replace(/\*(.+?)\*/g, '<em class="italic text-gray-300">$1</em>')
    .replace(/`(.+?)`/g, '<code class="bg-black/40 text-emerald-300 px-1 rounded text-xs font-mono border border-white/10">$1</code>');
}

// ── Confidence badge ──────────────────────────────────────────────────────────
function ConfidenceBadge({ score }: { score: number }) {
  const [color, ring] = score >= 85
    ? ["text-emerald-400", "bg-emerald-400/10 border-emerald-400/30"]
    : score >= 65
    ? ["text-amber-400", "bg-amber-400/10 border-amber-400/30"]
    : ["text-red-400", "bg-red-400/10 border-red-400/30"];
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full border cursor-help ${color} ${ring}`}
      title="AI confidence score">
      <Sparkles size={9} /> {score}%
    </span>
  );
}

// ── Provider pill ─────────────────────────────────────────────────────────────
function ProviderPill({ provider, fallback }: { provider?: string; fallback?: boolean }) {
  if (!provider) return null;
  const isStatic = provider.toLowerCase().includes("static") || provider.toLowerCase().includes("emergency");
  const style = isStatic ? "text-red-300 bg-red-500/10 border-red-500/20"
    : fallback ? "text-amber-300 bg-amber-500/10 border-amber-500/20"
    : "text-sky-300 bg-sky-500/10 border-sky-500/20";
  return (
    <span className={`inline-flex items-center text-xs px-2 py-0.5 rounded-full border ${style}`}>
      {isStatic ? "Static fallback" : fallback ? `${provider} (fallback)` : provider}
    </span>
  );
}

// ── Sources panel ─────────────────────────────────────────────────────────────
function SourcesPanel({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);
  if (!sources.length) return null;
  return (
    <div className="mt-3 pt-3 border-t border-white/5">
      <button onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors">
        <FileText size={11} />
        {sources.length} source{sources.length > 1 ? "s" : ""} used
        {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {sources.map((s, i) => (
            <div key={i} className="bg-black/30 border border-white/5 rounded-lg p-3">
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs font-medium text-gray-300 truncate">{s.name}</span>
                <span className="text-xs text-violet-400 ml-2 shrink-0 font-semibold">{Math.round(s.relevance * 100)}%</span>
              </div>
              <p className="text-xs text-gray-500 leading-relaxed line-clamp-2">{s.chunk}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Typing dots ───────────────────────────────────────────────────────────────
function TypingDots() {
  return (
    <div className="flex gap-1.5 items-end h-5 px-1 py-1">
      {[0, 1, 2].map(i => (
        <span key={i}
          className="w-2 h-2 rounded-full bg-gradient-to-br from-violet-400 to-brand-400 animate-bounce"
          style={{ animationDelay: `${i * 160}ms`, animationDuration: "1s" }} />
      ))}
    </div>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────
function MessageBubble({ msg, onCopy, onFeedback }: {
  msg: Message;
  onCopy: (t: string) => void;
  onFeedback: (id: string, chatLogId: string, type: "positive" | "negative") => void;
}) {
  const isUser = msg.role === "user";

  if (isUser) {
    return (
      <div className="flex gap-3 justify-end">
        <div className="max-w-[72%]">
          <div className="bg-gradient-to-br from-brand-600 to-violet-700 text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed shadow-lg shadow-violet-950/40">
            {msg.content}
          </div>
          <p className="text-[11px] text-gray-600 mt-1 text-right pr-1">
            {msg.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </p>
        </div>
        <div className="w-8 h-8 rounded-full bg-gray-800 border border-white/10 flex items-center justify-center shrink-0 mt-0.5">
          <User size={13} className="text-gray-400" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-brand-600 flex items-center justify-center shrink-0 mt-0.5 shadow-lg shadow-violet-900/50 ring-1 ring-white/10">
        <Bot size={13} className="text-white" />
      </div>
      <div className="max-w-[80%] flex-1">
        <div className="relative bg-gray-900/70 border border-white/[0.08] rounded-2xl rounded-tl-sm px-4 py-4 backdrop-blur-sm shadow-xl shadow-black/30">
          {/* top accent line */}
          <div className="absolute inset-x-0 top-0 h-px rounded-t-2xl bg-gradient-to-r from-transparent via-violet-500/40 to-transparent" />

          {msg.streaming ? <TypingDots /> : (
            <>
              {/* Metadata tags */}
              {(msg.graphUsed || msg.queryType || msg.confidence !== undefined || msg.providerUsed) && (
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {msg.graphUsed && (
                    <span className="flex items-center gap-1 text-xs text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 px-2 py-0.5 rounded-full">
                      <Network size={9} /> Graph
                    </span>
                  )}
                  {msg.queryType && msg.queryType !== "greeting" && (
                    <span className="text-xs text-violet-300 bg-violet-500/10 border border-violet-500/20 px-2 py-0.5 rounded-full capitalize">
                      {msg.queryType}
                    </span>
                  )}
                  {msg.confidence !== undefined && <ConfidenceBadge score={msg.confidence} />}
                  <ProviderPill provider={msg.providerUsed} fallback={msg.fallbackUsed} />
                  {msg.groundingScore != null && msg.groundingScore < 1 && (
                    <span className="text-xs text-gray-500 bg-white/5 border border-white/10 px-2 py-0.5 rounded-full cursor-help"
                      title="Answer grounding score">
                      Ground {(msg.groundingScore * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              )}

              <div className="text-gray-100"><SimpleMarkdown text={msg.content} /></div>
              {msg.sources && <SourcesPanel sources={msg.sources} />}
              {msg.groundingWarning && (
                <p className="mt-2 pl-3 border-l-2 border-amber-500/30 text-xs text-gray-500 italic leading-relaxed">
                  {msg.groundingWarning}
                </p>
              )}

              <div className="flex items-center gap-1.5 mt-3 pt-2.5 border-t border-white/5">
                <span className="text-[11px] text-gray-600 flex-1">
                  {msg.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
                <button onClick={() => onCopy(msg.content)}
                  className="p-1.5 rounded-lg text-gray-600 hover:text-gray-300 hover:bg-white/5 transition-all" title="Copy">
                  <Copy size={12} />
                </button>
                <button
                  onClick={() => msg.chatLogId && onFeedback(msg.id, msg.chatLogId, "positive")}
                  className={`p-1.5 rounded-lg transition-all hover:bg-white/5 ${msg.feedback === "positive" ? "text-emerald-400" : "text-gray-600 hover:text-emerald-400"}`}>
                  <ThumbsUp size={12} />
                </button>
                <button
                  onClick={() => msg.chatLogId && onFeedback(msg.id, msg.chatLogId, "negative")}
                  className={`p-1.5 rounded-lg transition-all hover:bg-white/5 ${msg.feedback === "negative" ? "text-red-400" : "text-gray-600 hover:text-red-400"}`}>
                  <ThumbsDown size={12} />
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Suggestions ───────────────────────────────────────────────────────────────
const SUGGESTIONS = [
  { text: "What is contract number 511047?", icon: FileText },
  { text: "Who are the main parties in the agreements?", icon: MessageSquare },
  { text: "What are the contract start and end dates?", icon: Clock },
  { text: "Summarize the key terms of this document", icon: Zap },
];

// ── Generate session ID ───────────────────────────────────────────────────────
function genSessionId() {
  return `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// ── Relative time helper ──────────────────────────────────────────────────────
function relativeTime(isoStr: string | null): string {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  const diff = Date.now() - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ── Main component ────────────────────────────────────────────────────────────
export default function ChatInterface({ userRole }: { userRole?: string }) {
  const isAdmin = userRole === "admin";
  const effectiveRole: Role = isAdmin ? "admin" : "user";

  const welcomeMsg = isAdmin
    ? "Hello Admin! I'm **CortexFlow AI** — your intelligent document assistant.\n\nYou have **full retrieval access**: exact line lookup, verbatim document content, source citations, and confidence scores.\n\nAsk any question and I'll return precise results with document references."
    : "Hello! I'm **CortexFlow AI** — your intelligent document assistant.\n\nAsk me anything about the documents in the knowledge base and I'll provide a clear, summarized answer.";

  const makeWelcome = (): Message => ({
    id: "welcome", role: "assistant", content: welcomeMsg,
    timestamp: new Date(), graphUsed: false, confidence: 100, queryType: "greeting", sources: [],
  });

  const [messages, setMessages] = useState<Message[]>([makeWelcome()]);
  const [input, setInput] = useState("");
  const [role, setRole] = useState<Role>(effectiveRole);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState("");
  const [feedbackToast, setFeedbackToast] = useState("");
  const [rateLimitSeconds, setRateLimitSeconds] = useState(0);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>(genSessionId);
  const [loadingSession, setLoadingSession] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const rateLimitTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const copyText = useCallback((text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(text.slice(0, 20));
      setTimeout(() => setCopied(""), 2000);
    });
  }, []);

  const submitFeedback = useCallback(async (msgId: string, chatLogId: string, type: "positive" | "negative") => {
    try {
      const token = localStorage.getItem("accessToken");
      await axios.post("/feedback", { chat_log_id: chatLogId, feedback: type },
        { headers: { Authorization: `Bearer ${token}` } });
      setMessages(prev => prev.map(m => m.id === msgId ? { ...m, feedback: type } : m));
      setFeedbackToast(type === "positive" ? "👍 Thanks!" : "👎 Noted!");
      setTimeout(() => setFeedbackToast(""), 2000);
    } catch { /* silent */ }
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const token = localStorage.getItem("accessToken");
      const res = await axios.get("/chat/sessions", { headers: { Authorization: `Bearer ${token}` } });
      setSessions(Array.isArray(res.data) ? res.data : []);
    } catch { setSessions([]); }
  }, []);

  useEffect(() => { loadSessions(); }, [loadSessions]);

  const openSession = useCallback(async (session: ChatSession) => {
    if (session.session_id === activeSessionId) return;
    setLoadingSession(session.session_id);
    try {
      const token = localStorage.getItem("accessToken");
      const res = await axios.get(`/chat/sessions/${session.session_id}`,
        { headers: { Authorization: `Bearer ${token}` } });
      const logs: any[] = res.data;
      const restored: Message[] = [makeWelcome()];
      for (const l of logs) {
        restored.push({
          id: `s-u-${l.id}`, role: "user", content: l.question,
          timestamp: l.created_at ? new Date(l.created_at) : new Date(),
        });
        restored.push({
          id: `s-a-${l.id}`, role: "assistant", content: l.answer,
          timestamp: l.created_at ? new Date(l.created_at) : new Date(),
          graphUsed: l.graph_used,
          confidence: l.confidence ? Math.round(l.confidence) : undefined,
          queryType: l.query_type,
          sources: [],
          chatLogId: l.id,
          feedback: l.feedback || null,
        });
      }
      setMessages(restored);
      setActiveSessionId(session.session_id);
    } catch { /* silent */ }
    finally { setLoadingSession(null); }
  }, [activeSessionId]);

  async function streamContent(msgId: string, fullText: string) {
    const chunkSize = 5;
    let revealed = "";
    for (let i = 0; i < fullText.length; i += chunkSize) {
      revealed += fullText.slice(i, i + chunkSize);
      setMessages(prev => prev.map(m => m.id === msgId ? { ...m, content: revealed, streaming: false } : m));
      await new Promise(r => setTimeout(r, 8));
    }
  }

  function handleStop() {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
  }

  async function handleSend(questionOverride?: string) {
    const q = (questionOverride ?? input).trim();
    if (!q || loading) return;
    const userMsg: Message = { id: Date.now().toString(), role: "user", content: q, timestamp: new Date() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setLoading(true);

    const aiId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, { id: aiId, role: "assistant", content: "", timestamp: new Date(), streaming: true }]);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const token = localStorage.getItem("accessToken");
      const headers: any = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch("/ask", {
        method: "POST",
        headers,
        body: JSON.stringify({ question: q, role, session_id: activeSessionId }),
        signal: controller.signal,
      });

      if (res.status === 429) {
        const errData = await res.json().catch(() => ({}));
        const secs = parseInt(res.headers.get("Retry-After") || "60", 10);
        if (!isNaN(secs) && secs > 0) {
          setRateLimitSeconds(secs);
          if (rateLimitTimerRef.current) clearInterval(rateLimitTimerRef.current);
          rateLimitTimerRef.current = setInterval(() => {
            setRateLimitSeconds(prev => {
              if (prev <= 1) { clearInterval(rateLimitTimerRef.current!); rateLimitTimerRef.current = null; return 0; }
              return prev - 1;
            });
          }, 1000);
        }
        throw new Error(errData.detail || `Rate limit exceeded. Retry in ${secs}s.`);
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      setMessages(prev => prev.map(m => m.id === aiId ? {
        ...m, content: "", streaming: false,
        graphUsed: data.graph_used,
        confidence: Math.round(data.confidence || 75),
        queryType: data.query_type || "fact",
        sources: data.sources || [],
        chatLogId: data.chat_log_id,
        feedback: null,
        groundingScore: data.grounding_score ?? null,
        groundingWarning: data.grounding_warning ?? null,
        providerUsed: data.provider_used ?? undefined,
        fallbackUsed: data.fallback_used ?? false,
      } : m));

      await streamContent(aiId, data.answer);
      // Refresh sessions list after every message
      loadSessions();
    } catch (err: any) {
      const content = err?.name === "AbortError"
        ? "_Response stopped._"
        : "**Error:** Could not reach the API. Please ensure the backend is running on port 8000.";
      setMessages(prev => prev.map(m => m.id === aiId ? { ...m, content, streaming: false, confidence: 0 } : m));
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }

  function startNewChat() {
    const newId = genSessionId();
    setActiveSessionId(newId);
    setMessages([makeWelcome()]);
    setInput("");
  }

  // Group sessions by time bucket
  const groupedSessions = (() => {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
    const weekAgo = new Date(today); weekAgo.setDate(weekAgo.getDate() - 7);
    const groups: { label: string; items: ChatSession[] }[] = [];
    const buckets: Record<string, ChatSession[]> = { Today: [], Yesterday: [], "Previous 7 days": [], Older: [] };
    for (const s of sessions) {
      const d = s.last_activity ? new Date(s.last_activity) : null;
      if (!d) { buckets.Older.push(s); continue; }
      const day = new Date(d); day.setHours(0, 0, 0, 0);
      if (day >= today) buckets.Today.push(s);
      else if (day >= yesterday) buckets.Yesterday.push(s);
      else if (day >= weekAgo) buckets["Previous 7 days"].push(s);
      else buckets.Older.push(s);
    }
    for (const [label, items] of Object.entries(buckets)) {
      if (items.length > 0) groups.push({ label, items });
    }
    return groups;
  })();

  return (
    <div className="flex h-full bg-gray-950 overflow-hidden">

      {/* ── Sessions sidebar ── */}
      <div className="w-60 shrink-0 flex flex-col overflow-hidden border-r border-white/[0.06] bg-[#111318]">
        {/* New chat */}
        <div className="px-3 pt-3 pb-2">
          <button
            onClick={startNewChat}
            className="w-full flex items-center gap-2.5 text-sm text-gray-300 hover:text-white bg-white/5 hover:bg-white/10 border border-white/[0.08] hover:border-white/20 rounded-xl px-3 py-2.5 transition-all group"
          >
            <div className="w-5 h-5 rounded-md bg-brand-600/30 flex items-center justify-center shrink-0">
              <Plus size={11} className="text-brand-300" />
            </div>
            New conversation
          </button>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          {sessions.length === 0 ? (
            <div className="px-3 py-6 text-center">
              <MessageSquare size={20} className="text-gray-700 mx-auto mb-2" />
              <p className="text-xs text-gray-600">No conversations yet.</p>
              <p className="text-xs text-gray-700 mt-1">Start chatting to see history here.</p>
            </div>
          ) : (
            groupedSessions.map(({ label, items }) => (
              <div key={label} className="mb-2">
                <p className="text-[10px] text-gray-600 uppercase tracking-widest font-semibold px-2 py-2">{label}</p>
                <div className="space-y-0.5">
                  {items.map(s => {
                    const isActive = s.session_id === activeSessionId;
                    const isLoading = loadingSession === s.session_id;
                    return (
                      <button
                        key={s.session_id}
                        onClick={() => openSession(s)}
                        className={`w-full text-left px-3 py-2.5 rounded-xl transition-all group relative ${
                          isActive
                            ? "bg-brand-600/20 border border-brand-500/30 text-white"
                            : "hover:bg-white/[0.05] text-gray-400 hover:text-gray-200"
                        }`}
                      >
                        {isLoading && (
                          <Loader2 size={11} className="absolute right-2.5 top-1/2 -translate-y-1/2 animate-spin text-brand-400" />
                        )}
                        <p className={`text-xs leading-relaxed truncate pr-4 ${isActive ? "text-white font-medium" : ""}`}>
                          {s.title}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-[10px] text-gray-600">
                            {s.message_count} msg{s.message_count !== 1 ? "s" : ""}
                          </span>
                          <span className="text-[10px] text-gray-700">·</span>
                          <span className="text-[10px] text-gray-600">{relativeTime(s.last_activity)}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── Chat pane ── */}
      <div className="flex-1 flex flex-col overflow-hidden bg-gray-950">

        {/* Admin banner */}
        {isAdmin && (
          <div className="shrink-0 bg-gradient-to-r from-red-950/50 to-transparent border-b border-red-900/30 px-5 py-2 flex items-center gap-3">
            <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse shrink-0" />
            <span className="text-xs text-red-300/80 font-medium">Admin Mode — Full document access enabled</span>
            <div className="ml-auto"><RoleSelector role={role} onChange={setRole} /></div>
          </div>
        )}
        {!isAdmin && (
          <div className="flex items-center justify-end px-5 py-2 border-b border-white/[0.04] shrink-0">
            <span className="text-xs text-gray-700">Role: <span className="text-gray-600">User</span> · Enter to send</span>
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-5 md:px-8 py-6 space-y-6">
          {messages.map(msg => (
            <MessageBubble key={msg.id} msg={msg} onCopy={copyText} onFeedback={submitFeedback} />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Toasts */}
        {(copied || feedbackToast) && (
          <div className="fixed bottom-24 right-6 flex flex-col gap-2 z-50 pointer-events-none">
            {copied && (
              <div className="bg-gray-900 border border-white/10 text-xs text-emerald-400 px-3 py-2 rounded-xl shadow-2xl flex items-center gap-2 backdrop-blur">
                <CheckCircle size={11} /> Copied!
              </div>
            )}
            {feedbackToast && (
              <div className="bg-gray-900 border border-white/10 text-xs text-violet-300 px-3 py-2 rounded-xl shadow-2xl backdrop-blur">
                {feedbackToast}
              </div>
            )}
          </div>
        )}

        {/* Suggestions */}
        {messages.length <= 1 && (
          <div className="px-5 md:px-8 pb-3 grid grid-cols-2 gap-2">
            {SUGGESTIONS.map(({ text: s, icon: Icon }) => (
              <button key={s} onClick={() => handleSend(s)}
                className="group text-left text-xs text-gray-500 hover:text-gray-200 bg-white/[0.03] hover:bg-white/[0.07] border border-white/[0.06] hover:border-violet-500/30 rounded-xl px-3.5 py-3 transition-all flex items-start gap-2.5">
                <Icon size={13} className="text-violet-500/50 group-hover:text-violet-400 mt-0.5 shrink-0 transition-colors" />
                <span className="leading-relaxed">{s}</span>
              </button>
            ))}
          </div>
        )}

        {/* Input */}
        <div className="shrink-0 px-5 md:px-8 py-4 border-t border-white/[0.05]">
          <div className="flex gap-3 items-end max-w-4xl mx-auto">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask anything about your documents…"
                rows={1}
                className="w-full bg-white/[0.04] border border-white/[0.08] hover:border-white/[0.14] focus:border-violet-500/50 rounded-2xl px-4 py-3.5 text-sm text-white placeholder-gray-600 resize-none focus:outline-none focus:ring-1 focus:ring-violet-500/20 transition-all max-h-36 overflow-y-auto"
                style={{ minHeight: "50px" }}
                onInput={e => {
                  const t = e.currentTarget;
                  t.style.height = "auto";
                  t.style.height = `${Math.min(t.scrollHeight, 144)}px`;
                }}
              />
            </div>
            {loading ? (
              <button onClick={handleStop}
                className="bg-red-600/80 hover:bg-red-500 text-white rounded-2xl p-3.5 transition shrink-0 shadow-lg shadow-red-950/50">
                <Square size={16} />
              </button>
            ) : rateLimitSeconds > 0 ? (
              <button disabled
                className="bg-white/5 text-amber-400 rounded-2xl px-3.5 py-3.5 shrink-0 text-xs font-bold min-w-[52px] text-center border border-amber-500/20">
                {rateLimitSeconds}s
              </button>
            ) : (
              <button onClick={() => handleSend()} disabled={!input.trim()}
                className="bg-gradient-to-br from-brand-600 to-violet-600 hover:from-brand-500 hover:to-violet-500 disabled:opacity-25 disabled:cursor-not-allowed text-white rounded-2xl p-3.5 transition-all shrink-0 shadow-lg shadow-violet-950/50">
                <Send size={16} />
              </button>
            )}
          </div>
          <p className="text-[11px] text-gray-700 text-center mt-2">
            {rateLimitSeconds > 0
              ? <span className="text-amber-600">⏱ Rate limit — retry in {rateLimitSeconds}s</span>
              : isAdmin
              ? <>Role: <span className="text-red-500/70 capitalize">{role}</span> · Enter to send · Shift+Enter new line</>
              : <>Enter to send · Shift+Enter new line</>}
          </p>
        </div>
      </div>
    </div>
  );
}
