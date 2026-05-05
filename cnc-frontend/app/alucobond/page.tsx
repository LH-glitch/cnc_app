"use client";

// ─────────────────────────────────────────────────────────────────────────────
// Alucobond — Single-wall clean rebuild
//
// Coordinate model (explicit, never implicit):
//   U = wall horizontal axis  → maps to world +X
//   V = wall vertical axis    → maps to world +Y
//   N = outward normal        → maps to world +Z
//
// All panel dimensions stay in mm throughout.
// Only multiply by S = 0.001 when handing values to Three.js.
//
// Layout is computed entirely on the client — no API needed for geometry.
// The backend is called only to render the flat-blank DXF.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useMemo, useEffect, useCallback, Suspense } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const S = 0.001; // mm → metres (Three.js scene units)

// ── Types ─────────────────────────────────────────────────────────────────────

interface WallParams {
  width: number;   // mm
  height: number;  // mm
}

interface CladdingParams {
  offset: number;       // mm  — skin stands this far in front of the wall surface
  panelWidth: number;   // mm
  panelHeight: number;  // mm
  jointGap: number;     // mm
  returnDepth: number;  // mm
  pattern: "horizontal" | "vertical" | "brick";
}

interface Returns { left: number; right: number; top: number; bottom: number; }

interface Panel {
  id: string;
  row: number; col: number; nRows: number; nCols: number;
  // 2D local-wall coordinates (mm). Origin = bottom-left corner of the wall face.
  uStart: number;  // U position of panel left edge
  vStart: number;  // V position of panel bottom edge
  visW: number;    // visible width  (< panelWidth only for trimmed edge panels)
  visH: number;    // visible height (< panelHeight only for trimmed edge panels)
  // Fabrication data
  returns: Returns;   // fold-return depth per side (mm)
  blankW: number;     // flat blank width  = returns.left + visW + returns.right
  blankH: number;     // flat blank height = returns.bottom + visH + returns.top
  type: "interior" | "edge" | "corner";
  foldLines: { axis: "h" | "v"; position: number }[]; // blank-coord positions (mm)
}

// ── Layout — pure function, no side-effects, no API ──────────────────────────

function rowUCols(
  pw: number, gap: number, wallW: number, brickOffset: boolean,
): { uStart: number; visW: number }[] {
  const cols: { uStart: number; visW: number }[] = [];
  let u = 0;
  if (brickOffset) {
    const hw = pw / 2;
    if (hw > 0.5) cols.push({ uStart: 0, visW: Math.min(hw, wallW) });
    u = hw + gap;
  }
  while (u < wallW - 0.5) {
    const visW = Math.min(pw, wallW - u);
    if (visW > 0.5) cols.push({ uStart: u, visW });
    u += pw + gap;
  }
  return cols;
}

function computeLayout(wall: WallParams, c: CladdingParams): Panel[] {
  let pw = c.panelWidth, ph = c.panelHeight;
  if (c.pattern === "vertical") [pw, ph] = [ph, pw];

  // ── V (vertical) rows ────────────────────────────────────────────────────
  const rows: { vStart: number; visH: number }[] = [];
  let v = 0;
  while (v < wall.height - 0.5) {
    const visH = Math.min(ph, wall.height - v);
    if (visH > 0.5) rows.push({ vStart: v, visH });
    v += ph + c.jointGap;
  }
  const nRows = rows.length;
  const panels: Panel[] = [];

  rows.forEach(({ vStart, visH }, ri) => {
    const brickRow = c.pattern === "brick" && ri % 2 === 1;
    const cols = rowUCols(pw, c.jointGap, wall.width, brickRow);
    const nCols = cols.length;

    cols.forEach(({ uStart, visW }, ci) => {
      // Edge detection — within 0.5 mm of wall boundary
      const onLeft   = uStart < 0.5;
      const onRight  = uStart + visW > wall.width - 0.5;
      const onBottom = ri === 0;
      const onTop    = ri === nRows - 1;

      const rd = c.returnDepth;
      const ret: Returns = {
        left:   onLeft   ? rd : 0,
        right:  onRight  ? rd : 0,
        bottom: onBottom ? rd : 0,
        top:    onTop    ? rd : 0,
      };
      const blankW = ret.left + visW + ret.right;
      const blankH = ret.bottom + visH + ret.top;

      const edgeCount = [onLeft, onRight, onBottom, onTop].filter(Boolean).length;
      const type: Panel["type"] =
        edgeCount >= 2 ? "corner" : edgeCount === 1 ? "edge" : "interior";

      // Fold-line positions are in blank coordinates (mm).
      // The blank origin is at the bottom-left corner of the flat blank.
      const foldLines: Panel["foldLines"] = [];
      if (ret.bottom) foldLines.push({ axis: "h", position: ret.bottom });
      if (ret.top)    foldLines.push({ axis: "h", position: ret.bottom + visH });
      if (ret.left)   foldLines.push({ axis: "v", position: ret.left });
      if (ret.right)  foldLines.push({ axis: "v", position: ret.left + visW });

      panels.push({
        id: `P${ri.toString().padStart(2, "0")}-${ci.toString().padStart(2, "0")}`,
        row: ri, col: ci, nRows, nCols,
        uStart, vStart, visW, visH,
        returns: ret, blankW, blankH, type, foldLines,
      });
    });
  });

  return panels;
}

