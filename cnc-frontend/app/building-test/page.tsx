"use client";

import { useState, useMemo, useCallback, Suspense, useEffect, useRef } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Html } from "@react-three/drei";
import * as THREE from "three";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const S = 0.001; // mm → metres

// ── Types ─────────────────────────────────────────────────────────────────────

type WallName   = "A" | "B" | "C" | "D";
type CornerName = "AB" | "BC" | "CD" | "DA";
type PanelMode  = "separate" | "wrap";

interface BuildingParams {
  buildingL: number; // mm — x dimension (Wall A / C length)
  buildingW: number; // mm — z dimension (Wall B / D length)
  buildingH: number; // mm
  panelW:    number;
  panelH:    number;
  edgeDepth: number;
  gap:       number;
}

// Separate panel on any wall
interface WallPanelDef {
  id:      string;
  wall:    WallName;
  row:     number;
  col:     number;
  visW:    number;
  visH:    number;
  along:   number;   // panel start along wall (x for A,C; z for B,D)
  oy:      number;
  facePos: number;   // face plane coord (z for A,C; x for B,D)
  surfPos: number;   // wall surface coord
  faceIsZ: boolean;  // true = Z-face (A,C), false = X-face (B,D)
}

// Corner wrap panel — spans two walls with one outside 90° arc bend
interface CornerWrapDef {
  id:          string;
  corner:      CornerName;
  row:         number;
  oy:          number;
  visH:        number;
  cx:          number;
  cz:          number;
  arcStart:    number;
  arcEnd:      number;
  segFrom:     number;
  segTo:       number;
  fromFacePos: number;
  fromSurfPos: number;
  fromIsZ:     boolean;
  fromExtSign: 1 | -1;
  toFacePos:   number;
  toSurfPos:   number;
  toIsZ:       boolean;
  toExtSign:   1 | -1;
}

// ── Three.js helpers ──────────────────────────────────────────────────────────

const m = (x: number, y: number, z: number) => new THREE.Vector3(x * S, y * S, z * S);

function makeQuad(
  p0: THREE.Vector3, p1: THREE.Vector3,
  p2: THREE.Vector3, p3: THREE.Vector3,
): THREE.BufferGeometry {
  const arr = new Float32Array([
    p0.x, p0.y, p0.z,  p1.x, p1.y, p1.z,
    p2.x, p2.y, p2.z,  p3.x, p3.y, p3.z,
  ]);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(arr, 3));
  g.setIndex([0, 1, 2,  0, 2, 3]);
  g.computeVertexNormals();
  return g;
}

// Z-face wall panel (Wall A: face at z=facePos, returns to z=surfPos; Wall C similar)
function makeZFaceGeos(along: number, oy: number, visW: number, visH: number,
  facePos: number, surfPos: number) {
  const x0 = along, x1 = along + visW, y0 = oy, y1 = oy + visH, fz = facePos, sz = surfPos;
  return [
    makeQuad(m(x0,y0,fz), m(x1,y0,fz), m(x1,y1,fz), m(x0,y1,fz)),
    makeQuad(m(x0,y1,fz), m(x1,y1,fz), m(x1,y1,sz), m(x0,y1,sz)),
    makeQuad(m(x0,y0,sz), m(x1,y0,sz), m(x1,y0,fz), m(x0,y0,fz)),
    makeQuad(m(x0,y0,fz), m(x0,y1,fz), m(x0,y1,sz), m(x0,y0,sz)),
    makeQuad(m(x1,y0,sz), m(x1,y1,sz), m(x1,y1,fz), m(x1,y0,fz)),
  ];
}

// X-face wall panel (Wall B: face at x=facePos, returns to x=surfPos; Wall D similar)
function makeXFaceGeos(along: number, oy: number, visW: number, visH: number,
  facePos: number, surfPos: number) {
  const z0 = along, z1 = along + visW, y0 = oy, y1 = oy + visH, fx = facePos, sx = surfPos;
  return [
    makeQuad(m(fx,y0,z0), m(fx,y0,z1), m(fx,y1,z1), m(fx,y1,z0)),
    makeQuad(m(fx,y1,z0), m(fx,y1,z1), m(sx,y1,z1), m(sx,y1,z0)),
    makeQuad(m(sx,y0,z0), m(sx,y0,z1), m(fx,y0,z1), m(fx,y0,z0)),
    makeQuad(m(fx,y0,z0), m(fx,y1,z0), m(sx,y1,z0), m(sx,y0,z0)),
    makeQuad(m(sx,y0,z1), m(sx,y1,z1), m(fx,y1,z1), m(fx,y0,z1)),
  ];
}

