"use client";

import { useRef, useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";

// ── Types & tool registry ──────────────────────────────────────────────────────

type Status = "live" | "beta" | "soon";
type Tool = {
  href: string; icon: string; name: string; tagline: string;
  status: Status; from: string; to: string; glow: string; zone: [number, number];
};

const TOOLS_LEFT: Tool[] = [
  { href: "/slicer",        icon: "≡", name: "Stacked Slicer", tagline: "STL → board profiles",   status: "live", from: "#7c3aed", to: "#0ea5e9", glow: "124,58,237",  zone: [230, 100] },
  { href: "/photo-to-dxf",  icon: "⊙", name: "Photo → DXF",    tagline: "Vectorize images",        status: "live", from: "#ec4899", to: "#a855f7", glow: "236,72,153", zone: [140, 160] },
  { href: "/dxf-generator", icon: "◇", name: "DXF Generator",  tagline: "Parametric shapes",       status: "live", from: "#10b981", to: "#06b6d4", glow: "16,185,129", zone: [360, 230] },
];
const TOOLS_RIGHT: Tool[] = [
  { href: "/sheet-layout",  icon: "⊞", name: "Sheet Layout",   tagline: "Nesting & optimization", status: "live", from: "#6366f1", to: "#8b5cf6", glow: "99,102,241",  zone: [310, 155] },
  { href: "/panels",        icon: "⬡", name: "3D Panels",      tagline: "Panel design",            status: "beta", from: "#06b6d4", to: "#3b82f6", glow: "6,182,212",   zone: [230, 75]  },
  { href: "/editor",        icon: "✎", name: "DXF Editor",     tagline: "Inspect geometry",        status: "beta", from: "#f59e0b", to: "#ef4444", glow: "245,158,11",  zone: [100, 230] },
];
const ALL_TOOLS = [...TOOLS_LEFT, ...TOOLS_RIGHT];

// ── Math utils ─────────────────────────────────────────────────────────────────

function lerp(a: number, b: number, t: number) { return a + (b - a) * t; }
function clamp(v: number, lo: number, hi: number) { return Math.min(hi, Math.max(lo, v)); }
function easeOut3(t: number) { t = clamp(t, 0, 1); return 1 - (1 - t) ** 3; }

// Spindle target for per-tool action loop (pt ∈ [0, 1], loops every 4s)
function toolMotion(href: string, zone: [number, number], pt: number): [number, number] {
  const [zx, zy] = zone;
  // JS % can return negative values for negative pt (floating-point timing jitter).
  // Normalise to [0, 1) so all index/trig math below is always well-defined.
  pt = ((pt % 1) + 1) % 1;
  switch (href) {
    case "/slicer": {
      // Sweep Y across work area at zone X
      const y = lerp(60, 240, (Math.sin(pt * Math.PI * 2) + 1) / 2);
      return [clamp(zx, 82, 378), clamp(y, 52, 248)];
    }
    case "/photo-to-dxf": {
      // Fast X scan at zone Y
      const x = lerp(90, 370, (Math.sin(pt * Math.PI * 4) + 1) / 2);
      return [x, clamp(zy, 52, 248)];
    }
    case "/dxf-generator": {
      // Trace a rectangle path
      const R = 50;
      const corners: [number, number][] = [
        [zx - R, zy - R * 0.5], [zx + R, zy - R * 0.5],
        [zx + R, zy + R * 0.5], [zx - R, zy + R * 0.5],
      ];
      const seg = clamp(Math.floor(pt * 4) % 4, 0, 3);
      const t2 = easeOut3((pt * 4) % 1);
      const a = corners[seg] ?? corners[0];
      const b = corners[(seg + 1) % 4] ?? corners[0];
      return [clamp(lerp(a[0], b[0], t2), 82, 378), clamp(lerp(a[1], b[1], t2), 52, 248)];
    }
    case "/sheet-layout": {
      // Lissajous-ish scan
      const angle = pt * Math.PI * 6;
      return [lerp(100, 360, (Math.sin(angle) + 1) / 2), lerp(70, 230, (Math.cos(angle * 1.3) + 1) / 2)];
    }
    case "/panels": {
      // Circular orbit around zone
      const angle = pt * Math.PI * 2;
      return [clamp(zx + Math.cos(angle) * 55, 82, 378), clamp(zy + Math.sin(angle) * 55, 52, 248)];
    }
    case "/editor": {
      // Wavy horizontal scan
      const x = lerp(90, 370, pt);
      return [x, clamp(zy + Math.sin(pt * Math.PI * 3) * 45, 52, 248)];
    }
    default:
      return [clamp(zx, 82, 378), clamp(zy, 52, 248)];
  }
}

// ── Feature preview animations (SMIL SVG — only rendered when card is active) ──

function SlicerAnim() {
  return (
    <svg viewBox="0 0 100 80" style={{ width: "100%", height: "100%" }}>
      <polygon points="50,5 82,20 50,36 18,20" fill="rgba(124,58,237,0.12)" stroke="#7c3aed" strokeWidth="1.2" />
      <polygon points="50,36 82,20 82,56 50,72" fill="rgba(124,58,237,0.07)" stroke="#7c3aed" strokeWidth="1" />
      <polygon points="50,36 18,20 18,56 50,72" fill="rgba(14,165,233,0.07)" stroke="#0ea5e9" strokeWidth="1" />
      <line x1="18" x2="82" y1="20" y2="20" stroke="#0ea5e9" strokeWidth="2.5" opacity="0">
        <animate attributeName="y1" values="20;56;56;20" dur="3s" repeatCount="indefinite" calcMode="spline" keySplines="0.4,0,0.6,1;0,0,0,0;0.4,0,0.6,1" />
        <animate attributeName="y2" values="20;56;56;20" dur="3s" repeatCount="indefinite" calcMode="spline" keySplines="0.4,0,0.6,1;0,0,0,0;0.4,0,0.6,1" />
        <animate attributeName="opacity" values="0;1;1;0" dur="3s" repeatCount="indefinite" />
      </line>
      <line x1="18" x2="82" y1="20" y2="20" stroke="rgba(14,165,233,0.3)" strokeWidth="8" opacity="0">
        <animate attributeName="y1" values="20;56;56;20" dur="3s" repeatCount="indefinite" calcMode="spline" keySplines="0.4,0,0.6,1;0,0,0,0;0.4,0,0.6,1" />
        <animate attributeName="y2" values="20;56;56;20" dur="3s" repeatCount="indefinite" calcMode="spline" keySplines="0.4,0,0.6,1;0,0,0,0;0.4,0,0.6,1" />
        <animate attributeName="opacity" values="0;0.6;0.6;0" dur="3s" repeatCount="indefinite" />
      </line>
      <polyline points="18,76 32,76 32,72 68,72 68,76 82,76" fill="none" stroke="#0ea5e9" strokeWidth="1.5" opacity="0.6" />
    </svg>
  );
}

function PhotoAnim() {
  const PX: [number, number, string][] = [
    [8, 8, "rgba(236,72,153,0.65)"], [18, 8, "rgba(168,85,247,0.5)"], [28, 8, "rgba(236,72,153,0.75)"],
    [8, 18, "rgba(168,85,247,0.4)"], [18, 18, "rgba(236,72,153,0.6)"], [28, 18, "rgba(168,85,247,0.55)"],
    [8, 28, "rgba(236,72,153,0.55)"], [18, 28, "rgba(168,85,247,0.7)"], [28, 28, "rgba(236,72,153,0.45)"],
    [8, 38, "rgba(168,85,247,0.6)"], [18, 38, "rgba(236,72,153,0.5)"], [28, 38, "rgba(168,85,247,0.65)"],
  ];
  return (
    <svg viewBox="0 0 100 70" style={{ width: "100%", height: "100%" }}>
      {PX.map(([x, y, fill], i) => <rect key={i} x={x} y={y} width={9} height={9} fill={fill} rx="1" />)}
      <polyline points="52,10 66,22 77,15 92,26" fill="none" stroke="#a855f7" strokeWidth="2" strokeDasharray="60" strokeDashoffset="60">
        <animate attributeName="stroke-dashoffset" values="60;0;0;60" dur="3s" repeatCount="indefinite" calcMode="spline" keySplines="0.4,0,0.2,1;0,0,0,0;0,0,0,0" />
      </polyline>
      <polyline points="52,34 70,40 83,33 93,44" fill="none" stroke="#ec4899" strokeWidth="1.5" strokeDasharray="50" strokeDashoffset="50">
        <animate attributeName="stroke-dashoffset" values="50;0;0;50" dur="3s" begin="0.6s" repeatCount="indefinite" calcMode="spline" keySplines="0.4,0,0.2,1;0,0,0,0;0,0,0,0" />
      </polyline>
      <polyline points="52,52 73,57 86,50" fill="none" stroke="#a855f7" strokeWidth="1" strokeDasharray="40" strokeDashoffset="40">
        <animate attributeName="stroke-dashoffset" values="40;0;0;40" dur="3s" begin="1.2s" repeatCount="indefinite" calcMode="spline" keySplines="0.4,0,0.2,1;0,0,0,0;0,0,0,0" />
      </polyline>
      <line y1="4" y2="66" stroke="rgba(255,255,255,0.65)" strokeWidth="1.5">
        <animate attributeName="x1" values="5;95;95;5" dur="3s" repeatCount="indefinite" />
        <animate attributeName="x2" values="5;95;95;5" dur="3s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0;0.8;0;0" dur="3s" repeatCount="indefinite" />
      </line>
    </svg>
  );
}

function GeneratorAnim() {
  return (
    <svg viewBox="0 0 100 80" style={{ width: "100%", height: "100%" }}>
      <rect x="15" y="18" width="70" height="44" rx="4" fill="none" stroke="#10b981" strokeWidth="2"
        strokeDasharray="228" strokeDashoffset="228">
        <animate attributeName="stroke-dashoffset" values="228;0;0;228" dur="3.5s" repeatCount="indefinite" calcMode="spline" keySplines="0.4,0,0.2,1;0,0,0,0;0,0,0,0" />
      </rect>
      <line x1="15" y1="9" x2="85" y2="9" stroke="#06b6d4" strokeWidth="0.8" strokeDasharray="3 2" opacity="0">
        <animate attributeName="opacity" values="0;0;0.9;0.9;0" dur="3.5s" repeatCount="indefinite" />
      </line>
      <text x="50" y="7" textAnchor="middle" fontSize="7" fill="#06b6d4" fontFamily="monospace" opacity="0">
        70 mm
        <animate attributeName="opacity" values="0;0;1;1;0" dur="3.5s" repeatCount="indefinite" />
      </text>
      <circle cx="50" cy="40" r="9" fill="none" stroke="#06b6d4" strokeWidth="1.5" opacity="0">
        <animate attributeName="opacity" values="0;0;0;1;1;0" dur="3.5s" repeatCount="indefinite" />
        <animate attributeName="r" values="0;0;0;9;9;9" dur="3.5s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}

function LayoutAnim() {
  const PARTS = [
    { x: 14, y: 14, w: 30, h: 20, c: "#6366f1", delay: "0s" },
    { x: 48, y: 14, w: 38, h: 14, c: "#8b5cf6", delay: "0.5s" },
    { x: 14, y: 38, w: 22, h: 28, c: "#6366f1", delay: "1s" },
    { x: 40, y: 32, w: 46, h: 16, c: "#8b5cf6", delay: "1.5s" },
    { x: 40, y: 52, w: 20, h: 12, c: "#6366f1", delay: "2s" },
  ];
  return (
    <svg viewBox="0 0 100 78" style={{ width: "100%", height: "100%" }}>
      <rect x="10" y="10" width="80" height="60" rx="2" fill="rgba(99,102,241,0.04)"
        stroke="rgba(99,102,241,0.4)" strokeWidth="1.2" strokeDasharray="4 2" />
      {PARTS.map((p, i) => (
        <rect key={i} x={p.x} y={p.y} width={p.w} height={p.h} rx="1"
          fill={`${p.c}33`} stroke={p.c} strokeWidth="1" opacity="0">
          <animate attributeName="opacity" values="0;1;1;1;0" dur="3.5s" begin={p.delay} repeatCount="indefinite" />
          <animate attributeName="y" values={`${p.y - 14};${p.y};${p.y};${p.y};${p.y}`}
            dur="3.5s" begin={p.delay} repeatCount="indefinite"
            calcMode="spline" keySplines="0.4,0,0.2,1;0,0,0,0;0,0,0,0;0,0,0,0" />
        </rect>
      ))}
    </svg>
  );
}

function PanelsAnim() {
  const items = Array.from({ length: 12 }, (_, i) => ({
    cx: 14 + (i % 4) * 22, cy: 18 + Math.floor(i / 4) * 22, delay: `${i * 0.12}s`,
  }));
  return (
    <svg viewBox="0 0 100 80" style={{ width: "100%", height: "100%" }}>
      {items.map((d, i) => (
        <polygon key={i}
          points={`${d.cx},${d.cy - 9} ${d.cx + 10},${d.cy} ${d.cx},${d.cy + 9} ${d.cx - 10},${d.cy}`}
          fill="rgba(6,182,212,0.12)" stroke="#06b6d4" strokeWidth="0.9" opacity="0">
          <animate attributeName="opacity" values="0;0.9;0.9;0.9;0" dur="3.5s" begin={d.delay} repeatCount="indefinite" />
        </polygon>
      ))}
    </svg>
  );
}

function EditorAnim() {
  return (
    <svg viewBox="0 0 100 70" style={{ width: "100%", height: "100%" }}>
      {[20, 40, 60, 80].map(x => <line key={`v${x}`} x1={x} y1="5" x2={x} y2="65" stroke="rgba(255,255,255,0.04)" strokeWidth="0.5" />)}
      {[15, 30, 45, 60].map(y => <line key={`h${y}`} x1="5" y1={y} x2="95" y2={y} stroke="rgba(255,255,255,0.04)" strokeWidth="0.5" />)}
      <polyline fill="none" stroke="#f59e0b" strokeWidth="1.6" opacity="0.7">
        <animate attributeName="points"
          values="10,55 28,35 50,45 72,20 90,32;10,55 28,35 50,22 72,20 90,32;10,55 28,35 50,45 72,20 90,32;10,55 28,35 50,58 72,20 90,32;10,55 28,35 50,45 72,20 90,32"
          dur="4s" repeatCount="indefinite" calcMode="spline"
          keySplines="0.4,0,0.6,1;0.4,0,0.6,1;0.4,0,0.6,1;0.4,0,0.6,1" />
      </polyline>
      {([[10, 55], [28, 35], [72, 20], [90, 32]] as [number, number][]).map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="3.5" fill="rgba(245,158,11,0.15)" stroke="#f59e0b" strokeWidth="1" />
      ))}
      <circle cx="50" r="4.5" fill="#f59e0b" stroke="white" strokeWidth="1.5">
        <animate attributeName="cy" values="45;22;45;58;45" dur="4s" repeatCount="indefinite"
          calcMode="spline" keySplines="0.4,0,0.6,1;0.4,0,0.6,1;0.4,0,0.6,1;0.4,0,0.6,1" />
      </circle>
    </svg>
  );
}

const ANIM_MAP: Record<string, () => React.ReactElement> = {
  "/slicer": SlicerAnim,
  "/photo-to-dxf": PhotoAnim,
  "/dxf-generator": GeneratorAnim,
  "/sheet-layout": LayoutAnim,
  "/panels": PanelsAnim,
  "/editor": EditorAnim,
};

// ── CNC Machine SVG — detailed realistic machine, no SMIL ─────────────────────

function CncMachine({ svgRef }: { svgRef: React.RefObject<SVGSVGElement | null> }) {
  const slots = [52, 79, 106, 133, 160, 187, 214, 241]; // T-slot Y positions
  const marks = [52, 79, 106, 133, 160, 187, 214, 241]; // rail scale marks

  return (
    <svg ref={svgRef} viewBox="0 0 460 300"
      style={{ width: "100%", height: "auto", display: "block", overflow: "visible" }}>

      {/* ── Outer frame ── */}
      <rect x="1" y="1" width="458" height="298" rx="14"
        fill="rgba(4,4,20,0.96)" stroke="rgba(124,58,237,0.28)" strokeWidth="1.5" />

      {/* ── Status bar ── */}
      <rect x="1" y="1" width="458" height="26" rx="14" fill="rgba(124,58,237,0.07)" />
      <rect x="1" y="13" width="458" height="14" fill="rgba(124,58,237,0.07)" />
      <circle data-mid="led-0" cx="17" cy="13" r="3.8" fill="#22c55e" />
      <circle data-mid="led-1" cx="33" cy="13" r="3.8" fill="#f59e0b" />
      <circle data-mid="led-2" cx="49" cy="13" r="3.8" fill="#7c3aed" />
      <text x="162" y="17" textAnchor="middle" fontSize="7" fill="rgba(255,255,255,0.20)" fontFamily="monospace">CNC-5 GANTRY ROUTER</text>
      <text x="318" y="17" textAnchor="middle" fontSize="7" fill="rgba(14,165,233,0.42)" fontFamily="monospace">STATUS: READY</text>

      {/* ── Left Y-axis rail assembly ── */}
      <rect x="2" y="26" width="44" height="252" rx="4"
        fill="rgba(124,58,237,0.07)" stroke="rgba(124,58,237,0.30)" strokeWidth="1" />
      {/* Linear guide rails (two grooves) */}
      <line x1="12" y1="30" x2="12" y2="274" stroke="rgba(255,255,255,0.17)" strokeWidth="1.3" />
      <line x1="34" y1="30" x2="34" y2="274" stroke="rgba(255,255,255,0.17)" strokeWidth="1.3" />
      {/* Ballscrew / leadscrew */}
      <line x1="23" y1="32" x2="23" y2="272" stroke="rgba(124,58,237,0.26)" strokeWidth="0.6" strokeDasharray="4 6" />
      {/* Limit switches */}
      <rect x="6" y="28" width="8" height="6" rx="1.5" fill="rgba(34,197,94,0.16)" stroke="rgba(34,197,94,0.42)" strokeWidth="0.7" />
      <rect x="6" y="270" width="8" height="6" rx="1.5" fill="rgba(34,197,94,0.16)" stroke="rgba(34,197,94,0.42)" strokeWidth="0.7" />
      {marks.map((y, i) => <line key={i} x1="38" y1={y} x2="44" y2={y} stroke="rgba(124,58,237,0.28)" strokeWidth="0.7" />)}

      {/* ── Right Y-axis rail assembly ── */}
      <rect x="414" y="26" width="44" height="252" rx="4"
        fill="rgba(124,58,237,0.07)" stroke="rgba(124,58,237,0.30)" strokeWidth="1" />
      <line x1="424" y1="30" x2="424" y2="274" stroke="rgba(255,255,255,0.17)" strokeWidth="1.3" />
      <line x1="446" y1="30" x2="446" y2="274" stroke="rgba(255,255,255,0.17)" strokeWidth="1.3" />
      <line x1="435" y1="32" x2="435" y2="272" stroke="rgba(124,58,237,0.26)" strokeWidth="0.6" strokeDasharray="4 6" />
      <rect x="446" y="28" width="8" height="6" rx="1.5" fill="rgba(34,197,94,0.16)" stroke="rgba(34,197,94,0.42)" strokeWidth="0.7" />
      <rect x="446" y="270" width="8" height="6" rx="1.5" fill="rgba(34,197,94,0.16)" stroke="rgba(34,197,94,0.42)" strokeWidth="0.7" />
      {marks.map((y, i) => <line key={i} x1="416" y1={y} x2="422" y2={y} stroke="rgba(124,58,237,0.28)" strokeWidth="0.7" />)}

      {/* ── Work bed (T-slot aluminium table) ── */}
      <rect x="46" y="26" width="368" height="252" rx="2"
        fill="rgba(5,7,20,0.92)" stroke="rgba(14,165,233,0.12)" strokeWidth="0.8" />
      {/* T-slot grooves viewed from above */}
      {slots.map((y, i) => (
        <g key={i}>
          <rect x="48" y={y - 1.5} width="364" height="3" rx="0.5" fill="rgba(2,4,14,0.98)" />
          <line x1="48" y1={y - 1.5} x2="412" y2={y - 1.5} stroke="rgba(14,165,233,0.13)" strokeWidth="0.5" />
          <line x1="48" y1={y + 1.5} x2="412" y2={y + 1.5} stroke="rgba(14,165,233,0.06)" strokeWidth="0.4" />
        </g>
      ))}
      {/* Subtle vertical cross-grid */}
      {[92, 138, 184, 230, 276, 322, 368].map(x => (
        <line key={x} x1={x} y1="26" x2={x} y2="278" stroke="rgba(255,255,255,0.018)" strokeWidth="0.5" />
      ))}
      {/* Bed edge profiles */}
      <rect x="46" y="26" width="5" height="252" fill="rgba(14,165,233,0.04)" />
      <rect x="409" y="26" width="5" height="252" fill="rgba(14,165,233,0.04)" />

      {/* ── Material / stock block ── */}
      <rect x="88" y="66" width="160" height="160" rx="2"
        fill="rgba(255,255,255,0.016)" stroke="rgba(255,255,255,0.09)" strokeWidth="1" />
      {[78, 91, 104, 117, 130, 143, 156, 169, 182, 195, 208].map((y, i) => (
        <line key={i} x1="90" y1={y} x2="246" y2={y} stroke="rgba(180,140,90,0.032)" strokeWidth="0.5" />
      ))}

      {/* ── T-slot hold-down clamps ── */}
      {([[88, 66], [248, 66], [88, 226], [248, 226]] as [number, number][]).map(([cx, cy], i) => (
        <g key={i}>
          <rect x={cx - 9} y={cy - 5} width="18" height="10" rx="2"
            fill="rgba(255,255,255,0.05)" stroke="rgba(255,255,255,0.16)" strokeWidth="0.8" />
          <circle cx={cx} cy={cy} r="2.5" fill="none" stroke="rgba(255,255,255,0.17)" strokeWidth="0.5" />
          <line x1={cx - 1.8} y1={cy} x2={cx + 1.8} y2={cy} stroke="rgba(255,255,255,0.17)" strokeWidth="0.5" />
          <line x1={cx} y1={cy - 1.8} x2={cx} y2={cy + 1.8} stroke="rgba(255,255,255,0.17)" strokeWidth="0.5" />
        </g>
      ))}

      {/* Tool path ghost */}
      <path d="M 92 70 L 244 70 L 244 222 L 92 222 Z"
        fill="none" stroke="rgba(14,165,233,0.07)" strokeWidth="0.8" strokeDasharray="5 8" />

      {/* ── Cut trail (drawn during action state) ── */}
      <polyline data-mid="cut-trail" fill="none" stroke="rgba(14,165,233,0.55)"
        strokeWidth="1.3" opacity="0" strokeLinecap="round" strokeLinejoin="round" />

      {/* ── Y-axis cable drag chain ── */}
      <path data-mid="cable-path" d="M 38,42 Q 18,87 38,133"
        fill="none" stroke="rgba(124,58,237,0.22)" strokeWidth="2.5" strokeLinecap="round" />

      {/* ── Gantry assembly (Y-axis — entire group translates in Y) ── */}
      <g data-mid="gantry-group">
        {/* Left Y-carriage block */}
        <rect x="2" y="120" width="46" height="26" rx="3"
          fill="rgba(14,165,233,0.16)" stroke="rgba(14,165,233,0.50)" strokeWidth="1.2" />
        <rect x="7" y="124" width="13" height="7" rx="2"
          fill="rgba(255,255,255,0.09)" stroke="rgba(255,255,255,0.19)" strokeWidth="0.5" />
        <rect x="7" y="135" width="13" height="7" rx="2"
          fill="rgba(255,255,255,0.09)" stroke="rgba(255,255,255,0.19)" strokeWidth="0.5" />
        {/* Cable exit port */}
        <rect x="44" y="129" width="5" height="8" rx="1"
          fill="rgba(14,165,233,0.09)" stroke="rgba(14,165,233,0.26)" strokeWidth="0.5" />

        {/* Right Y-carriage block */}
        <rect x="412" y="120" width="46" height="26" rx="3"
          fill="rgba(14,165,233,0.16)" stroke="rgba(14,165,233,0.50)" strokeWidth="1.2" />
        <rect x="439" y="124" width="13" height="7" rx="2"
          fill="rgba(255,255,255,0.09)" stroke="rgba(255,255,255,0.19)" strokeWidth="0.5" />
        <rect x="439" y="135" width="13" height="7" rx="2"
          fill="rgba(255,255,255,0.09)" stroke="rgba(255,255,255,0.19)" strokeWidth="0.5" />

        {/* Gantry beam */}
        <rect x="46" y="126" width="368" height="14" rx="3"
          fill="rgba(14,165,233,0.22)" stroke="rgba(14,165,233,0.70)" strokeWidth="1.4" />
        {/* X linear rail lines on beam face */}
        <line x1="48" y1="128.5" x2="412" y2="128.5" stroke="rgba(255,255,255,0.22)" strokeWidth="0.9" />
        <line x1="48" y1="137" x2="412" y2="137" stroke="rgba(255,255,255,0.11)" strokeWidth="0.6" />
        {/* X ballscrew */}
        <line x1="56" y1="133" x2="404" y2="133" stroke="rgba(14,165,233,0.30)" strokeWidth="0.6" strokeDasharray="5 5" />
        {/* X limit switches */}
        <rect x="48" y="127" width="6" height="6" rx="1"
          fill="rgba(34,197,94,0.12)" stroke="rgba(34,197,94,0.32)" strokeWidth="0.6" />
        <rect x="406" y="127" width="6" height="6" rx="1"
          fill="rgba(34,197,94,0.12)" stroke="rgba(34,197,94,0.32)" strokeWidth="0.6" />
      </g>

      {/* ── Spindle assembly (X+Y axes — group translated by RAF) ── */}
      <g data-mid="spindle-group" transform="translate(230,133)">
        {/* X-carriage plate */}
        <rect x="-20" y="-26" width="40" height="22" rx="3"
          fill="rgba(124,58,237,0.18)" stroke="rgba(124,58,237,0.52)" strokeWidth="1.2" />
        {/* Bearing pads */}
        <rect x="-16" y="-24" width="11" height="6" rx="1.5"
          fill="rgba(255,255,255,0.10)" stroke="rgba(255,255,255,0.21)" strokeWidth="0.5" />
        <rect x="5" y="-24" width="11" height="6" rx="1.5"
          fill="rgba(255,255,255,0.10)" stroke="rgba(255,255,255,0.21)" strokeWidth="0.5" />
        {/* Z-column / router mount plate */}
        <rect x="-12" y="-4" width="24" height="18" rx="2"
          fill="rgba(124,58,237,0.11)" stroke="rgba(124,58,237,0.26)" strokeWidth="0.7" />
        {/* Spindle body (router motor housing) */}
        <circle cx="0" cy="0" r="14"
          fill="rgba(124,58,237,0.30)" stroke="#7c3aed" strokeWidth="1.8" />
        {/* Rotation ring — transform (rotate) driven by RAF */}
        <circle data-mid="spindle-ring" cx="0" cy="0" r="10"
          fill="none" stroke="rgba(124,58,237,0.36)" strokeWidth="0.7" strokeDasharray="3 4" />
        {/* Collet chuck */}
        <circle cx="0" cy="0" r="5.5"
          fill="rgba(124,58,237,0.65)" stroke="rgba(255,255,255,0.58)" strokeWidth="1.2" />
        <circle cx="0" cy="0" r="2.5" fill="rgba(255,255,255,0.30)" />
        {/* Collet nut */}
        <path d="M -4.5,9 L -3,15 L 3,15 L 4.5,9 Z"
          fill="rgba(255,255,255,0.07)" stroke="rgba(255,255,255,0.14)" strokeWidth="0.5" />
        {/* Tool bit */}
        <rect x="-1.5" y="15" width="3" height="9" rx="0.8"
          fill="rgba(210,215,230,0.16)" stroke="rgba(255,255,255,0.22)" strokeWidth="0.5" />
        {/* Dust shoe (dashed circle around bit tip) */}
        <circle cx="0" cy="19" r="8"
          fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="1" strokeDasharray="2 3" />
        {/* Cut glow — fill/opacity driven by RAF */}
        <circle data-mid="cut-glow" cx="0" cy="19" r="11"
          fill="rgba(124,58,237,0)" opacity="0" />
      </g>

      {/* ── Active zone hotspot ── */}
      <circle data-mid="hotspot-ring" cx="230" cy="133" r="22"
        fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth="1.5" opacity="0" />
      <circle data-mid="hotspot-dot" cx="230" cy="133" r="5"
        fill="rgba(255,255,255,0.9)" opacity="0" />

      {/* ── Bottom panel ── */}
      <rect x="1" y="278" width="458" height="21" rx="14"
        fill="rgba(124,58,237,0.04)" stroke="rgba(124,58,237,0.15)" strokeWidth="0.8" />
      {/* Coordinate readout */}
      <rect x="4" y="280" width="130" height="17" rx="3"
        fill="rgba(245,158,11,0.06)" stroke="rgba(245,158,11,0.18)" strokeWidth="0.7" />
      <text data-mid="coord-readout" x="69" y="291" textAnchor="middle"
        fontSize="7" fill="rgba(245,158,11,0.58)" fontFamily="monospace">X:230.0 Y:133.0</text>
      {/* RPM readout */}
      <rect x="140" y="280" width="86" height="17" rx="3"
        fill="rgba(14,165,233,0.06)" stroke="rgba(14,165,233,0.18)" strokeWidth="0.7" />
      <text data-mid="rpm-readout" x="183" y="291" textAnchor="middle"
        fontSize="7" fill="rgba(14,165,233,0.52)" fontFamily="monospace">RPM: 18000</text>
      {/* Feed rate readout */}
      <rect x="232" y="280" width="92" height="17" rx="3"
        fill="rgba(124,58,237,0.06)" stroke="rgba(124,58,237,0.18)" strokeWidth="0.7" />
      <text data-mid="feed-readout" x="278" y="291" textAnchor="middle"
        fontSize="7" fill="rgba(124,58,237,0.52)" fontFamily="monospace">F: 2500 mm/m</text>
      {/* Control buttons */}
      <rect x="330" y="280" width="126" height="17" rx="3"
        fill="rgba(14,165,233,0.04)" stroke="rgba(14,165,233,0.14)" strokeWidth="0.7" />
      {[342, 356, 370, 384, 398, 412, 426, 440].map((x, i) => (
        <circle key={i} cx={x} cy={288.5} r="2.8"
          fill={i === 0 ? "rgba(239,68,68,0.75)" : i === 1 ? "rgba(251,191,36,0.60)" : i === 2 ? "rgba(34,197,94,0.60)" : "rgba(255,255,255,0.10)"} />
      ))}
    </svg>
  );
}

// ── Feature node card ──────────────────────────────────────────────────────────

function FeatureNode({ tool, side, onEnter, isActive, onHover }: {
  tool: Tool; side: "left" | "right";
  onEnter: (href: string) => void;
  isActive: boolean;
  onHover: (href: string | null) => void;
}) {
  const AnimComp = ANIM_MAP[tool.href];
  const statusColor = tool.status === "live" ? "#86efac"
    : tool.status === "beta" ? "#fde68a" : "rgba(255,255,255,0.25)";
  const connectorStyle: React.CSSProperties = side === "left"
    ? { borderRight: `2px solid ${isActive ? `rgba(${tool.glow},0.7)` : "rgba(255,255,255,0.06)"}` }
    : { borderLeft: `2px solid ${isActive ? `rgba(${tool.glow},0.7)` : "rgba(255,255,255,0.06)"}` };

  return (
    <div
      onMouseEnter={() => onHover(tool.href)}
      onMouseLeave={() => onHover(null)}
      onClick={() => onEnter(tool.href)}
      style={{
        position: "relative", padding: "12px 14px", borderRadius: 12, cursor: "pointer",
        border: `1px solid ${isActive ? `rgba(${tool.glow},0.40)` : "rgba(255,255,255,0.07)"}`,
        background: isActive ? `rgba(${tool.glow},0.07)` : "rgba(255,255,255,0.022)",
        backdropFilter: "blur(18px)", WebkitBackdropFilter: "blur(18px)",
        transition: "border-color 0.25s, background 0.25s, box-shadow 0.25s",
        boxShadow: isActive
          ? `0 0 28px rgba(${tool.glow},0.16), 0 8px 32px rgba(0,0,0,0.4)`
          : "0 2px 16px rgba(0,0,0,0.2)",
        userSelect: "none",
        ...connectorStyle,
      }}
    >
      {/* Accent top bar */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, height: 2,
        borderRadius: "12px 12px 0 0",
        background: `linear-gradient(90deg, ${tool.from}, ${tool.to})`,
        opacity: isActive ? 1 : 0.3, transition: "opacity 0.25s",
      }} />

      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <div style={{
          width: 30, height: 30, borderRadius: 8, flexShrink: 0,
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: 17,
          background: `linear-gradient(135deg, ${tool.from}20, ${tool.to}20)`,
          border: `1px solid ${tool.from}40`,
          color: isActive ? tool.from : "rgba(255,255,255,0.45)",
          filter: isActive ? `drop-shadow(0 0 6px ${tool.from})` : "none",
          transition: "color 0.25s, filter 0.25s",
        }}>
          {tool.icon}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 12, fontWeight: 700, letterSpacing: "-0.01em",
            color: isActive ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.58)",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            transition: "color 0.25s",
          }}>
            {tool.name}
          </div>
          <div style={{ fontSize: 10, color: "rgba(255,255,255,0.26)", marginTop: 1 }}>
            {tool.tagline}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 3, flexShrink: 0 }}>
          <span style={{
            width: 5, height: 5, borderRadius: "50%", background: statusColor,
            display: "inline-block",
            boxShadow: tool.status !== "soon" ? `0 0 5px ${statusColor}` : "none",
          }} />
          <span style={{ fontSize: 8, fontWeight: 700, color: statusColor, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            {tool.status}
          </span>
        </div>
      </div>

      {/* Animation preview panel */}
      <div style={{
        height: isActive ? 76 : 0, overflow: "hidden",
        transition: "height 0.32s cubic-bezier(0.22,1,0.36,1)",
      }}>
        <div style={{
          height: 76, borderRadius: 8, overflow: "hidden",
          background: "rgba(0,0,0,0.32)",
          border: `1px solid rgba(${tool.glow},0.18)`,
          marginTop: 10,
        }}>
          {isActive && <AnimComp />}
        </div>
      </div>

      {/* Open CTA */}
      <div style={{
        overflow: "hidden", maxHeight: isActive ? 24 : 0,
        transition: "max-height 0.28s cubic-bezier(0.22,1,0.36,1)",
      }}>
        <div style={{
          marginTop: 8, fontSize: 11, fontWeight: 600,
          textAlign: side === "left" ? "right" : "left",
          background: `linear-gradient(135deg, ${tool.from}, ${tool.to})`,
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
        }}>
          Open →
        </div>
      </div>
    </div>
  );
}

