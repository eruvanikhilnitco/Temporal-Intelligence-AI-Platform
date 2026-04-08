import { useState, useCallback, useRef } from "react";
import {
  Upload, FileText, CheckCircle, AlertCircle, Loader2, X,
  GitBranch, Brain, Database, ChevronDown, ChevronUp, Link2,
  Cloud, FolderOpen, Play, RefreshCw, Folder
} from "lucide-react";
import axios from "axios";

interface UploadedFile {
  name: string;
  size: number;
  status: "uploading" | "success" | "queued" | "done" | "error" | "unchanged";
  message?: string;
  jobId?: string;
  entities?: {
    contracts: string[];
    dates: string[];
    amounts: string[];
    organizations: string[];
  };
}

const ALLOWED = [".pdf", ".xml", ".txt", ".docx", ".json", ".csv", ".html", ".pptx", ".md"];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function KnowledgeGraphPipeline({ entities }: { entities: UploadedFile["entities"] }) {
  const [open, setOpen] = useState(false);
  if (!entities) return null;
  const hasAny = Object.values(entities).some(a => a.length > 0);
  return (
    <div className="mt-3 border-t border-gray-700 pt-3">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2 text-xs text-gray-400 hover:text-gray-200 transition">
        <GitBranch size={12} className="text-emerald-400" />
        Knowledge Graph Pipeline
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          <div className="flex items-center gap-2 text-xs text-gray-400 flex-wrap">
            {["NER Extraction", "Relationship Mapping", "Graph Storage (SQLite)", "Vector Chunk Linking"].map((step, i) => (
              <span key={step} className="flex items-center gap-1">
                <span className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2 py-0.5 rounded-full">{step}</span>
                {i < 3 && <span className="text-gray-600">→</span>}
              </span>
            ))}
          </div>
          {hasAny ? (
            <div className="grid grid-cols-2 gap-2 mt-2">
              {Object.entries(entities).map(([key, vals]) =>
                vals.length > 0 ? (
                  <div key={key} className="bg-gray-900 rounded-lg px-3 py-2">
                    <p className="text-xs text-gray-500 capitalize mb-1">{key}</p>
                    {vals.slice(0, 3).map(v => (
                      <p key={v} className="text-xs text-gray-300 truncate">• {v}</p>
                    ))}
                    {vals.length > 3 && <p className="text-xs text-gray-500">+{vals.length - 3} more</p>}
                  </div>
                ) : null
              )}
            </div>
          ) : (
            <p className="text-xs text-gray-500 mt-1">No structured entities found in this document.</p>
          )}
        </div>
      )}
    </div>
  );
}

function FileCard({ file, onRemove }: { file: UploadedFile; onRemove: () => void }) {
  const isQueued = file.status === "queued";
  const isDone = file.status === "done" || file.status === "success";
  const isUnchanged = file.status === "unchanged";

  const borderColor = isUnchanged
    ? "border-yellow-600/40"
    : file.status === "error" ? "border-red-600/40"
    : isDone ? "border-emerald-600/30"
    : "border-gray-700";

  return (
    <div className={`bg-gray-800 border rounded-xl p-4 ${borderColor}`}>
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 bg-gray-700 rounded-lg flex items-center justify-center shrink-0">
          <FileText size={16} className="text-gray-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm text-white font-medium truncate">{file.name}</p>
            <div className="flex items-center gap-2 shrink-0">
              {file.status === "uploading" && <Loader2 size={14} className="text-brand-400 animate-spin" />}
              {isQueued && <RefreshCw size={14} className="text-yellow-400 animate-spin" />}
              {isDone && <CheckCircle size={14} className="text-emerald-400" />}
              {isUnchanged && <CheckCircle size={14} className="text-yellow-400" />}
              {file.status === "error" && <AlertCircle size={14} className="text-red-400" />}
              <button onClick={onRemove} className="text-gray-500 hover:text-gray-300 transition"><X size={14} /></button>
            </div>
          </div>
          <p className="text-xs text-gray-500">{formatBytes(file.size)}</p>

          {file.status === "uploading" && (
            <div className="mt-2">
              <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
                <div className="h-1 bg-brand-500 rounded-full animate-pulse w-3/4" />
              </div>
              <p className="text-xs text-gray-400 mt-1">Uploading…</p>
            </div>
          )}

          {isQueued && (
            <div className="mt-2">
              <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
                <div className="h-1 bg-yellow-500 rounded-full w-full animate-pulse" />
              </div>
              <p className="text-xs text-yellow-400 mt-1 flex items-center gap-1">
                <RefreshCw size={10} className="animate-spin" />
                Processing — embedding and building knowledge graph…
              </p>
            </div>
          )}

          {isDone && (
            <p className="text-xs text-emerald-400 mt-1">✓ Ready — you can now search this document</p>
          )}

          {isUnchanged && (
            <p className="text-xs text-yellow-400 mt-1">⟳ No changes detected — skipped re-processing</p>
          )}

          {file.status === "error" && file.message && (
            <p className="text-xs text-red-400 mt-1">{file.message}</p>
          )}

          {(isDone || isQueued) && <KnowledgeGraphPipeline entities={file.entities} />}
        </div>
      </div>
    </div>
  );
}

