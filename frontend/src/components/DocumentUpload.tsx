import { useState, useCallback } from "react";
import {
  Upload, FileText, CheckCircle, AlertCircle, Loader2, X,
  GitBranch, Brain, Database, ChevronDown, ChevronUp, Link2, HardDrive, Cloud
} from "lucide-react";
import axios from "axios";

interface UploadedFile {
  name: string;
  size: number;
  status: "uploading" | "success" | "error";
  message?: string;
  entities?: {
    contracts: string[];
    dates: string[];
    amounts: string[];
    organizations: string[];
  };
}

const ALLOWED = [".pdf", ".xml", ".txt", ".docx", ".json", ".csv", ".html"];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Knowledge graph pipeline display ─────────────────────────────────────────
function KnowledgeGraphPipeline({ entities }: { entities: UploadedFile["entities"] }) {
  const [open, setOpen] = useState(false);
  if (!entities) return null;

  const hasAny = Object.values(entities).some(a => a.length > 0);
  return (
    <div className="mt-3 border-t border-gray-700 pt-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-xs text-gray-400 hover:text-gray-200 transition"
      >
        <GitBranch size={12} className="text-emerald-400" />
        Knowledge Graph Pipeline
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {/* Pipeline steps */}
          <div className="flex items-center gap-2 text-xs text-gray-400 flex-wrap">
            {["NER Extraction", "Relationship Mapping", "Graph Storage (Neo4j)", "Chunk Linking"].map((step, i) => (
              <span key={step} className="flex items-center gap-1">
                <span className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2 py-0.5 rounded-full">{step}</span>
                {i < 3 && <span className="text-gray-600">→</span>}
              </span>
            ))}
          </div>

          {/* Extracted entities */}
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

// ── File card ─────────────────────────────────────────────────────────────────
function FileCard({ file, onRemove }: { file: UploadedFile; onRemove: () => void }) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 bg-gray-700 rounded-lg flex items-center justify-center shrink-0">
          <FileText size={16} className="text-gray-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm text-white font-medium truncate">{file.name}</p>
            <div className="flex items-center gap-2 shrink-0">
              {file.status === "uploading" && <Loader2 size={14} className="text-brand-400 animate-spin" />}
              {file.status === "success" && <CheckCircle size={14} className="text-emerald-400" />}
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
              <p className="text-xs text-gray-400 mt-1">Embedding + graph ingestion…</p>
            </div>
          )}
          {file.message && file.status !== "uploading" && (
            <p className={`text-xs mt-1 ${file.status === "success" ? "text-emerald-400" : "text-red-400"}`}>
              {file.message}
            </p>
          )}
          {file.status === "success" && <KnowledgeGraphPipeline entities={file.entities} />}
        </div>
      </div>
    </div>
  );
}

// ── External source card ──────────────────────────────────────────────────────
function ExternalCard({ icon: Icon, label, desc, badge }: any) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-xl p-4 flex items-center gap-3 opacity-70">
      <div className="w-9 h-9 bg-gray-700 rounded-lg flex items-center justify-center shrink-0">
        <Icon size={16} className="text-gray-400" />
      </div>
      <div className="flex-1">
        <p className="text-sm font-medium text-white">{label}</p>
        <p className="text-xs text-gray-400">{desc}</p>
      </div>
      <span className="text-xs bg-gray-700 text-gray-400 px-2 py-0.5 rounded-full">{badge}</span>
    </div>
  );
}