// Build geometry for one face+returns of a corner wrap panel.
// Returns [faceQuad, sideReturn, topReturn, botReturn].
function buildFaceGeos(
  oy: number, H: number,
  isZ: boolean, extSign: 1 | -1, facePos: number, surfPos: number,
  cx: number, cz: number, seg: number,
): THREE.BufferGeometry[] {
  const y0 = oy, y1 = oy + H;
  if (isZ) {
    // Z-face at z=facePos, extending extSign*seg from cx in X
    const xCorner = cx, xEdge = cx + extSign * seg;
    const fz = facePos, sz = surfPos;
    return [
      makeQuad(m(xEdge,y0,fz), m(xCorner,y0,fz), m(xCorner,y1,fz), m(xEdge,y1,fz)),
      makeQuad(m(xEdge,y0,fz), m(xEdge,y0,sz),   m(xEdge,y1,sz),   m(xEdge,y1,fz)),
      makeQuad(m(xEdge,y1,fz), m(xCorner,y1,fz), m(xCorner,y1,sz), m(xEdge,y1,sz)),
      makeQuad(m(xEdge,y0,sz), m(xCorner,y0,sz), m(xCorner,y0,fz), m(xEdge,y0,fz)),
    ];
  } else {
    // X-face at x=facePos, extending extSign*seg from cz in Z
    const zCorner = cz, zEdge = cz + extSign * seg;
    const fx = facePos, sx = surfPos;
    return [
      makeQuad(m(fx,y0,zEdge), m(fx,y0,zCorner), m(fx,y1,zCorner), m(fx,y1,zEdge)),
      makeQuad(m(fx,y0,zEdge), m(sx,y0,zEdge),   m(sx,y1,zEdge),   m(fx,y1,zEdge)),
      makeQuad(m(fx,y1,zEdge), m(fx,y1,zCorner), m(sx,y1,zCorner), m(sx,y1,zEdge)),
      makeQuad(m(sx,y0,zEdge), m(sx,y0,zCorner), m(fx,y0,zCorner), m(fx,y0,zEdge)),
    ];
  }
}

// ── Layout ────────────────────────────────────────────────────────────────────

function colLayout(wallLen: number, panelW: number, gap: number) {
  const cols: { start: number; width: number }[] = [];
  for (let x = 0; x < wallLen; x += panelW + gap) {
    const w = Math.min(panelW, wallLen - x);
    if (w > 1) cols.push({ start: x, width: w });
  }
  return cols;
}