// ── Ingest Queue Status ───────────────────────────────────────────────────────
function IngestQueueStatus() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem("accessToken");
      const res = await axios.get("/upload/status/all", {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      setJobs(Array.isArray(res.data) ? res.data : []);
    } catch { setJobs([]); }
    finally { setLoading(false); }
  };

  const statusColor: Record<string, string> = {
    done: "text-emerald-400",
    processing: "text-yellow-400",
    queued: "text-blue-400",
    error: "text-red-400",
  };

  return (
    <div className="bg-gray-800/60 border border-gray-700 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-semibold text-white flex items-center gap-2">
          <RefreshCw size={14} className="text-brand-400" /> Background Ingest Queue
        </p>
        <button onClick={load} disabled={loading}
          className="text-xs text-gray-400 hover:text-white flex items-center gap-1 transition">
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>
      {jobs.length === 0 ? (
        <p className="text-xs text-gray-500">No recent ingest jobs. Upload a file to see queue activity.</p>
      ) : (
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {jobs.map((j: any) => (
            <div key={j.job_id} className="flex items-center gap-3 text-xs">
              <span className={`font-medium shrink-0 w-16 ${statusColor[j.status] || "text-gray-400"}`}>{j.status}</span>
              <span className="text-gray-300 flex-1 truncate font-mono">{j.file?.split("/").pop() || j.file}</span>
              {j.elapsed_s && <span className="text-gray-500 shrink-0">{j.elapsed_s}s</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── SharePoint Connector ───────────────────────────────────────────────────────
function SharePointConnector() {
  const [form, setForm] = useState({ site_url: "", username: "", password: "", library_path: "Shared Documents" });
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [log, setLog] = useState<string[]>([]);

  const field = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm(p => ({ ...p, [k]: e.target.value }));

  async function connect() {
    if (!form.site_url || !form.username || !form.password) {
      setError("Site URL, username and password are required.");
      return;
    }
    setError("");
    setResult(null);
    setLog([]);
    setRunning(true);
    setLog(["Connecting to SharePoint…"]);

    try {
      const token = localStorage.getItem("accessToken");
      setLog(prev => [...prev, `Authenticating as ${form.username}…`]);
      setLog(prev => [...prev, `Traversing library: ${form.library_path} (recursive)…`]);

      const res = await axios.post("/admin/sharepoint/ingest", form, {
        headers: { Authorization: `Bearer ${token}` },
      });

      setLog(prev => [...prev, `Ingestion complete.`]);
      setResult(res.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Connection failed. Check credentials and site URL.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-white">SharePoint Connector</h2>
        <p className="text-sm text-gray-400 mt-1">
          Connect to your SharePoint site and recursively ingest all documents from a library — including nested folders at any depth.
        </p>
      </div>

      {/* Connection form */}
      <div className="bg-gray-800 border border-gray-700 rounded-xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Cloud size={16} className="text-brand-400" />
          <p className="text-sm font-semibold text-white">SharePoint Connection</p>
        </div>

        <div className="grid gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">SharePoint Site URL</label>
            <input value={form.site_url} onChange={field("site_url")}
              placeholder="https://yourcompany.sharepoint.com/sites/YourSite"
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand-500 transition" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">Username / Email</label>
              <input value={form.username} onChange={field("username")}
                placeholder="user@company.com"
                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand-500 transition" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">Password</label>
              <input type="password" value={form.password} onChange={field("password")}
                placeholder="••••••••"
                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand-500 transition" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Document Library Path</label>
            <input value={form.library_path} onChange={field("library_path")}
              placeholder="Shared Documents"
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand-500 transition" />
            <p className="text-xs text-gray-500 mt-1">e.g. "Shared Documents" or "Shared Documents/Contracts/2024"</p>
          </div>
        </div>

        {error && (
          <div className="flex gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
            <AlertCircle size={15} className="shrink-0 mt-0.5" /> {error}
          </div>
        )}

        <button onClick={connect} disabled={running}
          className="w-full flex items-center justify-center gap-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white font-semibold py-2.5 rounded-lg transition text-sm">
          {running ? <><Loader2 size={15} className="animate-spin" /> Ingesting…</> : <><Play size={15} /> Connect & Ingest All Files</>}
        </button>
      </div>

      {/* Live log */}
      {log.length > 0 && (
        <div className="bg-gray-900 border border-gray-700 rounded-xl p-4">
          <p className="text-xs font-medium text-gray-400 mb-2 flex items-center gap-1.5">
            <RefreshCw size={11} className={running ? "animate-spin text-brand-400" : "text-gray-500"} /> Ingestion Log
          </p>
          <div className="space-y-1">
            {log.map((l, i) => (
              <p key={i} className="text-xs text-gray-300 font-mono">› {l}</p>
            ))}
          </div>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className={`border rounded-xl p-5 ${result.errors === 0 ? "bg-emerald-500/5 border-emerald-500/20" : "bg-yellow-500/5 border-yellow-500/20"}`}>
          <div className="flex items-center gap-2 mb-3">
            {result.errors === 0
              ? <CheckCircle size={16} className="text-emerald-400" />
              : <AlertCircle size={16} className="text-yellow-400" />}
            <p className="text-sm font-semibold text-white">Ingestion Complete</p>
          </div>
          <div className="grid grid-cols-2 gap-3 mb-3 text-sm">
            <div className="bg-gray-800 rounded-lg px-3 py-2 text-center">
              <p className="text-2xl font-bold text-emerald-400">{result.ingested}</p>
              <p className="text-xs text-gray-400">Files Ingested</p>
            </div>
            <div className="bg-gray-800 rounded-lg px-3 py-2 text-center">
              <p className="text-2xl font-bold text-red-400">{result.errors}</p>
              <p className="text-xs text-gray-400">Errors</p>
            </div>
          </div>
          {result.files?.length > 0 && (
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {result.files.map((f: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs text-gray-300">
                  <CheckCircle size={10} className="text-emerald-400 shrink-0" />
                  <span className="truncate">{f.file}</span>
                </div>
              ))}
            </div>
          )}
          {result.error_details?.length > 0 && (
            <div className="mt-3 space-y-1">
              <p className="text-xs font-medium text-red-400">Errors:</p>
              {result.error_details.map((e: any, i: number) => (
                <div key={i} className="text-xs text-gray-400">
                  <span className="text-red-400">✗</span> {e.file}: {e.error}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Recursive traversal info */}
      <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
        <p className="text-xs font-medium text-gray-300 mb-3 flex items-center gap-1.5">
          <FolderOpen size={13} className="text-brand-400" /> Recursive Traversal — How It Works
        </p>
        <div className="space-y-1.5 text-xs text-gray-400">
          {[
            "Authenticates with SharePoint using your credentials",
            "Lists all files in the root library folder",
            "Recursively traverses every subfolder at any depth",
            "Downloads each file and runs it through the ingestion pipeline",
            "Embeds chunks into Qdrant vector store",
            "Extracts entities and builds knowledge graph (SQLite / Neo4j)",
          ].map((s, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-brand-400 font-bold shrink-0">{i + 1}.</span> {s}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Folder Upload Component ───────────────────────────────────────────────────
interface FolderFileResult {
  path: string;
  name: string;
  status: "pending" | "uploading" | "success" | "error" | "skipped";
  message?: string;
}

function FolderUpload() {
  const [results, setResults] = useState<FolderFileResult[]>([]);
  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<{ success: number; errors: number; skipped: number } | null>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  async function handleFolderSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;

    const allFiles = Array.from(fileList);

    // Build display list
    const initial: FolderFileResult[] = allFiles.map(f => ({
      path: (f as any).webkitRelativePath || f.name,
      name: f.name,
      status: "pending",
    }));
    setResults(initial);
    setSummary(null);
    setRunning(true);

    try {
      const token = localStorage.getItem("accessToken");
      const formData = new FormData();

      // Use webkitRelativePath as the filename so the server preserves folder structure
      for (const file of allFiles) {
        const relativePath = (file as any).webkitRelativePath || file.name;
        // Create a new File with the relative path as name so server can reconstruct
        const renamedFile = new File([file], relativePath, { type: file.type });
        formData.append("files", renamedFile);
      }

      // Mark all as uploading
      setResults(prev => prev.map(r => ({ ...r, status: "uploading" })));

      const res = await axios.post("/upload/batch", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });

      const data = res.data;
      const fileResults: FolderFileResult[] = (data.files || []).map((f: any) => ({
        path: f.filename,
        name: f.filename.split("/").pop() || f.filename,
        status: f.status as FolderFileResult["status"],
        message: f.message,
      }));

      setResults(fileResults);
      setSummary({ success: data.success, errors: data.errors, skipped: data.skipped });
    } catch (err: any) {
      setResults(prev => prev.map(r => ({
        ...r,
        status: "error",
        message: err.response?.data?.detail || "Upload failed",
      })));
    } finally {
      setRunning(false);
      // Reset input so the same folder can be re-selected
      if (folderInputRef.current) folderInputRef.current.value = "";
    }
  }

  const statusIcon = (status: FolderFileResult["status"]) => {
    if (status === "uploading") return <Loader2 size={13} className="text-brand-400 animate-spin" />;
    if (status === "success")   return <CheckCircle size={13} className="text-emerald-400" />;
    if (status === "error")     return <AlertCircle size={13} className="text-red-400" />;
    if (status === "skipped")   return <AlertCircle size={13} className="text-yellow-400" />;
    return <div className="w-3 h-3 rounded-full border border-gray-600" />;
  };

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-bold text-white">Folder Upload</h2>
        <p className="text-sm text-gray-400 mt-1">
          Select a folder (including nested sub-folders) — all supported documents inside will be
          ingested automatically into the vector store and knowledge graph.
        </p>
      </div>

      {/* Drop zone / button */}
      <div
        onClick={() => folderInputRef.current?.click()}
        className="relative border-2 border-dashed border-gray-700 hover:border-brand-500 hover:bg-brand-600/5 rounded-2xl p-12 text-center transition cursor-pointer"
      >
        <Folder size={40} className="mx-auto mb-4 text-gray-500" />
        <p className="text-base font-medium text-white mb-1">Click to select a folder</p>
        <p className="text-sm text-gray-400 mb-3">All files in nested sub-folders are included</p>
        <div className="flex flex-wrap justify-center gap-2">
          {ALLOWED.map(ext => (
            <span key={ext} className="text-xs bg-gray-800 border border-gray-700 text-gray-400 px-2 py-0.5 rounded-full">{ext}</span>
          ))}
        </div>
        {/* webkitdirectory allows folder selection with full recursive file list */}
        <input
          ref={folderInputRef}
          type="file"
          className="hidden"
          multiple
          // @ts-ignore — webkitdirectory is not in standard types but works in all browsers
          webkitdirectory=""
          onChange={handleFolderSelect}
        />
      </div>

      {/* How it works */}
      <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
        <p className="text-xs font-medium text-gray-300 mb-3 flex items-center gap-1.5">
          <FolderOpen size={13} className="text-brand-400" /> How Folder Upload Works
        </p>
        <div className="space-y-1.5 text-xs text-gray-400">
          {[
            "Select any folder — the browser reads the entire tree recursively",
            "All supported file types are detected and uploaded",
            "Unsupported files (.exe, .zip, etc.) are automatically skipped",
            "Each file is embedded into Qdrant and added to the knowledge graph (SQLite)",
            "Cross-document relationships are automatically detected and linked",
            "Folder structure is preserved in file naming for traceability",
          ].map((s, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-brand-400 font-bold shrink-0">{i + 1}.</span> {s}
            </div>
          ))}
        </div>
      </div>

      {/* Summary */}
      {summary && (
        <div className={`border rounded-xl p-4 ${summary.errors === 0 ? "bg-emerald-500/5 border-emerald-500/20" : "bg-yellow-500/5 border-yellow-500/20"}`}>
          <p className="text-sm font-semibold text-white mb-3">Upload Complete</p>
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="bg-gray-800 rounded-lg px-3 py-2">
              <p className="text-xl font-bold text-emerald-400">{summary.success}</p>
              <p className="text-xs text-gray-400">Ingested</p>
            </div>
            <div className="bg-gray-800 rounded-lg px-3 py-2">
              <p className="text-xl font-bold text-yellow-400">{summary.skipped}</p>
              <p className="text-xs text-gray-400">Skipped</p>
            </div>
            <div className="bg-gray-800 rounded-lg px-3 py-2">
              <p className="text-xl font-bold text-red-400">{summary.errors}</p>
              <p className="text-xs text-gray-400">Errors</p>
            </div>
          </div>
        </div>
      )}

      {/* File list */}
      {results.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-gray-400">{results.length} file{results.length !== 1 ? "s" : ""} detected</p>
          <div className="max-h-72 overflow-y-auto space-y-1 pr-1">
            {results.map((r, i) => (
              <div key={i} className="flex items-center gap-3 bg-gray-800/60 border border-gray-700 rounded-lg px-3 py-2">
                <div className="shrink-0">{statusIcon(r.status)}</div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-white truncate font-mono">{r.path}</p>
                  {r.message && (
                    <p className={`text-xs mt-0.5 ${r.status === "success" ? "text-emerald-400" : r.status === "skipped" ? "text-yellow-400" : "text-red-400"}`}>
                      {r.message}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function DocumentUpload() {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const [activeTab, setActiveTab] = useState<"files" | "folder" | "sharepoint" | "etl">("files");

  const pollJob = useCallback((name: string, jobId: string) => {
    const token = localStorage.getItem("accessToken");
    const interval = setInterval(async () => {
      try {
        const res = await axios.get(`/upload/status/${jobId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        const s = res.data.status;
        if (s === "done" || s === "error") {
          clearInterval(interval);
          setFiles(prev => prev.map(f =>
            f.name === name ? {
              ...f,
              status: s === "done" ? "done" : "error",
              message: s === "done" ? "✓ Ingested and ready to search" : (res.data.error || "Ingestion failed"),
            } : f
          ));
        }
      } catch { clearInterval(interval); }
    }, 3000);
    // Stop polling after 3 minutes max
    setTimeout(() => clearInterval(interval), 180_000);
  }, []);

  const processFile = useCallback(async (file: File) => {
    const entry: UploadedFile = { name: file.name, size: file.size, status: "uploading" };
    setFiles(prev => [...prev, entry]);

    try {
      const token = localStorage.getItem("accessToken");
      const form = new FormData();
      form.append("file", file);
      const res = await axios.post("/upload", form, {
        headers: {
          "Content-Type": "multipart/form-data",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      const apiStatus = res.data.status;
      const jobId = res.data.message?.match(/job: ([a-f0-9-]+)/)?.[1];
      const newStatus: UploadedFile["status"] =
        apiStatus === "queued" ? "queued"
        : apiStatus === "unchanged" ? "unchanged"
        : apiStatus === "success" ? "done"
        : "error";

      setFiles(prev => prev.map(f =>
        f.name === file.name ? {
          ...f,
          status: newStatus,
          message: res.data.message,
          jobId,
          entities: res.data.entities,
        } : f
      ));

      // Auto-poll if queued
      if (newStatus === "queued" && jobId) {
        pollJob(file.name, jobId);
      }
    } catch (err: any) {
      setFiles(prev => prev.map(f =>
        f.name === file.name ? { ...f, status: "error", message: err.response?.data?.detail || "Upload failed." } : f
      ));
    }
  }, [pollJob]);

  function handleFiles(list: FileList | null) {
    if (!list) return;
    Array.from(list).forEach(f => {
      const ext = "." + f.name.split(".").pop()?.toLowerCase();
      if (ALLOWED.includes(ext)) processFile(f);
    });
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-800 px-6 pt-1 shrink-0">
        {[
          { id: "files", label: "Local Files" },
          { id: "folder", label: "Folder Upload" },
          { id: "sharepoint", label: "SharePoint" },
          { id: "etl", label: "ETL Pipeline" },
        ].map(({ id, label }) => (
          <button key={id} onClick={() => setActiveTab(id as any)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition -mb-px ${
              activeTab === id ? "border-brand-500 text-brand-300" : "border-transparent text-gray-400 hover:text-white"
            }`}>
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* ── LOCAL FILES ── */}
        {activeTab === "files" && (
          <>
            <div>
              <h2 className="text-lg font-bold text-white">Document Upload</h2>
              <p className="text-sm text-gray-400 mt-1">
                Supports PDF, XML, DOCX, TXT, JSON, CSV, HTML, PPTX, MD · Each file is embedded into Qdrant and the knowledge graph is auto-built. Use the Folder Upload tab to upload entire directory trees.
              </p>
            </div>

            <div
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => document.getElementById("file-input")?.click()}
              className={`relative border-2 border-dashed rounded-2xl p-12 text-center transition cursor-pointer ${
                dragging ? "border-brand-500 bg-brand-600/10" : "border-gray-700 hover:border-gray-600 hover:bg-gray-900/50"
              }`}
            >
              <Upload size={40} className={`mx-auto mb-4 transition ${dragging ? "text-brand-400" : "text-gray-500"}`} />
              <p className="text-base font-medium text-white mb-1">{dragging ? "Release to upload" : "Drag & drop your documents"}</p>
              <p className="text-sm text-gray-400 mb-3">or click to browse</p>
              <div className="flex flex-wrap justify-center gap-2">
                {ALLOWED.map(ext => (
                  <span key={ext} className="text-xs bg-gray-800 border border-gray-700 text-gray-400 px-2 py-0.5 rounded-full">{ext}</span>
                ))}
              </div>
              <input id="file-input" type="file" className="hidden" multiple accept={ALLOWED.join(",")}
                onChange={e => handleFiles(e.target.files)} />
            </div>

            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-medium text-gray-300">Document Processing Pipeline</p>
                <span className="text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">Async / Non-blocking</span>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {[
                  { icon: Upload, label: "Queue", color: "text-brand-400" },
                  { icon: FileText, label: "Parse & Chunk", color: "text-blue-400" },
                  { icon: Brain, label: "Embed (BAAI 1024d)", color: "text-violet-400" },
                  { icon: Database, label: "Qdrant Store", color: "text-blue-400" },
                  { icon: GitBranch, label: "NER + Graph", color: "text-emerald-400" },
                  { icon: CheckCircle, label: "Searchable", color: "text-emerald-400" },
                ].map(({ icon: Icon, label, color }, i, arr) => (
                  <span key={label} className="flex items-center gap-2">
                    <span className="flex items-center gap-1.5 text-xs text-gray-300">
                      <Icon size={13} className={color} /> {label}
                    </span>
                    {i < arr.length - 1 && <span className="text-gray-600 text-xs">→</span>}
                  </span>
                ))}
              </div>
            </div>

            {files.length > 0 && (
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <p className="text-sm font-medium text-gray-300">{files.length} file{files.length > 1 ? "s" : ""}</p>
                  <button onClick={() => setFiles([])} className="text-xs text-gray-500 hover:text-gray-300">Clear all</button>
                </div>
                {files.map((f, i) => (
                  <FileCard key={f.name + i} file={f} onRemove={() => setFiles(prev => prev.filter((_, j) => j !== i))} />
                ))}
              </div>
            )}
          </>
        )}

        {/* ── FOLDER UPLOAD ── */}
        {activeTab === "folder" && <FolderUpload />}

        {/* ── SHAREPOINT ── */}
        {activeTab === "sharepoint" && <SharePointConnector />}

        {/* ── ETL PIPELINE ── */}
        {activeTab === "etl" && (
          <>
            <div>
              <h2 className="text-lg font-bold text-white">ETL Pipeline</h2>
              <p className="text-sm text-gray-400 mt-1">
                Full document ingestion pipeline — from raw file to searchable vector + knowledge graph.
                All steps run asynchronously in the background after upload.
              </p>
            </div>

            {/* Architecture overview badge row */}
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: "Vector Store", value: "Qdrant", color: "text-blue-400 bg-blue-500/10 border-blue-500/20" },
                { label: "Graph DB", value: "SQLite (Neo4j fallback)", color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
                { label: "LLM", value: "Cohere command-r7b", color: "text-yellow-400 bg-yellow-500/10 border-yellow-500/20" },
              ].map(({ label, value, color }) => (
                <div key={label} className={`border rounded-xl p-3 text-center ${color}`}>
                  <p className="text-xs font-bold">{value}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{label}</p>
                </div>
              ))}
            </div>

            <div className="space-y-4">
              {[
                {
                  step: "1", icon: Upload, title: "Async File Ingest Queue",
                  desc: "Files are accepted instantly and queued for background processing. The upload returns immediately — no waiting for ingestion.",
                  badge: "Non-blocking",
                },
                {
                  step: "2", icon: FileText, title: "Parse & Chunk",
                  desc: "Documents are parsed (PDF, DOCX, TXT, CSV, JSON, HTML, PPTX, XML, MD) and split into semantic chunks of ~512 tokens with overlap.",
                  badge: "Active",
                },
                {
                  step: "3", icon: Brain, title: "Embedding (BAAI/bge-large-en-v1.5)",
                  desc: "Each chunk is embedded using a 1024-dim sentence transformer model. Batch embedding via batch_embed() for 10x throughput.",
                  badge: "Active",
                },
                {
                  step: "4", icon: Database, title: "Vector Store — Qdrant",
                  desc: "Embeddings with metadata (filename, access_roles, document_type) are upserted into Qdrant collections for cosine similarity search.",
                  badge: "Active",
                },
                {
                  step: "5", icon: Brain, title: "NER — Named Entity Recognition",
                  desc: "spaCy extracts PERSON, ORG, DATE, MONEY, and CONTRACT entities. Cohere LLM classifies document type and sensitivity.",
                  badge: "Active",
                },
                {
                  step: "6", icon: Link2, title: "Relationship Extraction",
                  desc: "Regex + pattern rules detect relationships: CONTRACT→issued_by→ORG, DOCUMENT→starts_on→DATE, PARTY→signs→CONTRACT.",
                  badge: "Active",
                },
                {
                  step: "7", icon: GitBranch, title: "Graph Storage — SQLite / Neo4j",
                  desc: "Entities and relationships stored in SQLite graph DB (primary). Neo4j used automatically when available at bolt://localhost:7687.",
                  badge: "Active",
                },
                {
                  step: "8", icon: CheckCircle, title: "Cache Warm & Ready",
                  desc: "After ingestion, the in-memory TTL cache is primed. Subsequent identical queries are answered instantly from cache.",
                  badge: "Active",
                },
              ].map(({ step, icon: Icon, title, desc, badge }) => (
                <div key={step} className="flex gap-4">
                  <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 bg-brand-600/20 text-brand-300 border border-brand-500/30">{step}</div>
                  <div className="flex-1 pb-4 border-b border-gray-800 last:border-0">
                    <div className="flex items-center gap-2 mb-1">
                      <Icon size={15} className="text-brand-400" />
                      <p className="text-sm font-medium text-white">{title}</p>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">{badge}</span>
                    </div>
                    <p className="text-xs text-gray-400 leading-relaxed">{desc}</p>
                  </div>
                </div>
              ))}
            </div>

            {/* Ingest queue status */}
            <IngestQueueStatus />
          </>
        )}
      </div>
    </div>
  );
}