export default function DocumentUpload() {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const [activeTab, setActiveTab] = useState<"files" | "external" | "etl">("files");

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
      setFiles(prev => prev.map(f =>
        f.name === file.name ? {
          ...f,
          status: res.data.status === "success" ? "success" : "error",
          message: res.data.message,
          entities: res.data.entities,
        } : f
      ));
    } catch (err: any) {
      setFiles(prev => prev.map(f =>
        f.name === file.name ? { ...f, status: "error", message: err.response?.data?.detail || "Upload failed." } : f
      ));
    }
  }, []);

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
          { id: "external", label: "External Sources" },
          { id: "etl", label: "ETL Pipeline" },
        ].map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id as any)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition -mb-px ${
              activeTab === id
                ? "border-brand-500 text-brand-300"
                : "border-transparent text-gray-400 hover:text-white"
            }`}
          >
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
                Supports PDF, XML, DOCX, TXT, JSON, CSV · Each file is embedded into Qdrant and the knowledge graph is auto-built.
              </p>
            </div>

            {/* Drop zone */}
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
              <p className="text-base font-medium text-white mb-1">
                {dragging ? "Release to upload" : "Drag & drop your documents"}
              </p>
              <p className="text-sm text-gray-400 mb-3">or click to browse</p>
              <div className="flex flex-wrap justify-center gap-2">
                {ALLOWED.map(ext => (
                  <span key={ext} className="text-xs bg-gray-800 border border-gray-700 text-gray-400 px-2 py-0.5 rounded-full">{ext}</span>
                ))}
              </div>
              <input
                id="file-input"
                type="file"
                className="hidden"
                multiple
                accept={ALLOWED.join(",")}
                onChange={e => handleFiles(e.target.files)}
              />
            </div>

            {/* Processing pipeline info */}
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
              <p className="text-xs font-medium text-gray-300 mb-3">Document Processing Pipeline</p>
              <div className="flex items-center gap-2 flex-wrap">
                {[
                  { icon: FileText, label: "Parse & Chunk", color: "text-blue-400" },
                  { icon: Brain, label: "Embed (BAAI)", color: "text-violet-400" },
                  { icon: Database, label: "Store (Qdrant)", color: "text-blue-400" },
                  { icon: GitBranch, label: "NER Extraction", color: "text-emerald-400" },
                  { icon: Link2, label: "Build Graph", color: "text-emerald-400" },
                  { icon: CheckCircle, label: "Ready to Query", color: "text-emerald-400" },
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

            {/* Files list */}
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

        {/* ── EXTERNAL SOURCES ── */}
        {activeTab === "external" && (
          <>
            <div>
              <h2 className="text-lg font-bold text-white">External Sources</h2>
              <p className="text-sm text-gray-400 mt-1">Connect to external document repositories for automatic ingestion.</p>
            </div>
            <div className="space-y-3">
              <ExternalCard icon={Cloud} label="SharePoint" desc="Connect your SharePoint libraries" badge="Coming Soon" />
              <ExternalCard icon={HardDrive} label="Google Drive" desc="Import from Drive folders" badge="Coming Soon" />
              <ExternalCard icon={Cloud} label="Amazon S3" desc="Ingest from S3 buckets" badge="Coming Soon" />
              <ExternalCard icon={Link2} label="REST API" desc="Pull documents from custom APIs" badge="Coming Soon" />
            </div>
            <div className="bg-brand-600/10 border border-brand-500/30 rounded-xl p-5 text-sm text-brand-300">
              <p className="font-medium mb-1">Phase 2 Upload Coming Soon</p>
              <p className="text-xs text-gray-400">External source connectors will automatically ingest documents into the RAG + Graph pipeline with authentication support.</p>
            </div>
          </>
        )}

        {/* ── ETL PIPELINE ── */}
        {activeTab === "etl" && (
          <>
            <div>
              <h2 className="text-lg font-bold text-white">Advanced ETL Pipeline</h2>
              <p className="text-sm text-gray-400 mt-1">Phase 3 — automated knowledge graph generation from raw documents.</p>
            </div>
            <div className="space-y-4">
              {[
                { step: "1", icon: FileText, title: "OCR & Text Extraction", desc: "Process scanned PDFs, images, and complex formats using Apache Tika + Tesseract OCR.", status: "active" },
                { step: "2", icon: Brain, title: "Named Entity Recognition (NER)", desc: "spaCy NER pipeline extracts PERSON, ORG, DATE, MONEY, CONTRACT entities from text.", status: "active" },
                { step: "3", icon: Link2, title: "Relationship Extraction", desc: "Regex + ML patterns detect relationships: CONTRACT→issued_by→ORG, CONTRACT→starts_on→DATE.", status: "active" },
                { step: "4", icon: GitBranch, title: "Automatic Graph Generation", desc: "Extracted entities and relationships are stored as Neo4j nodes and edges automatically.", status: "active" },
                { step: "5", icon: Database, title: "Chunk-to-Node Linking", desc: "Each vector chunk is linked to relevant graph nodes for unified retrieval.", status: "active" },
                { step: "6", icon: Cloud, title: "Table Extraction", desc: "Structured table data extracted and indexed as structured knowledge.", status: "soon" },
                { step: "7", icon: HardDrive, title: "Metadata Tagging", desc: "Automatic document classification and metadata tagging for improved retrieval.", status: "soon" },
              ].map(({ step, icon: Icon, title, desc, status }) => (
                <div key={step} className="flex gap-4">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                    status === "active" ? "bg-emerald-600/20 text-emerald-300 border border-emerald-500/30" : "bg-gray-700 text-gray-500 border border-gray-600"
                  }`}>{step}</div>
                  <div className="flex-1 pb-4 border-b border-gray-800">
                    <div className="flex items-center gap-2 mb-1">
                      <Icon size={15} className={status === "active" ? "text-emerald-400" : "text-gray-500"} />
                      <p className="text-sm font-medium text-white">{title}</p>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        status === "active" ? "bg-emerald-500/20 text-emerald-300" : "bg-gray-700 text-gray-400"
                      }`}>{status === "active" ? "Active" : "Coming Soon"}</span>
                    </div>
                    <p className="text-xs text-gray-400 leading-relaxed">{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