function computeLayout(
  { buildingL: L, buildingW: W, buildingH: H, panelW, panelH, edgeDepth: d, gap }: BuildingParams,
  mode: PanelMode,
): { panels: WallPanelDef[]; wraps: CornerWrapDef[] } {
  const colsA = colLayout(L, panelW, gap);
  const colsB = colLayout(W, panelW, gap);
  const colsC = colLayout(L, panelW, gap);
  const colsD = colLayout(W, panelW, gap);

  // Corner segment widths (first/last column of each wall)
  const segDA_D = colsD[0]?.width ?? 0;
  const segDA_A = colsA[0]?.width ?? 0;
  const segAB_A = colsA.at(-1)?.width ?? 0;
  const segAB_B = colsB[0]?.width ?? 0;
  const segBC_B = colsB.at(-1)?.width ?? 0;
  const segBC_C = colsC.at(-1)?.width ?? 0;
  const segCD_C = colsC[0]?.width ?? 0;
  const segCD_D = colsD.at(-1)?.width ?? 0;

  // Column indices claimed by wrap corners (each wall loses col=0 and col=last)
  const claimA = new Set<number>(mode === "wrap" ? [0, colsA.length - 1] : []);
  const claimB = new Set<number>(mode === "wrap" ? [0, colsB.length - 1] : []);
  const claimC = new Set<number>(mode === "wrap" ? [0, colsC.length - 1] : []);
  const claimD = new Set<number>(mode === "wrap" ? [0, colsD.length - 1] : []);

  const panels: WallPanelDef[] = [];
  const wraps:  CornerWrapDef[] = [];

  let rowIdx = 0;
  for (let y = 0; y < H; y += panelH + gap) {
    const visH = Math.min(panelH, H - y);
    if (visH <= 1) break;

    // Wall A — Z-face, faceZ=-d, surfZ=0, along x
    colsA.forEach(({ start, width }, ci) => {
      if (!claimA.has(ci))
        panels.push({ id: `A-${rowIdx}-${ci}`, wall: "A", row: rowIdx, col: ci,
          visW: width, visH, along: start, oy: y, facePos: -d, surfPos: 0, faceIsZ: true });
    });
    // Wall B — X-face, faceX=L+d, surfX=L, along z
    colsB.forEach(({ start, width }, ci) => {
      if (!claimB.has(ci))
        panels.push({ id: `B-${rowIdx}-${ci}`, wall: "B", row: rowIdx, col: ci,
          visW: width, visH, along: start, oy: y, facePos: L + d, surfPos: L, faceIsZ: false });
    });
    // Wall C — Z-face, faceZ=W+d, surfZ=W, along x
    colsC.forEach(({ start, width }, ci) => {
      if (!claimC.has(ci))
        panels.push({ id: `C-${rowIdx}-${ci}`, wall: "C", row: rowIdx, col: ci,
          visW: width, visH, along: start, oy: y, facePos: W + d, surfPos: W, faceIsZ: true });
    });
    // Wall D — X-face, faceX=-d, surfX=0, along z
    colsD.forEach(({ start, width }, ci) => {
      if (!claimD.has(ci))
        panels.push({ id: `D-${rowIdx}-${ci}`, wall: "D", row: rowIdx, col: ci,
          visW: width, visH, along: start, oy: y, facePos: -d, surfPos: 0, faceIsZ: false });
    });

    if (mode === "wrap") {
      // Corner AB (cx=L, cz=0): Wall A last-col + Wall B col-0
      //   FaceFrom = Wall A (Z-face z=-d, extends -X from L)
      //   FaceTo   = Wall B (X-face x=L+d, extends +Z from 0)
      //   Arc: θ = -π/2 → 0
      if (segAB_A > 0 && segAB_B > 0)
        wraps.push({
          id: `W-AB-${rowIdx}`, corner: "AB", row: rowIdx, oy: y, visH,
          cx: L, cz: 0, arcStart: -Math.PI / 2, arcEnd: 0,
          segFrom: segAB_A, segTo: segAB_B,
          fromFacePos: -d,    fromSurfPos: 0, fromIsZ: true,  fromExtSign: -1,
          toFacePos:   L + d, toSurfPos:   L, toIsZ:   false, toExtSign:    1,
        });

      // Corner BC (cx=L, cz=W): Wall B last-col + Wall C last-col
      //   FaceFrom = Wall B (X-face x=L+d, extends -Z from W)
      //   FaceTo   = Wall C (Z-face z=W+d, extends -X from L)
      //   Arc: θ = 0 → π/2
      if (segBC_B > 0 && segBC_C > 0)
        wraps.push({
          id: `W-BC-${rowIdx}`, corner: "BC", row: rowIdx, oy: y, visH,
          cx: L, cz: W, arcStart: 0, arcEnd: Math.PI / 2,
          segFrom: segBC_B, segTo: segBC_C,
          fromFacePos: L + d, fromSurfPos: L, fromIsZ: false, fromExtSign: -1,
          toFacePos:   W + d, toSurfPos:   W, toIsZ:   true,  toExtSign:   -1,
        });

      // Corner CD (cx=0, cz=W): Wall C col-0 + Wall D last-col
      //   FaceFrom = Wall C (Z-face z=W+d, extends +X from 0)
      //   FaceTo   = Wall D (X-face x=-d, extends -Z from W)
      //   Arc: θ = π/2 → π
      if (segCD_C > 0 && segCD_D > 0)
        wraps.push({
          id: `W-CD-${rowIdx}`, corner: "CD", row: rowIdx, oy: y, visH,
          cx: 0, cz: W, arcStart: Math.PI / 2, arcEnd: Math.PI,
          segFrom: segCD_C, segTo: segCD_D,
          fromFacePos: W + d, fromSurfPos: W, fromIsZ: true,  fromExtSign:  1,
          toFacePos:   -d,    toSurfPos:   0, toIsZ:   false, toExtSign:   -1,
        });

      // Corner DA (cx=0, cz=0): Wall D col-0 + Wall A col-0
      //   FaceFrom = Wall D (X-face x=-d, extends +Z from 0)
      //   FaceTo   = Wall A (Z-face z=-d, extends +X from 0)
      //   Arc: θ = π → 3π/2
      if (segDA_D > 0 && segDA_A > 0)
        wraps.push({
          id: `W-DA-${rowIdx}`, corner: "DA", row: rowIdx, oy: y, visH,
          cx: 0, cz: 0, arcStart: Math.PI, arcEnd: 3 * Math.PI / 2,
          segFrom: segDA_D, segTo: segDA_A,
          fromFacePos: -d, fromSurfPos: 0, fromIsZ: false, fromExtSign: 1,
          toFacePos:   -d, toSurfPos:   0, toIsZ:   true,  toExtSign:   1,
        });
    }

    rowIdx++;
  }

  return { panels, wraps };
}

// ── 3D: Building body ─────────────────────────────────────────────────────────

function BuildingBody({ L, W, H }: { L: number; W: number; H: number }) {
  const T = 120;
  const mat = { color: "#252b3a", roughness: 0.88 as const, metalness: 0.06 as const };
  return (
    <group>
      <mesh position={[L / 2 * S, H / 2 * S, -T / 2 * S]}>
        <boxGeometry args={[L * S, H * S, T * S]} />
        <meshStandardMaterial {...mat} />
      </mesh>
      <mesh position={[(L + T / 2) * S, H / 2 * S, W / 2 * S]}>
        <boxGeometry args={[T * S, H * S, W * S]} />
        <meshStandardMaterial {...mat} />
      </mesh>
      <mesh position={[L / 2 * S, H / 2 * S, (W + T / 2) * S]}>
        <boxGeometry args={[L * S, H * S, T * S]} />
        <meshStandardMaterial {...mat} />
      </mesh>
      <mesh position={[-T / 2 * S, H / 2 * S, W / 2 * S]}>
        <boxGeometry args={[T * S, H * S, W * S]} />
        <meshStandardMaterial {...mat} />
      </mesh>
    </group>
  );
}

// ── 3D: Wall labels ───────────────────────────────────────────────────────────

function WallLabel({ pos, text }: { pos: [number, number, number]; text: string }) {
  return (
    <Html position={pos} center style={{ pointerEvents: "none" }}>
      <div style={{
        background: "rgba(0,0,0,0.70)", color: "rgba(255,255,255,0.85)",
        padding: "3px 10px", borderRadius: 4,
        fontSize: 11, fontWeight: 700, letterSpacing: "0.10em",
        border: "1px solid rgba(255,255,255,0.18)",
        whiteSpace: "nowrap",
      }}>
        {text}
      </div>
    </Html>
  );
}