// ── Connector wire ─────────────────────────────────────────────────────────────

function ConnectorWire({ side, activeGlow }: { side: "left" | "right"; activeGlow: string | null }) {
  return (
    <div style={{ width: 24, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{
        width: "100%", height: 1,
        background: activeGlow
          ? `linear-gradient(${side === "left" ? "90deg" : "270deg"}, transparent, ${activeGlow})`
          : "rgba(255,255,255,0.06)",
        transition: "background 0.35s",
      }} />
    </div>
  );
}

// ── Entrance page ──────────────────────────────────────────────────────────────

export default function EntrancePage() {
  const router = useRouter();
  const [leaving, setLeaving] = useState(false);
  const [activeHref, setActiveHref] = useState<string | null>(null);

  // DOM refs
  const heroRef      = useRef<HTMLDivElement>(null);
  const titleRef     = useRef<HTMLHeadingElement>(null);
  const shineRef     = useRef<HTMLDivElement>(null);
  const machineRef   = useRef<HTMLDivElement>(null);
  const machineBoxRef = useRef<HTMLDivElement>(null);
  const svgRef       = useRef<SVGSVGElement>(null);
  const ambientRef   = useRef<HTMLDivElement>(null);

  // Unified animation state machine (written by hover handler, read by RAF)
  const animState = useRef<{
    kind: "idle" | "hover" | "action";
    href: string | null;
    startT: number;
  }>({ kind: "idle", href: null, startT: 0 });

  // Smooth spindle position (lerped each frame)
  const spX   = useRef(230);
  const spY   = useRef(133);
  const spRot = useRef(0);

  // Cut trail points (maintained by RAF, read by SVG polyline)
  const trailRef = useRef<[number, number][]>([]);

  // Title hover state
  const titleHovRef  = useRef(false);
  const titleMxRef   = useRef(0.5);
  const titleLerpRef = useRef(0.5);

  const onTitleMouseEnter = useCallback(() => { titleHovRef.current = true; }, []);
  const onTitleMouseLeave = useCallback(() => { titleHovRef.current = false; }, []);
  const onTitleMouseMove  = useCallback((e: React.MouseEvent<HTMLHeadingElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    titleMxRef.current = clamp((e.clientX - r.left) / r.width, 0, 1);
  }, []);

  // Hover debounce refs
  const hoverTimer  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const actionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleHover = useCallback((href: string | null) => {
    if (hoverTimer.current)  clearTimeout(hoverTimer.current);
    if (actionTimer.current) clearTimeout(actionTimer.current);
    hoverTimer.current = setTimeout(() => {
      setActiveHref(href);
      if (href) {
        animState.current = { kind: "hover", href, startT: performance.now() / 1000 };
        // Upgrade to action after 600ms sustained hover
        actionTimer.current = setTimeout(() => {
          if (animState.current.href === href) {
            animState.current = { kind: "action", href, startT: performance.now() / 1000 };
          }
        }, 600);
      } else {
        animState.current = { kind: "idle", href: null, startT: performance.now() / 1000 };
      }
    }, 100);
  }, []);

  // ── Single unified RAF loop ──────────────────────────────────────────────────
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    // Cache SVG element refs once at mount
    const els = {
      ganGroup:     null as Element | null,
      spGroup:      null as Element | null,
      spRing:       null as Element | null,
      cutTrail:     null as Element | null,
      cutGlow:      null as Element | null,
      cablePath:    null as Element | null,
      leds:         [] as Element[],
      hotspotRing:  null as Element | null,
      hotspotDot:   null as Element | null,
      coordReadout: null as Element | null,
      rpmReadout:   null as Element | null,
      feedReadout:  null as Element | null,
    };
    const svg = svgRef.current;
    if (svg) {
      const q = (s: string) => svg.querySelector(`[data-mid="${s}"]`);
      els.ganGroup     = q("gantry-group");
      els.spGroup      = q("spindle-group");
      els.spRing       = q("spindle-ring");
      els.cutTrail     = q("cut-trail");
      els.cutGlow      = q("cut-glow");
      els.cablePath    = q("cable-path");
      els.leds         = [0, 1, 2].map(i => q(`led-${i}`)).filter(Boolean) as Element[];
      els.hotspotRing  = q("hotspot-ring");
      els.hotspotDot   = q("hotspot-dot");
      els.coordReadout = q("coord-readout");
      els.rpmReadout   = q("rpm-readout");
      els.feedReadout  = q("feed-readout");
    }

    const mouse = { tx: 0, ty: 0, cx: 0, cy: 0 }; // target / current normalised [-1,1]
    const onMouseMove = (e: MouseEvent) => {
      mouse.tx = (e.clientX / window.innerWidth)  * 2 - 1;
      mouse.ty = (e.clientY / window.innerHeight) * 2 - 1;
    };

    let rafId = 0;
    const startTime = performance.now();
    let lastT = 0;
    let lastRpmT = 0;
    let lastRpm = 18000;

    function tick() {
      const now = performance.now();
      const t  = (now - startTime) / 1000;
      const dt = Math.min(t - lastT, 0.05); // cap at 50ms
      lastT = t;

      // ── Mouse lerp ──
      const ML = 0.07;
      mouse.cx += (mouse.tx - mouse.cx) * ML;
      mouse.cy += (mouse.ty - mouse.cy) * ML;
      const { cx: nx, cy: ny } = mouse;

      // ── Parallax / tilt (GPU: transform only) ──
      if (heroRef.current) {
        heroRef.current.style.transform =
          `perspective(1200px) rotateX(${-ny * 5}deg) rotateY(${nx * 5}deg) translateX(${nx * 8}px) translateY(${ny * 4}px)`;
      }
      if (machineRef.current) {
        machineRef.current.style.transform = `translateX(${-nx * 14}px) translateY(${-ny * 9}px)`;
      }

      // ── Title letter-light ──
      if (titleRef.current) {
        const angle = 135 + nx * 18;
        titleLerpRef.current += (titleMxRef.current - titleLerpRef.current) * 0.11;
        const lx = titleLerpRef.current * 100;
        titleRef.current.style.backgroundImage = titleHovRef.current
          ? `radial-gradient(ellipse 20% 120% at ${lx}% 50%, rgba(255,255,255,0.92), rgba(255,255,255,0.05) 55%, transparent 70%), linear-gradient(${angle}deg, #fff 25%, #c4b5fd 58%, #38bdf8 100%)`
          : `linear-gradient(${angle}deg, #fff 25%, #c4b5fd 58%, #38bdf8 100%)`;
      }
      if (shineRef.current) {
        shineRef.current.style.background =
          `radial-gradient(ellipse 70% 50% at ${(nx + 1) * 50}% ${(ny + 1) * 50}%, rgba(255,255,255,0.06), transparent 70%)`;
      }

      // ── State machine → spindle target ──
      const state = animState.current;
      let targetX = 230, targetY = 133, spd = 0.022;

      if (state.kind === "idle") {
        // Slow sinusoidal drift, 9-11s period
        targetX = 230 + Math.sin(t / 5.5) * 110;
        targetY = 133 + Math.sin(t / 4.3) * 60;
        spd = 0.022;
      } else if (state.kind === "hover") {
        const tool = ALL_TOOLS.find(tt => tt.href === state.href);
        if (tool) { targetX = tool.zone[0]; targetY = tool.zone[1]; spd = 0.062; }
      } else {
        // action: per-tool motion loop, 4s period
        const tool = ALL_TOOLS.find(tt => tt.href === state.href);
        if (tool) {
          const pt = ((t - state.startT) % 4) / 4;
          [targetX, targetY] = toolMotion(state.href!, tool.zone, pt);
          spd = 0.075;
        }
      }

      targetX = clamp(targetX, 82, 378);
      targetY = clamp(targetY, 52, 248);
      spX.current += (targetX - spX.current) * spd;
      spY.current += (targetY - spY.current) * spd;
      spRot.current = (spRot.current + dt * 200) % 360; // 200°/s

      const sx = spX.current, sy = spY.current;

      // ── Write machine SVG attributes ──
      const activeTool = state.href ? ALL_TOOLS.find(tt => tt.href === state.href) : null;

      // Gantry group: Y-axis translate only (133 = rest position)
      els.ganGroup?.setAttribute("transform", `translate(0,${(sy - 133).toFixed(1)})`);

      // Spindle group: X+Y with multi-frequency vibration during action
      const vib = state.kind === "action"
        ? Math.sin(t * 31) * 0.50 + Math.sin(t * 47) * 0.28 : 0;
      els.spGroup?.setAttribute("transform",
        `translate(${(sx + vib).toFixed(2)},${(sy + vib * 0.5).toFixed(2)})`);

      // Spindle ring: rotate in local coords (group's local origin = spindle centre)
      els.spRing?.setAttribute("transform", `rotate(${spRot.current.toFixed(1)})`);

      // Cable drag chain: quadratic bezier from fixed anchor to gantry Y
      const sag = Math.max(4, 38 - Math.abs(sy - 42) * 0.18);
      const mid = ((42 + sy) / 2).toFixed(1);
      els.cablePath?.setAttribute("d",
        `M 38,42 Q ${sag.toFixed(1)},${mid} 38,${sy.toFixed(1)}`);

      // Cut trail + glow (action state only)
      if (state.kind === "action" && activeTool) {
        const trail = trailRef.current;
        trail.push([sx, sy]);
        if (trail.length > 55) trail.splice(0, trail.length - 55);
        if (els.cutTrail && trail.length > 1) {
          els.cutTrail.setAttribute("points", trail.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(" "));
          els.cutTrail.setAttribute("stroke", `rgba(${activeTool.glow},0.60)`);
          els.cutTrail.setAttribute("opacity", "1");
        }
        if (els.cutGlow) {
          const glowPulse = (Math.sin(t * 8) + 1) / 2;
          els.cutGlow.setAttribute("fill", `rgba(${activeTool.glow},${lerp(0.5, 0.9, glowPulse).toFixed(2)})`);
          els.cutGlow.setAttribute("opacity", lerp(0.6, 1, glowPulse).toFixed(2));
        }
      } else {
        trailRef.current.length = 0;
        els.cutTrail?.setAttribute("opacity", "0");
        els.cutGlow?.setAttribute("opacity", "0");
      }

      // LEDs — individual oscillation
      els.leds.forEach((led, i) => {
        const osc = (Math.sin(t * (1.4 + i * 0.35) + i * 2.09) + 1) / 2;
        led.setAttribute("opacity", lerp(0.3, 1, osc).toFixed(3));
      });

      // ── Hotspot (active zone indicator) ──
      if (activeTool && els.hotspotRing && els.hotspotDot) {
        const [hz, vz] = activeTool.zone;
        const pulse = (Math.sin(t * 3.5) + 1) / 2;
        els.hotspotRing.setAttribute("cx", String(hz));
        els.hotspotRing.setAttribute("cy", String(vz));
        els.hotspotRing.setAttribute("r", lerp(16, 26, pulse).toFixed(1));
        els.hotspotRing.setAttribute("opacity", lerp(0.3, 0.9, 1 - pulse).toFixed(3));
        els.hotspotRing.setAttribute("stroke", `rgba(${activeTool.glow},0.85)`);
        els.hotspotDot.setAttribute("cx", String(hz));
        els.hotspotDot.setAttribute("cy", String(vz));
        els.hotspotDot.setAttribute("fill", `rgba(${activeTool.glow},0.9)`);
        els.hotspotDot.setAttribute("opacity", lerp(0.4, 0.9, (Math.sin(t * 5) + 1) / 2).toFixed(3));
      } else {
        els.hotspotRing?.setAttribute("opacity", "0");
        els.hotspotDot?.setAttribute("opacity", "0");
      }

      // Readouts
      if (els.coordReadout) {
        els.coordReadout.textContent = `X:${sx.toFixed(1)} Y:${sy.toFixed(1)}`;
      }
      if (els.rpmReadout) {
        const baseRpm = state.kind === "action" ? 24000 : state.kind === "hover" ? 21000 : 18000;
        if (t - lastRpmT > 0.15) {
          lastRpm = baseRpm + (state.kind === "action" ? Math.round((Math.random() - 0.5) * 400) : 0);
          lastRpmT = t;
        }
        els.rpmReadout.textContent = `RPM: ${lastRpm}`;
      }
      if (els.feedReadout) {
        els.feedReadout.textContent = state.kind === "action" ? "F: 2800 mm/m" : "F: 2500 mm/m";
      }

      // ── Ambient reactive background ──
      if (ambientRef.current) {
        const col = activeTool ? activeTool.glow : "124,58,237";
        const intensity = activeTool ? 0.15 : 0.07;
        ambientRef.current.style.background =
          `radial-gradient(ellipse 80% 50% at 50% 65%, rgba(${col},${intensity}) 0%, transparent 70%)`;
      }

      // Machine glow color
      if (machineBoxRef.current) {
        machineBoxRef.current.style.boxShadow = activeTool
          ? `0 0 60px rgba(${activeTool.glow},0.22), 0 24px 80px rgba(0,0,0,0.6)`
          : "0 16px 60px rgba(0,0,0,0.5)";
      }

      rafId = requestAnimationFrame(tick);
    }

    window.addEventListener("mousemove", onMouseMove, { passive: true });
    rafId = requestAnimationFrame(tick);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      cancelAnimationFrame(rafId);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function enterTool(href: string) {
    setLeaving(true);
    setTimeout(() => router.push(href), 300);
  }

  const activeTool = ALL_TOOLS.find(t => t.href === activeHref) ?? null;
  const activeGlow = activeTool ? `rgba(${activeTool.glow},0.7)` : null;

  return (
    <div style={{
      minHeight: "100vh", position: "relative", overflow: "hidden",
      opacity: leaving ? 0 : 1,
      transform: leaving ? "scale(1.04)" : "scale(1)",
      transition: "opacity 0.3s ease, transform 0.3s ease",
    }}>

      {/* Reactive ambient background — color set by RAF */}
      <div ref={ambientRef} style={{
        position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0,
        transition: "background 0.55s ease",
      }} />

      {/* Star field */}
      <div style={{
        position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0,
        backgroundImage: `
          radial-gradient(circle, rgba(255,255,255,0.55) 1px, transparent 1px),
          radial-gradient(circle, rgba(124,58,237,0.45) 1px, transparent 1px),
          radial-gradient(circle, rgba(14,165,233,0.35) 1px, transparent 1px)
        `,
        backgroundSize: "97px 89px, 157px 141px, 211px 199px",
        backgroundPosition: "0 0, 43px 61px, 91px 33px",
        opacity: 0.35,
      }} />

      {/* Perspective grid floor */}
      <div style={{
        position: "fixed", bottom: 0, left: "-25%", right: "-25%",
        height: "40vh", pointerEvents: "none", zIndex: 0,
        backgroundImage: `
          linear-gradient(rgba(124,58,237,0.18) 1px, transparent 1px),
          linear-gradient(90deg, rgba(14,165,233,0.12) 1px, transparent 1px)
        `,
        backgroundSize: "80px 80px",
        transform: "perspective(600px) rotateX(60deg)",
        transformOrigin: "top center",
        maskImage: "linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.55) 55%)",
        WebkitMaskImage: "linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.55) 55%)",
      }} />

      {/* Ambient orbs */}
      <div style={{ position: "fixed", width: 700, height: 700, borderRadius: "50%", pointerEvents: "none", zIndex: 0, top: "-25%", left: "-18%", background: "radial-gradient(circle, rgba(124,58,237,0.12) 0%, transparent 70%)", animation: "slowOrb 22s ease-in-out infinite" }} />
      <div style={{ position: "fixed", width: 550, height: 550, borderRadius: "50%", pointerEvents: "none", zIndex: 0, bottom: "0%", right: "-12%", background: "radial-gradient(circle, rgba(14,165,233,0.10) 0%, transparent 70%)", animation: "slowOrb 18s ease-in-out infinite reverse" }} />
      <div style={{ position: "fixed", width: 400, height: 400, borderRadius: "50%", pointerEvents: "none", zIndex: 0, top: "30%", right: "10%", background: "radial-gradient(circle, rgba(236,72,153,0.06) 0%, transparent 70%)", animation: "slowOrb 26s ease-in-out infinite 4s" }} />

      {/* Main content */}
      <div style={{
        position: "relative", zIndex: 1, maxWidth: 1120, margin: "0 auto",
        padding: "44px 20px 80px", display: "flex", flexDirection: "column", alignItems: "center",
      }}>

        {/* Hero header */}
        <div style={{ marginBottom: 36, animation: "entranceHeader 0.7s cubic-bezier(0.23,1,0.32,1) both" }}>
          <div ref={heroRef} style={{ textAlign: "center", position: "relative", willChange: "transform", transformOrigin: "center center" }}>
            <div ref={shineRef} style={{ position: "absolute", inset: "-40px -80px", pointerEvents: "none", borderRadius: 32 }} />

            <div style={{
              width: 62, height: 62, borderRadius: 18, margin: "0 auto 20px",
              background: "linear-gradient(135deg, rgba(124,58,237,0.28), rgba(14,165,233,0.18))",
              border: "1px solid rgba(124,58,237,0.38)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 30, animation: "logoPulse 4s ease-in-out infinite",
            }}>◈</div>

            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.28em", textTransform: "uppercase", color: "rgba(255,255,255,0.22)", marginBottom: 14 }}>
              Fabrication Suite
            </div>

            <h1
              ref={titleRef}
              onMouseEnter={onTitleMouseEnter}
              onMouseLeave={onTitleMouseLeave}
              onMouseMove={onTitleMouseMove}
              style={{
                fontSize: "clamp(38px, 5.5vw, 68px)", fontWeight: 800,
                letterSpacing: "-0.045em", lineHeight: 1.05, margin: "0 0 16px",
                backgroundImage: "linear-gradient(135deg, #fff 25%, #c4b5fd 58%, #38bdf8 100%)",
                WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
                cursor: "default", userSelect: "none",
              }}
            >
              CNC Platform
            </h1>

            <p style={{ fontSize: 15, color: "rgba(255,255,255,0.38)", margin: "0 auto 24px", maxWidth: 420, lineHeight: 1.65 }}>
              Six professional fabrication tools — slice, trace, generate, nest, panel, and edit — in one browser-based suite.
            </p>

            <div style={{ display: "flex", gap: 8, justifyContent: "center", alignItems: "center", flexWrap: "wrap" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 12px", borderRadius: 9999, background: "rgba(34,197,94,0.10)", border: "1px solid rgba(34,197,94,0.20)", fontSize: 10, fontWeight: 600, color: "#86efac" }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#22c55e", boxShadow: "0 0 6px #22c55e", display: "inline-block" }} />
                4 tools live
              </span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 12px", borderRadius: 9999, background: "rgba(251,191,36,0.09)", border: "1px solid rgba(251,191,36,0.18)", fontSize: 10, fontWeight: 600, color: "#fde68a" }}>
                2 in beta
              </span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 12px", borderRadius: 9999, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", fontSize: 10, color: "rgba(255,255,255,0.28)" }}>
                v1.0
              </span>
            </div>
          </div>
        </div>

        {/* 3-column layout */}
        <div style={{
          width: "100%", display: "flex", alignItems: "center", gap: 0,
          animation: "cardEntrance 0.6s cubic-bezier(0.23,1,0.32,1) 0.15s both",
        }}>

          {/* Left cards */}
          <div style={{ flex: "0 0 210px", display: "flex", flexDirection: "column", gap: 8 }}>
            {TOOLS_LEFT.map(t => (
              <FeatureNode key={t.href} tool={t} side="left"
                onEnter={enterTool} isActive={activeHref === t.href} onHover={handleHover} />
            ))}
          </div>

          <ConnectorWire side="left" activeGlow={TOOLS_LEFT.some(t => t.href === activeHref) ? activeGlow : null} />

          {/* Machine center */}
          <div ref={machineRef} style={{ flex: 1, minWidth: 0, willChange: "transform" }}>
            <div ref={machineBoxRef} style={{
              borderRadius: 16, overflow: "hidden",
              transition: "box-shadow 0.45s",
              boxShadow: "0 16px 60px rgba(0,0,0,0.5)",
            }}>
              <CncMachine svgRef={svgRef} />
            </div>
            <div style={{
              textAlign: "center", marginTop: 10,
              fontSize: 9, color: "rgba(255,255,255,0.18)",
              fontFamily: "monospace", letterSpacing: "0.12em", textTransform: "uppercase",
            }}>
              {activeHref
                ? `● ${ALL_TOOLS.find(t => t.href === activeHref)?.name} — hover to preview`
                : "◈ CNC-5 Gantry Router — hover a tool to activate"}
            </div>
          </div>

          <ConnectorWire side="right" activeGlow={TOOLS_RIGHT.some(t => t.href === activeHref) ? activeGlow : null} />

          {/* Right cards */}
          <div style={{ flex: "0 0 210px", display: "flex", flexDirection: "column", gap: 8 }}>
            {TOOLS_RIGHT.map(t => (
              <FeatureNode key={t.href} tool={t} side="right"
                onEnter={enterTool} isActive={activeHref === t.href} onHover={handleHover} />
            ))}
          </div>
        </div>

        {/* Footer */}
        <div style={{ marginTop: 36, textAlign: "center", animation: "cardEntrance 0.55s cubic-bezier(0.23,1,0.32,1) 0.4s both" }}>
          <button
            onClick={() => enterTool("/dashboard")}
            style={{
              background: "none", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 9,
              cursor: "pointer", padding: "8px 20px", fontSize: 12,
              color: "rgba(255,255,255,0.32)", display: "inline-flex", alignItems: "center", gap: 6,
              fontFamily: "inherit", transition: "color 0.2s, border-color 0.2s, background 0.2s",
            }}
            onMouseEnter={e => {
              e.currentTarget.style.color = "rgba(255,255,255,0.72)";
              e.currentTarget.style.borderColor = "rgba(255,255,255,0.18)";
              e.currentTarget.style.background = "rgba(255,255,255,0.04)";
            }}
            onMouseLeave={e => {
              e.currentTarget.style.color = "rgba(255,255,255,0.32)";
              e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
              e.currentTarget.style.background = "none";
            }}
          >
            View full dashboard →
          </button>
        </div>

      </div>
    </div>
  );
}
