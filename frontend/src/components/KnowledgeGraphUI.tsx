import { useState, useEffect, useRef, useCallback } from "react";
import {
  GitBranch, Search, RefreshCw, ZoomIn, ZoomOut, Maximize2,
  Info, X, Database, Network, Loader2, AlertCircle
} from "lucide-react";
import axios from "axios";

interface GraphNode {
  id: string;
  name: string;
  type: string;
  source?: string;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

interface GraphEdge {
  from_node: string;
  relation: string;
  to_node: string;
  source?: string;
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_nodes: number;
  total_edges: number;
}

const TYPE_COLORS: Record<string, string> = {
  Contract: "#6366f1",
  Organization: "#10b981",
  Date: "#f59e0b",
  Amount: "#ec4899",
  Document: "#3b82f6",
  Entity: "#8b5cf6",
};

const TYPE_BG: Record<string, string> = {
  Contract: "bg-indigo-500/20 text-indigo-300 border-indigo-500/30",
  Organization: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  Date: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  Amount: "bg-pink-500/20 text-pink-300 border-pink-500/30",
  Document: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  Entity: "bg-violet-500/20 text-violet-300 border-violet-500/30",
};

function getColor(type: string): string {
  return TYPE_COLORS[type] || "#8b5cf6";
}

// ── Force-directed layout (simple spring simulation) ─────────────────────────
function useForceLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
  iterations: number = 80
): GraphNode[] {
  const [positioned, setPositioned] = useState<GraphNode[]>([]);

  useEffect(() => {
    if (!nodes.length) { setPositioned([]); return; }

    const REPULSION = 3500;
    const ATTRACTION = 0.03;
    const DAMPING = 0.85;
    const CENTER_PULL = 0.01;

    // Init positions
    const ns: GraphNode[] = nodes.map((n, i) => ({
      ...n,
      x: width / 2 + (Math.random() - 0.5) * width * 0.6,
      y: height / 2 + (Math.random() - 0.5) * height * 0.6,
      vx: 0,
      vy: 0,
    }));

    const nodeMap: Record<string, GraphNode> = {};
    ns.forEach(n => { nodeMap[n.id] = n; });

    for (let iter = 0; iter < iterations; iter++) {
      // Repulsion between all pairs
      for (let i = 0; i < ns.length; i++) {
        for (let j = i + 1; j < ns.length; j++) {
          const a = ns[i], b = ns[j];
          const dx = b.x! - a.x!;
          const dy = b.y! - a.y!;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = REPULSION / (dist * dist);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          a.vx! -= fx; a.vy! -= fy;
          b.vx! += fx; b.vy! += fy;
        }
      }

      // Attraction along edges
      edges.forEach(e => {
        const a = nodeMap[e.from_node];
        const b = nodeMap[e.to_node];
        if (!a || !b) return;
        const dx = b.x! - a.x!;
        const dy = b.y! - a.y!;
        a.vx! += dx * ATTRACTION;
        a.vy! += dy * ATTRACTION;
        b.vx! -= dx * ATTRACTION;
        b.vy! -= dy * ATTRACTION;
      });

      // Center pull + damping
      ns.forEach(n => {
        n.vx! += (width / 2 - n.x!) * CENTER_PULL;
        n.vy! += (height / 2 - n.y!) * CENTER_PULL;
        n.vx! *= DAMPING;
        n.vy! *= DAMPING;
        n.x! += n.vx!;
        n.y! += n.vy!;
        // Bounds
        n.x! = Math.max(40, Math.min(width - 40, n.x!));
        n.y! = Math.max(40, Math.min(height - 40, n.y!));
      });
    }

    setPositioned(ns);
  }, [nodes, edges, width, height]);

  return positioned;
}