// ── 3D: Separate wall panel ───────────────────────────────────────────────────

function WallPanelMesh({ panel, selected, onSelect }: {
  panel: WallPanelDef;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const { faceIsZ, along, oy, visW, visH, facePos, surfPos } = panel;

  const geos = useMemo(() => {
    return faceIsZ
      ? makeZFaceGeos(along, oy, visW, visH, facePos, surfPos)
      : makeXFaceGeos(along, oy, visW, visH, facePos, surfPos);
  }, [panel]); // eslint-disable-line react-hooks/exhaustive-deps

  const faceColor = selected ? "#c4b5fd"
    : panel.wall === "A" ? "#9db8d8"
    : panel.wall === "B" ? "#88b8aa"
    : panel.wall === "C" ? "#a8c4b8"
    : "#8090c4";
  const retColor = selected ? "#a78bfa"
    : panel.wall === "A" ? "#6a90b8"
    : panel.wall === "B" ? "#5a9890"
    : panel.wall === "C" ? "#7aa498"
    : "#5870a8";

  const click = useCallback((e: { stopPropagation(): void }) => {
    e.stopPropagation(); onSelect(panel.id);
  }, [panel.id, onSelect]);

  return (
    <group>
      <mesh geometry={geos[0]} onClick={click}>
        <meshStandardMaterial color={faceColor} metalness={0.65} roughness={0.26} side={THREE.DoubleSide} />
      </mesh>
      {geos.slice(1).map((g, i) => (
        <mesh key={i} geometry={g} onClick={click}>
          <meshStandardMaterial color={retColor} metalness={0.50} roughness={0.38} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </group>
  );
}

// ── 3D: Corner wrap panel ─────────────────────────────────────────────────────
//
//  Geometry (outside convex corner):
//    face-from — rectangle on the "from" wall face
//    bend arc  — n quads sweeping 90° outward around the corner
//    face-to   — rectangle on the "to" wall face
//    6 returns — 3 per face: side + top + bottom
//
//  Arc centred at (cx, y, cz), radius = edgeDepth.
//  arcStart → arcEnd sweep +π/2 counter-clockwise (viewed from above).

function CornerWrapMesh({ wrap, edgeDepth: d, bendSegments, selected, onSelect }: {
  wrap: CornerWrapDef;
  edgeDepth: number;
  bendSegments: number;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const { cx, cz, arcStart, arcEnd, oy, visH: H, segFrom, segTo,
    fromFacePos, fromSurfPos, fromIsZ, fromExtSign,
    toFacePos,   toSurfPos,   toIsZ,   toExtSign } = wrap;

  const { faceGeos, bendGeos, retGeos } = useMemo(() => {
    const n = Math.max(1, Math.round(bendSegments));

    const fromGeos = buildFaceGeos(oy, H, fromIsZ, fromExtSign,
      fromFacePos, fromSurfPos, cx, cz, segFrom);
    const toGeos   = buildFaceGeos(oy, H, toIsZ,   toExtSign,
      toFacePos,   toSurfPos,   cx, cz, segTo);

    const bends: THREE.BufferGeometry[] = [];
    for (let i = 0; i < n; i++) {
      const θ0 = arcStart + (i       / n) * (arcEnd - arcStart);
      const θ1 = arcStart + ((i + 1) / n) * (arcEnd - arcStart);
      const x0 = cx + d * Math.cos(θ0), z0 = cz + d * Math.sin(θ0);
      const x1 = cx + d * Math.cos(θ1), z1 = cz + d * Math.sin(θ1);
      bends.push(makeQuad(
        m(x0, oy,   z0), m(x1, oy,   z1),
        m(x1, oy+H, z1), m(x0, oy+H, z0),
      ));
    }

    return {
      faceGeos: [fromGeos[0], toGeos[0]],
      bendGeos: bends,
      retGeos:  [...fromGeos.slice(1), ...toGeos.slice(1)],
    };
  }, [wrap, d, bendSegments]); // eslint-disable-line react-hooks/exhaustive-deps

  const faceCol = selected ? "#d8c4ff" : "#aac4e2";
  const bendCol = selected ? "#c0aaff" : "#8898d0";
  const retCol  = selected ? "#b09de8" : "#6888b0";
  const click   = useCallback((e: { stopPropagation(): void }) => {
    e.stopPropagation(); onSelect(wrap.id);
  }, [wrap.id, onSelect]);

  return (
    <group>
      {faceGeos.map((g, i) => (
        <mesh key={`f${i}`} geometry={g} onClick={click}>
          <meshStandardMaterial color={faceCol} metalness={0.65} roughness={0.24} side={THREE.DoubleSide} />
        </mesh>
      ))}
      {bendGeos.map((g, i) => (
        <mesh key={`b${i}`} geometry={g} onClick={click}>
          <meshStandardMaterial color={bendCol} metalness={0.72} roughness={0.18} side={THREE.DoubleSide} />
        </mesh>
      ))}
      {retGeos.map((g, i) => (
        <mesh key={`r${i}`} geometry={g} onClick={click}>
          <meshStandardMaterial color={retCol} metalness={0.50} roughness={0.38} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </group>
  );
}

// ── 3D: Camera ────────────────────────────────────────────────────────────────

function BuildingCamera({ L, W, H }: { L: number; W: number; H: number }) {
  const { camera } = useThree();
  const initialized = useRef(false);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    const maxDim = Math.max(L, W, H);
    const dist = maxDim * S * 1.4;
    // Position: outside front-right corner (AB), elevated
    camera.position.set(L * S + dist, H * S * 0.75, -dist);
    (camera as THREE.PerspectiveCamera).updateProjectionMatrix();
  }); // intentionally no dep array — fires once via ref guard
  return null;
}

// ── UI atoms ──────────────────────────────────────────────────────────────────

function Num({ label, value, min, max, step = 1, unit, onChange }: {
  label: string; value: number; min?: number; max?: number;
  step?: number; unit?: string; onChange: (v: number) => void;
}) {
  return (
    <div style={{ marginBottom: 9 }}>
      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase",
        letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 3 }}>
        {label}{unit && <span style={{ opacity: 0.5 }}> ({unit})</span>}
      </div>
      <input type="number" value={value} min={min} max={max} step={step}
        onChange={e => onChange(Number(e.target.value))}
        style={{ width: "100%", background: "rgba(255,255,255,0.06)",
          border: "1px solid rgba(255,255,255,0.12)", borderRadius: 6,
          color: "var(--text-primary)", padding: "5px 9px", fontSize: 13,
          outline: "none", boxSizing: "border-box", fontFamily: "inherit" }} />
    </div>
  );
}

function Card({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="glass-sm" style={{ padding: "11px 13px", marginBottom: 10 }}>
      <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase",
        letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 9 }}>
        {label}
      </div>
      {children}
    </div>
  );
}

function KV({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between",
      alignItems: "baseline", marginBottom: 5, fontSize: 12 }}>
      <span style={{ color: "var(--text-subtle)" }}>{k}</span>
      <span style={{ color: "var(--text-primary)", fontWeight: 600,
        fontFamily: mono ? "monospace" : "inherit", fontSize: mono ? 11 : 12 }}>{v}</span>
    </div>
  );
}