// ── 2D → 3D transform (the one place this math lives) ────────────────────────
//
//   Wall is centred horizontally at X = 0.
//   Wall base sits at Y = 0 (ground level).
//   Wall surface is at Z = 0.
//   Cladding skin sits at Z = offset * S.
//
//   panel centre in world (metres):
//     x = (uStart + visW/2  −  wallWidth/2) * S
//     y = (vStart + visH/2) * S
//     z = offset * S
//
function worldCentre(p: Panel, wall: WallParams, offset: number): [number, number, number] {
  return [
    (p.uStart + p.visW / 2 - wall.width / 2) * S,
    (p.vStart + p.visH / 2) * S,
    offset * S,
  ];
}

// ── Colours ───────────────────────────────────────────────────────────────────

const TC: Record<string, string> = {
  interior: "#4f7bc8",
  edge:     "#7c5abf",
  corner:   "#b05ab0",
};

// ── 3D: wall surface ──────────────────────────────────────────────────────────

function WallSurface({ wall }: { wall: WallParams }) {
  const W = wall.width * S, H = wall.height * S;
  return (
    <group position={[0, H / 2, 0]}>
      {/* Solid surface */}
      <mesh>
        <planeGeometry args={[W, H]} />
        <meshBasicMaterial color="#0d1c35" transparent opacity={0.65} side={THREE.FrontSide} />
      </mesh>
      {/* Outline at Z+ε to avoid z-fighting with the surface */}
      <mesh position={[0, 0, 0.0005]}>
        <edgesGeometry args={[new THREE.PlaneGeometry(W, H)]} />
        <lineBasicMaterial color="#253a60" />
      </mesh>
    </group>
  );
}

// ── 3D: skin-plane outline ────────────────────────────────────────────────────

function SkinOutline({ wall, offset }: { wall: WallParams; offset: number }) {
  const W = wall.width * S, H = wall.height * S, Z = offset * S;
  return (
    <mesh position={[0, H / 2, Z]}>
      <edgesGeometry args={[new THREE.PlaneGeometry(W, H)]} />
      <lineBasicMaterial color="#6b21a8" transparent opacity={0.45} />
    </mesh>
  );
}

// ── 3D: axis arrows at bottom-left of skin plane ─────────────────────────────

function AxisArrows({ wall, offset }: { wall: WallParams; offset: number }) {
  const originX = -wall.width * S / 2;
  const originZ = offset * S;
  const len = Math.min(wall.width, wall.height) * S * 0.10;
  const origin = new THREE.Vector3(originX, 0, originZ);
  const uArrow = useMemo(
    () => new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), origin, len, 0xff5555, len * 0.28, len * 0.14),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [originX, originZ, len],
  );
  const vArrow = useMemo(
    () => new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), origin, len, 0x55cc55, len * 0.28, len * 0.14),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [originX, originZ, len],
  );
  const nArrow = useMemo(
    () => new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), origin, len, 0x5588ff, len * 0.28, len * 0.14),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [originX, originZ, len],
  );
  return (
    <>
      <primitive object={uArrow} />
      <primitive object={vArrow} />
      <primitive object={nArrow} />
    </>
  );
}

// ── 3D: one panel ─────────────────────────────────────────────────────────────

function PanelMesh({
  p, wall, offset, selectedId, onSelect,
}: {
  p: Panel; wall: WallParams; offset: number;
  selectedId: string | null; onSelect: (p: Panel) => void;
}) {
  const [cx, cy, cz] = worldCentre(p, wall, offset);
  const sel = selectedId === p.id;
  return (
    <group position={[cx, cy, cz]}>
      {/* Panel face */}
      <mesh onClick={(e) => { e.stopPropagation(); onSelect(p); }}>
        <planeGeometry args={[p.visW * S, p.visH * S]} />
        <meshStandardMaterial
          color={sel ? "#f59e0b" : (TC[p.type] ?? TC.interior)}
          emissive={sel ? "#3d1f00" : "#000000"}
          metalness={0.5} roughness={0.4}
          side={THREE.FrontSide}
        />
      </mesh>
      {/* Panel edge lines, nudged forward to stay visible */}
      <mesh position={[0, 0, 0.002]}>
        <edgesGeometry args={[new THREE.PlaneGeometry(p.visW * S, p.visH * S)]} />
        <lineBasicMaterial color="#000000" transparent opacity={0.22} />
      </mesh>
    </group>
  );
}

// ── 3D: camera initialisation ─────────────────────────────────────────────────

function SceneCamera({ wall }: { wall: WallParams }) {
  const { camera } = useThree();
  useEffect(() => {
    const W = wall.width * S, H = wall.height * S;
    const dist = Math.max(W, H) * 1.85;
    camera.position.set(W * 0.30, H * 0.55, dist);
    (camera as THREE.PerspectiveCamera).lookAt(0, H * 0.5, 0);
  }, [wall, camera]);
  return null;
}

// ── UI atoms ──────────────────────────────────────────────────────────────────

