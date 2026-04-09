import { useState, useEffect, useRef, useCallback } from "react";
import {
  GitBranch, Search, RefreshCw, Database, Network,
  Loader2, AlertCircle, ChevronDown, ChevronRight, ArrowRight, X,
  Table2, Share2
} from "lucide-react";
import axios from "axios";

// ── Types ─────────────────────────────────────────────────────────────────────
interface GraphNode { id: string; name: string; type: string; source?: string }
interface GraphEdge { from_node: string; relation: string; to_node: string; source?: string }
interface GraphData  { nodes: GraphNode[]; edges: GraphEdge[]; total_nodes: number; total_edges: number }
interface Pos3D      { id: string; x: number; y: number; z: number; vx: number; vy: number; vz: number }

// ── Colors ────────────────────────────────────────────────────────────────────
const HEX: Record<string, string> = {
  Contract: "#6366f1", Organization: "#10b981", Date: "#f59e0b",
  Amount: "#ec4899",  Document: "#3b82f6",      Entity: "#8b5cf6",
};
const BADGE: Record<string, string> = {
  Contract:     "bg-indigo-500/10  text-indigo-300  border-indigo-500/30",
  Organization: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  Date:         "bg-amber-500/10   text-amber-300   border-amber-500/30",
  Amount:       "bg-pink-500/10    text-pink-300    border-pink-500/30",
  Document:     "bg-blue-500/10    text-blue-300    border-blue-500/30",
  Entity:       "bg-violet-500/10  text-violet-300  border-violet-500/30",
};
const DOT: Record<string, string> = {
  Contract: "bg-indigo-400", Organization: "bg-emerald-400", Date: "bg-amber-400",
  Amount: "bg-pink-400", Document: "bg-blue-400", Entity: "bg-violet-400",
};
function hexColor(t: string) { return HEX[t] || "#8b5cf6" }
function badgeClass(t: string) { return BADGE[t] || BADGE.Entity }
function dotClass(t: string)   { return DOT[t]  || DOT.Entity }

function TypeBadge({ type }: { type: string }) {
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border font-medium ${badgeClass(type)}`}>
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotClass(type)}`} />
      {type}
    </span>
  );
}

// ── 3D Force Layout ───────────────────────────────────────────────────────────
function compute3DLayout(nodes: GraphNode[], edges: GraphEdge[]): Pos3D[] {
  if (!nodes.length) return [];
  const n = nodes.length;
  const radius = Math.max(120, Math.sqrt(n) * 28);

  const ns: Pos3D[] = nodes.map((node, i) => {
    const phi   = Math.acos(1 - 2 * (i + 0.5) / n);
    const theta = 2.399963 * i; // golden angle
    return {
      id: node.id,
      x: radius * Math.sin(phi) * Math.cos(theta),
      y: radius * Math.sin(phi) * Math.sin(theta),
      z: radius * Math.cos(phi),
      vx: 0, vy: 0, vz: 0,
    };
  });

  const nm: Record<string, Pos3D> = {};
  ns.forEach(p => { nm[p.id] = p; });

  const REPEL = 14000, ATTRACT = 0.012, DAMP = 0.82;
  for (let iter = 0; iter < 80; iter++) {
    for (let i = 0; i < ns.length; i++) {
      for (let j = i + 1; j < ns.length; j++) {
        const a = ns[i], b = ns[j];
        const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
        const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
        const f = REPEL / (d * d);
        a.vx -= (dx / d) * f; a.vy -= (dy / d) * f; a.vz -= (dz / d) * f;
        b.vx += (dx / d) * f; b.vy += (dy / d) * f; b.vz += (dz / d) * f;
      }
    }
    edges.forEach(e => {
      const a = nm[e.from_node], b = nm[e.to_node];
      if (!a || !b) return;
      const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
      a.vx += dx * ATTRACT; a.vy += dy * ATTRACT; a.vz += dz * ATTRACT;
      b.vx -= dx * ATTRACT; b.vy -= dy * ATTRACT; b.vz -= dz * ATTRACT;
    });
    ns.forEach(p => {
      p.vx *= DAMP; p.vy *= DAMP; p.vz *= DAMP;
      p.x += p.vx; p.y += p.vy; p.z += p.vz;
    });
  }
  return ns;
}