function SegControl<T extends string>({ options, value, onChange, colors }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  colors?: Partial<Record<T, string>>;
}) {
  return (
    <div style={{ display: "flex", gap: 3,
      background: "rgba(255,255,255,0.04)", borderRadius: 9, padding: 3,
      border: "1px solid rgba(255,255,255,0.07)" }}>
      {options.map(opt => {
        const active = value === opt.value;
        const bg = active ? (colors?.[opt.value] ?? "linear-gradient(135deg,#06b6d4,#3b82f6)") : "transparent";
        return (
          <button key={opt.value} onClick={() => onChange(opt.value)} style={{
            flex: 1, padding: "8px 0", borderRadius: 6, border: "none",
            cursor: "pointer", fontSize: 11, fontWeight: 700, fontFamily: "inherit",
            background: bg,
            color: active ? "#fff" : "var(--text-subtle)",
            transition: "background 0.18s, color 0.18s", letterSpacing: "0.02em",
          }}>
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function BuildingTestPage() {
  const [params, setParams] = useState<BuildingParams>({
    buildingL: 4000, buildingW: 3000, buildingH: 2800,
    panelW: 1000, panelH: 600, edgeDepth: 30, gap: 6,
  });
  const [panelMode,    setPanelMode]    = useState<PanelMode>("separate");
  const [bendSegments, setBendSegments] = useState(3);
  const [selectedId,   setSelectedId]  = useState<string | null>(null);
  const [exporting,    setExporting]   = useState(false);

  const set = (k: keyof BuildingParams) => (v: number) =>
    setParams(p => ({ ...p, [k]: v }));

  const { panels, wraps } = useMemo(
    () => computeLayout(params, panelMode),
    [params, panelMode],
  );

  // Deselect when panel disappears after layout change
  const allIds = useMemo(() => new Set([...panels.map(p => p.id), ...wraps.map(w => w.id)]), [panels, wraps]);
  useEffect(() => { if (selectedId && !allIds.has(selectedId)) setSelectedId(null); }, [allIds, selectedId]);

  const selectedPanel = selectedId && !selectedId.startsWith("W-")
    ? panels.find(p => p.id === selectedId) ?? null : null;
  const selectedWrap = selectedId?.startsWith("W-")
    ? wraps.find(w => w.id === selectedId) ?? null : null;

  const { buildingL: L, buildingW: W, buildingH: H, edgeDepth: d } = params;

  const exportDxf = useCallback(async () => {
    if (!selectedPanel && !selectedWrap) return;
    setExporting(true);
    try {
      let url_path: string, body: object, fname: string;
      if (selectedWrap) {
        url_path = `${BASE}/corner-wrap-outside/dxf`;
        fname    = `wrap-${selectedWrap.corner}-${selectedWrap.row}.dxf`;
        body     = {
          segFrom:    selectedWrap.segFrom,
          segTo:      selectedWrap.segTo,
          height:     selectedWrap.visH,
          edge_depth: d,
          filename:   fname,
        };
      } else {
        url_path = `${BASE}/folded-board/dxf`;
        fname    = `panel-${selectedPanel!.id}.dxf`;
        body     = {
          width: selectedPanel!.visW, height: selectedPanel!.visH,
          edge_depth: d, filename: fname,
        };
      }
      const res  = await fetch(url_path, { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      Object.assign(document.createElement("a"), { href, download: fname }).click();
      URL.revokeObjectURL(href);
    } catch (e) { console.error(e); }
    setExporting(false);
  }, [selectedPanel, selectedWrap, d]);

  // Wall counts for stats
  const countByWall = useMemo(() => {
    const c: Record<WallName, number> = { A: 0, B: 0, C: 0, D: 0 };
    panels.forEach(p => c[p.wall]++);
    return c;
  }, [panels]);

  const orbitTarget: [number, number, number] = [L / 2 * S, H / 2 * S, W / 2 * S];

  const wrapCornerCounts = useMemo(() => {
    const c: Record<CornerName, number> = { AB: 0, BC: 0, CD: 0, DA: 0 };
    wraps.forEach(w => c[w.corner]++);
    return c;
  }, [wraps]);

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: "var(--bg-primary)" }}>

      {/* ── Left controls ── */}
      <div style={{ width: 240, flexShrink: 0, overflowY: "auto", padding: "18px 14px",
        borderRight: "1px solid var(--glass-border)" }}>

        <div style={{ marginBottom: 12 }}>
          <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em",
            textTransform: "uppercase", color: "var(--text-subtle)" }}>
            Building Test
          </span>
          <h1 style={{ fontSize: 16, fontWeight: 800, margin: "4px 0 4px", letterSpacing: "-0.02em" }}>
            4-Wall{" "}
            <span style={{ background: "linear-gradient(135deg,#10b981,#06b6d4)",
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
              Building
            </span>
          </h1>
          <p style={{ fontSize: 10, color: "var(--text-subtle)", margin: 0, lineHeight: 1.55 }}>
            Outside corners · 4 walls · wrap or separate panels
          </p>
        </div>

        {/* Panel mode toggle */}
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 6 }}>
            Panel Style
          </div>
          <SegControl<PanelMode>
            value={panelMode} onChange={v => { setPanelMode(v); setSelectedId(null); }}
            options={[
              { value: "separate", label: "⬜ Separate" },
              { value: "wrap",     label: "⌐ Wrap Corners" },
            ]}
            colors={{
              separate: "linear-gradient(135deg,#6366f1,#7c3aed)",
              wrap:     "linear-gradient(135deg,#10b981,#06b6d4)",
            }}
          />
          {panelMode === "wrap" && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 9, color: "var(--text-subtle)", lineHeight: 1.6,
                padding: "6px 8px", marginBottom: 8,
                background: "rgba(16,185,129,0.07)",
                border: "1px solid rgba(16,185,129,0.18)", borderRadius: 6 }}>
                Corner panels span both walls. One panel per row at each of the 4 corners.
              </div>
              <Num
                label="Bend segments"
                value={bendSegments} min={1} max={8} step={1}
                onChange={setBendSegments}
              />
            </div>
          )}
        </div>

        <Card label="Building dimensions">
          <Num label="Length (Wall A/C)" value={params.buildingL} min={500} max={20000} step={100} unit="mm" onChange={set("buildingL")} />
          <Num label="Width (Wall B/D)"  value={params.buildingW} min={500} max={20000} step={100} unit="mm" onChange={set("buildingW")} />
          <Num label="Height"            value={params.buildingH} min={200} max={15000} step={100} unit="mm" onChange={set("buildingH")} />
        </Card>

        <Card label="Panel">
          <Num label="Panel width"   value={params.panelW}    min={100} max={4000} step={50}  unit="mm" onChange={set("panelW")} />
          <Num label="Panel height"  value={params.panelH}    min={100} max={4000} step={50}  unit="mm" onChange={set("panelH")} />
          <Num label="Edge / return" value={params.edgeDepth} min={5}   max={200}  step={5}   unit="mm" onChange={set("edgeDepth")} />
          <Num label="Joint gap"     value={params.gap}       min={0}   max={50}   step={1}   unit="mm" onChange={set("gap")} />
        </Card>

        <Card label="Panel count">
          {panelMode === "wrap" ? (
            <>
              <KV k="Wrap — Corner AB"  v={wrapCornerCounts.AB} />
              <KV k="Wrap — Corner BC"  v={wrapCornerCounts.BC} />
              <KV k="Wrap — Corner CD"  v={wrapCornerCounts.CD} />
              <KV k="Wrap — Corner DA"  v={wrapCornerCounts.DA} />
              <div style={{ height: 1, background: "var(--glass-border)", margin: "7px 0" }} />
              <KV k="Regular Wall A"    v={countByWall.A} />
              <KV k="Regular Wall B"    v={countByWall.B} />
              <KV k="Regular Wall C"    v={countByWall.C} />
              <KV k="Regular Wall D"    v={countByWall.D} />
              <div style={{ height: 1, background: "var(--glass-border)", margin: "7px 0" }} />
              <KV k="Total"             v={panels.length + wraps.length} />
            </>
          ) : (
            <>
              <KV k="Wall A" v={countByWall.A} />
              <KV k="Wall B" v={countByWall.B} />
              <KV k="Wall C" v={countByWall.C} />
              <KV k="Wall D" v={countByWall.D} />
              <div style={{ height: 1, background: "var(--glass-border)", margin: "7px 0" }} />
              <KV k="Total" v={panels.length} />
            </>
          )}
        </Card>

        <Card label="Coordinate model">
          <div style={{ fontSize: 10, color: "var(--text-subtle)", lineHeight: 1.75 }}>
            <div>Wall A (front)  z=0, panels z=−d</div>
            <div>Wall B (right)  x=L, panels x=L+d</div>
            <div>Wall C (back)   z=W, panels z=W+d</div>
            <div>Wall D (left)   x=0, panels x=−d</div>
            <div style={{ marginTop: 6, color: "#86efac" }}>All 4 corners are convex (outside).</div>
          </div>
        </Card>
      </div>

      {/* ── 3D canvas ── */}
      <div style={{ flex: 1, background: "#07070e", position: "relative" }}>
        <Canvas camera={{ fov: 42, near: 0.001, far: 1000 }} gl={{ antialias: true }}
          style={{ width: "100%", height: "100%" }}
          onPointerMissed={() => setSelectedId(null)}>
          <Suspense fallback={null}>
            <BuildingCamera L={L} W={W} H={H} />

            <ambientLight intensity={0.40} />
            <directionalLight position={[5, 8, -4]} intensity={0.90} castShadow />
            <directionalLight position={[-4, 3, 6]}  intensity={0.30} />
            <directionalLight position={[2, -2, -3]} intensity={0.12} />

            <BuildingBody L={L} W={W} H={H} />

            {/* Wall labels at mid-face, just above mid-height */}
            <WallLabel pos={[L / 2 * S, H * 0.62 * S, -params.edgeDepth * 2 * S]} text="A" />
            <WallLabel pos={[(L + params.edgeDepth * 2) * S, H * 0.62 * S, W / 2 * S]} text="B" />
            <WallLabel pos={[L / 2 * S, H * 0.62 * S, (W + params.edgeDepth * 2) * S]} text="C" />
            <WallLabel pos={[-params.edgeDepth * 2 * S, H * 0.62 * S, W / 2 * S]} text="D" />

            {/* Regular panels */}
            {panels.map(p => (
              <WallPanelMesh key={p.id} panel={p}
                selected={p.id === selectedId} onSelect={setSelectedId} />
            ))}

            {/* Corner wrap panels */}
            {wraps.map(w => (
              <CornerWrapMesh key={w.id} wrap={w} edgeDepth={params.edgeDepth}
                bendSegments={bendSegments}
                selected={w.id === selectedId} onSelect={setSelectedId} />
            ))}

            {/* Ground plane */}
            <mesh rotation={[-Math.PI / 2, 0, 0]}
              position={[L / 2 * S, -0.001, W / 2 * S]}>
              <planeGeometry args={[(L + 4000) * S, (W + 4000) * S]} />
              <meshStandardMaterial color="#0c0e18" roughness={1} />
            </mesh>

            <OrbitControls enableDamping dampingFactor={0.08} target={orbitTarget} makeDefault />
          </Suspense>
        </Canvas>

        {/* Mode badge */}
        <div style={{ position: "absolute", top: 14, left: "50%", transform: "translateX(-50%)",
          display: "flex", gap: 6, pointerEvents: "none" }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
            color: "#86efac", background: "rgba(0,0,0,0.55)", padding: "4px 14px",
            borderRadius: 20, border: "1px solid rgba(34,197,94,0.25)", whiteSpace: "nowrap" }}>
            Outside corners · 4 walls
          </div>
          {panelMode === "wrap" && (
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
              color: "#6ee7b7", background: "rgba(0,0,0,0.55)", padding: "4px 14px",
              borderRadius: 20, border: "1px solid rgba(16,185,129,0.30)", whiteSpace: "nowrap" }}>
              Wrap corners
            </div>
          )}
        </div>

        <div style={{ position: "absolute", bottom: 14, left: "50%", transform: "translateX(-50%)",
          fontSize: 11, color: "rgba(255,255,255,0.3)", pointerEvents: "none",
          background: "rgba(0,0,0,0.4)", padding: "4px 12px", borderRadius: 6 }}>
          Click a panel to inspect · Orbit with mouse
        </div>
      </div>

      {/* ── Right info panel ── */}
      <div style={{ width: 260, flexShrink: 0, overflowY: "auto", padding: "18px 14px",
        borderLeft: "1px solid var(--glass-border)" }}>

        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)", marginBottom: 4 }}>
          {selectedWrap
            ? `Corner ${selectedWrap.corner} — Row ${selectedWrap.row}`
            : selectedPanel
              ? `Panel ${selectedPanel.id}`
              : "No panel selected"}
        </div>
        <div style={{ fontSize: 10, color: "#86efac", marginBottom: 12,
          fontWeight: 600, letterSpacing: "0.04em" }}>
          {selectedWrap
            ? `Wrap panel · outside corner ${selectedWrap.corner}`
            : selectedPanel
              ? `Wall ${selectedPanel.wall} · outside · ${panelMode}`
              : "4-wall building · outside corners"}
        </div>

        {selectedWrap ? (
          <>
            <Card label="Corner wrap panel">
              <KV k="Corner"       v={selectedWrap.corner} />
              <KV k="Row"          v={selectedWrap.row} />
              <KV k="From seg"     v={`${selectedWrap.segFrom} mm`} mono />
              <KV k="To seg"       v={`${selectedWrap.segTo} mm`} mono />
              <KV k="Face height"  v={`${selectedWrap.visH} mm`} mono />
              <KV k="Edge depth"   v={`${d} mm`} mono />
              <KV k="Bend angle"   v="90° outside" />
              <KV k="Segments"     v={bendSegments} />
            </Card>

            <Card label="Flat blank">
              <KV k="From face"    v={`${selectedWrap.segFrom} mm`} mono />
              <KV k="Arc (unrolled)" v={`${(Math.PI / 2 * d).toFixed(0)} mm`} mono />
              <KV k="To face"      v={`${selectedWrap.segTo} mm`} mono />
              <KV k="Total width"  v={`${(2 * d + selectedWrap.segFrom + Math.PI / 2 * d + selectedWrap.segTo).toFixed(0)} mm`} mono />
              <KV k="Total height" v={`${selectedWrap.visH + 2 * d} mm`} mono />
              <div style={{ marginTop: 8, padding: "6px 8px", fontSize: 9,
                background: "rgba(16,185,129,0.07)", border: "1px solid rgba(16,185,129,0.18)",
                borderRadius: 5, color: "var(--text-subtle)", lineHeight: 1.6 }}>
                Outside corner — no V-notch relief needed. Simple rectangle with 4 bend lines.
                Arc strip width = π/2 × edge_depth.
              </div>
            </Card>

            <button onClick={exportDxf} disabled={exporting} style={{
              width: "100%", padding: "10px 0", borderRadius: 9, border: "none",
              cursor: exporting ? "default" : "pointer",
              background: "linear-gradient(135deg,#10b981,#06b6d4)",
              color: "#fff", fontSize: 13, fontWeight: 700,
              opacity: exporting ? 0.6 : 1, fontFamily: "inherit",
            }}>
              {exporting ? "Exporting…" : "↓ Export Wrap DXF"}
            </button>
            <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-subtle)", textAlign: "center" }}>
              Outside corner wrap · {d}mm returns · 90° bend
            </div>
          </>
        ) : selectedPanel ? (
          <>
            <Card label="Panel info">
              <KV k="Wall"       v={`Wall ${selectedPanel.wall}`} />
              <KV k="Row"        v={selectedPanel.row} />
              <KV k="Column"     v={selectedPanel.col} />
              <KV k="Face size"  v={`${selectedPanel.visW} × ${selectedPanel.visH} mm`} mono />
              <KV k="Edge depth" v={`${d} mm`} mono />
              <KV k="Blank"      v={`${selectedPanel.visW + 2 * d} × ${selectedPanel.visH + 2 * d} mm`} mono />
            </Card>

            <Card label="Position">
              <KV k="Face plane"  v={selectedPanel.faceIsZ
                ? `z = ${selectedPanel.facePos} mm` : `x = ${selectedPanel.facePos} mm`} mono />
              <KV k="Wall surface" v={selectedPanel.faceIsZ
                ? `z = ${selectedPanel.surfPos} mm` : `x = ${selectedPanel.surfPos} mm`} mono />
              <KV k="Along start" v={`${selectedPanel.along} mm`} mono />
            </Card>

            <button onClick={exportDxf} disabled={exporting} style={{
              width: "100%", padding: "10px 0", borderRadius: 9, border: "none",
              cursor: exporting ? "default" : "pointer",
              background: "linear-gradient(135deg,#06b6d4,#7c3aed)",
              color: "#fff", fontSize: 13, fontWeight: 700,
              opacity: exporting ? 0.6 : 1, fontFamily: "inherit",
            }}>
              {exporting ? "Exporting…" : "↓ Export Panel DXF"}
            </button>
            <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-subtle)", textAlign: "center" }}>
              Plus-shaped flat blank · {d}mm returns
            </div>
          </>
        ) : (
          <div style={{ fontSize: 12, color: "var(--text-subtle)", lineHeight: 1.7 }}>
            <p style={{ margin: "0 0 10px" }}>
              Click any panel to inspect it and export its flat-blank DXF.
            </p>
            <p style={{ margin: "0 0 10px" }}>
              In Wrap Corner mode, one panel per row spans across each 90° building corner.
            </p>
            <div className="glass-sm" style={{ padding: "10px 12px", fontSize: 10, lineHeight: 1.7 }}>
              <div style={{ fontWeight: 700, marginBottom: 5, color: "var(--text-muted)" }}>Corners</div>
              {(["AB", "BC", "CD", "DA"] as CornerName[]).map(c => (
                <div key={c} style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                  <span style={{ color: "var(--text-subtle)" }}>Corner {c}</span>
                  <span style={{ color: "#86efac", fontWeight: 600 }}>
                    {wrapCornerCounts[c]} wrap rows
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