function Num({
  label, value, min, max, step, unit, onChange,
}: {
  label: string; value: number; min?: number; max?: number;
  step?: number; unit?: string; onChange: (v: number) => void;
}) {
  return (
    <div style={{ marginBottom: 9 }}>
      <div style={{
        fontSize: 10, fontWeight: 700, textTransform: "uppercase",
        letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 3,
      }}>
        {label}{unit && <span style={{ opacity: 0.5 }}> ({unit})</span>}
      </div>
      <input
        type="number" value={value} min={min} max={max} step={step ?? 1}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{
          width: "100%", background: "rgba(255,255,255,0.06)",
          border: "1px solid rgba(255,255,255,0.12)", borderRadius: 6,
          color: "var(--text-primary)", padding: "5px 9px", fontSize: 13,
          outline: "none", boxSizing: "border-box", fontFamily: "inherit",
        }}
      />
    </div>
  );
}

function Sect({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="glass-sm" style={{ padding: "11px 13px", marginBottom: 10 }}>
      <div style={{
        fontSize: 9, fontWeight: 700, textTransform: "uppercase",
        letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 9,
      }}>
        {label}
      </div>
      {children}
    </div>
  );
}

function KV({ k, v, mono, dim }: { k: string; v: React.ReactNode; mono?: boolean; dim?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 5, fontSize: 12 }}>
      <span style={{ color: "var(--text-subtle)" }}>{k}</span>
      <span style={{
        color: dim ? "var(--text-subtle)" : "var(--text-primary)",
        fontWeight: 600,
        fontFamily: mono ? "monospace" : "inherit",
        fontSize: mono ? 11 : 12,
      }}>
        {v}
      </span>
    </div>
  );
}

// ── Panel inspector (Stage 3 — explicit 2D ↔ 3D verification) ────────────────

function PanelInspector({
  panel, wall, offset, onExport, exporting, exportError,
}: {
  panel: Panel; wall: WallParams; offset: number;
  onExport: () => void; exporting: boolean; exportError: string | null;
}) {
  const r = panel.returns;
  const [cx, cy, cz] = worldCentre(panel, wall, offset);
  const tc = TC[panel.type] ?? TC.interior;
  const hasReturns = r.left || r.right || r.top || r.bottom;

  return (
    <div>

      {/* Identity */}
      <div className="glass-sm" style={{ padding: "12px 14px", marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
          <div>
            <div style={{ fontSize: 9, color: "var(--text-subtle)", marginBottom: 3 }}>Panel ID</div>
            <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.02em", fontFamily: "monospace", color: "var(--text-primary)" }}>
              {panel.id}
            </div>
          </div>
          <div style={{
            fontSize: 9, fontWeight: 700, padding: "3px 8px", borderRadius: 4,
            textTransform: "uppercase", letterSpacing: "0.06em",
            background: `${tc}20`, color: tc, border: `1px solid ${tc}40`, marginTop: 2,
          }}>
            {panel.type}
          </div>
        </div>
        <KV k="Row / Col" v={`${panel.row}  /  ${panel.col}`} />
        <KV k="Grid"      v={`${panel.nRows} rows × ${panel.nCols} cols`} />
      </div>

      {/* 2D wall-local coordinates */}
      <Sect label="2D — wall local (mm)">
        <div style={{ fontSize: 10, color: "var(--text-subtle)", marginBottom: 6, lineHeight: 1.6 }}>
          Origin = bottom-left of wall face
        </div>
        <KV k="U  (horizontal)" v={`${panel.uStart.toFixed(0)} → ${(panel.uStart + panel.visW).toFixed(0)}`} mono />
        <KV k="V  (vertical)"   v={`${panel.vStart.toFixed(0)} → ${(panel.vStart + panel.visH).toFixed(0)}`} mono />
        <KV k="Visible size"    v={`${panel.visW.toFixed(0)} × ${panel.visH.toFixed(0)} mm`} />
      </Sect>

      {/* 3D world position — formula shown explicitly */}
      <Sect label="3D — world position (m)">
        <div style={{ fontFamily: "monospace", fontSize: 10, color: "var(--text-muted)", lineHeight: 1.85, marginBottom: 8 }}>
          <div>x = (uStart + visW/2 − wallW/2) × S</div>
          <div>y = (vStart + visH/2) × S</div>
          <div>z = offset × S</div>
        </div>
        <KV k="Centre"   v={`(${cx.toFixed(3)}, ${cy.toFixed(3)}, ${cz.toFixed(3)})`} mono />
        <KV k="Size"     v={`${(panel.visW * S).toFixed(3)} × ${(panel.visH * S).toFixed(3)} m`} mono />
      </Sect>

      {/* Flat blank — breakdown shown as equation */}
      <Sect label="Flat blank (mm)">
        <KV
          k="Width"
          v={`${r.left ? r.left + " + " : ""}${panel.visW.toFixed(0)}${r.right ? " + " + r.right : ""} = ${panel.blankW.toFixed(0)}`}
          mono
        />
        <KV
          k="Height"
          v={`${r.bottom ? r.bottom + " + " : ""}${panel.visH.toFixed(0)}${r.top ? " + " + r.top : ""} = ${panel.blankH.toFixed(0)}`}
          mono
        />
        <KV k="Area" v={`${(panel.blankW * panel.blankH / 1e6).toFixed(4)} m²`} />
        <KV k="Visible area" v={`${(panel.visW * panel.visH / 1e6).toFixed(4)} m²`} />
      </Sect>

      {/* Returns */}
      {hasReturns ? (
        <Sect label="Fold returns (90°, mm)">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px" }}>
            {(["left", "right", "top", "bottom"] as const).map((side) => (
              <div key={side} style={{ fontSize: 11, display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--text-subtle)", textTransform: "capitalize" }}>{side}</span>
                <span style={{ fontWeight: 600, color: r[side] ? "#86efac" : "var(--text-subtle)" }}>
                  {r[side] ? `${r[side].toFixed(0)} mm` : "—"}
                </span>
              </div>
            ))}
          </div>
        </Sect>
      ) : (
        <div style={{
          fontSize: 11, color: "var(--text-subtle)", marginBottom: 10,
          padding: "8px 12px", background: "rgba(255,255,255,0.03)",
          borderRadius: 8, border: "1px solid rgba(255,255,255,0.07)",
        }}>
          Interior panel — no fold returns needed.
        </div>
      )}

      {/* Fold lines */}
      {panel.foldLines.length > 0 && (
        <Sect label="Fold lines in blank (mm)">
          {panel.foldLines.map((fl, i) => (
            <div key={i} style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 3, fontFamily: "monospace" }}>
              {fl.axis === "h" ? "H (horizontal)" : "V (vertical)"}  at  {fl.position.toFixed(0)} mm
            </div>
          ))}
          {hasReturns && (r.left || r.right) && (r.top || r.bottom) && (
            <div style={{ marginTop: 6, fontSize: 10, color: "rgba(251,191,36,0.75)", lineHeight: 1.5 }}>
              ⚠ Corner waste squares must be cut at fold-line intersections before bending.
            </div>
          )}
        </Sect>
      )}

      {/* DXF export */}
      <button
        onClick={onExport}
        disabled={exporting}
        style={{
          width: "100%", padding: "10px 0", borderRadius: 9, border: "none",
          cursor: exporting ? "default" : "pointer",
          background: "linear-gradient(135deg,#10b981,#06b6d4)",
          color: "#fff", fontSize: 13, fontWeight: 700,
          opacity: exporting ? 0.6 : 1, fontFamily: "inherit", transition: "opacity 0.2s",
        }}
      >
        {exporting ? "Exporting…" : "↓ Export Flat-Blank DXF"}
      </button>
      <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-subtle)", textAlign: "center" }}>
        Blank outline · fold lines · cut marks · dimensions
      </div>

      {exportError && (
        <div style={{
          marginTop: 10, padding: "8px 12px", borderRadius: 7,
          background: "rgba(239,68,68,0.10)", border: "1px solid rgba(239,68,68,0.32)",
          fontSize: 11, color: "#fca5a5", lineHeight: 1.55,
        }}>
          <span style={{ fontWeight: 700 }}>Export failed:</span> {exportError}
        </div>
      )}

    </div>
  );
}

