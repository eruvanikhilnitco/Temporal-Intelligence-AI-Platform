import { useState, useRef, useEffect, useCallback } from "react";
import {
  Send, Bot, User, Loader2, Network, FileText, ChevronDown, ChevronUp,
  Copy, ThumbsUp, ThumbsDown, Sparkles, RefreshCw, CheckCircle, History, Square
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
}

// ── Simple inline markdown renderer ─────────────────────────────────────────
function SimpleMarkdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];

  lines.forEach((line, i) => {
    if (line.startsWith("### ")) {
      elements.push(<h3 key={i} className="text-sm font-bold text-white mt-2 mb-1">{line.slice(4)}</h3>);
    } else if (line.startsWith("## ")) {
      elements.push(<h2 key={i} className="text-base font-bold text-white mt-3 mb-1">{line.slice(3)}</h2>);
    } else if (line.match(/^[-*•]\s/)) {
      const content = line.replace(/^[-*•]\s/, "");
      elements.push(
        <li key={i} className="flex items-start gap-2 text-sm leading-relaxed">
          <span className="w-1.5 h-1.5 rounded-full bg-brand-400 mt-2 shrink-0" />
          <span dangerouslySetInnerHTML={{ __html: inlineFmt(content) }} />
        </li>
      );
    } else if (line.startsWith("    ") || line.startsWith("\t")) {
      elements.push(
        <code key={i} className="block bg-gray-900 border border-gray-700 rounded px-3 py-1 text-xs text-emerald-300 font-mono my-1">
          {line.trim()}
        </code>
      );
    } else if (line.trim()) {
      elements.push(
        <p key={i} className="text-sm leading-relaxed" dangerouslySetInnerHTML={{ __html: inlineFmt(line) }} />
      );
    } else {
      elements.push(<div key={i} className="h-2" />);
    }
  });

  return <div className="space-y-1">{elements}</div>;
}

function inlineFmt(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-white">$1</strong>')
    .replace(/\*(.+?)\*/g, '<em class="italic">$1</em>')
    .replace(/`(.+?)`/g, '<code class="bg-gray-800 text-emerald-300 px-1 rounded text-xs font-mono">$1</code>');
}

