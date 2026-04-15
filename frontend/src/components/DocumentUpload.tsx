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

// ── SharePoint File Browser ───────────────────────────────────────────────────
const SUPPORTED_EXTS = new Set([".pdf",".xml",".txt",".docx",".json",".csv",".html",".pptx",".md"]);

function fileIcon(ext: string): string {
  if (ext === ".pdf") return "📄";
  if ([".docx",".doc"].includes(ext)) return "📝";
  if ([".xlsx",".csv"].includes(ext)) return "📊";
  if (ext === ".pptx") return "📑";
  if (ext === ".txt" || ext === ".md") return "📃";
  return "📎";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes/1024).toFixed(0)}KB`;
  return `${(bytes/(1024*1024)).toFixed(1)}MB`;
}

interface SPItem {
  id: string;
  name: string;
  type: "file" | "folder";
  ext?: string;
  size?: number;
  modified?: string;
  child_count?: number;
  downloadUrl?: string;
  children?: SPItem[] | null; // null = not loaded, [] = empty
  loading?: boolean;
}

function FolderNode({
  item,
  depth,
  siteUrl,
  libraryName,
  selectedIds,
  onToggleFile,
  onSelectFolder,
  onLoadChildren,
}: {
  item: SPItem;
  depth: number;
  siteUrl: string;
  libraryName: string;
  selectedIds: Set<string>;
  onToggleFile: (item: SPItem) => void;
  onSelectFolder: (item: SPItem) => void;
  onLoadChildren: (item: SPItem) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  function handleFolderClick() {
    const next = !expanded;
    setExpanded(next);
    if (next && item.children === null) {
      onLoadChildren(item);
    }
  }

  const indent = depth * 16;

  if (item.type === "folder") {
    return (
      <div>
        <div
          className="flex items-center gap-2 py-1.5 px-2 hover:bg-white/5 rounded-lg cursor-pointer group"
          style={{ paddingLeft: `${8 + indent}px` }}
        >
          <button onClick={handleFolderClick} className="flex items-center gap-2 flex-1 min-w-0">
            <span className="text-sm shrink-0">{expanded ? "📂" : "📁"}</span>
            <span className="text-sm text-gray-200 truncate flex-1 text-left">{item.name}</span>
            {item.child_count !== undefined && (
              <span className="text-xs text-gray-600 shrink-0">{item.child_count} items</span>
            )}
            {item.loading && <Loader2 size={11} className="animate-spin text-brand-400 shrink-0" />}
          </button>
          {/* "Ingest folder" button */}
          <button
            onClick={(e) => { e.stopPropagation(); onSelectFolder(item); }}
            className="text-xs text-brand-400 hover:text-brand-300 border border-brand-500/30 hover:border-brand-400/50 px-2 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-all shrink-0"
            title="Ingest entire folder"
          >
            Upload folder
          </button>
        </div>
        {expanded && item.children && (
          <div>
            {item.children.length === 0 ? (
              <p className="text-xs text-gray-600 italic py-1" style={{ paddingLeft: `${24 + indent}px` }}>Empty folder</p>
            ) : (
              item.children.map(child => (
                <FolderNode
                  key={child.id}
                  item={child}
                  depth={depth + 1}
                  siteUrl={siteUrl}
                  libraryName={libraryName}
                  selectedIds={selectedIds}
                  onToggleFile={onToggleFile}
                  onSelectFolder={onSelectFolder}
                  onLoadChildren={onLoadChildren}
                />
              ))
            )}
          </div>
        )}
      </div>
    );
  }

  // File row
  const supported = SUPPORTED_EXTS.has(item.ext || "");
  const checked = selectedIds.has(item.id);
  return (
    <div
      className={`flex items-center gap-2 py-1.5 px-2 rounded-lg ${supported ? "hover:bg-white/5 cursor-pointer" : "opacity-40 cursor-not-allowed"} ${checked ? "bg-brand-600/10 border border-brand-500/20" : ""}`}
      style={{ paddingLeft: `${8 + indent}px` }}
      onClick={() => supported && onToggleFile(item)}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={!supported}
        onChange={() => supported && onToggleFile(item)}
        onClick={e => e.stopPropagation()}
        className="w-3.5 h-3.5 accent-brand-500 shrink-0 cursor-pointer"
      />
      <span className="text-sm shrink-0">{fileIcon(item.ext || "")}</span>
      <span className="text-sm text-gray-200 truncate flex-1">{item.name}</span>
      {item.size !== undefined && (
        <span className="text-xs text-gray-600 shrink-0">{formatSize(item.size)}</span>
      )}
      {!supported && (
        <span className="text-xs text-gray-600 shrink-0">unsupported</span>
      )}
    </div>
  );
}

// ── SharePoint Connector ──────────────────────────────────────────────────────
function SharePointConnector({ onNavigateToAdmin }: { onNavigateToAdmin?: () => void }) {
  const [siteUrl, setSiteUrl] = useState("");
  const [connected, setConnected] = useState(false);
  const [siteDisplayName, setSiteDisplayName] = useState("");
  const [libraries, setLibraries] = useState<{ id: string; name: string }[]>([]);
  const [selectedLibrary, setSelectedLibrary] = useState("Shared Documents");
  const [testing, setTesting] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [treeItems, setTreeItems] = useState<SPItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectedItems, setSelectedItems] = useState<SPItem[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");

  const authHeaders = () => ({
    Authorization: `Bearer ${localStorage.getItem("accessToken")}`,
  });

  async function testConnection() {
    if (!siteUrl.trim()) { setError("SharePoint Site URL is required."); return; }
    setError(""); setConnected(false); setLibraries([]); setTreeItems([]); setTesting(true);
    try {
      const res = await axios.post("/admin/sharepoint/test",
        { site_url: siteUrl, library_name: selectedLibrary },
        { headers: authHeaders() }
      );
      setSiteDisplayName(res.data.site_display_name || siteUrl);
      const libs = res.data.libraries || [];
      setLibraries(libs);
      if (libs.length > 0) setSelectedLibrary(libs[0].name);
      setConnected(true);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Connection failed. Check your Site URL and .env credentials.");
    } finally {
      setTesting(false);
    }
  }

  async function browseRoot(library?: string) {
    setBrowsing(true); setError(""); setTreeItems([]);
    const lib = library || selectedLibrary;
    try {
      const res = await axios.post("/admin/sharepoint/browse",
        { site_url: siteUrl, library_name: lib },
        { headers: authHeaders() }
      );
      setTreeItems((res.data.items || []).map((it: any) => ({
        ...it,
        children: it.type === "folder" ? null : undefined,
      })));
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to browse files.");
    } finally {
      setBrowsing(false);
    }
  }

  async function loadChildren(item: SPItem) {
    // Mark as loading
    setTreeItems(prev => markLoading(prev, item.id, true));
    try {
      const res = await axios.post("/admin/sharepoint/browse",
        { site_url: siteUrl, library_name: selectedLibrary, item_id: item.id },
        { headers: authHeaders() }
      );
      const children: SPItem[] = (res.data.items || []).map((it: any) => ({
        ...it,
        children: it.type === "folder" ? null : undefined,
      }));
      setTreeItems(prev => insertChildren(prev, item.id, children));
    } catch (err: any) {
      setError(`Failed to load folder "${item.name}": ${err.response?.data?.detail || err.message}`);
      setTreeItems(prev => markLoading(prev, item.id, false));
    }
  }

  function markLoading(items: SPItem[], id: string, loading: boolean): SPItem[] {
    return items.map(it => {
      if (it.id === id) return { ...it, loading };
      if (it.children) return { ...it, children: markLoading(it.children, id, loading) };
      return it;
    });
  }

  function insertChildren(items: SPItem[], parentId: string, children: SPItem[]): SPItem[] {
    return items.map(it => {
      if (it.id === parentId) return { ...it, children, loading: false };
      if (it.children) return { ...it, children: insertChildren(it.children, parentId, children) };
      return it;
    });
  }

  function toggleFile(item: SPItem) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(item.id)) next.delete(item.id);
      else next.add(item.id);
      return next;
    });
    setSelectedItems(prev => {
      if (prev.find(x => x.id === item.id)) return prev.filter(x => x.id !== item.id);
      return [...prev, item];
    });
    setResult(null);
  }

  // Collect all files recursively from a subtree
  function collectFiles(items: SPItem[]): SPItem[] {
    const files: SPItem[] = [];
    for (const it of items) {
      if (it.type === "file" && SUPPORTED_EXTS.has(it.ext || "")) files.push(it);
      if (it.children) files.push(...collectFiles(it.children));
    }
    return files;
  }

  async function selectFolderForIngest(folder: SPItem) {
    // Load all children recursively (up to 2 levels) and select all files
    let items = folder.children;
    if (!items) {
      try {
        const res = await axios.post("/admin/sharepoint/browse",
          { site_url: siteUrl, library_name: selectedLibrary, item_id: folder.id },
          { headers: authHeaders() }
        );
        items = (res.data.items || []).map((it: any) => ({
          ...it, children: it.type === "folder" ? null : undefined,
        }));
        setTreeItems(prev => insertChildren(prev, folder.id, items!));
      } catch { return; }
    }
    const files = collectFiles(items || []);
    setSelectedIds(prev => { const n = new Set(prev); files.forEach(f => n.add(f.id)); return n; });
    setSelectedItems(prev => {
      const existing = new Set(prev.map(x => x.id));
      return [...prev, ...files.filter(f => !existing.has(f.id))];
    });
  }

  async function ingestSelected() {
    if (selectedItems.length === 0) return;
    setError(""); setResult(null); setRunning(true);
    try {
      const res = await axios.post("/admin/sharepoint/ingest/items", {
        site_url: siteUrl,
        library_name: selectedLibrary,
        items: selectedItems.map(it => ({ id: it.id, name: it.name, downloadUrl: it.downloadUrl || "" })),
      }, { headers: authHeaders() });
      setResult(res.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Ingestion failed. Check server logs.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-bold text-white flex items-center gap-2">
          <Cloud size={18} className="text-brand-400" /> SharePoint File Browser
        </h2>
        <p className="text-sm text-gray-400 mt-1">
          Credentials configured server-side in <code className="text-brand-300 bg-gray-900/60 px-1 rounded text-xs">.env</code> — no passwords needed here.
        </p>
      </div>

      {/* Step 1 — Connect */}
      <div className="bg-gray-800/60 border border-gray-700 rounded-xl p-4 space-y-3">
        <p className="text-xs font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
          <span className="w-5 h-5 rounded-full bg-brand-600/30 text-brand-300 flex items-center justify-center text-xs font-bold">1</span>
          Connect to Site
        </p>
        <div className="flex gap-2">
          <input
            value={siteUrl}
            onChange={e => { setSiteUrl(e.target.value); setConnected(false); setTreeItems([]); }}
            placeholder="https://company.sharepoint.com/sites/SiteName"
            className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand-500 transition"
          />
          <button
            onClick={testConnection}
            disabled={testing}
            className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-sm rounded-lg transition font-medium shrink-0"
          >
            {testing ? <><Loader2 size={13} className="animate-spin" /> Testing…</> : <><Play size={13} /> Connect</>}
          </button>
        </div>

        {error && (
          <div className="flex gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-300">
            <AlertCircle size={15} className="shrink-0 mt-0.5" />
            <span className="text-xs leading-relaxed">{error}</span>
          </div>
        )}

        {connected && (
          <div className="flex items-center gap-2 p-2.5 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-sm text-emerald-300">
            <CheckCircle size={14} className="shrink-0" />
            Connected to <strong>{siteDisplayName}</strong>
          </div>
        )}
      </div>

      {/* Step 2 — Browse & Select */}
      {connected && (
        <div className="bg-gray-800/60 border border-gray-700 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
              <span className="w-5 h-5 rounded-full bg-brand-600/30 text-brand-300 flex items-center justify-center text-xs font-bold">2</span>
              Browse &amp; Select Files
            </p>
            <div className="flex items-center gap-2">
              {libraries.length > 0 && (
                <select
                  value={selectedLibrary}
                  onChange={e => { setSelectedLibrary(e.target.value); browseRoot(e.target.value); }}
                  className="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:border-brand-500"
                >
                  {libraries.map(l => <option key={l.id} value={l.name}>{l.name}</option>)}
                </select>
              )}
              <button
                onClick={() => browseRoot()}
                disabled={browsing}
                className="flex items-center gap-1.5 text-xs text-brand-400 hover:text-brand-300 border border-brand-500/30 hover:border-brand-400 px-3 py-1.5 rounded-lg transition"
              >
                {browsing ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                {treeItems.length === 0 ? "Load files" : "Refresh"}
              </button>
            </div>
          </div>

          {/* File tree */}
          {treeItems.length > 0 ? (
            <div className="bg-gray-900/60 border border-gray-700/60 rounded-xl overflow-hidden">
              {/* Header */}
              <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700/60 bg-gray-900/40">
                <span className="text-xs text-gray-500">{treeItems.length} items at root level</span>
                <div className="flex items-center gap-3">
                  {selectedIds.size > 0 && (
                    <span className="text-xs text-brand-400 font-medium">{selectedIds.size} file{selectedIds.size !== 1 ? "s" : ""} selected</span>
                  )}
                  <button
                    onClick={() => { setSelectedIds(new Set()); setSelectedItems([]); }}
                    className="text-xs text-gray-600 hover:text-gray-400 transition"
                  >
                    Clear
                  </button>
                </div>
              </div>
              {/* Tree */}
              <div className="max-h-80 overflow-y-auto p-2 space-y-0.5">
                {treeItems.map(item => (
                  <FolderNode
                    key={item.id}
                    item={item}
                    depth={0}
                    siteUrl={siteUrl}
                    libraryName={selectedLibrary}
                    selectedIds={selectedIds}
                    onToggleFile={toggleFile}
                    onSelectFolder={selectFolderForIngest}
                    onLoadChildren={loadChildren}
                  />
                ))}
              </div>
            </div>
          ) : browsing ? (
            <div className="flex items-center justify-center py-10 text-gray-500 text-sm gap-2">
              <Loader2 size={16} className="animate-spin" /> Loading files from SharePoint…
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <FolderOpen size={28} className="text-gray-700 mb-2" />
              <p className="text-sm text-gray-500">Click "Load files" to browse your SharePoint library</p>
            </div>
          )}

          {/* Ingest button */}
          {selectedIds.size > 0 && (
            <button
              onClick={ingestSelected}
              disabled={running}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-brand-600 to-violet-600 hover:from-brand-500 hover:to-violet-500 disabled:opacity-50 text-white font-semibold py-3 rounded-xl transition text-sm shadow-lg shadow-brand-900/30"
            >
              {running
                ? <><Loader2 size={15} className="animate-spin" /> Ingesting {selectedIds.size} file{selectedIds.size !== 1 ? "s" : ""}…</>
                : <><Play size={15} /> Ingest {selectedIds.size} selected file{selectedIds.size !== 1 ? "s" : ""}</>}
            </button>
          )}
        </div>
      )}

      {/* Result */}
      {result && (
        <div className={`border rounded-xl p-4 ${result.errors === 0 ? "bg-emerald-500/5 border-emerald-500/20" : "bg-amber-500/5 border-amber-500/20"}`}>
          <div className="flex items-center justify-between gap-2 mb-3">
            <div className="flex items-center gap-2">
              {result.errors === 0
                ? <CheckCircle size={16} className="text-emerald-400" />
                : <AlertCircle size={16} className="text-amber-400" />}
              <p className="text-sm font-semibold text-white">Ingestion Queued</p>
            </div>
            {onNavigateToAdmin && (
              <button
                onClick={onNavigateToAdmin}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-brand-600/20 hover:bg-brand-600/40 border border-brand-500/30 text-brand-300 rounded-lg transition font-medium shrink-0"
              >
                View Chunks in Admin Panel →
              </button>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div className="bg-gray-800/80 rounded-lg px-3 py-2.5 text-center">
              <p className="text-2xl font-bold text-emerald-400">{result.ingested}</p>
              <p className="text-xs text-gray-400 mt-0.5">Files Ingested</p>
            </div>
            <div className="bg-gray-800/80 rounded-lg px-3 py-2.5 text-center">
              <p className="text-2xl font-bold text-red-400">{result.errors}</p>
              <p className="text-xs text-gray-400 mt-0.5">Errors</p>
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
              <p className="text-xs font-semibold text-red-400 mb-1">Errors:</p>
              {result.error_details.map((e: any, i: number) => (
                <div key={i} className="text-xs text-gray-400 bg-red-500/5 rounded px-2 py-1">✗ {e.file}: {e.error}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Auth info */}
      <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-3">
        <p className="text-xs font-medium text-gray-400 mb-2">How it works</p>
        <div className="space-y-1 text-xs text-gray-600">
          {[
            "Azure AD app uses client_credentials — no user sign-in required",
            "Set SHAREPOINT_TENANT_ID, CLIENT_ID, CLIENT_SECRET in server .env",
            "App needs Sites.Read.All and Files.Read.All permissions",
            "Files are chunked, embedded in Qdrant and linked in the knowledge graph",
          ].map((s, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-brand-600 font-bold shrink-0">{i + 1}.</span> {s}
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

export default function DocumentUpload({ onNavigateToAdmin }: { onNavigateToAdmin?: () => void }) {
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
        {activeTab === "sharepoint" && <SharePointConnector onNavigateToAdmin={onNavigateToAdmin} />}

      </div>
    </div>
  );
}