// ── Summary (no panel selected) ───────────────────────────────────────────────

function WallSummary({ panels }: { panels: Panel[] }) {
  const counts = { interior: 0, edge: 0, corner: 0 };
  let visArea = 0, blkArea = 0;
  for (const p of panels) {
    counts[p.type]++;
    visArea += p.visW * p.visH;
    blkArea += p.blankW * p.blankH;
  }
  const total = panels.length;

  if (total === 0) return (
    <div style={{ fontSize: 12, color: "var(--text-subtle)", lineHeight: 1.75 }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)", marginBottom: 8 }}>
        Panel inspector
      </div>
      <p style={{ margin: "0 0 10px" }}>
        Adjust wall and cladding parameters — the layout updates live.
      </p>
      <p style={{ margin: 0 }}>
        Click any panel to verify its 2D wall coordinates, 3D installed position, flat blank size, and fold lines.
      </p>
    </div>
  );

  const wastePct = blkArea > 0 ? (blkArea - visArea) / blkArea * 100 : 0;

  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)", marginBottom: 12 }}>
        Wall summary
      </div>

      <Sect label="Panel count">
        {([
          { label: "Total",              val: total,           color: "#fff"     },
          { label: "Interior (no folds)",val: counts.interior, color: TC.interior },
          { label: "Edge (1 fold)",      val: counts.edge,     color: TC.edge    },
          { label: "Corner (2 folds)",   val: counts.corner,   color: TC.corner  },
        ] as const).map(({ label, val, color }) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
            <div style={{ width: 8, height: 8, borderRadius: 2, background: color as string, flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: "var(--text-muted)", flex: 1 }}>{label as string}</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)" }}>{val as number}</span>
          </div>
        ))}
      </Sect>

      <Sect label="Material area">
        <KV k="Visible face"   v={`${(visArea / 1e6).toFixed(3)} m²`} />
        <KV k="Blank (to order)" v={`${(blkArea / 1e6).toFixed(3)} m²`} />
        <KV k="Return waste"   v={`${wastePct.toFixed(1)} %`} />
      </Sect>

      <div style={{
        fontSize: 11, color: "var(--text-subtle)", lineHeight: 1.7,
        padding: "8px 0",
      }}>
        Click any panel to inspect its 2D coordinates, 3D position, flat blank, fold lines, and export DXF.
      </div>
    </div>
  );
}

// ── Stress presets ────────────────────────────────────────────────────────────

interface AluPreset {
  name:  string;
  desc:  string;
  wall:  Partial<WallParams>;
  clad:  Partial<CladdingParams>;
}