// ── Confidence badge ─────────────────────────────────────────────────────────
function ConfidenceBadge({ score }: { score: number }) {
  const color = score >= 85 ? "text-emerald-400 bg-emerald-400/10 border-emerald-400/20"
    : score >= 65 ? "text-yellow-400 bg-yellow-400/10 border-yellow-400/20"
    : "text-red-400 bg-red-400/10 border-red-400/20";
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full border ${color}`}>
      <Sparkles size={10} /> {score}%
    </span>
  );
}

// ── Source accordion ─────────────────────────────────────────────────────────
function SourcesPanel({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);
  if (!sources.length) return null;
  return (
    <div className="mt-3 border-t border-gray-700 pt-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-300 transition"
      >
        <FileText size={12} />
        {sources.length} source{sources.length > 1 ? "s" : ""} used
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {sources.map((s, i) => (
            <div key={i} className="bg-gray-900 border border-gray-700 rounded-lg p-3">
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs font-medium text-gray-300 truncate">{s.name}</span>
                <span className="text-xs text-brand-400 ml-2 shrink-0">{Math.round(s.relevance * 100)}%</span>
              </div>
              <p className="text-xs text-gray-500 leading-relaxed line-clamp-2">{s.chunk}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Typing indicator ─────────────────────────────────────────────────────────
function TypingDots() {
  return (
    <div className="flex gap-1 items-center h-5 px-1">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-2 h-2 bg-brand-400 rounded-full animate-bounce"
          style={{ animationDelay: `${i * 120}ms`, animationDuration: "0.8s" }}
        />
      ))}
    </div>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────
function MessageBubble({
  msg,
  onCopy,
  onFeedback,
}: {
  msg: Message;
  onCopy: (t: string) => void;
  onFeedback: (id: string, chatLogId: string, type: "positive" | "negative") => void;
}) {
  const isUser = msg.role === "user";

  if (isUser) {
    return (
      <div className="flex gap-3 justify-end">
        <div className="max-w-[75%] bg-brand-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed">
          {msg.content}
          <p className="text-xs text-brand-200 mt-1.5 text-right">
            {msg.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </p>
        </div>
        <div className="w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center shrink-0 mt-0.5">
          <User size={14} className="text-gray-300" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-brand-600 to-violet-600 flex items-center justify-center shrink-0 mt-0.5">
        <Bot size={14} className="text-white" />
      </div>
      <div className="max-w-[80%] flex-1">
        <div className="bg-gray-800 border border-gray-700 rounded-2xl rounded-tl-sm px-4 py-3">
          {msg.streaming ? (
            <TypingDots />
          ) : (
            <>
              {/* Tags row */}
              <div className="flex flex-wrap items-center gap-2 mb-2">
                {msg.graphUsed && (
                  <span className="flex items-center gap-1 text-xs text-emerald-400 bg-emerald-400/10 border border-emerald-400/20 px-2 py-0.5 rounded-full">
                    <Network size={10} /> Graph
                  </span>
                )}
                {msg.queryType && (
                  <span className="text-xs text-violet-300 bg-violet-400/10 border border-violet-400/20 px-2 py-0.5 rounded-full capitalize">
                    {msg.queryType}
                  </span>
                )}
                {msg.confidence !== undefined && <ConfidenceBadge score={msg.confidence} />}
              </div>

              {/* Content */}
              <div className="text-gray-100">
                <SimpleMarkdown text={msg.content} />
              </div>

              {/* Sources */}
              {msg.sources && <SourcesPanel sources={msg.sources} />}

              {/* Action row */}
              <div className="flex items-center gap-3 mt-3 pt-2 border-t border-gray-700">
                <span className="text-xs text-gray-500 flex-1">
                  {msg.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
                <button onClick={() => onCopy(msg.content)} className="text-gray-500 hover:text-gray-300 transition" title="Copy">
                  <Copy size={12} />
                </button>
                <button
                  onClick={() => msg.chatLogId && onFeedback(msg.id, msg.chatLogId, "positive")}
                  className={`transition ${msg.feedback === "positive" ? "text-emerald-400" : "text-gray-500 hover:text-emerald-400"}`}
                  title="Good response"
                >
                  <ThumbsUp size={12} />
                </button>
                <button
                  onClick={() => msg.chatLogId && onFeedback(msg.id, msg.chatLogId, "negative")}
                  className={`transition ${msg.feedback === "negative" ? "text-red-400" : "text-gray-500 hover:text-red-400"}`}
                  title="Poor response"
                >
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

// ── Suggested questions ───────────────────────────────────────────────────────
const SUGGESTIONS = [
  "What is contract number 511047?",
  "Who are the main parties in the agreements?",
  "What are the contract start and end dates?",
  "Summarize the key terms of this document",
];

// ── Main ChatInterface ────────────────────────────────────────────────────────
export default function ChatInterface({ userRole }: { userRole?: string }) {
  const isAdmin = userRole === "admin";
  const effectiveRole: Role = isAdmin ? "admin" : "user";

  const welcomeMsg = isAdmin
    ? "Hello Admin! I'm **CortexFlow AI** — your intelligent document assistant.\n\nYou have **full retrieval access**: exact line lookup, verbatim document content, source citations, and confidence scores.\n\nAsk any question and I'll return precise results with document references."
    : "Hello! I'm **CortexFlow AI** — your intelligent document assistant.\n\nAsk me anything about the documents in the knowledge base and I'll provide a clear, summarized answer.";

  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content: welcomeMsg,
      timestamp: new Date(),
      graphUsed: false,
      confidence: 100,
      queryType: "greeting",
      sources: [],
    },
  ]);
  const [input, setInput] = useState("");
  const [role, setRole] = useState<Role>(effectiveRole);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const copyText = useCallback((text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(text.slice(0, 20));
      setTimeout(() => setCopied(""), 2000);
    });
  }, []);

  const submitFeedback = useCallback(async (
    msgId: string,
    chatLogId: string,
    type: "positive" | "negative"
  ) => {
    try {
      const token = localStorage.getItem("accessToken");
      await axios.post(
        "/feedback",
        { chat_log_id: chatLogId, feedback: type },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setMessages(prev =>
        prev.map(m => m.id === msgId ? { ...m, feedback: type } : m)
      );
    } catch {
      // silently fail
    }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const token = localStorage.getItem("accessToken");
      const res = await axios.get("/chat/history?limit=30", {
        headers: { Authorization: `Bearer ${token}` },
      });
      setHistory(res.data);
    } catch {
      setHistory([]);
    }
  }, []);

  // Load history on mount so sidebar is populated immediately
  useEffect(() => { loadHistory(); }, [loadHistory]);

  const restoreHistoryItem = useCallback((item: any) => {
    // Restore the Q&A pair as actual messages in the chat
    const userMsg: Message = {
      id: `hist-u-${item.id}`,
      role: "user",
      content: item.question,
      timestamp: item.created_at ? new Date(item.created_at) : new Date(),
    };
    const aiMsg: Message = {
      id: `hist-a-${item.id}`,
      role: "assistant",
      content: item.answer,
      timestamp: item.created_at ? new Date(item.created_at) : new Date(),
      graphUsed: item.graph_used,
      confidence: item.confidence ? Math.round(item.confidence) : undefined,
      queryType: item.query_type,
      sources: [],
      chatLogId: item.id,
      feedback: item.feedback || null,
    };
    setMessages(prev => [...prev, userMsg, aiMsg]);
    setShowHistory(false);
  }, []);

  // Simulate streaming from server response
  async function streamContent(msgId: string, fullText: string) {
    const chunkSize = 4;
    let revealed = "";
    for (let i = 0; i < fullText.length; i += chunkSize) {
      revealed += fullText.slice(i, i + chunkSize);
      setMessages(prev =>
        prev.map(m => m.id === msgId ? { ...m, content: revealed, streaming: false } : m)
      );
      await new Promise(r => setTimeout(r, 10));
    }
  }

  function handleStop() {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }

  async function handleSend(questionOverride?: string) {
    const q = (questionOverride ?? input).trim();
    if (!q || loading) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: q,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setLoading(true);

    const aiId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, {
      id: aiId,
      role: "assistant",
      content: "",
      timestamp: new Date(),
      streaming: true,
    }]);

    // Create AbortController for this request
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const token = localStorage.getItem("accessToken");
      const headers: any = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch("/ask", {
        method: "POST",
        headers,
        body: JSON.stringify({ question: q, role }),
        signal: controller.signal,
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      setMessages(prev =>
        prev.map(m => m.id === aiId ? {
          ...m,
          content: "",
          streaming: false,
          graphUsed: data.graph_used,
          confidence: Math.round(data.confidence || 75),
          queryType: data.query_type || "fact",
          sources: data.sources || [],
          chatLogId: data.chat_log_id,
          feedback: null,
        } : m)
      );

      await streamContent(aiId, data.answer);
    } catch (err: any) {
      if (err?.name === "AbortError") {
        setMessages(prev =>
          prev.map(m => m.id === aiId ? {
            ...m,
            content: "_Response stopped by user._",
            streaming: false,
            confidence: 0,
          } : m)
        );
      } else {
        setMessages(prev =>
          prev.map(m => m.id === aiId ? {
            ...m,
            content: "**Error:** Could not reach the API. Please ensure the backend is running on port 8000.",
            streaming: false,
            confidence: 0,
          } : m)
        );
      }
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function clearHistory() {
    setMessages(prev => prev.slice(0, 1));
  }

  // Group history by date label
  const groupedHistory = (() => {
    const today = new Date(); today.setHours(0,0,0,0);
    const yesterday = new Date(today); yesterday.setDate(yesterday.getDate()-1);
    const groups: Record<string, any[]> = {};
    history.forEach(h => {
      const d = new Date(h.created_at);
      d.setHours(0,0,0,0);
      const label = d >= today ? "Today" : d >= yesterday ? "Yesterday" : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
      if (!groups[label]) groups[label] = [];
      groups[label].push(h);
    });
    return groups;
  })();

  return (
    <div className="flex h-full bg-gray-950 overflow-hidden">

      {/* ── Left history sidebar ── */}
      <div className="w-56 shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <p className="text-xs font-semibold text-gray-300 uppercase tracking-wider">History</p>
          <button onClick={clearHistory} title="Clear chat" className="p-1 hover:bg-gray-800 rounded text-gray-600 hover:text-gray-400 transition">
            <RefreshCw size={12} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {history.length === 0 ? (
            <p className="text-xs text-gray-600 px-4 py-3 italic">No history yet.</p>
          ) : (
            Object.entries(groupedHistory).map(([label, items]) => (
              <div key={label}>
                <p className="text-xs text-gray-600 uppercase tracking-wider px-4 pt-3 pb-1">{label}</p>
                {items.map(h => (
                  <button key={h.id} onClick={() => restoreHistoryItem(h)}
                    className="w-full text-left px-4 py-2 hover:bg-gray-800 transition group">
                    <p className="text-xs text-gray-300 truncate group-hover:text-white">{h.question}</p>
                    {h.confidence > 0 && (
                      <p className="text-xs text-brand-500 mt-0.5">{Math.round(h.confidence)}% confidence</p>
                    )}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
        <div className="px-4 py-3 border-t border-gray-800">
          <button onClick={() => { setMessages([{ id: "welcome", role: "assistant", content: welcomeMsg, timestamp: new Date(), graphUsed: false, confidence: 100, queryType: "greeting", sources: [] }]); setInput(""); }}
            className="w-full text-xs text-gray-500 hover:text-white bg-gray-800 hover:bg-gray-700 rounded-lg px-3 py-2 transition text-left">
            + New conversation
          </button>
        </div>
      </div>

      {/* ── Right chat pane ── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center justify-end px-4 py-2 border-b border-gray-800 shrink-0 bg-gray-900/50 gap-2">
          {isAdmin && <RoleSelector role={role} onChange={setRole} />}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto chat-scroll px-4 md:px-6 py-5 space-y-5">
          {messages.map(msg => (
            <MessageBubble key={msg.id} msg={msg} onCopy={copyText} onFeedback={submitFeedback} />
          ))}
          {copied && (
            <div className="fixed bottom-24 right-6 bg-gray-800 border border-gray-700 text-xs text-emerald-400 px-3 py-1.5 rounded-lg shadow flex items-center gap-1.5">
              <CheckCircle size={11} /> Copied!
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Suggestions */}
        {messages.length <= 1 && (
          <div className="px-6 pb-2 grid grid-cols-2 gap-2">
            {SUGGESTIONS.map(s => (
              <button key={s} onClick={() => handleSend(s)}
                className="text-left text-xs text-gray-400 hover:text-gray-200 bg-gray-900 hover:bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 transition">
                {s}
              </button>
            ))}
          </div>
        )}

        {/* Input */}
        <div className="shrink-0 px-4 md:px-6 py-4 border-t border-gray-800 bg-gray-900/30">
          <div className="flex gap-3 items-end max-w-4xl mx-auto">
            <div className="flex-1 relative">
              <textarea ref={textareaRef} value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask anything about your documents…"
                rows={1}
                className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-sm text-white placeholder-gray-500 resize-none focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/40 transition max-h-32 overflow-y-auto"
                style={{ minHeight: "46px" }}
                onInput={e => {
                  const t = e.currentTarget;
                  t.style.height = "auto";
                  t.style.height = `${Math.min(t.scrollHeight, 128)}px`;
                }}
              />
            </div>
            {loading ? (
              <button onClick={handleStop}
                className="bg-red-600 hover:bg-red-500 text-white rounded-xl p-3 transition shrink-0 shadow-lg shadow-red-600/20"
                title="Stop generating">
                <Square size={18} />
              </button>
            ) : (
              <button onClick={() => handleSend()} disabled={!input.trim()}
                className="bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl p-3 transition shrink-0 shadow-lg shadow-brand-600/20">
                <Send size={18} />
              </button>
            )}
          </div>
          <p className="text-xs text-gray-600 text-center mt-2">
            {isAdmin
              ? <>Role: <span className="text-red-400 capitalize">{role}</span> · Full retrieval · Enter to send</>
              : <>Summarized responses · Enter to send · Shift+Enter for new line</>}
          </p>
        </div>
      </div>
    </div>
  );
}
