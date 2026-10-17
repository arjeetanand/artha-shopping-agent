import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { getTasteGraph, getTasteProfile, syncRetailerAccount, getProfileConnections, getTasteMemories, getProfileInvoices, invoiceDownloadUrl, cancelRetailerSync, disconnectRetailer, removeTasteMemory, reindexTasteMemories } from '../lib/api';
import '../taste-graph.css';

const RETAILER_CONFIG = {
  amazon: { name: 'Amazon India', color: '#B54708', badge: 'AMZN' },
  flipkart: { name: 'Flipkart', color: '#2D5BD1', badge: 'FK' },
  ajio: { name: 'Ajio Luxe', color: '#A94F32', badge: 'AJIO' },
  myntra: { name: 'Myntra Fashion', color: '#C25E3E', badge: 'MYNT' },
  instagram: { name: 'Instagram', color: '#A94F32', badge: 'IG' },
};
const ACTIVE_SYNC_STATES = new Set(['connecting','awaiting_login','syncing','indexing']);

export function TasteGraphView({ onClose, onApplyToSearch, onSignIn, searchId }) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);

  const [graphData, setGraphData] = useState({ nodes: [], links: [], metrics: {} });
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncingProvider, setSyncingProvider] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [hoveredNode, setHoveredNode] = useState(null);
  const [activeFilter, setActiveFilter] = useState('all');
  const [errorMsg, setErrorMsg] = useState('');
  const [showProfileMobile, setShowProfileMobile] = useState(false);
  const [memories, setMemories] = useState([]);
  const [invoices, setInvoices] = useState([]);

  // Physics simulation state refs (to avoid re-renders during 60fps tick)
  const simNodesRef = useRef([]);
  const simLinksRef = useRef([]);
  const animFrameRef = useRef(null);
  const transformRef = useRef({ x: 0, y: 0, scale: 1 });
  const isDraggingNodeRef = useRef(null);
  const isPanningRef = useRef(false);
  const lastMousePosRef = useRef({ x: 0, y: 0 });
  const pulsePhaseRef = useRef(0);

  // Load profile and graph
  const loadData = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    setErrorMsg('');
    try {
      const [graphRes, profileRes, memoryRes, invoiceRes] = await Promise.all([
        getTasteGraph(searchId),
        getTasteProfile(),
        getTasteMemories(),
        getProfileInvoices(),
      ]);
      setGraphData(graphRes);
      setProfile(profileRes);
      setMemories(memoryRes.memories || []);
      setInvoices(invoiceRes.invoices || []);
      initSimulation(graphRes.nodes, graphRes.links);
    } catch (err) {
      setErrorMsg(err.message || 'Failed to load Shopping OS knowledge graph');
    } finally {
      setLoading(false);
    }
  }, [searchId]);

  useEffect(() => {
    loadData();
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [loadData]);

  const hasActiveSync = (profile?.connected_accounts || []).some(connection => ACTIVE_SYNC_STATES.has(connection.status));
  useEffect(() => {
    if (!hasActiveSync) return undefined;
    let disposed = false;
    const timer = window.setInterval(async () => {
      try {
        const data = await getProfileConnections();
        if (disposed) return;
        setProfile(current => ({...current,connected_accounts:data.connections || []}));
        if (!(data.connections || []).some(connection => ACTIVE_SYNC_STATES.has(connection.status))) await loadData(false);
      } catch (err) { if (!disposed) setErrorMsg(err.message); }
    }, 2000);
    return () => {disposed=true;window.clearInterval(timer);};
  }, [hasActiveSync,loadData]);

  // Handle retailer sync
  const handleSyncRetailer = async (provider) => {
    setSyncingProvider(provider);
    try {
      await syncRetailerAccount(provider);
      await loadData(false);
    } catch (err) {
      setErrorMsg(`Sync failed for ${provider}: ${err.message}`);
    } finally {
      setSyncingProvider(null);
    }
  };

  // Initialize Force-Directed Nodes with cosmic radial placement
  const initSimulation = (rawNodes, rawLinks) => {
    const width = containerRef.current ? containerRef.current.clientWidth : 800;
    const height = containerRef.current ? containerRef.current.clientHeight : 600;
    const cx = width / 2;
    const cy = height / 2;

    const existingMap = new Map(simNodesRef.current.map((n) => [n.id, n]));

    const nodes = (rawNodes || []).map((node, index) => {
      const existing = existingMap.get(node.id);
      if (existing) {
        return { ...node, x: existing.x, y: existing.y, vx: existing.vx || 0, vy: existing.vy || 0, radius: node.size || 16 };
      }

      if (node.group === 'root') {
        return { ...node, x: cx, y: cy, vx: 0, vy: 0, radius: 28, fixed: true };
      }

      // Group-based radial orbital clusters
      let distance = 160;
      let angle = (index / (rawNodes.length || 1)) * Math.PI * 2;
      if (node.group === 'store') distance = 110;
      else if (node.group === 'vibe') distance = 170;
      else if (node.group === 'brand') distance = 240;
      else if (node.group === 'size') distance = 190;
      else if (node.group === 'address') distance = 210;
      else if (node.group === 'order') distance = 300 + (index % 4) * 30;
      else if (node.group === 'search') distance = 140;

      return {
        ...node,
        x: cx + Math.cos(angle) * distance + (Math.random() - 0.5) * 40,
        y: cy + Math.sin(angle) * distance + (Math.random() - 0.5) * 40,
        vx: (Math.random() - 0.5) * 2,
        vy: (Math.random() - 0.5) * 2,
        radius: node.size || 16,
      };
    });

    const links = (rawLinks || []).map((link) => ({
      ...link,
      sourceId: typeof link.source === 'object' ? link.source.id : link.source,
      targetId: typeof link.target === 'object' ? link.target.id : link.target,
    }));

    simNodesRef.current = nodes;
    simLinksRef.current = links;

    if (!existingMap.size) {
      const scale = Math.min(width / 850, height / 650, 1);
      transformRef.current = {x:cx*(1-scale),y:cy*(1-scale),scale};
    }
  };

  // Canvas drawing & physics step loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let running = true;

    const render = () => {
      if (!running) return;

      const dpr = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;

      if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
        canvas.width = width * dpr;
        canvas.height = height * dpr;
      }

      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, width, height);

      const nodes = simNodesRef.current;
      const links = simLinksRef.current;
      const nodeMap = new Map(nodes.map((n) => [n.id, n]));
      const cx = width / 2;
      const cy = height / 2;

      // 1. Physics Step
      const kRepulsion = 1800;
      const kSpring = 0.04;
      const damping = 0.88;

      // Repulsion between nodes
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        if (a.fixed && isDraggingNodeRef.current !== a) {
          a.x = cx;
          a.y = cy;
          continue;
        }

        // Mild gravity toward center
        const gdx = cx - a.x;
        const gdy = cy - a.y;
        a.vx += gdx * 0.0008;
        a.vy += gdy * 0.0008;

        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const distSq = dx * dx + dy * dy + 1;
          const dist = Math.sqrt(distSq);
          const minDist = (a.radius + b.radius) * 2.2;

          if (dist < 400) {
            const force = (kRepulsion / distSq) * (dist < minDist ? 2.5 : 1);
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;
            if (!a.fixed) {
              a.vx -= fx;
              a.vy -= fy;
            }
            if (!b.fixed) {
              b.vx += fx;
              b.vy += fy;
            }
          }
        }
      }

      // Spring forces along links
      for (const link of links) {
        const source = nodeMap.get(link.sourceId);
        const target = nodeMap.get(link.targetId);
        if (!source || !target) continue;

        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const idealDist = link.strength ? 120 / link.strength : 120;
        const springForce = (dist - idealDist) * kSpring;
        const fx = (dx / dist) * springForce;
        const fy = (dy / dist) * springForce;

        if (!source.fixed) {
          source.vx += fx;
          source.vy += fy;
        }
        if (!target.fixed) {
          target.vx -= fx;
          target.vy -= fy;
        }
      }

      // Update positions
      for (const node of nodes) {
        if (isDraggingNodeRef.current === node) continue;
        if (node.fixed) continue;
        node.vx *= damping;
        node.vy *= damping;
        node.x += node.vx;
        node.y += node.vy;
      }

      // 2. Rendering Graph with Transform
      const { x: panX, y: panY, scale } = transformRef.current;
      ctx.save();
      ctx.translate(panX, panY);
      ctx.scale(scale, scale);

      pulsePhaseRef.current = (pulsePhaseRef.current + 0.03) % (Math.PI * 2);

      // Draw subtle warm paper grid background
      ctx.strokeStyle = 'rgba(34, 42, 36, 0.05)';
      ctx.lineWidth = 1;
      const gridSize = 60;
      const startX = -panX / scale - 200;
      const endX = (width - panX) / scale + 200;
      const startY = -panY / scale - 200;
      const endY = (height - panY) / scale + 200;

      ctx.beginPath();
      for (let x = Math.floor(startX / gridSize) * gridSize; x < endX; x += gridSize) {
        ctx.moveTo(x, startY);
        ctx.lineTo(x, endY);
      }
      for (let y = Math.floor(startY / gridSize) * gridSize; y < endY; y += gridSize) {
        ctx.moveTo(startX, y);
        ctx.lineTo(endX, y);
      }
      ctx.stroke();

      // Draw Links
      for (const link of links) {
        const source = nodeMap.get(link.sourceId);
        const target = nodeMap.get(link.targetId);
        if (!source || !target) continue;

        const isFiltered = activeFilter !== 'all' && source.group !== activeFilter && target.group !== activeFilter && source.group !== 'root';
        const isHovered = hoveredNode && (source.id === hoveredNode.id || target.id === hoveredNode.id);

        ctx.beginPath();
        ctx.moveTo(source.x, source.y);
        ctx.lineTo(target.x, target.y);

        if (isHovered) {
          ctx.strokeStyle = '#A94F32';
          ctx.lineWidth = 2.5;
          ctx.shadowColor = 'rgba(169, 79, 50, 0.35)';
          ctx.shadowBlur = 8;
        } else if (isFiltered) {
          ctx.strokeStyle = 'rgba(34, 42, 36, 0.05)';
          ctx.lineWidth = 1;
          ctx.shadowBlur = 0;
        } else {
          ctx.strokeStyle = 'rgba(34, 42, 36, 0.16)';
          ctx.lineWidth = 1.2;
          ctx.shadowBlur = 0;
        }
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Animated energy particle moving along edges
        if (!isFiltered) {
          const t = ((pulsePhaseRef.current / (Math.PI * 2)) + (link.sourceId.length % 5) * 0.2) % 1;
          const px = source.x + (target.x - source.x) * t;
          const py = source.y + (target.y - source.y) * t;
          ctx.beginPath();
          ctx.arc(px, py, 2, 0, Math.PI * 2);
          ctx.fillStyle = isHovered ? '#A94F32' : 'rgba(34, 42, 36, 0.35)';
          ctx.fill();
        }
      }

      // Draw Nodes
      for (const node of nodes) {
        const isFiltered = activeFilter !== 'all' && node.group !== activeFilter && node.group !== 'root';
        const isSelected = selectedNode?.id === node.id;
        const isHovered = hoveredNode?.id === node.id;
        const alpha = isFiltered ? 0.2 : 1.0;

        ctx.save();
        ctx.globalAlpha = alpha;

        // Outer glow
        const glowRadius = node.radius + (isSelected ? 12 : isHovered ? 8 : 4);
        const glowGrad = ctx.createRadialGradient(node.x, node.y, node.radius * 0.5, node.x, node.y, glowRadius);
        glowGrad.addColorStop(0, node.color);
        glowGrad.addColorStop(1, 'transparent');
        ctx.beginPath();
        ctx.arc(node.x, node.y, glowRadius, 0, Math.PI * 2);
        ctx.fillStyle = glowGrad;
        ctx.fill();

        // Node Body
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        ctx.fillStyle = node.color;
        ctx.fill();

        // Border
        ctx.strokeStyle = isSelected ? '#1C3027' : isHovered ? '#A94F32' : '#FFFFFF';
        ctx.lineWidth = isSelected ? 3 : isHovered ? 2.5 : 2;
        ctx.stroke();

        // Inner core ring for root / stores
        if (node.group === 'root') {
          const pulse = Math.sin(pulsePhaseRef.current) * 3;
          ctx.beginPath();
          ctx.arc(node.x, node.y, node.radius + 6 + pulse, 0, Math.PI * 2);
          ctx.strokeStyle = 'rgba(28, 48, 39, 0.35)';
          ctx.lineWidth = 2;
          ctx.stroke();
        }

        // Node Label
        ctx.font = node.group === 'root' ? '600 12px system-ui, sans-serif' : '500 11px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';

        // Draw pill background for label for clarity
        const textY = node.y + node.radius + 6;
        const label = node.label;
        const textMetrics = ctx.measureText(label);
        const pillW = textMetrics.width + 12;
        const pillH = 18;

        ctx.fillStyle = isSelected ? '#1C3027' : 'rgba(255, 254, 250, 0.95)';
        ctx.beginPath();
        ctx.roundRect(node.x - pillW / 2, textY, pillW, pillH, 9);
        ctx.fill();
        ctx.strokeStyle = isSelected ? '#1C3027' : isHovered ? '#A94F32' : 'rgba(34, 42, 36, 0.15)';
        ctx.lineWidth = 1;
        ctx.stroke();

        ctx.fillStyle = isSelected ? '#FFFEFA' : isHovered ? '#A94F32' : '#222A24';
        ctx.fillText(label, node.x, textY + 3);

        ctx.restore();
      }

      ctx.restore();
      ctx.restore();

      animFrameRef.current = requestAnimationFrame(render);
    };

    render();

    return () => {
      running = false;
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [activeFilter, selectedNode, hoveredNode]);

  // Coordinate Conversion (Screen -> World)
  const screenToWorld = (screenX, screenY) => {
    const { x: panX, y: panY, scale } = transformRef.current;
    return {
      x: (screenX - panX) / scale,
      y: (screenY - panY) / scale,
    };
  };

  const handleMouseDown = (e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const worldPos = screenToWorld(sx, sy);

    lastMousePosRef.current = { x: sx, y: sy };

    // Hit test nodes
    const nodes = simNodesRef.current;
    let hit = null;
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const dx = worldPos.x - n.x;
      const dy = worldPos.y - n.y;
      if (dx * dx + dy * dy <= (n.radius + 8) * (n.radius + 8)) {
        hit = n;
        break;
      }
    }

    if (hit) {
      isDraggingNodeRef.current = hit;
      setSelectedNode(hit);
    } else {
      isPanningRef.current = true;
      setSelectedNode(null);
    }
  };

  const handleMouseMove = (e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const worldPos = screenToWorld(sx, sy);

    if (isDraggingNodeRef.current) {
      isDraggingNodeRef.current.x = worldPos.x;
      isDraggingNodeRef.current.y = worldPos.y;
      isDraggingNodeRef.current.vx = 0;
      isDraggingNodeRef.current.vy = 0;
      return;
    }

    if (isPanningRef.current) {
      const dx = sx - lastMousePosRef.current.x;
      const dy = sy - lastMousePosRef.current.y;
      transformRef.current.x += dx;
      transformRef.current.y += dy;
      lastMousePosRef.current = { x: sx, y: sy };
      return;
    }

    // Hover detection
    const nodes = simNodesRef.current;
    let hit = null;
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const dx = worldPos.x - n.x;
      const dy = worldPos.y - n.y;
      if (dx * dx + dy * dy <= (n.radius + 8) * (n.radius + 8)) {
        hit = n;
        break;
      }
    }
    setHoveredNode(hit);
    if (canvasRef.current) {
      canvasRef.current.style.cursor = hit ? 'pointer' : 'grab';
    }
  };

  const handleMouseUp = () => {
    isDraggingNodeRef.current = null;
    isPanningRef.current = false;
  };

  const handleWheel = (e) => {
    e.preventDefault();
    const rect = canvasRef.current.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89;
    const newScale = Math.min(Math.max(transformRef.current.scale * zoomFactor, 0.4), 2.8);

    // Zoom towards cursor
    transformRef.current.x = sx - (sx - transformRef.current.x) * (newScale / transformRef.current.scale);
    transformRef.current.y = sy - (sy - transformRef.current.y) * (newScale / transformRef.current.scale);
    transformRef.current.scale = newScale;
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    canvas?.addEventListener('wheel',handleWheel,{passive:false});
    return () => canvas?.removeEventListener('wheel',handleWheel);
  }, []);

  const resetView = () => {
    transformRef.current = { x: 0, y: 0, scale: 1 };
    initSimulation(graphData.nodes, graphData.links);
  };

  const metrics = graphData.metrics || {};
  const depthScore = profile?.stats?.context_depth_score ?? 0;
  const connections = profile?.connected_accounts || [];
  const connectionMap = new Map(connections.map((c) => [c.provider.toLowerCase(), c]));

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#F5F3ED] text-[#222A24]">
      {/* Top Navigation & Status Bar */}
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-[#2D4539] bg-[#1C3027] px-6 py-3.5 text-[#E9EEE7]">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#A94F32] text-white shadow-md shadow-black/20">
            <Icon name="network" size={22} className="text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold text-[#FFFEFA] tracking-tight font-serif">Shopping OS: Taste & Context Graph</h1>
              <span className="rounded-full bg-[#243B31] px-2.5 py-0.5 text-xs font-medium text-[#A3E5B9] border border-[#3A5D4D]">
                Private Taste Memory
              </span>
            </div>
            <p className="text-xs text-[#9EACA3]">
              Connect accounts to read six months of orders and invoices. Shared posts and saved products enrich your taste.
            </p>
          </div>
        </div>

        {/* Depth Score HUD */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3 rounded-2xl border border-[#3A5D4D] bg-[#243B31]/80 px-4 py-2 shadow-inner">
            <div className="relative flex h-10 w-10 items-center justify-center">
              <svg className="h-10 w-10 -rotate-90">
                <circle cx="20" cy="20" r="16" stroke="rgba(255,255,255,0.12)" strokeWidth="3" fill="none" />
                <circle
                  cx="20"
                  cy="20"
                  r="16"
                  stroke="#A94F32"
                  strokeWidth="3.5"
                  strokeDasharray="100"
                  strokeDashoffset={100 - Math.min(depthScore, 100)}
                  strokeLinecap="round"
                  fill="none"
                  className="transition-all duration-700 ease-out"
                />
              </svg>
              <span className="absolute text-xs font-bold text-[#FFFEFA]">{depthScore}%</span>
            </div>
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-[#E58B68]">Context Depth</div>
              <div className="text-xs text-[#9EACA3]">
                <span className="font-semibold text-[#FFFEFA]">{metrics.total_nodes || 0}</span> nodes •{' '}
                <span className="font-semibold text-[#FFFEFA]">{metrics.total_edges || 0}</span> links
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {profile && (
              <button
                type="button"
                onClick={() => loadData(false)}
                disabled={syncingProvider !== null}
                className="taste-os-btn-secondary"
              >
                <Icon name="refresh" size={14} className={syncingProvider ? 'animate-spin' : ''} />
                Refresh graph
              </button>
            )}

            {onApplyToSearch && (
              <button
                type="button"
                onClick={() => {
                  onApplyToSearch(profile?.preferences);
                  if (onClose) onClose();
                }}
                className="taste-os-btn-primary"
              >
                <Icon name="spark" size={14} />
                Apply Taste DNA to Search
              </button>
            )}

            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="taste-os-btn-icon"
                aria-label="Close"
              >
                <Icon name="close" size={18} />
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Connected Retailer Hubs Strip */}
      <div className="flex flex-nowrap items-center gap-3 overflow-x-auto border-b border-[#E5E1D7] bg-[#EBE8DE] px-6 py-2.5 md:flex-wrap text-[#222A24]">
        <span className="text-xs font-medium text-[#596159] flex items-center gap-1.5 shrink-0">
          <Icon name="shoppingBag" size={14} /> Retailer Hubs:
        </span>
        {Object.entries(RETAILER_CONFIG).map(([key, cfg]) => {
          const conn = connectionMap.get(key);
          const isConnected = ['connected', 'synced', 'partial'].includes(conn?.status);
          const isSyncing = syncingProvider === key || ACTIVE_SYNC_STATES.has(conn?.status);

          return (
            <div
              key={key}
              className={`flex shrink-0 items-center gap-2 rounded-xl border px-3 py-1.5 text-xs transition ${
                isConnected
                  ? 'border-[#DED9CC] bg-[#FFFEFA] text-[#222A24] shadow-sm'
                  : 'border-[#E5E1D7] bg-[#F1EFE8] text-[#596159]'
              }`}
            >
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: cfg.color }} />
              <span className="font-semibold text-[#222A24]">{cfg.name}</span>
              <span className="text-[11px] text-[#596159]">
                {isSyncing ? conn?.status?.replaceAll('_',' ') || 'Opening' : key === 'instagram' && isConnected ? 'Connected' : isConnected ? `${conn.synced_orders_count || 0} orders` : conn?.status || 'Not connected'}
              </span>
              <button
                type="button"
                onClick={() => handleSyncRetailer(key)}
                disabled={isSyncing || !profile}
                className="taste-os-chip-btn"
              >
                <Icon name="refresh" size={10} className={isSyncing ? 'animate-spin' : ''} />
                {isSyncing ? 'In progress' : isConnected ? 'Resync' : 'Connect'}
              </button>
            </div>
          );
        })}

        {/* Filter Pills */}
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {['all', 'store', 'vibe', 'brand', 'size', 'address', 'order', 'memory', 'invoice'].map((filt) => (
            <button
              key={filt}
              type="button"
              onClick={() => setActiveFilter(filt)}
              className={`taste-os-filter-pill ${activeFilter === filt ? 'is-active' : ''}`}
            >
              {filt}
            </button>
          ))}
          <button
            type="button"
            onClick={resetView}
            className="taste-os-reset-btn"
            title="Reset Graph Zoom & Position"
          >
            <Icon name="refresh" size={14} />
          </button>
        </div>
      </div>

      {connections.some(connection => connection.details?.message) && (
        <div className="max-h-40 overflow-y-auto border-b border-[#E5E1D7] bg-[#FFFEFA] px-6 py-3 text-xs" aria-live="polite">
          {connections.filter(connection => connection.details?.message).map(connection => (
            <div key={connection.provider} className="mb-2 flex flex-wrap items-center gap-2">
              <strong className="capitalize">{connection.provider}</strong>
              <span>{connection.details.message}</span>
              {connection.details.cutoff && <span>From {connection.details.cutoff} · {connection.details.orders || 0} orders · {connection.details.invoices || 0} invoices · {connection.details.coverage_complete ? 'History checked' : 'Coverage incomplete'}</span>}
              {(connection.details.missing_invoices > 0) && <span>{connection.details.missing_invoices} invoices unavailable</span>}
              <button type="button" className="taste-os-chip-btn" onClick={async () => {
                try {
                  await (ACTIVE_SYNC_STATES.has(connection.status) ? cancelRetailerSync(connection.provider) : disconnectRetailer(connection.provider));
                  await loadData(false);
                } catch (err) {setErrorMsg(err.message);}
              }}>{ACTIVE_SYNC_STATES.has(connection.status) ? 'Cancel sync' : 'Disconnect'}</button>
            </div>
          ))}
        </div>
      )}

      {/* Main Canvas & Sidebar Container */}
      <div ref={containerRef} className="relative flex-1 overflow-hidden bg-[#F5F3ED]">
        <button type="button" onClick={() => setShowProfileMobile((current) => !current)} className="absolute left-4 top-4 z-20 rounded-lg border border-[#DED9CC] bg-[#FFFEFA]/95 px-3 py-2 text-xs font-semibold text-[#A94F32] shadow-sm md:hidden">
          {showProfileMobile ? 'Hide Taste DNA' : 'Show Taste DNA'}
        </button>
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={`Taste graph with ${metrics.total_nodes || 0} nodes. Purchases, saved inspirations, and invoices are listed in Taste DNA.`}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          className="h-full w-full block select-none"
        />

        {/* Hover / Select Floating Card */}
        {(selectedNode || hoveredNode) && (
          <div className="pointer-events-none absolute bottom-6 left-6 z-10 max-w-sm rounded-2xl border border-[#E5E1D7] bg-[#FFFEFA]/95 p-4 shadow-xl backdrop-blur-md">
            {(() => {
              const node = selectedNode || hoveredNode;
              return (
                <div>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="h-3 w-3 rounded-full" style={{ backgroundColor: node.color }} />
                    <span className="text-xs uppercase tracking-wider font-semibold text-[#596159]">{node.group}</span>
                    <span className="ml-auto text-[11px] text-[#828B84]">ID: {node.id}</span>
                  </div>
                  <h3 className="text-sm font-bold text-[#222A24] mb-1 font-serif">{node.label}</h3>
                  {node.meta && (
                    <div className="space-y-1 text-xs text-[#596159]">
                      {node.meta.summary && <p className="text-[#596159] italic">{node.meta.summary}</p>}
                      {node.meta.price && <p className="text-[#287E5D] font-semibold">{node.meta.price}</p>}
                      {node.meta.status && <p className="text-[#596159] capitalize">Status: {node.meta.status}</p>}
                      {node.meta.provider && <p className="text-[#A94F32] font-medium uppercase">Provider: {node.meta.provider}</p>}
                      {node.meta.pincode && <p className="text-[#2D5BD1]">Pincode: {node.meta.pincode}</p>}
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        )}

        {/* Floating Taste DNA Legend & Summary */}
        <div className={`${showProfileMobile ? 'block' : 'hidden'} absolute left-4 right-4 top-16 z-10 max-h-[45vh] overflow-y-auto rounded-2xl border border-[#E5E1D7] bg-[#FFFEFA]/95 p-4 shadow-xl backdrop-blur-md md:top-6 md:right-6 md:left-auto md:block md:max-h-[calc(100vh-260px)] md:w-80 text-[#222A24]`}>
          <div className="flex items-center justify-between mb-3 border-b border-[#E5E1D7] pb-2">
            <h2 className="text-xs font-bold uppercase tracking-wider text-[#222A24] flex items-center gap-1.5">
              <Icon name="spark" size={14} className="text-[#A94F32]" />
              Your Taste Profile DNA
            </h2>
            <span className="text-[11px] text-[#A94F32] font-medium">Auto-Adapting</span>
          </div>

          <div className="space-y-3 text-xs">
            <p>{metrics.tracked_orders || 0} verified orders · {memories.length} memories · {metrics.vectors_ready || 0} semantic vectors</p>
            <p className="text-[#596159]">Purchase titles and saved style summaries use the configured AI model. Invoice PDFs and retailer login sessions stay on this machine.</p>
            {!memories.length && <p>Connect a retailer, save a product, or share a post to start learning your taste.</p>}
            {/* Preferred Aesthetic */}
            <div>
              <div className="text-[11px] text-[#596159] mb-1 font-medium">Primary Aesthetic Vibes</div>
              <div className="flex flex-wrap gap-1.5">
                {(profile?.preferences?.vibes || []).map((vibe) => (
                  <span key={vibe} className="rounded-lg bg-[#FFF0EB] px-2.5 py-1 font-medium text-[#A94F32] border border-[#FCD4C7]">
                    ✨ {vibe}
                  </span>
                ))}
              </div>
            </div>

            {/* Favorite Brands */}
            <div>
              <div className="text-[11px] text-[#596159] mb-1 font-medium">Brand Affinity (from orders)</div>
              <div className="flex flex-wrap gap-1.5">
                {(profile?.preferences?.brands || []).map((brand) => (
                  <span key={brand} className="rounded-lg bg-[#EDF8F1] px-2 py-0.5 font-medium text-[#287E5D] border border-[#C2E8D3]">
                    {brand}
                  </span>
                ))}
              </div>
            </div>

            {/* Sizing & Delivery */}
            <div className="grid grid-cols-2 gap-2 pt-2 border-t border-[#E5E1D7]">
              <div>
                <div className="text-[11px] text-[#596159] mb-0.5">Size DNA</div>
                <div className="font-semibold text-[#B54708]">
                  Top: {profile?.preferences?.sizes?.top || 'Unknown'} • Shoes: {profile?.preferences?.sizes?.shoes || 'Unknown'}
                </div>
              </div>
              <div>
                <div className="text-[11px] text-[#596159] mb-0.5">Primary Hub</div>
                <div className="font-semibold text-[#2D5BD1] truncate">
                  {profile?.preferences?.addresses?.[0] ? `${profile.preferences.addresses[0].city} (${profile.preferences.addresses[0].pincode})` : 'Not set'}
                </div>
              </div>
            </div>
            <div className="border-t border-[#E5E1D7] pt-3">
              <h3 className="mb-2 font-semibold">Saved inspirations</h3>
              {memories.filter(memory => memory.kind !== 'purchase').slice(0,10).map(memory => (
                <div key={memory.id} className="mb-2 flex items-start gap-2">
                  <a className="text-[#287E5D] underline" href={memory.source_url} target="_blank" rel="noreferrer">{memory.attributes.theme || memory.attributes.name || memory.document.slice(0,60)}</a>
                  <button type="button" className="ml-auto text-[#A94F32]" aria-label={`Forget ${memory.attributes.theme || memory.attributes.name || 'inspiration'}`} onClick={async () => {
                    try {await removeTasteMemory(memory.id);await loadData(false);} catch (err) {setErrorMsg(err.message);}
                  }}>Forget</button>
                </div>
              ))}
              {memories.some(memory => memory.embedding_status === 'pending') && <button type="button" className="taste-os-chip-btn" onClick={async () => {
                try {await reindexTasteMemories();await loadData(false);} catch (err) {setErrorMsg(err.message);}
              }}>Retry pending semantic indexing</button>}
            </div>
            <div className="border-t border-[#E5E1D7] pt-3">
              <h3 className="mb-2 font-semibold">Invoices ({invoices.length})</h3>
              {invoices.slice(0,20).map(invoice => <a key={invoice.id} className="mb-1 block text-[#287E5D] underline" href={invoiceDownloadUrl(invoice.id)}>{invoice.provider} · {invoice.retailer_order_id} · PDF</a>)}
            </div>
          </div>
        </div>

        {/* Loading Overlay */}
        {loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-[#F5F3ED]/80 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-3">
              <Icon name="network" size={36} className="animate-pulse text-[#A94F32]" />
              <p className="text-sm font-medium text-[#222A24]">Synthesizing Taste & Order Knowledge Graph...</p>
            </div>
          </div>
        )}

        {/* Error Notification */}
        {errorMsg && (
          <div className="absolute bottom-6 right-6 z-30 max-w-sm rounded-xl border border-[#F8D7DA] bg-[#FFF5F5] p-3 text-xs text-[#991B1B] shadow-xl backdrop-blur">
            {errorMsg}
            {errorMsg.includes('Sign in') && onSignIn && (
              <button type="button" onClick={onSignIn} className="mt-2 block rounded bg-[#A94F32] hover:bg-[#8E3F27] px-3 py-1.5 text-white">
                Sign in with Google
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