const ALU_PRESETS: AluPreset[] = [
  {
    name: "Standard 90°",
    desc: "Typical facade — baseline configuration",
    wall: { width: 6000, height: 3600 },
    clad: { panelWidth: 1200, panelHeight: 600,  returnDepth: 30, jointGap: 10, pattern: "horizontal" },
  },
  {
    name: "Large format",
    desc: "Oversize panels — transport & handling stress",
    wall: { width: 9000, height: 4500 },
    clad: { panelWidth: 2400, panelHeight: 900,  returnDepth: 40, jointGap: 12, pattern: "horizontal" },
  },
  {
    name: "Small panels",
    desc: "High panel count — DXF volume stress",
    wall: { width: 4800, height: 3000 },
    clad: { panelWidth: 300,  panelHeight: 200,  returnDepth: 20, jointGap: 6,  pattern: "horizontal" },
  },
  {
    name: "Deep protrusion",
    desc: "Large return depth — blank size stress",
    wall: { width: 5400, height: 3200 },
    clad: { panelWidth: 900,  panelHeight: 500,  returnDepth: 80, jointGap: 10, pattern: "horizontal" },
  },
  {
    name: "Narrow wall stress",
    desc: "Wall narrower than a panel — leftover columns",
    wall: { width: 800,  height: 2800 },
    clad: { panelWidth: 600,  panelHeight: 500,  returnDepth: 30, jointGap: 8,  pattern: "horizontal" },
  },
  {
    name: "Brick / tall wall",
    desc: "Staggered layout — wide & tall facade",
    wall: { width: 10000, height: 5000 },
    clad: { panelWidth: 1500, panelHeight: 600,  returnDepth: 35, jointGap: 12, pattern: "brick" },
  },
];

// ── Suggest best layout ───────────────────────────────────────────────────────

interface AluSuggestion {
  recommendedPanelW: number;
  recommendedPanelH: number;
  panelCount: number;
  efficiencyPct: number;
  wastePct: number;
  warnings: string[];
  tips: string[];
}