// ── 3D Graph Canvas ───────────────────────────────────────────────────────────
function Graph3DCanvas({
  nodes, edges, nodeMap, onNodeSelect,
}: {
  nodes: GraphNode[]; edges: GraphEdge[];
  nodeMap: Record<string, GraphNode>;
  onNodeSelect: (n: GraphNode | null) => void;
}) {
  const canvasRef    = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const layoutRef    = useRef<Pos3D[]>([]);
  const rotRef       = useRef({ rotX: 0.25, rotY: 0.5, dragging: false, lastX: 0, lastY: 0, autoRotate: true });
  const hoveredRef   = useRef<string | null>(null);
  const selectedRef  = useRef<string | null>(null);

  const [canvasSize, setCanvasSize] = useState({ w: 800, h: 500 });
  const [tooltip, setTooltip] = useState<{ node: GraphNode; x: number; y: number } | null>(null);

  // Compute layout once on node change
  useEffect(() => {
    layoutRef.current = compute3DLayout(nodes, edges);
  }, [nodes, edges]);

  // Resize observer
  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver(entries => {
      const r = entries[0].contentRect;
      setCanvasSize({ w: Math.floor(r.width), h: Math.floor(r.height) });
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  // Projection helper
  const project = (p: Pos3D, rotX: number, rotY: number, w: number, h: number) => {
    let x = p.x, y = p.y, z = p.z;
    // Rotate Y
    const cy = Math.cos(rotY), sy = Math.sin(rotY);
    const tx = x * cy + z * sy; const tz = -x * sy + z * cy;
    x = tx; z = tz;
    // Rotate X
    const cx2 = Math.cos(rotX), sx2 = Math.sin(rotX);
    const ty2 = y * cx2 - z * sx2; const tz2 = y * sx2 + z * cx2;
    y = ty2; z = tz2;
    // Perspective
    const FOV = 560;
    const sc = FOV / (z + FOV + 180);
    return { sx: w / 2 + x * sc, sy: h / 2 + y * sc, depth: z, scale: sc };
  };

  // Render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf: number;

    const draw = () => {
      const { rotX, rotY, dragging, autoRotate } = rotRef.current;
      if (!dragging && autoRotate) rotRef.current.rotY += 0.003;

      const w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      // Subtle grid
      ctx.strokeStyle = "rgba(255,255,255,0.025)";
      ctx.lineWidth = 1;
      for (let i = 1; i < 6; i++) {
        ctx.beginPath(); ctx.moveTo((w / 6) * i, 0); ctx.lineTo((w / 6) * i, h); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, (h / 4) * i); ctx.lineTo(w, (h / 4) * i); ctx.stroke();
      }

      const layout = layoutRef.current;
      if (!layout.length) { raf = requestAnimationFrame(draw); return; }

      // Project all nodes
      type ProjNode = Pos3D & { sx: number; sy: number; depth: number; scale: number };
      const projected: ProjNode[] = layout.map(p => ({
        ...p, ...project(p, rotRef.current.rotX, rotRef.current.rotY, w, h),
      }));
      const projMap: Record<string, ProjNode> = {};
      projected.forEach(p => { projMap[p.id] = p; });

      // Draw edges (sorted back→front)
      const sortedEdges = edges
        .map(e => {
          const a = projMap[e.from_node], b = projMap[e.to_node];
          if (!a || !b) return null;
          return { e, a, b, depth: (a.depth + b.depth) / 2 };
        })
        .filter(Boolean)
        .sort((a, b) => a!.depth - b!.depth) as Array<{ e: GraphEdge; a: ProjNode; b: ProjNode; depth: number }>;

      sortedEdges.forEach(({ e, a, b }) => {
        const isLinked = hoveredRef.current && (e.from_node === hoveredRef.current || e.to_node === hoveredRef.current);
        const alpha = isLinked ? 0.7 : Math.max(0.05, Math.min(0.25, 0.2 * b.scale));
        const hx = hexColor(nodeMap[e.from_node]?.type || "Entity");
        ctx.beginPath();
        ctx.moveTo(a.sx, a.sy);
        ctx.lineTo(b.sx, b.sy);
        ctx.strokeStyle = isLinked ? hx + "bb" : `rgba(99,102,241,${alpha})`;
        ctx.lineWidth = isLinked ? 1.5 : 0.8;
        ctx.stroke();

        // Relation label on hovered edges
        if (isLinked && e.relation) {
          const mx = (a.sx + b.sx) / 2, my = (a.sy + b.sy) / 2;
          ctx.font = "9px system-ui, sans-serif";
          ctx.textAlign = "center";
          ctx.fillStyle = "rgba(156,163,175,0.9)";
          ctx.fillText(e.relation.toLowerCase().replace(/_/g, " "), mx, my - 4);
        }
      });

      // Draw nodes (back→front)
      [...projected].sort((a, b) => a.depth - b.depth).forEach(p => {
        const node = nodeMap[p.id];
        if (!node) return;
        const color  = hexColor(node.type);
        const isHov  = hoveredRef.current  === p.id;
        const isSel  = selectedRef.current === p.id;
        const r = Math.max(5, 18 * p.scale);

        // Glow
        ctx.shadowBlur  = isHov || isSel ? 24 : 8;
        ctx.shadowColor = color + (isHov || isSel ? "ff" : "88");

        // Circle fill + stroke
        ctx.beginPath();
        ctx.arc(p.sx, p.sy, r, 0, Math.PI * 2);
        ctx.fillStyle = color + (isHov ? "cc" : isSel ? "bb" : "44");
        ctx.fill();
        ctx.strokeStyle = color + (isHov || isSel ? "ff" : "bb");
        ctx.lineWidth = isHov || isSel ? 2.5 : 1.2;
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Label
        if (isHov || isSel || p.scale > 0.9) {
          const nm = node.name || p.id;
          const lbl = nm.length > 14 ? nm.slice(0, 12) + "…" : nm;
          const fs = Math.max(8, Math.round(11 * p.scale));
          ctx.font = `${fs}px system-ui, sans-serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          // Text shadow for readability
          ctx.shadowColor = "rgba(0,0,0,0.8)";
          ctx.shadowBlur = 4;
          ctx.fillStyle = "rgba(255,255,255,0.95)";
          ctx.fillText(lbl, p.sx, p.sy);
          ctx.shadowBlur = 0;
        }
      });

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [nodes, edges, nodeMap, canvasSize]);

  // Hit test
  const hitTest = useCallback((cx: number, cy: number): string | null => {
    const layout = layoutRef.current;
    const canvas = canvasRef.current;
    if (!layout.length || !canvas) return null;
    const w = canvas.width, h = canvas.height;
    let best: string | null = null, bestDist = Infinity;
    layout.forEach(p => {
      const proj = project(p, rotRef.current.rotX, rotRef.current.rotY, w, h);
      const r = Math.max(8, 20 * proj.scale);
      const d = Math.hypot(cx - proj.sx, cy - proj.sy);
      if (d < r && d < bestDist) { bestDist = d; best = p.id; }
    });
    return best;
  }, []);

  const onMouseDown = (e: React.MouseEvent) => {
    rotRef.current.dragging = true;
    rotRef.current.lastX = e.clientX;
    rotRef.current.lastY = e.clientY;
    rotRef.current.autoRotate = false;
  };

  const onMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const r = rotRef.current;
    const rect = e.currentTarget.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;

    if (r.dragging) {
      r.rotY += (e.clientX - r.lastX) * 0.007;
      r.rotX += (e.clientY - r.lastY) * 0.007;
      r.rotX = Math.max(-1.3, Math.min(1.3, r.rotX));
      r.lastX = e.clientX;
      r.lastY = e.clientY;
      setTooltip(null);
    } else {
      const hit = hitTest(cx, cy);
      hoveredRef.current = hit;
      if (hit && nodeMap[hit]) {
        setTooltip({ node: nodeMap[hit], x: cx, y: cy });
      } else {
        setTooltip(null);
      }
    }
  };

  const onMouseUp = () => { rotRef.current.dragging = false; };

  const onClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
    selectedRef.current = hit;
    onNodeSelect(hit && nodeMap[hit] ? nodeMap[hit] : null);
  };

  const onDoubleClick = () => {
    rotRef.current.autoRotate = !rotRef.current.autoRotate;
  };

  const onMouseLeave = () => {
    rotRef.current.dragging = false;
    hoveredRef.current = null;
    setTooltip(null);
  };

  // Legend types
  const typeOrder = ["Contract", "Organization", "Document", "Amount", "Date", "Entity"];
  const presentTypes = typeOrder.filter(t => nodes.some(n => n.type === t));

  return (
    <div ref={containerRef} className="relative w-full h-full bg-gray-950 overflow-hidden">
      <canvas
        ref={canvasRef}
        width={canvasSize.w}
        height={canvasSize.h}
        style={{ width: "100%", height: "100%", display: "block" }}
        className="cursor-grab active:cursor-grabbing select-none"
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onClick={onClick}
        onDoubleClick={onDoubleClick}
        onMouseLeave={onMouseLeave}
      />

      {/* Legend */}
      <div className="absolute top-3 left-3 flex flex-wrap gap-1.5 max-w-xs">
        {presentTypes.map(t => (
          <span key={t} className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${badgeClass(t)} backdrop-blur-sm`}>
            <span className={`w-1.5 h-1.5 rounded-full ${dotClass(t)}`} />
            {t}
          </span>
        ))}
      </div>

      {/* Hover tooltip */}
      {tooltip && (
        <div
          className="absolute pointer-events-none bg-gray-900/95 border border-gray-700 rounded-xl px-3 py-2.5 shadow-2xl z-20 min-w-[140px]"
          style={{ left: tooltip.x + 14, top: Math.max(8, tooltip.y - 10) }}
        >
          <TypeBadge type={tooltip.node.type} />
          <p className="text-sm font-semibold text-white mt-1.5">{tooltip.node.name}</p>
          {tooltip.node.source && (
            <p className="text-xs text-gray-500 mt-0.5">{tooltip.node.source.split("/").pop()}</p>
          )}
        </div>
      )}

      {/* Controls */}
      <div className="absolute bottom-3 right-3 flex flex-col items-end gap-1">
        <p className="text-xs text-gray-600">drag to rotate · click to select · double-click to toggle auto-rotate</p>
      </div>
    </div>
  );
}