// ── Node tooltip ──────────────────────────────────────────────────────────────
function NodeTooltip({ node, onClose }: { node: GraphNode; onClose: () => void }) {
  return (
    <div className="absolute top-4 right-4 bg-gray-900 border border-gray-700 rounded-xl p-4 min-w-[220px] shadow-xl z-10">
      <div className="flex justify-between items-start mb-2">
        <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${TYPE_BG[node.type] || "bg-violet-500/20 text-violet-300 border-violet-500/30"}`}>
          {node.type}
        </span>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-300 ml-2">
          <X size={14} />
        </button>
      </div>
      <p className="text-sm font-semibold text-white break-words">{node.name}</p>
      {node.source && (
        <p className="text-xs text-gray-400 mt-1">Source: {node.source}</p>
      )}
    </div>
  );
}

// ── SVG Graph Canvas ──────────────────────────────────────────────────────────
function GraphCanvas({
  nodes, edges, width, height, onNodeClick,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width: number;
  height: number;
  onNodeClick: (n: GraphNode) => void;
}) {
  const nodeMap: Record<string, GraphNode> = {};
  nodes.forEach(n => { nodeMap[n.id] = n; });

  return (
    <svg width={width} height={height} className="select-none">
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L0,6 L8,3 z" fill="#4b5563" />
        </marker>
      </defs>

      {/* Edges */}
      {edges.map((e, i) => {
        const a = nodeMap[e.from_node];
        const b = nodeMap[e.to_node];
        if (!a?.x || !b?.x) return null;
        const mx = (a.x + b.x) / 2;
        const my = (a.y! + b.y!) / 2;
        return (
          <g key={i}>
            <line
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke="#374151" strokeWidth={1.5}
              markerEnd="url(#arrow)"
              className="opacity-60"
            />
            <text
              x={mx} y={my! - 4}
              textAnchor="middle" fontSize={9}
              fill="#6b7280" className="pointer-events-none"
            >
              {e.relation?.toLowerCase().replace(/_/g, " ")}
            </text>
          </g>
        );
      })}

      {/* Nodes */}
      {nodes.map(n => {
        if (!n.x) return null;
        const color = getColor(n.type);
        const label = n.name.length > 18 ? n.name.slice(0, 16) + "…" : n.name;
        return (
          <g
            key={n.id}
            onClick={() => onNodeClick(n)}
            className="cursor-pointer"
          >
            <circle
              cx={n.x} cy={n.y} r={22}
              fill={color + "33"}
              stroke={color}
              strokeWidth={1.5}
              className="hover:stroke-2 transition-all"
            />
            <text
              x={n.x} y={n.y! + 1}
              textAnchor="middle" dominantBaseline="middle"
              fontSize={8.5} fill="white" className="pointer-events-none font-medium"
            >
              {label}
            </text>
            <text
              x={n.x} y={n.y! + 32}
              textAnchor="middle"
              fontSize={8} fill={color} className="pointer-events-none opacity-70"
            >
              {n.type}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function KnowledgeGraphUI() {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [filterType, setFilterType] = useState<string>("All");
  const [scale, setScale] = useState(1);
  const canvasRef = useRef<HTMLDivElement>(null);

  const W = 900, H = 560;

  // Filter nodes by type
  const filteredNodes = graphData?.nodes.filter(n =>
    filterType === "All" || n.type === filterType
  ) || [];

  const filteredEdges = graphData?.edges.filter(e =>
    filteredNodes.some(n => n.id === e.from_node) &&
    filteredNodes.some(n => n.id === e.to_node)
  ) || [];

  const positioned = useForceLayout(filteredNodes, filteredEdges, W, H, 100);

  const fetchGraph = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = localStorage.getItem("accessToken");
      const res = await axios.get("/admin/graph/data", {
        headers: { Authorization: `Bearer ${token}` },
      });
      setGraphData(res.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to load graph data.");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSearch = async () => {
    if (!searchQuery.trim()) { fetchGraph(); return; }
    setLoading(true);
    try {
      const token = localStorage.getItem("accessToken");
      const res = await axios.get(`/admin/graph/search?keyword=${encodeURIComponent(searchQuery)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      // Reconstruct mini graph from search results
      const results = res.data.results || [];
      const nodes: Record<string, GraphNode> = {};
      const edges: GraphEdge[] = [];
      results.forEach((r: any) => {
        if (r.from) nodes[r.from] = { id: r.from, name: r.from, type: r.type || "Entity" };
        if (r.to) nodes[r.to] = { id: r.to, name: r.to, type: "Entity" };
        if (r.from && r.to && r.relation) {
          edges.push({ from_node: r.from, relation: r.relation, to_node: r.to });
        }
      });
      setGraphData({
        nodes: Object.values(nodes),
        edges,
        total_nodes: Object.keys(nodes).length,
        total_edges: edges.length,
      });
    } catch {
      setError("Search failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  const nodeTypes = ["All", ...Array.from(new Set(graphData?.nodes.map(n => n.type) || []))];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-800 shrink-0">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Network size={20} className="text-emerald-400" />
              Knowledge Graph
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Explore entity relationships extracted from your documents
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setScale(s => Math.max(0.4, s - 0.2))}
              className="p-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-gray-400 hover:text-white transition"
              title="Zoom out"
            >
              <ZoomOut size={15} />
            </button>
            <span className="text-xs text-gray-400 w-10 text-center">{Math.round(scale * 100)}%</span>
            <button
              onClick={() => setScale(s => Math.min(2, s + 0.2))}
              className="p-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-gray-400 hover:text-white transition"
              title="Zoom in"
            >
              <ZoomIn size={15} />
            </button>
            <button
              onClick={fetchGraph}
              className="p-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-gray-400 hover:text-white transition"
              title="Refresh"
            >
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Search + filters */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2 flex-1 min-w-[200px]">
            <div className="relative flex-1">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => e.key === "Enter" && handleSearch()}
                placeholder="Search entities…"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition"
              />
            </div>
            <button
              onClick={handleSearch}
              className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg transition"
            >
              Search
            </button>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {nodeTypes.map(type => (
              <button
                key={type}
                onClick={() => setFilterType(type)}
                className={`text-xs px-3 py-1.5 rounded-full border transition ${
                  filterType === type
                    ? "bg-brand-600 border-brand-500 text-white"
                    : "bg-gray-800 border-gray-700 text-gray-400 hover:text-white"
                }`}
              >
                {type}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Stats bar */}
      {graphData && (
        <div className="flex items-center gap-6 px-6 py-2.5 bg-gray-900/50 border-b border-gray-800 shrink-0 text-xs text-gray-400">
          <span className="flex items-center gap-1.5">
            <Database size={12} className="text-blue-400" />
            {graphData.total_nodes} nodes
          </span>
          <span className="flex items-center gap-1.5">
            <GitBranch size={12} className="text-emerald-400" />
            {graphData.total_edges} edges
          </span>
          {filterType !== "All" && (
            <span className="flex items-center gap-1.5">
              <Network size={12} className="text-violet-400" />
              Showing: {filteredNodes.length} {filterType} nodes
            </span>
          )}

          {/* Legend */}
          <div className="flex items-center gap-3 ml-auto flex-wrap">
            {Object.entries(TYPE_COLORS).slice(0, 5).map(([type, color]) => (
              <span key={type} className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
                <span>{type}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Canvas */}
      <div className="flex-1 overflow-hidden relative bg-gray-950" ref={canvasRef}>
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-950/80 z-20">
            <div className="flex flex-col items-center gap-3">
              <Loader2 size={32} className="text-brand-400 animate-spin" />
              <p className="text-sm text-gray-400">Loading knowledge graph…</p>
            </div>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center p-8 bg-gray-900 border border-gray-800 rounded-2xl max-w-sm">
              <AlertCircle size={40} className="mx-auto text-red-400 mb-3" />
              <p className="text-white font-semibold mb-1">Graph unavailable</p>
              <p className="text-sm text-gray-400 mb-4">{error}</p>
              <button
                onClick={fetchGraph}
                className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm rounded-lg transition"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {!loading && !error && positioned.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center p-8">
              <Network size={48} className="mx-auto text-gray-600 mb-3" />
              <p className="text-white font-semibold mb-1">No graph data</p>
              <p className="text-sm text-gray-400">
                Upload documents to build the knowledge graph.
              </p>
            </div>
          </div>
        )}

        {positioned.length > 0 && (
          <div
            className="overflow-auto h-full"
            style={{ transform: `scale(${scale})`, transformOrigin: "top left" }}
          >
            <GraphCanvas
              nodes={positioned}
              edges={filteredEdges}
              width={W}
              height={H}
              onNodeClick={setSelectedNode}
            />
          </div>
        )}

        {selectedNode && (
          <NodeTooltip
            node={selectedNode}
            onClose={() => setSelectedNode(null)}
          />
        )}
      </div>

      {/* Bottom: Query runner */}
      <div className="px-6 py-3 border-t border-gray-800 bg-gray-900/50 shrink-0">
        <p className="text-xs text-gray-500 flex items-center gap-1.5">
          <Info size={11} />
          Click any node to inspect it · Use search to explore specific entities · Graph updates automatically on document upload
        </p>
      </div>
    </div>
  );
}