function suggestAluLayout(wall: WallParams, clad: CladdingParams): AluSuggestion {
  const { width: W, height: H } = wall;
  const { panelWidth: pw, panelHeight: ph, returnDepth: rd, jointGap: gap, pattern } = clad;

  const warnings: string[] = [];
  const tips: string[] = [];

  // --- geometry ---
  const effectivePW = pattern === "vertical" ? ph : pw;
  const effectivePH = pattern === "vertical" ? pw : ph;

  const nCols = Math.ceil(W / (effectivePW + gap));
  const nRows = Math.ceil(H / (effectivePH + gap));

  const remW = W - Math.floor(W / (effectivePW + gap)) * (effectivePW + gap);
  const remH = H - Math.floor(H / (effectivePH + gap)) * (effectivePH + gap);

  // --- warnings ---
  if (effectivePW < 200)
    warnings.push(`Panel width ${effectivePW} mm is very small. High part count increases installation cost.`);
  if (effectivePW > 2500)
    warnings.push(`Panel width ${effectivePW} mm exceeds typical transport limit (~2.5 m). Verify logistics.`);
  if (effectivePH < 200)
    warnings.push(`Panel height ${effectivePH} mm is very small. Consider larger panels.`);
  if (rd > effectivePW * 0.15)
    warnings.push(`Return depth ${rd} mm is large relative to panel width (${(rd / effectivePW * 100).toFixed(0)} %). Check blank bending capacity.`);
  if (remW > 0 && remW < effectivePW * 0.2)
    warnings.push(`Leftover column is narrow (${remW.toFixed(0)} mm). Adjust panel width to reduce waste.`);
  if (remH > 0 && remH < effectivePH * 0.2)
    warnings.push(`Leftover row is short (${remH.toFixed(0)} mm). Adjust panel height to reduce waste.`);

  // --- recommended sizes ---
  // Best panel width = divisor of W that minimises leftover
  let bestPW = effectivePW;
  let minRem = remW;
  for (const candidate of [400, 600, 800, 900, 1000, 1200, 1500, 1800]) {
    const rem = W % (candidate + gap);
    if (rem < minRem && rem < effectivePW * 0.1) { minRem = rem; bestPW = candidate; }
  }
  if (bestPW !== effectivePW)
    tips.push(`Reduce panel width to ${bestPW} mm to avoid the leftover column (saves ${remW.toFixed(0)} mm of waste per row).`);

  // --- tips ---
  const aspectRatio = W / H;
  if (aspectRatio > 2.5 && pattern !== "horizontal")
    tips.push("Wall is much wider than tall — horizontal pattern minimises leftover rows.");
  if (aspectRatio < 0.6 && pattern !== "vertical")
    tips.push("Wall is much taller than wide — vertical pattern may give better proportions.");
  if (pattern === "brick")
    tips.push("Brick pattern requires half-width cuts on every other row. Allow extra blank material.");

  // --- efficiency ---
  const panelCount = nCols * nRows;
  // Approximate: visible face area vs blank area (with returns on edges)
  const visArea  = W * H;
  const blankArea = panelCount * (effectivePW + 2 * rd) * (effectivePH + 2 * rd);
  const efficiencyPct = Math.min(99, Math.round(visArea / blankArea * 100));
  const wastePct      = 100 - efficiencyPct;

  tips.push(`Estimated layout efficiency: ${efficiencyPct}% (return waste ~${wastePct}%).`);

  return {
    recommendedPanelW: bestPW,
    recommendedPanelH: effectivePH,
    panelCount,
    efficiencyPct,
    wastePct,
    warnings,
    tips,
  };
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AlucobondPage() {
  const [wall, setWall] = useState<WallParams>({ width: 6000, height: 3600 });
  const [clad, setClad] = useState<CladdingParams>({
    offset: 50, panelWidth: 1200, panelHeight: 600,
    jointGap: 10, returnDepth: 30, pattern: "horizontal",
  });
  const [selected,     setSelected]     = useState<Panel | null>(null);
  const [exporting,    setExporting]    = useState(false);
  const [exportError,  setExportError]  = useState<string | null>(null);
  const [suggestion,   setSuggestion]   = useState<AluSuggestion | null>(null);

  const setW = (k: keyof WallParams) => (v: number) =>
    setWall(w => ({ ...w, [k]: v }));
  const setC = (k: keyof CladdingParams) => (v: number | string) =>
    setClad(c => ({ ...c, [k]: v as never }));

  // Recompute layout whenever params change
  const panels = useMemo(() => computeLayout(wall, clad), [wall, clad]);

  // Keep selection live — refresh panel data when params change
  const selectedId = selected?.id ?? null;
  useEffect(() => {
    if (!selectedId) return;
    const fresh = panels.find(p => p.id === selectedId);
    setSelected(fresh ?? null);
  }, [panels, selectedId]);

  const exportDxf = useCallback(async () => {
    if (!selected) return;
    setExporting(true);
    setExportError(null);
    try {
      const res = await fetch(`${BASE}/alucobond/panel-dxf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          panel: {
            id:            selected.id,
            visibleWidth:  selected.visW,
            visibleHeight: selected.visH,
            returns:       selected.returns,
            blankWidth:    selected.blankW,
            blankHeight:   selected.blankH,
            foldLines:     selected.foldLines,
          },
          filename: `${selected.id}.dxf`,
        }),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      Object.assign(document.createElement("a"), { href: url, download: `${selected.id}.dxf` }).click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(
        e instanceof Error ? e.message : "Export failed — is the backend running on port 8000?"
      );
    } finally {
      setExporting(false);
    }
  }, [selected]);

  const H3 = wall.height * S;

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: "var(--bg-primary)" }}>

      {/* ── Left: parameters ── */}
      <div style={{
        width: 244, flexShrink: 0, overflowY: "auto",
        padding: "18px 14px", borderRight: "1px solid var(--glass-border)",
      }}>
        <div style={{ marginBottom: 14 }}>
          <span style={{
            fontSize: 9, fontWeight: 700, letterSpacing: "0.12em",
            textTransform: "uppercase", color: "var(--text-subtle)",
          }}>
            Alucobond · Single Wall
          </span>
          <h1 style={{ fontSize: 17, fontWeight: 800, margin: "4px 0 4px", letterSpacing: "-0.02em" }}>
            Cladding{" "}
            <span style={{
              background: "linear-gradient(135deg,#06b6d4,#7c3aed)",
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
            }}>
              Geometry
            </span>
          </h1>
          <p style={{ fontSize: 10, color: "var(--text-subtle)", margin: 0, lineHeight: 1.55 }}>
            Layout updates live as you adjust parameters.
          </p>
        </div>

        {/* Wall */}
        <Sect label="Wall structure">
          <Num label="Width"  value={wall.width}  min={500}   max={60000} step={100} unit="mm" onChange={setW("width")}  />
          <Num label="Height" value={wall.height} min={500}   max={30000} step={100} unit="mm" onChange={setW("height")} />
        </Sect>

        {/* Cladding */}
        <Sect label="Cladding skin">
          <Num label="Offset from wall"  value={clad.offset}      min={0}   max={500}  step={5}  unit="mm" onChange={setC("offset")}      />
          <Num label="Panel width"       value={clad.panelWidth}  min={100} max={6000} step={50} unit="mm" onChange={setC("panelWidth")}  />
          <Num label="Panel height"      value={clad.panelHeight} min={100} max={6000} step={50} unit="mm" onChange={setC("panelHeight")} />
          <Num label="Joint gap"         value={clad.jointGap}    min={0}   max={100}  step={1}  unit="mm" onChange={setC("jointGap")}    />
          <Num label="Return depth"      value={clad.returnDepth} min={0}   max={200}  step={5}  unit="mm" onChange={setC("returnDepth")} />
          <div style={{ marginBottom: 0 }}>
            <div style={{
              fontSize: 10, fontWeight: 700, textTransform: "uppercase",
              letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 3,
            }}>
              Pattern
            </div>
            <select
              value={clad.pattern}
              onChange={(e) => setC("pattern")(e.target.value)}
              style={{
                width: "100%", background: "rgba(255,255,255,0.06)",
                border: "1px solid rgba(255,255,255,0.12)", borderRadius: 6,
                color: "var(--text-primary)", padding: "5px 9px", fontSize: 13,
                outline: "none", fontFamily: "inherit",
              }}
            >
              <option value="horizontal">Horizontal</option>
              <option value="vertical">Vertical</option>
              <option value="brick">Brick / Offset</option>
            </select>
          </div>
        </Sect>

        {/* Coordinate model legend */}
        <div className="glass-sm" style={{ padding: "11px 13px", marginBottom: 10 }}>
          <div style={{
            fontSize: 9, fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 8,
          }}>
            Coordinate model
          </div>
          {[
            { color: "#ff5555", sym: "U", desc: "horizontal  →  world +X" },
            { color: "#55cc55", sym: "V", desc: "vertical    →  world +Y" },
            { color: "#5588ff", sym: "N", desc: "outward     →  world +Z" },
          ].map(({ color, sym, desc }) => (
            <div key={sym} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5, fontSize: 11 }}>
              <div style={{ width: 14, height: 4, borderRadius: 2, background: color, flexShrink: 0 }} />
              <span style={{ fontWeight: 700, fontFamily: "monospace", color: "var(--text-primary)" }}>{sym}</span>
              <span style={{ color: "var(--text-subtle)", fontSize: 10 }}>{desc}</span>
            </div>
          ))}
        </div>

        {/* Panel type legend */}
        <div className="glass-sm" style={{ padding: "11px 13px", marginBottom: 10 }}>
          <div style={{
            fontSize: 9, fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 8,
          }}>
            Panel types
          </div>
          {(["interior", "edge", "corner"] as const).map(t => (
            <div key={t} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5, fontSize: 11 }}>
              <div style={{ width: 10, height: 10, borderRadius: 2, background: TC[t], flexShrink: 0 }} />
              <span style={{ textTransform: "capitalize", fontWeight: 600, color: "var(--text-muted)" }}>{t}</span>
              <span style={{ fontSize: 10, color: "var(--text-subtle)" }}>
                {t === "interior" ? "no folds" : t === "edge" ? "1 return fold" : "2 return folds"}
              </span>
            </div>
          ))}
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: "#f59e0b", flexShrink: 0 }} />
            <span style={{ fontWeight: 600, color: "var(--text-muted)" }}>Selected</span>
          </div>
        </div>

        {/* ── Stress test presets ── */}
        <div className="glass-sm" style={{ padding: "11px 13px", marginBottom: 10 }}>
          <div style={{
            fontSize: 9, fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 7,
          }}>
            Stress Test Presets
          </div>
          <div style={{
            fontSize: 9, color: "var(--text-subtle)", lineHeight: 1.6, marginBottom: 8,
            padding: "5px 7px", background: "rgba(255,255,255,0.03)", borderRadius: 5,
            border: "1px solid rgba(255,255,255,0.06)",
          }}>
            Use these presets to verify panel placement, wrap corners, and DXF export under difficult geometry.
          </div>
          <div style={{ fontSize: 9, color: "var(--text-subtle)", opacity: 0.6, lineHeight: 1.6, marginBottom: 8 }}>
            These presets help verify geometry stability under difficult real-world cladding cases.
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {ALU_PRESETS.map(preset => (
              <button
                key={preset.name}
                onClick={() => {
                  setWall(w => ({ ...w, ...preset.wall }));
                  setClad(c => ({ ...c, ...preset.clad }));
                  setSelected(null);
                  setSuggestion(null);
                }}
                style={{
                  display: "flex", flexDirection: "column", alignItems: "flex-start",
                  padding: "7px 9px", borderRadius: 6,
                  border: "1px solid rgba(255,255,255,0.08)",
                  background: "rgba(255,255,255,0.03)", cursor: "pointer",
                  fontFamily: "inherit", textAlign: "left", transition: "background 0.15s",
                }}
                onMouseEnter={e => (e.currentTarget.style.background = "rgba(255,255,255,0.07)")}
                onMouseLeave={e => (e.currentTarget.style.background = "rgba(255,255,255,0.03)")}
              >
                <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)" }}>
                  {preset.name}
                </span>
                <span style={{ fontSize: 9, color: "var(--text-subtle)", marginTop: 2 }}>
                  {preset.desc}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* ── Suggest best layout ── */}
        <button
          onClick={() => setSuggestion(suggestAluLayout(wall, clad))}
          style={{
            width: "100%", padding: "10px 0", borderRadius: 9, border: "none",
            cursor: "pointer", background: "linear-gradient(135deg,#f59e0b,#f97316)",
            color: "#fff", fontSize: 12, fontWeight: 700, fontFamily: "inherit",
            marginBottom: suggestion ? 10 : 0,
          }}
        >
          ✦ Suggest Best Layout
        </button>
        <div style={{ fontSize: 9, color: "var(--text-subtle)", opacity: 0.6, lineHeight: 1.6, marginTop: 5, marginBottom: suggestion ? 0 : 4 }}>
          Suggestions estimate panel count, waste, and leftover cuts to help choose a more fabrication-friendly layout.
        </div>

        {suggestion && (
          <div className="glass-sm" style={{ padding: "11px 13px", marginBottom: 10, marginTop: 10 }}>
            <div style={{
              fontSize: 9, fontWeight: 700, textTransform: "uppercase",
              letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 8,
            }}>
              Layout Recommendation
            </div>

            {/* Summary row */}
            <div style={{
              display: "flex", alignItems: "center", gap: 8, marginBottom: 9,
              padding: "7px 9px", borderRadius: 6,
              background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.18)",
            }}>
              <span style={{ fontSize: 16 }}>⊞</span>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#6ee7b7" }}>
                  {suggestion.panelCount} panels · {suggestion.efficiencyPct}% efficiency
                </div>
                <div style={{ fontSize: 9, color: "var(--text-subtle)", marginTop: 2 }}>
                  Return waste ~{suggestion.wastePct}%
                </div>
              </div>
            </div>

            {/* Tips */}
            {suggestion.tips.map((tip, i) => (
              <div key={i} style={{
                fontSize: 10, color: "#a3e635", marginBottom: 5,
                lineHeight: 1.55, display: "flex", gap: 5,
              }}>
                <span style={{ flexShrink: 0, opacity: 0.7 }}>→</span>
                <span>{tip}</span>
              </div>
            ))}

            {/* Warnings */}
            {suggestion.warnings.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div style={{
                  fontSize: 9, fontWeight: 700, color: "#fde68a",
                  textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 5,
                }}>
                  Warnings
                </div>
                {suggestion.warnings.map((w, i) => (
                  <div key={i} style={{
                    fontSize: 10, color: "#fde68a", marginBottom: 5,
                    lineHeight: 1.55, display: "flex", gap: 5,
                  }}>
                    <span style={{ flexShrink: 0 }}>⚠</span>
                    <span>{w}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Apply recommended size */}
            {suggestion.recommendedPanelW !== (clad.pattern === "vertical" ? clad.panelHeight : clad.panelWidth) && (
              <button
                onClick={() => {
                  const key = clad.pattern === "vertical" ? "panelHeight" : "panelWidth";
                  setClad(c => ({ ...c, [key]: suggestion!.recommendedPanelW }));
                  setSuggestion(null);
                }}
                style={{
                  marginTop: 8, width: "100%", padding: "7px 0", borderRadius: 6,
                  border: "1px solid rgba(163,230,53,0.30)",
                  background: "rgba(163,230,53,0.08)",
                  color: "#a3e635", fontSize: 11, fontWeight: 700,
                  cursor: "pointer", fontFamily: "inherit",
                }}
              >
                Apply {suggestion.recommendedPanelW} mm panel width
              </button>
            )}

            <button
              onClick={() => setSuggestion(null)}
              style={{
                marginTop: 6, fontSize: 10, color: "var(--text-subtle)",
                background: "none", border: "none", cursor: "pointer",
                fontFamily: "inherit", padding: 0,
              }}
            >
              Dismiss
            </button>
          </div>
        )}

      </div>

      {/* ── Centre: 3D viewer ── */}
      <div style={{ flex: 1, position: "relative", background: "#07070e" }}>
        <Canvas
          camera={{ fov: 45, near: 0.01, far: 2000 }}
          gl={{ antialias: true }}
          style={{ width: "100%", height: "100%" }}
          onPointerMissed={() => setSelected(null)}
        >
          <Suspense fallback={null}>
            <SceneCamera wall={wall} />
            <ambientLight intensity={0.55} />
            <directionalLight position={[4, 7, 6]}   intensity={0.9} />
            <directionalLight position={[-3, 2, -4]} intensity={0.25} />

            <WallSurface wall={wall} />
            <SkinOutline wall={wall} offset={clad.offset} />
            <AxisArrows  wall={wall} offset={clad.offset} />

            {panels.map(p => (
              <PanelMesh
                key={p.id}
                p={p}
                wall={wall}
                offset={clad.offset}
                selectedId={selectedId}
                onSelect={setSelected}
              />
            ))}

            <gridHelper
              args={[
                Math.max(wall.width, wall.height) * S * 3,
                24,
                "#161628",
                "#161628",
              ]}
              position={[0, 0, 0]}
            />

            <OrbitControls
              target={[0, H3 * 0.5, 0]}
              enableDamping
              dampingFactor={0.08}
              makeDefault
            />
          </Suspense>
        </Canvas>

        {/* Stats overlay */}
        {panels.length > 0 && (
          <div style={{
            position: "absolute", top: 12, left: "50%",
            transform: "translateX(-50%)",
            display: "flex", gap: 6, pointerEvents: "none",
          }}>
            {([
              { label: "panels",   value: panels.length,                               color: "#a0a0c0" },
              { label: "interior", value: panels.filter(p => p.type === "interior").length, color: TC.interior },
              { label: "edge",     value: panels.filter(p => p.type === "edge").length,     color: TC.edge     },
              { label: "corner",   value: panels.filter(p => p.type === "corner").length,   color: TC.corner   },
            ] as const).map(({ label, value, color }) => (
              <div key={label as string} style={{
                fontSize: 10, fontWeight: 700, padding: "3px 8px", borderRadius: 4,
                background: "rgba(7,7,14,0.84)", border: "1px solid rgba(255,255,255,0.08)",
                color: color as string, letterSpacing: "0.04em",
              }}>
                {value as number} {label as string}
              </div>
            ))}
          </div>
        )}

        {/* Click-to-inspect hint */}
        {panels.length > 0 && !selected && (
          <div style={{
            position: "absolute", bottom: 16, left: "50%", transform: "translateX(-50%)",
            background: "rgba(7,7,14,0.82)", border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: 8, padding: "7px 16px", fontSize: 11,
            color: "var(--text-subtle)", pointerEvents: "none",
          }}>
            Click any panel → inspect 2D coords · 3D position · blank · fold lines
          </div>
        )}
      </div>

      {/* ── Right: inspector / summary ── */}
      <div style={{
        width: 272, flexShrink: 0, overflowY: "auto",
        padding: "18px 14px", borderLeft: "1px solid var(--glass-border)",
      }}>
        {selected
          ? (
            <PanelInspector
              panel={selected}
              wall={wall}
              offset={clad.offset}
              onExport={exportDxf}
              exporting={exporting}
              exportError={exportError}
            />
          ) : (
            <WallSummary panels={panels} />
          )}
      </div>

    </div>
  );
}