// ── Relationship Table ────────────────────────────────────────────────────────
function RelationshipsTable({ edges, nodeMap, search, selectedNode }: {
  edges: GraphEdge[]; nodeMap: Record<string, GraphNode>;
  search: string; selectedNode: GraphNode | null;
}) {
  const filtered = edges.filter(e => {
    const from = nodeMap[e.from_node]?.name || e.from_node;
    const to   = nodeMap[e.to_node]?.name   || e.to_node;
    const rel  = e.relation || "";
    const q    = search.toLowerCase();
    const matchSearch   = !q || from.toLowerCase().includes(q) || to.toLowerCase().includes(q) || rel.toLowerCase().includes(q);
    const matchSelected = !selectedNode || e.from_node === selectedNode.id || e.to_node === selectedNode.id;
    return matchSearch && matchSelected;
  });

  if (!filtered.length) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-gray-500">
        <Network size={28} className="mb-2 opacity-40" />
        <p className="text-sm">{selectedNode ? `No relationships for "${selectedNode.name}"` : "No matches"}</p>
      </div>
    );
  }

  return (
    <table className="w-full text-sm">
      <thead className="sticky top-0 bg-gray-900/95 backdrop-blur z-10">
        <tr className="border-b border-gray-700">
          <th className="text-left text-xs text-gray-400 font-semibold py-2.5 px-4">From</th>
          <th className="text-center text-xs text-gray-400 font-semibold py-2.5 px-2 w-44">Relation</th>
          <th className="text-left text-xs text-gray-400 font-semibold py-2.5 px-4">To</th>
          <th className="text-left text-xs text-gray-400 font-semibold py-2.5 px-4 hidden lg:table-cell">Source</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-800/60">
        {filtered.map((e, i) => {
          const fNode = nodeMap[e.from_node], tNode = nodeMap[e.to_node];
          const fColor = hexColor(fNode?.type || "Entity");
          const tColor = hexColor(tNode?.type || "Entity");
          const isHl = selectedNode && (e.from_node === selectedNode.id || e.to_node === selectedNode.id);
          return (
            <tr key={i} className={`transition-colors ${isHl ? "bg-gray-800/40" : "hover:bg-gray-800/20"}`}>
              <td className="py-3 px-4">
                <p className="font-medium truncate max-w-[150px]" style={{ color: fColor }}>
                  {fNode?.name || e.from_node}
                </p>
                {fNode?.type && <TypeBadge type={fNode.type} />}
              </td>
              <td className="py-3 px-2">
                <div className="flex items-center gap-1">
                  <div className="h-px flex-1 bg-gray-700" />
                  <span className="text-xs text-gray-400 bg-gray-800 border border-gray-700 px-2 py-0.5 rounded-full whitespace-nowrap">
                    {e.relation?.toLowerCase().replace(/_/g, " ") || "relates to"}
                  </span>
                  <ArrowRight size={11} className="text-gray-600 shrink-0" />
                </div>
              </td>
              <td className="py-3 px-4">
                <p className="font-medium truncate max-w-[150px]" style={{ color: tColor }}>
                  {tNode?.name || e.to_node}
                </p>
                {tNode?.type && <TypeBadge type={tNode.type} />}
              </td>
              <td className="py-3 px-4 hidden lg:table-cell">
                <span className="text-xs text-gray-600 truncate block max-w-[120px]">
                  {(e.source || "—").split("/").pop() || "—"}
                </span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ── Entity browser ────────────────────────────────────────────────────────────
function EntitySection({ type, nodes, search, selected, onSelect }: {
  type: string; nodes: GraphNode[]; search: string;
  selected: GraphNode | null; onSelect: (n: GraphNode | null) => void;
}) {
  const [open, setOpen] = useState(true);
  const filtered = search ? nodes.filter(n => n.name.toLowerCase().includes(search.toLowerCase())) : nodes;
  if (!filtered.length) return null;
  const color = hexColor(type);
  const badge = badgeClass(type);
  const dot   = dotClass(type);
  return (
    <div className="border border-gray-700 rounded-xl overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-800 hover:bg-gray-750 transition"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2">
          <span className={`w-2.5 h-2.5 rounded-full ${dot}`} />
          <span className="text-sm font-semibold" style={{ color }}>{type}</span>
          <span className="text-xs text-gray-500 bg-gray-700 px-1.5 py-0.5 rounded-full">{filtered.length}</span>
        </div>
        {open ? <ChevronDown size={13} className="text-gray-500" /> : <ChevronRight size={13} className="text-gray-500" />}
      </button>
      {open && (
        <div className="divide-y divide-gray-800/50 bg-gray-900">
          {filtered.map(n => (
            <button
              key={n.id}
              onClick={() => onSelect(selected?.id === n.id ? null : n)}
              className={`w-full text-left px-4 py-2 text-sm transition flex items-center justify-between group ${
                selected?.id === n.id ? `${badge}` : "text-gray-300 hover:bg-gray-800 hover:text-white"
              }`}
            >
              <span className="truncate">{n.name}</span>
              {n.source && (
                <span className="text-xs text-gray-600 group-hover:text-gray-500 ml-2 shrink-0 truncate max-w-[90px]">
                  {n.source.split("/").pop()}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────
const TYPE_ORDER = ["Contract", "Organization", "Document", "Amount", "Date", "Entity"];

export default function KnowledgeGraphUI() {
  const [graphData, setGraphData]       = useState<GraphData | null>(null);
  const [loading, setLoading]           = useState(false);
  const [error, setError]               = useState("");
  const [searchQuery, setSearchQuery]   = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [rightTab, setRightTab]         = useState<"table">("table");

  const fetchGraph = useCallback(async () => {
    setLoading(true); setError(""); setSelectedNode(null);
    try {
      const token = localStorage.getItem("accessToken");
      const res = await axios.get("/admin/graph/data", {
        headers: { Authorization: `Bearer ${token}` },
        timeout: 15000,
      });
      setGraphData(res.data);
    } catch (err: any) {
      if (axios.isCancel(err) || err?.code === "ECONNABORTED") {
        setError("Request timed out. The server may be restarting — click Refresh to retry.");
      } else {
        setError(err.response?.data?.detail || "Failed to load graph data. Click Refresh to retry.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  const nodeMap: Record<string, GraphNode> = {};
  (graphData?.nodes ?? []).forEach(n => { nodeMap[n.id] = n; });

  const byType: Record<string, GraphNode[]> = {};
  (graphData?.nodes ?? []).forEach(n => {
    if (!byType[n.type]) byType[n.type] = [];
    byType[n.type].push(n);
  });
  const sortedTypes = [
    ...TYPE_ORDER.filter(t => byType[t]),
    ...Object.keys(byType).filter(t => !TYPE_ORDER.includes(t)),
  ];

  const totalNodes = graphData?.total_nodes ?? 0;
  const totalEdges = graphData?.total_edges ?? 0;
  const hasData    = !loading && !error && (graphData?.nodes?.length ?? 0) > 0;

  return (
    <div className="flex flex-col h-full overflow-hidden">

      {/* ── Header ── */}
      <div className="px-6 py-4 border-b border-gray-800 shrink-0">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Share2 size={19} className="text-emerald-400" />
              Knowledge Graph
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">Entity relationships extracted from your documents</p>
          </div>
          <button onClick={fetchGraph} disabled={loading}
            className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-gray-400 hover:text-white transition text-xs disabled:opacity-50">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>

        {/* Stats + search */}
        <div className="flex items-center gap-3 flex-wrap">
          {graphData && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="flex items-center gap-1.5 text-xs bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-gray-300">
                <Database size={11} className="text-blue-400" />
                <strong className="text-white">{totalNodes}</strong> entities
              </span>
              <span className="flex items-center gap-1.5 text-xs bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-gray-300">
                <GitBranch size={11} className="text-emerald-400" />
                <strong className="text-white">{totalEdges}</strong> relationships
              </span>
              {sortedTypes.slice(0, 4).map(t => (
                <span key={t} className={`text-xs px-2 py-1 rounded-lg border ${badgeClass(t)}`}>
                  {byType[t].length} {t}
                </span>
              ))}
            </div>
          )}
          <div className="relative flex-1 min-w-[180px]">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              type="text" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
              placeholder="Filter entities and relationships…"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-9 pr-8 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition"
            />
            {searchQuery && (
              <button onClick={() => setSearchQuery("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300">
                <X size={12} />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── States ── */}
      {loading && (
        <div className="flex-1 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3 text-gray-400">
            <Loader2 size={32} className="text-brand-400 animate-spin" />
            <p className="text-sm">Loading knowledge graph…</p>
          </div>
        </div>
      )}
      {!loading && error && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="text-center bg-gray-900 border border-gray-800 rounded-2xl p-8 max-w-sm w-full">
            <AlertCircle size={40} className="mx-auto text-red-400 mb-3" />
            <p className="text-white font-semibold mb-1">Graph unavailable</p>
            <p className="text-sm text-gray-400 mb-4">{error}</p>
            <button onClick={fetchGraph} className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg transition">Retry</button>
          </div>
        </div>
      )}
      {!loading && !error && !hasData && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="text-center">
            <Network size={52} className="mx-auto text-gray-700 mb-4" />
            <p className="text-white font-semibold mb-1">No graph data yet</p>
            <p className="text-sm text-gray-400">Upload documents to build the knowledge graph.</p>
          </div>
        </div>
      )}

      {/* ── Main split layout ── */}
      {hasData && (
        <div className="flex-1 overflow-hidden flex min-h-0">

          {/* Left — Entity browser */}
          <div className="w-72 shrink-0 border-r border-gray-800 flex flex-col overflow-hidden bg-gray-900/30">
            <div className="px-3 py-2.5 border-b border-gray-800">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Entities</p>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {sortedTypes.map(type => (
                <EntitySection
                  key={type} type={type} nodes={byType[type]}
                  search={searchQuery} selected={selectedNode} onSelect={setSelectedNode}
                />
              ))}
            </div>
          </div>

          {/* Right — 3D graph or table */}
          <div className="flex-1 overflow-hidden flex flex-col min-w-0">

            {/* Tab bar */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-gray-800 shrink-0">
              <div className="flex gap-1">
                <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-brand-600 text-white">
                  <Table2 size={13} /> Entity Relationships
                </span>
              </div>
              {selectedNode ? (
                <div className={`flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg ${badgeClass(selectedNode.type)}`}>
                  <TypeBadge type={selectedNode.type} />
                  <span className="font-medium truncate max-w-[120px]">{selectedNode.name}</span>
                  <button onClick={() => setSelectedNode(null)} className="text-gray-400 hover:text-gray-200 ml-1">
                    <X size={11} />
                  </button>
                </div>
              ) : (
                <p className="text-xs text-gray-600">
                  {totalEdges} relationships · click entity to filter
                </p>
              )}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-hidden">
              <div className="h-full overflow-y-auto">
                <RelationshipsTable
                  edges={graphData!.edges}
                  nodeMap={nodeMap}
                  search={searchQuery}
                  selectedNode={selectedNode}
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
