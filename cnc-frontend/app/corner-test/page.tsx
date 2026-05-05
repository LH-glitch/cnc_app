"use client";

import { useState, useMemo, useCallback, Suspense, useEffect, useRef } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import * as THREE from "three";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const S = 0.001; // mm → metres

// ── Types ─────────────────────────────────────────────────────────────────────

type CornerMode = "outside" | "inside";
type PanelMode  = "separate" | "wrap" | "multi-wrap";
type PreviewStyle = "clean" | "detailed";
type WallId = "A" | "B" | "C" | "D";
type CornerId = "AB" | "BC" | "CD" | "DA";

interface SceneParams {
  wallAWidth: number;
  wallBWidth: number;
  wallHeight: number;
  panelW:     number;
  panelH:     number;
  edgeDepth:  number;
  gap:        number;
  cornerAngle: number;
  protrusionWidth: number;
  protrusionDepth: number;
  protrusionPosition: number;
}

interface PanelDef {
  id: string;
  wall: WallId;
  wallKey?: string;
  row: number; col: number;
  visW: number; visH: number;
  ox: number; oy: number; oz: number;
}

// Wrap panel spans both walls with one bend at the corner (any angle).
interface WrapPanelDef {
  id:   string;
  corner?: string;
  fromWall?: WallId;
  toWall?: WallId;
  row:  number;
  oy:   number;
  visH: number;
  segA: number;   // mm — face width on Wall A (x direction)
  segB: number;   // mm — face width on Wall B (z direction)
}

// One wall segment covered by a multi-wrap panel
interface WallSpan {
  wall:   WallDef;
  startU: number;   // position along wall (mm from wall start)
  endU:   number;
  length: number;   // = endU - startU
}

// One corner crossing within a multi-wrap panel
interface CornerCross {
  corner:         CornerDef;
  fromWall:       WallDef;
  toWall:         WallDef;
  distAlongPanel: number;  // mm from panel left edge to this bend
  angleDeg:       number;
}

// A panel that can span multiple walls and cross multiple corners
interface MultiWrapDef {
  id:          string;
  row:         number;
  oy:          number;
  visH:        number;
  perimStart:  number;   // mm from perimeter origin (wall A start)
  totalWidth:  number;   // sum of face widths (not including arc lengths)
  wallSpans:   WallSpan[];
  corners:     CornerCross[];
}

// ── Coordinate model ──────────────────────────────────────────────────────────
//
//  All panel geometry is vector-based: wallPoint(wall, u, v) places any point
//  at position u along the wall tangent and v along the wall outward normal.
//  offset = +d for outside (convex), -d for inside (concave).
//  Corner arcs use atan2 on the outward vectors — no axis-aligned assumptions.

interface WallDef {
  id: string;
  wall: WallId;
  label: string;
  length: number;
  start: { x: number; z: number };
  tangent: { x: number; z: number };
  outward: { x: number; z: number };
}

interface CornerDef {
  id: string;
  from: WallDef;
  to: WallDef;
  point: { x: number; z: number };
  angleDeg: number;
}

// ── Multi-wrap perimeter layout ───────────────────────────────────────────────
//
//  Treats the building perimeter as a continuous linear strip (wall A start →
//  wall A → corner AB → wall B → ... → wall D end).  Panels are placed every
//  (panelW + gap) mm along that strip and can cross as many corners as their
//  width allows.  The strip is linear, not circular — the DA corner is not
//  included so panels never wrap around the full building.

interface PerimItem {
  wall:        WallDef;
  cornerAfter: CornerDef | null;  // corner to the next wall (null for last wall)
  startDist:   number;            // cumulative mm from perimeter origin
}

function buildPerimeter(walls: WallDef[], corners: CornerDef[]): PerimItem[] {
  let dist = 0;
  return walls.map((w, i) => {
    const item: PerimItem = {
      wall:        w,
      cornerAfter: i < walls.length - 1 ? corners[i] : null,
      startDist:   dist,
    };
    dist += w.length;
    return item;
  });
}

function computeMultiWrapLayout(
  params: SceneParams,
  walls: WallDef[],
  corners: CornerDef[],
): { panels: MultiWrapDef[] } {
  const { panelW, panelH, gap, wallHeight: H } = params;
  const perim = buildPerimeter(walls, corners);
  const total = perim.reduce((acc, it) => acc + it.wall.length, 0);
  const panels: MultiWrapDef[] = [];

  for (let row = 0, y = 0; y < H; y += panelH + gap, row++) {
    const visH = Math.min(panelH, H - y);
    if (visH <= 1) break;

    let u = 0;
    let col = 0;
    while (u < total) {
      const panelEnd = Math.min(u + panelW, total);
      const totalW   = panelEnd - u;
      if (totalW <= 1) break;

      const wallSpans:    WallSpan[]    = [];
      const panelCorners: CornerCross[] = [];

      for (const item of perim) {
        const wStart = item.startDist;
        const wEnd   = wStart + item.wall.length;
        const oStart = Math.max(u, wStart);
        const oEnd   = Math.min(panelEnd, wEnd);
        if (oEnd <= oStart) continue;

        wallSpans.push({
          wall:   item.wall,
          startU: oStart - wStart,
          endU:   oEnd   - wStart,
          length: oEnd   - oStart,
        });

        // Corner at the end of this wall segment, if it falls inside the panel
        if (item.cornerAfter && wEnd > u && wEnd < panelEnd) {
          panelCorners.push({
            corner:         item.cornerAfter,
            fromWall:       item.wall,
            toWall:         item.cornerAfter.to,
            distAlongPanel: wEnd - u,
            angleDeg:       item.cornerAfter.angleDeg,
          });
        }
      }

      panels.push({
        id:         `MW-${row}-${col}`,
        row,
        oy:         y,
        visH,
        perimStart: u,
        totalWidth: totalW,
        wallSpans,
        corners:    panelCorners,
      });

      u = panelEnd + gap;
      col++;
    }
  }

  return { panels };
}

// ── Three.js helpers ──────────────────────────────────────────────────────────

const rightNormal = (t: { x: number; z: number }) => ({ x: t.z, z: -t.x });
const add2 = (a: { x: number; z: number }, b: { x: number; z: number }) => ({ x: a.x + b.x, z: a.z + b.z });
const mul2 = (v: { x: number; z: number }, s: number) => ({ x: v.x * s, z: v.z * s });
const wall = (id: string, base: WallId, label: string, length: number, start: { x: number; z: number }, tangent: { x: number; z: number }): WallDef => ({
  id,
  wall: base,
  label,
  length,
  start,
  tangent,
  outward: rightNormal(tangent),
});

function buildingWalls(params: SceneParams): WallDef[] {
  const W = params.wallAWidth;
  const D = params.wallBWidth;
  const theta = THREE.MathUtils.degToRad(Math.min(160, Math.max(35, params.cornerAngle)));
  const aT = { x: 1, z: 0 };
  const bT = { x: Math.cos(theta), z: Math.sin(theta) };
  const cT = { x: -1, z: 0 };
  const dT = { x: -bT.x, z: -bT.z };
  const p0 = { x: 0, z: 0 };
  const p1 = add2(p0, mul2(aT, W));
  const p2 = add2(p1, mul2(bT, D));
  const p3 = add2(p2, mul2(cT, W));

  const protrudes = params.protrusionWidth > 1 && params.protrusionDepth > 1;
  if (!protrudes) {
    return [
      wall("A", "A", "Wall A (front)", W, p0, aT),
      wall("B", "B", "Wall B (right)", D, p1, bT),
      wall("C", "C", "Wall C (back)", W, p2, cT),
      wall("D", "D", "Wall D (left)", D, p3, dT),
    ];
  }

  const pos = Math.min(Math.max(params.protrusionPosition, 50), Math.max(50, W - params.protrusionWidth - 50));
  const pw = Math.min(params.protrusionWidth, Math.max(1, W - pos));
  const pd = params.protrusionDepth;
  const aOut = rightNormal(aT);
  const q0 = p0;
  const q1 = add2(p0, mul2(aT, pos));
  const q2 = add2(q1, mul2(aOut, pd));
  const q3 = add2(q2, mul2(aT, pw));
  const q4 = add2(q1, mul2(aT, pw));

  const out = [
    wall("A-L", "A", "Wall A left", pos, q0, aT),
    wall("A-P-L", "A", "Wall A protrusion side", pd, q1, aOut),
    wall("A-P", "A", "Wall A protrusion face", pw, q2, aT),
    wall("A-P-R", "A", "Wall A protrusion side", pd, q3, mul2(aOut, -1)),
  ];
  const rightLen = W - pos - pw;
  if (rightLen > 1) out.push(wall("A-R", "A", "Wall A right", rightLen, q4, aT));
  return [
    ...out,
    wall("B", "B", "Wall B (right)", D, p1, bT),
    wall("C", "C", "Wall C (back)", W, p2, cT),
    wall("D", "D", "Wall D (left)", D, p3, dT),
  ];
}

function buildingCorners(walls: WallDef[]): CornerDef[] {
  return walls.map((from, i) => {
    const to = walls[(i + 1) % walls.length];
    const point = add2(from.start, mul2(from.tangent, from.length));
    const dot = Math.max(-1, Math.min(1, from.tangent.x * to.tangent.x + from.tangent.z * to.tangent.z));
    const cross = from.tangent.x * to.tangent.z - from.tangent.z * to.tangent.x;
    const turn = Math.abs(THREE.MathUtils.radToDeg(Math.atan2(cross, dot)));
    return { id: `${from.id}-${to.id}`, from, to, point, angleDeg: turn };
  });
}

function layoutBounds(walls: WallDef[]) {
  const points = walls.flatMap(w => [w.start, add2(w.start, mul2(w.tangent, w.length))]);
  const xs = points.map(p => p.x);
  const zs = points.map(p => p.z);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minZ = Math.min(...zs);
  const maxZ = Math.max(...zs);
  return {
    minX,
    maxX,
    minZ,
    maxZ,
    cx: (minX + maxX) / 2,
    cz: (minZ + maxZ) / 2,
    width: Math.max(1, maxX - minX),
    depth: Math.max(1, maxZ - minZ),
  };
}

function computeBuildingLayout(
  params: SceneParams,
  panelMode: PanelMode,
): { walls: WallDef[]; corners: CornerDef[]; regularPanels: PanelDef[]; wraps: WrapPanelDef[]; multiWrapPanels: MultiWrapDef[]; bounds: ReturnType<typeof layoutBounds> } {
  const walls = buildingWalls(params);
  const corners = buildingCorners(walls);
  const bounds = layoutBounds(walls);

  if (panelMode === "multi-wrap") {
    const { panels } = computeMultiWrapLayout(params, walls, corners);
    return { walls, corners, regularPanels: [], wraps: [], multiWrapPanels: panels, bounds };
  }

  const regularPanels: PanelDef[] = [];
  const wraps: WrapPanelDef[] = [];
  const cornerReserve = (wall: WallDef) => (
    panelMode === "wrap" ? Math.min(params.panelW, Math.max(0, (wall.length - params.gap) / 2)) : 0
  );

  for (const wall of walls) {
    for (let row = 0, y = 0; y < params.wallHeight; y += params.panelH + params.gap, row++) {
      const visH = Math.min(params.panelH, params.wallHeight - y);
      if (visH <= 1) break;

      const reserve = cornerReserve(wall);
      const startU = panelMode === "wrap" ? reserve + params.gap : 0;
      const endU = panelMode === "wrap" ? Math.max(startU, wall.length - reserve - params.gap) : wall.length;
      for (let col = panelMode === "wrap" ? 1 : 0, u = startU; u < endU; u += params.panelW + params.gap, col++) {
        const visW = Math.min(params.panelW, endU - u);
        if (visW > 1) {
          regularPanels.push({ id: `${wall.id}-${row}-${col}`, wall: wall.wall, wallKey: wall.id, row, col, visW, visH, ox: u, oy: y, oz: 0 });
        }
      }
    }
  }

  if (panelMode === "wrap") {
    for (const corner of corners) {
      const segA = cornerReserve(corner.from);
      const segB = cornerReserve(corner.to);
      if (segA <= 1 || segB <= 1) continue;
      for (let row = 0, y = 0; y < params.wallHeight; y += params.panelH + params.gap, row++) {
        const visH = Math.min(params.panelH, params.wallHeight - y);
        if (visH <= 1) break;
        wraps.push({
          id: `W-${corner.id}-${row}`,
          corner: corner.id,
          fromWall: corner.from.wall,
          toWall: corner.to.wall,
          row,
          oy: y,
          visH,
          segA,
          segB,
        });
      }
    }
  }

  return { walls, corners, regularPanels, wraps, multiWrapPanels: [], bounds };
}

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

function makeVerticalStrip(path: { x: number; z: number }[], y0: number, y1: number): THREE.BufferGeometry {
  const vertices: number[] = [];
  const indices: number[] = [];

  path.forEach(({ x, z }) => {
    const bottom = m(x, y0, z);
    const top = m(x, y1, z);
    vertices.push(bottom.x, bottom.y, bottom.z, top.x, top.y, top.z);
  });

  for (let i = 0; i < path.length - 1; i++) {
    const a = i * 2;
    const b = a + 1;
    const c = a + 2;
    const d = a + 3;
    indices.push(a, c, d, a, d, b);
  }

  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(vertices), 3));
  g.setIndex(indices);
  g.computeVertexNormals();
  return g;
}

const wallPoint = (wall: WallDef, u: number, v: number) => ({
  x: wall.start.x + wall.tangent.x * u + wall.outward.x * v,
  z: wall.start.z + wall.tangent.z * u + wall.outward.z * v,
});

const point3 = (p: { x: number; z: number }, y: number) => m(p.x, y, p.z);

function makeWallQuad(
  wall: WallDef,
  u0: number,
  u1: number,
  y0: number,
  y1: number,
  v0: number,
  v1: number,
): THREE.BufferGeometry {
  return makeQuad(
    point3(wallPoint(wall, u0, v0), y0),
    point3(wallPoint(wall, u1, v0), y0),
    point3(wallPoint(wall, u1, v1), y1),
    point3(wallPoint(wall, u0, v1), y1),
  );
}

function makeWallFaceQuad(
  wall: WallDef,
  u0: number,
  u1: number,
  y0: number,
  y1: number,
  v: number,
): THREE.BufferGeometry {
  return makeQuad(
    point3(wallPoint(wall, u0, v), y0),
    point3(wallPoint(wall, u1, v), y0),
    point3(wallPoint(wall, u1, v), y1),
    point3(wallPoint(wall, u0, v), y1),
  );
}

// ── 3D: wall bodies ───────────────────────────────────────────────────────────

const WALL_COLORS: Record<WallId, { face: string; ret: string }> = {
  A: { face: "#5ba3d8", ret: "#3a7ab4" },
  B: { face: "#44b896", ret: "#2a9478" },
  C: { face: "#d4904e", ret: "#b06c2e" },
  D: { face: "#c46aaa", ret: "#9c4888" },
};

const CLEAN_WALL_COLORS: Record<WallId, { face: string; ret: string }> = {
  A: { face: "#9db8d8", ret: "#6a90b8" },
  B: { face: "#88b8aa", ret: "#5a9890" },
  C: { face: "#d9b980", ret: "#b89158" },
  D: { face: "#cba0ba", ret: "#a97894" },
};

const WRAP_FACE  = "#5a9acc";
const WRAP_RET   = "#3a78aa";
const CLEAN_WRAP_FACE = "#aac4e2";
const CLEAN_WRAP_RET  = "#6888b0";
const SEL_FACE   = "#68e8ff";
const SEL_RET    = "#28c0e0";
const SEL_EMI    = "#007898";
const SEL_EMI_I  = 0.44;
const DIM_OPA    = 0.13;

function BuildingWalls({ walls, H, previewStyle }: { walls: WallDef[]; H: number; previewStyle: PreviewStyle }) {
  const T = 120;
  const wallColor = previewStyle === "clean" ? "#252b3a" : "#1a2438";
  return (
    <group>
      {walls.map(wall => {
        const center = wallPoint(wall, wall.length / 2, -T / 2);
        const rotY = -Math.atan2(wall.tangent.z, wall.tangent.x);
        return (
          <mesh key={wall.id} position={[center.x * S, H / 2 * S, center.z * S]} rotation={[0, rotY, 0]}>
            <boxGeometry args={[wall.length * S, H * S, T * S]} />
            <meshStandardMaterial color={wallColor} roughness={0.88} metalness={0.06} />
          </mesh>
        );
      })}
    </group>
  );
}

function WallLabels({ walls, H }: { walls: WallDef[]; H: number }) {
  return (
    <group>
      {walls.map(wall => {
        const p = wallPoint(wall, wall.length / 2, 180);
        return (
            <Html key={wall.id} position={[p.x * S, (H + 130) * S, p.z * S]} center>
            <div style={{
              padding: "3px 8px", borderRadius: 6, background: "rgba(0,0,0,0.65)",
              border: "1px solid rgba(255,255,255,0.16)", color: "#e5eefc",
              fontSize: 11, fontWeight: 800, whiteSpace: "nowrap", pointerEvents: "none",
            }}>
              {wall.label}
            </div>
          </Html>
        );
      })}
    </group>
  );
}

type DebugPt = { x: number; y: number; z: number };
type DebugSeg = [DebugPt, DebugPt];

function debugPt(p: { x: number; z: number }, y: number): DebugPt {
  return { x: p.x, y, z: p.z };
}

function DebugSegments({ segments, color, opacity = 1, depthTest = false }: {
  segments: DebugSeg[];
  color: string;
  opacity?: number;
  depthTest?: boolean;
}) {
  const geo = useMemo(() => {
    const arr = new Float32Array(segments.flatMap(([a, b]) => [
      a.x * S, a.y * S, a.z * S,
      b.x * S, b.y * S, b.z * S,
    ]));
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(arr, 3));
    return g;
  }, [segments]);

  return (
    <lineSegments geometry={geo}>
      <lineBasicMaterial color={color} transparent opacity={opacity} depthTest={depthTest} />
    </lineSegments>
  );
}

function outlineFromPath(path: { x: number; z: number }[], y0: number, y1: number): DebugSeg[] {
  const segs: DebugSeg[] = [];
  for (let i = 0; i < path.length - 1; i++) {
    segs.push([debugPt(path[i], y0), debugPt(path[i + 1], y0)]);
    segs.push([debugPt(path[i], y1), debugPt(path[i + 1], y1)]);
  }
  if (path.length > 0) {
    segs.push([debugPt(path[0], y0), debugPt(path[0], y1)]);
    segs.push([debugPt(path[path.length - 1], y0), debugPt(path[path.length - 1], y1)]);
  }
  return segs;
}

function wrapDebugPath(corner: CornerDef, A: number, B: number, d: number, mode: CornerMode, bendSegments: number) {
  const n = Math.max(1, Math.round(bendSegments));
  const offset = mode === "outside" ? d : -d;
  const p = corner.point;
  const fromStartPt = { x: p.x - corner.from.tangent.x * A, z: p.z - corner.from.tangent.z * A };
  const toEndPt = { x: p.x + corner.to.tangent.x * B, z: p.z + corner.to.tangent.z * B };

  if (d === 0) return [fromStartPt, { x: p.x, z: p.z }, toEndPt];

  const fromStart = { x: fromStartPt.x + corner.from.outward.x * offset, z: fromStartPt.z + corner.from.outward.z * offset };
  const fromEdge = { x: p.x + corner.from.outward.x * offset, z: p.z + corner.from.outward.z * offset };
  const toEdge = { x: p.x + corner.to.outward.x * offset, z: p.z + corner.to.outward.z * offset };
  const toEnd = { x: toEndPt.x + corner.to.outward.x * offset, z: toEndPt.z + corner.to.outward.z * offset };
  const startAngle = Math.atan2(fromEdge.z - p.z, fromEdge.x - p.x);
  const endAngle = Math.atan2(toEdge.z - p.z, toEdge.x - p.x);
  let delta = endAngle - startAngle;
  while (delta <= -Math.PI) delta += Math.PI * 2;
  while (delta > Math.PI) delta -= Math.PI * 2;

  const path = [fromStart, fromEdge];
  for (let i = 1; i <= n; i++) {
    const a = startAngle + delta * (i / n);
    path.push({ x: p.x + Math.cos(a) * d, z: p.z + Math.sin(a) * d });
  }
  path.push(toEnd);
  return path;
}

function multiWrapDebugPath(panel: MultiWrapDef, d: number, mode: CornerMode, bendSegments: number) {
  const offset = mode === "outside" ? d : -d;
  const n = Math.max(1, Math.round(bendSegments));
  const absOff = Math.abs(offset);
  const path: { x: number; z: number }[] = [];

  for (let i = 0; i < panel.wallSpans.length; i++) {
    const span = panel.wallSpans[i];
    if (i === 0) path.push(wallPoint(span.wall, span.startU, offset));
    path.push(wallPoint(span.wall, span.endU, offset));

    if (i < panel.corners.length && d !== 0) {
      const cc = panel.corners[i];
      const p = cc.corner.point;
      const fromEdge = { x: p.x + cc.fromWall.outward.x * offset, z: p.z + cc.fromWall.outward.z * offset };
      const toEdge = { x: p.x + cc.toWall.outward.x * offset, z: p.z + cc.toWall.outward.z * offset };
      const startA = Math.atan2(fromEdge.z - p.z, fromEdge.x - p.x);
      const endA = Math.atan2(toEdge.z - p.z, toEdge.x - p.x);
      let delta = endA - startA;
      while (delta <= -Math.PI) delta += Math.PI * 2;
      while (delta > Math.PI) delta -= Math.PI * 2;
      for (let j = 1; j <= n; j++) {
        const a = startA + delta * (j / n);
        path.push({ x: p.x + Math.cos(a) * absOff, z: p.z + Math.sin(a) * absOff });
      }
    }
  }

  return path;
}

function DebugGeometryOverlay({ walls, regularPanels, wraps, multiWrapPanels, wallById, cornerById, params, mode, bendSegments }: {
  walls: WallDef[];
  regularPanels: PanelDef[];
  wraps: WrapPanelDef[];
  multiWrapPanels: MultiWrapDef[];
  wallById: Record<string, WallDef>;
  cornerById: Record<string, CornerDef>;
  params: SceneParams;
  mode: CornerMode;
  bendSegments: number;
}) {
  const offset = mode === "outside" ? params.edgeDepth : -params.edgeDepth;
  const vectorY = params.wallHeight + 260;
  const vectorLen = 420;
  const panelRaise = 7;

  const wallDirSegs = useMemo<DebugSeg[]>(() => walls.map(w => {
    const mid = wallPoint(w, w.length / 2, 0);
    return [
      debugPt(mid, vectorY),
      debugPt({ x: mid.x + w.tangent.x * vectorLen, z: mid.z + w.tangent.z * vectorLen }, vectorY),
    ];
  }), [walls, vectorY]);

  const wallNormalSegs = useMemo<DebugSeg[]>(() => walls.map(w => {
    const mid = wallPoint(w, w.length / 2, 0);
    return [
      debugPt(mid, vectorY + 70),
      debugPt({ x: mid.x + w.outward.x * vectorLen, z: mid.z + w.outward.z * vectorLen }, vectorY + 70),
    ];
  }), [walls, vectorY]);

  const regularOutlines = useMemo<DebugSeg[]>(() => regularPanels.flatMap(panel => {
    const wall = wallById[panel.wallKey ?? panel.wall];
    if (!wall) return [];
    const u0 = panel.ox;
    const u1 = panel.ox + panel.visW;
    const y0 = panel.oy + panelRaise;
    const y1 = panel.oy + panel.visH + panelRaise;
    return [
      [debugPt(wallPoint(wall, u0, offset), y0), debugPt(wallPoint(wall, u1, offset), y0)],
      [debugPt(wallPoint(wall, u1, offset), y0), debugPt(wallPoint(wall, u1, offset), y1)],
      [debugPt(wallPoint(wall, u1, offset), y1), debugPt(wallPoint(wall, u0, offset), y1)],
      [debugPt(wallPoint(wall, u0, offset), y1), debugPt(wallPoint(wall, u0, offset), y0)],
    ] as DebugSeg[];
  }), [regularPanels, wallById, offset]);

  const wrapOutlines = useMemo<DebugSeg[]>(() => wraps.flatMap(panel => {
    const corner = panel.corner ? cornerById[panel.corner] : null;
    if (!corner) return [];
    return outlineFromPath(
      wrapDebugPath(corner, panel.segA, panel.segB, params.edgeDepth, mode, bendSegments),
      panel.oy + panelRaise,
      panel.oy + panel.visH + panelRaise,
    );
  }), [wraps, cornerById, params.edgeDepth, mode, bendSegments]);

  const multiWrapOutlines = useMemo<DebugSeg[]>(() => multiWrapPanels.flatMap(panel => (
    outlineFromPath(
      multiWrapDebugPath(panel, params.edgeDepth, mode, bendSegments),
      panel.oy + panelRaise,
      panel.oy + panel.visH + panelRaise,
    )
  )), [multiWrapPanels, params.edgeDepth, mode, bendSegments]);

  return (
    <group>
      <DebugSegments segments={wallDirSegs} color="#facc15" opacity={0.95} />
      <DebugSegments segments={wallNormalSegs} color="#22d3ee" opacity={0.95} />
      <DebugSegments segments={regularOutlines} color="#ffffff" opacity={0.82} />
      <DebugSegments segments={wrapOutlines} color="#ff4fd8" opacity={0.95} />
      <DebugSegments segments={multiWrapOutlines} color="#a78bfa" opacity={0.95} />

      {walls.map(w => {
        const p = wallPoint(w, w.length / 2, 320);
        return (
          <Html key={`debug-${w.id}`} position={[p.x * S, (params.wallHeight + 430) * S, p.z * S]} center>
            <div style={{
              padding: "4px 7px",
              borderRadius: 5,
              background: "rgba(2,6,23,0.82)",
              border: "1px solid rgba(125,211,252,0.45)",
              color: "#e0f2fe",
              fontSize: 10,
              fontFamily: "monospace",
              lineHeight: 1.35,
              whiteSpace: "nowrap",
              pointerEvents: "none",
            }}>
              <div>{w.id} ({w.wall}) len={w.length.toFixed(0)}</div>
              <div style={{ color: "#facc15" }}>t=({w.tangent.x.toFixed(2)}, {w.tangent.z.toFixed(2)})</div>
              <div style={{ color: "#22d3ee" }}>n=({w.outward.x.toFixed(2)}, {w.outward.z.toFixed(2)})</div>
            </div>
          </Html>
        );
      })}

      <Html position={[0, (params.wallHeight + 720) * S, 0]} center>
        <div style={{
          padding: "6px 9px",
          borderRadius: 6,
          background: "rgba(0,0,0,0.72)",
          border: "1px solid rgba(255,255,255,0.22)",
          color: "#e5e7eb",
          fontSize: 11,
          fontFamily: "monospace",
          lineHeight: 1.45,
          whiteSpace: "nowrap",
          pointerEvents: "none",
        }}>
          DEBUG: yellow=tangent, cyan=outward normal, white=panel face, magenta=wrap, violet=multi-wrap
        </div>
      </Html>
    </group>
  );
}

function BuildingPanelMesh({ panel, wall, edgeDepth: d, mode, previewStyle, selected, hasSelection, pulseActive, onSelect }: {
  panel: PanelDef;
  wall: WallDef;
  edgeDepth: number;
  mode: CornerMode;
  previewStyle: PreviewStyle;
  selected: boolean;
  hasSelection: boolean;
  pulseActive: boolean;
  onSelect: (id: string) => void;
}) {
  const { ox: u, oy, visW: W, visH: H } = panel;
  const offset = mode === "outside" ? d : -d;
  const geos = useMemo(() => {
    const u1 = u + W;
    const y1 = oy + H;
    const face = makeWallFaceQuad(wall, u, u1, oy, y1, offset);
    if (d === 0) return [face];
    const top = makeQuad(point3(wallPoint(wall, u, offset), y1), point3(wallPoint(wall, u1, offset), y1), point3(wallPoint(wall, u1, 0), y1), point3(wallPoint(wall, u, 0), y1));
    const bottom = makeQuad(point3(wallPoint(wall, u, 0), oy), point3(wallPoint(wall, u1, 0), oy), point3(wallPoint(wall, u1, offset), oy), point3(wallPoint(wall, u, offset), oy));
    const start = makeQuad(point3(wallPoint(wall, u, offset), oy), point3(wallPoint(wall, u, offset), y1), point3(wallPoint(wall, u, 0), y1), point3(wallPoint(wall, u, 0), oy));
    const end = makeQuad(point3(wallPoint(wall, u1, 0), oy), point3(wallPoint(wall, u1, 0), y1), point3(wallPoint(wall, u1, offset), y1), point3(wallPoint(wall, u1, offset), oy));
    return [face, top, bottom, start, end];
  }, [wall, u, oy, W, H, offset, d]);
  const colors = previewStyle === "clean" ? CLEAN_WALL_COLORS[panel.wall] : WALL_COLORS[panel.wall];
  const dimmed = hasSelection && !selected && !pulseActive;
  const faceColor = selected ? SEL_FACE : colors.face;
  const retColor  = selected ? SEL_RET  : colors.ret;
  const emi   = selected ? SEL_EMI   : pulseActive ? "#166534" : "#000000";
  const emiI  = previewStyle === "clean" ? 0 : selected ? SEL_EMI_I : pulseActive ? 0.28 : 0;
  const faceMetal = previewStyle === "clean" ? 0.48 : selected ? 0.80 : 0.65;
  const retMetal  = previewStyle === "clean" ? 0.36 : selected ? 0.75 : 0.50;
  const faceRough = previewStyle === "clean" ? 0.34 : selected ? 0.16 : 0.26;
  const retRough  = previewStyle === "clean" ? 0.44 : selected ? 0.22 : 0.38;
  const click = useCallback((e: { stopPropagation: () => void }) => {
    e.stopPropagation(); onSelect(panel.id);
  }, [panel.id, onSelect]);

  return (
    <group>
      <mesh geometry={geos[0]} onClick={click}>
        <meshStandardMaterial color={faceColor} metalness={faceMetal}
          roughness={faceRough}
          emissive={emi} emissiveIntensity={emiI}
          transparent={dimmed} opacity={dimmed ? DIM_OPA : 1} side={THREE.DoubleSide} />
      </mesh>
      {geos.slice(1).map((g, i) => (
        <mesh key={i} geometry={g} onClick={click}>
          <meshStandardMaterial color={retColor} metalness={retMetal}
            roughness={retRough}
            emissive={emi} emissiveIntensity={emiI * 0.6}
            transparent={dimmed} opacity={dimmed ? DIM_OPA : 1} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </group>
  );
}

function BuildingWrapPanelMesh({ panel, corner, edgeDepth: d, bendSegments, mode, previewStyle, selected, hasSelection, pulseActive, onSelect }: {
  panel: WrapPanelDef;
  corner: CornerDef;
  edgeDepth: number;
  bendSegments: number;
  mode: CornerMode;
  previewStyle: PreviewStyle;
  selected: boolean;
  hasSelection: boolean;
  pulseActive: boolean;
  onSelect: (id: string) => void;
}) {
  const { oy, visH: H, segA: A, segB: B } = panel;
  const { surfaceGeo, retGeos } = useMemo(() => {
    const n = Math.max(1, Math.round(bendSegments));
    const offset = mode === "outside" ? d : -d;
    const p = corner.point;
    const fromStartPt = { x: p.x - corner.from.tangent.x * A, z: p.z - corner.from.tangent.z * A };
    const toEndPt = { x: p.x + corner.to.tangent.x * B, z: p.z + corner.to.tangent.z * B };

    if (d === 0) {
      return {
        surfaceGeo: makeVerticalStrip([fromStartPt, { x: p.x, z: p.z }, toEndPt], oy, oy + H),
        retGeos: [],
      };
    }

    const fromStart = { x: fromStartPt.x + corner.from.outward.x * offset, z: fromStartPt.z + corner.from.outward.z * offset };
    const fromEdge = { x: p.x + corner.from.outward.x * offset, z: p.z + corner.from.outward.z * offset };
    const toEdge = { x: p.x + corner.to.outward.x * offset, z: p.z + corner.to.outward.z * offset };
    const toEnd = { x: toEndPt.x + corner.to.outward.x * offset, z: toEndPt.z + corner.to.outward.z * offset };
    const startAngle = Math.atan2(fromEdge.z - p.z, fromEdge.x - p.x);
    const endAngle = Math.atan2(toEdge.z - p.z, toEdge.x - p.x);
    let delta = endAngle - startAngle;
    while (delta <= -Math.PI) delta += Math.PI * 2;
    while (delta > Math.PI) delta -= Math.PI * 2;
    const surfacePath = [fromStart, fromEdge];
    for (let i = 1; i <= n; i++) {
      const a = startAngle + delta * (i / n);
      surfacePath.push({ x: p.x + Math.cos(a) * d, z: p.z + Math.sin(a) * d });
    }
    surfacePath.push(toEnd);
    const surfaceGeo = makeVerticalStrip(surfacePath, oy, oy + H);
    const fromU0 = corner.from.length - A;
    const fromU1 = corner.from.length;
    const y1 = oy + H;
    const retFrom = makeQuad(point3(wallPoint(corner.from, fromU0, 0), oy), point3(wallPoint(corner.from, fromU0, offset), oy), point3(wallPoint(corner.from, fromU0, offset), y1), point3(wallPoint(corner.from, fromU0, 0), y1));
    const retTo = makeQuad(point3(wallPoint(corner.to, B, offset), oy), point3(wallPoint(corner.to, B, 0), oy), point3(wallPoint(corner.to, B, 0), y1), point3(wallPoint(corner.to, B, offset), y1));
    const topFrom = makeQuad(point3(wallPoint(corner.from, fromU0, offset), y1), point3(wallPoint(corner.from, fromU1, offset), y1), point3(wallPoint(corner.from, fromU1, 0), y1), point3(wallPoint(corner.from, fromU0, 0), y1));
    const topTo = makeQuad(point3(wallPoint(corner.to, 0, offset), y1), point3(wallPoint(corner.to, B, offset), y1), point3(wallPoint(corner.to, B, 0), y1), point3(wallPoint(corner.to, 0, 0), y1));
    const botFrom = makeQuad(point3(wallPoint(corner.from, fromU0, 0), oy), point3(wallPoint(corner.from, fromU1, 0), oy), point3(wallPoint(corner.from, fromU1, offset), oy), point3(wallPoint(corner.from, fromU0, offset), oy));
    const botTo = makeQuad(point3(wallPoint(corner.to, 0, 0), oy), point3(wallPoint(corner.to, B, 0), oy), point3(wallPoint(corner.to, B, offset), oy), point3(wallPoint(corner.to, 0, offset), oy));
    return { surfaceGeo, retGeos: [retFrom, retTo, topFrom, topTo, botFrom, botTo] };
  }, [panel, corner, d, bendSegments, mode]);
  const dimmed  = hasSelection && !selected && !pulseActive;
  const faceCol = selected ? SEL_FACE : previewStyle === "clean" ? CLEAN_WRAP_FACE : WRAP_FACE;
  const retCol  = selected ? SEL_RET  : previewStyle === "clean" ? CLEAN_WRAP_RET  : WRAP_RET;
  const emi  = selected ? SEL_EMI   : pulseActive ? "#166534" : "#000000";
  const emiI = previewStyle === "clean" ? 0 : selected ? SEL_EMI_I : pulseActive ? 0.28 : 0;
  const faceMetal = previewStyle === "clean" ? 0.48 : selected ? 0.80 : 0.65;
  const retMetal  = previewStyle === "clean" ? 0.36 : selected ? 0.75 : 0.50;
  const faceRough = previewStyle === "clean" ? 0.32 : selected ? 0.16 : 0.22;
  const retRough  = previewStyle === "clean" ? 0.44 : selected ? 0.22 : 0.38;
  const click = useCallback((e: { stopPropagation: () => void }) => {
    e.stopPropagation(); onSelect(panel.id);
  }, [panel.id, onSelect]);

  return (
    <group>
      <mesh geometry={surfaceGeo} onClick={click}>
        <meshStandardMaterial color={faceCol} metalness={faceMetal}
          roughness={faceRough}
          emissive={emi} emissiveIntensity={emiI}
          transparent={dimmed} opacity={dimmed ? DIM_OPA : 1} side={THREE.DoubleSide} />
      </mesh>
      {retGeos.map((g, i) => (
        <mesh key={i} geometry={g} onClick={click}>
          <meshStandardMaterial color={retCol} metalness={retMetal}
            roughness={retRough}
            emissive={emi} emissiveIntensity={emiI * 0.6}
            transparent={dimmed} opacity={dimmed ? DIM_OPA : 1} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </group>
  );
}

// ── 3D: multi-corner wrap panel ───────────────────────────────────────────────

const MWRAP_FACE = "#a78bfa";   // violet — visually distinct from single-wall colors
function CornerSeamFillers({ corners, wallHeight: H, edgeDepth: d, mode, previewStyle, bendSegments }: {
  corners: CornerDef[];
  wallHeight: number;
  edgeDepth: number;
  mode: CornerMode;
  previewStyle: PreviewStyle;
  bendSegments: number;
}) {
  const geos = useMemo(() => {
    if (d === 0) return [];
    const n = Math.max(1, Math.round(bendSegments));
    const offset = mode === "outside" ? d : -d;
    return corners.map(corner => {
      const p = corner.point;
      const fromEdge = { x: p.x + corner.from.outward.x * offset, z: p.z + corner.from.outward.z * offset };
      const toEdge = { x: p.x + corner.to.outward.x * offset, z: p.z + corner.to.outward.z * offset };
      const startA = Math.atan2(fromEdge.z - p.z, fromEdge.x - p.x);
      const endA = Math.atan2(toEdge.z - p.z, toEdge.x - p.x);
      let delta = endA - startA;
      while (delta <= -Math.PI) delta += Math.PI * 2;
      while (delta > Math.PI) delta -= Math.PI * 2;

      const path = [fromEdge];
      for (let i = 1; i <= n; i++) {
        const a = startA + delta * (i / n);
        path.push({ x: p.x + Math.cos(a) * Math.abs(d), z: p.z + Math.sin(a) * Math.abs(d) });
      }
      path.push(toEdge);
      return makeVerticalStrip(path, 0, H);
    });
  }, [corners, H, d, mode, bendSegments]);

  const color = previewStyle === "clean" ? CLEAN_WRAP_FACE : WRAP_FACE;
  const metalness = previewStyle === "clean" ? 0.46 : 0.62;
  const roughness = previewStyle === "clean" ? 0.34 : 0.24;

  return (
    <group>
      {geos.map((geo, i) => (
        <mesh key={corners[i]?.id ?? i} geometry={geo}>
          <meshStandardMaterial color={color} metalness={metalness} roughness={roughness} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </group>
  );
}

const MWRAP_RET  = "#7c3aed";
const CLEAN_MWRAP_FACE = "#b9a7df";
const CLEAN_MWRAP_RET  = "#8f78be";

function MultiWrapPanelMesh({ panel, edgeDepth: d, mode, bendSegments, previewStyle, selected, hasSelection, pulseActive, onSelect }: {
  panel:        MultiWrapDef;
  edgeDepth:    number;
  mode:         CornerMode;
  bendSegments: number;
  previewStyle: PreviewStyle;
  selected:     boolean;
  hasSelection: boolean;
  pulseActive:  boolean;
  onSelect:     (id: string) => void;
}) {
  const { oy, visH: H, wallSpans, corners: panelCorners } = panel;
  const y1 = oy + H;

  const { surfaceGeo, retGeos } = useMemo(() => {
    const offset = mode === "outside" ? d : -d;
    const n      = Math.max(1, Math.round(bendSegments));
    const absOff = Math.abs(offset);

    // ── Build surface path ────────────────────────────────────────────────────
    // Walk: start of span 0 → end of span 0 → arc → start of span 1 … → end of last span
    const path: { x: number; z: number }[] = [];

    for (let i = 0; i < wallSpans.length; i++) {
      const span = wallSpans[i];
      if (i === 0) path.push(wallPoint(span.wall, span.startU, offset));
      path.push(wallPoint(span.wall, span.endU, offset));

      if (i < panelCorners.length && d !== 0) {
        const cc = panelCorners[i];
        const p  = cc.corner.point;
        const fromEdge = { x: p.x + cc.fromWall.outward.x * offset, z: p.z + cc.fromWall.outward.z * offset };
        const toEdge   = { x: p.x + cc.toWall.outward.x   * offset, z: p.z + cc.toWall.outward.z   * offset };
        const startA = Math.atan2(fromEdge.z - p.z, fromEdge.x - p.x);
        const endA   = Math.atan2(toEdge.z   - p.z, toEdge.x   - p.x);
        let delta = endA - startA;
        while (delta <= -Math.PI) delta += Math.PI * 2;
        while (delta >   Math.PI) delta -= Math.PI * 2;
        // arc: j=1..n; at j=n we land on toEdge = wallPoint(nextSpan.wall, 0, offset)
        for (let j = 1; j <= n; j++) {
          const a = startA + delta * (j / n);
          path.push({ x: p.x + Math.cos(a) * absOff, z: p.z + Math.sin(a) * absOff });
        }
        // arc endpoint = wallPoint(wallSpans[i+1].wall, 0, offset)
        // next iteration's first point would duplicate it — skip by not adding start again
      }
    }

    const surfaceGeo = makeVerticalStrip(path, oy, y1);

    if (d === 0) return { surfaceGeo, retGeos: [] };

    // ── Returns ────────────────────────────────────────────────────────────────
    const retGeos: THREE.BufferGeometry[] = [];

    for (const span of wallSpans) {
      // Top and bottom return per wall face segment
      retGeos.push(makeQuad(
        point3(wallPoint(span.wall, span.startU, offset), y1),
        point3(wallPoint(span.wall, span.endU,   offset), y1),
        point3(wallPoint(span.wall, span.endU,   0),      y1),
        point3(wallPoint(span.wall, span.startU, 0),      y1),
      ));
      retGeos.push(makeQuad(
        point3(wallPoint(span.wall, span.startU, 0),      oy),
        point3(wallPoint(span.wall, span.endU,   0),      oy),
        point3(wallPoint(span.wall, span.endU,   offset), oy),
        point3(wallPoint(span.wall, span.startU, offset), oy),
      ));
    }

    // Left edge return (perpendicular cap at panel start)
    const s0 = wallSpans[0];
    retGeos.push(makeQuad(
      point3(wallPoint(s0.wall, s0.startU, 0),      oy),
      point3(wallPoint(s0.wall, s0.startU, offset), oy),
      point3(wallPoint(s0.wall, s0.startU, offset), y1),
      point3(wallPoint(s0.wall, s0.startU, 0),      y1),
    ));

    // Right edge return
    const sN = wallSpans[wallSpans.length - 1];
    retGeos.push(makeQuad(
      point3(wallPoint(sN.wall, sN.endU, offset), oy),
      point3(wallPoint(sN.wall, sN.endU, 0),      oy),
      point3(wallPoint(sN.wall, sN.endU, 0),      y1),
      point3(wallPoint(sN.wall, sN.endU, offset), y1),
    ));

    return { surfaceGeo, retGeos };
  }, [panel, d, mode, bendSegments]); // eslint-disable-line react-hooks/exhaustive-deps

  const dimmed  = hasSelection && !selected && !pulseActive;
  const faceCol = selected ? SEL_FACE : previewStyle === "clean" ? CLEAN_MWRAP_FACE : MWRAP_FACE;
  const retCol  = selected ? SEL_RET  : previewStyle === "clean" ? CLEAN_MWRAP_RET  : MWRAP_RET;
  const emi  = selected ? SEL_EMI   : pulseActive ? "#166534" : "#000000";
  const emiI = previewStyle === "clean" ? 0 : selected ? SEL_EMI_I : pulseActive ? 0.28 : 0;
  const faceMetal = previewStyle === "clean" ? 0.48 : selected ? 0.80 : 0.65;
  const retMetal  = previewStyle === "clean" ? 0.36 : selected ? 0.75 : 0.50;
  const faceRough = previewStyle === "clean" ? 0.32 : selected ? 0.16 : 0.22;
  const retRough  = previewStyle === "clean" ? 0.44 : selected ? 0.22 : 0.38;
  const click = useCallback((e: { stopPropagation: () => void }) => {
    e.stopPropagation(); onSelect(panel.id);
  }, [panel.id, onSelect]);

  return (
    <group>
      <mesh geometry={surfaceGeo} onClick={click}>
        <meshStandardMaterial color={faceCol} metalness={faceMetal}
          roughness={faceRough}
          emissive={emi} emissiveIntensity={emiI}
          transparent={dimmed} opacity={dimmed ? DIM_OPA : 1} side={THREE.DoubleSide} />
      </mesh>
      {retGeos.map((g, i) => (
        <mesh key={i} geometry={g} onClick={click}>
          <meshStandardMaterial color={retCol} metalness={retMetal}
            roughness={retRough}
            emissive={emi} emissiveIntensity={emiI * 0.6}
            transparent={dimmed} opacity={dimmed ? DIM_OPA : 1} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </group>
  );
}

// ── 3D: ground + grid ────────────────────────────────────────────────────────

function SceneGrid({ bounds, previewStyle }: { bounds: ReturnType<typeof layoutBounds>; previewStyle: PreviewStyle }) {
  const gridSize = (Math.max(bounds.width, bounds.depth) + 8000) * S;
  const grid = useMemo(() => {
    const g = new THREE.GridHelper(gridSize, 30, new THREE.Color("#1e3a5e"), new THREE.Color("#162e4a"));
    const mats = Array.isArray(g.material) ? g.material : [g.material];
    mats.forEach(mat => { mat.transparent = true; (mat as THREE.LineBasicMaterial).opacity = previewStyle === "clean" ? 0.18 : 0.70; });
    return g;
  }, [gridSize, previewStyle]);
  return (
    <>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[bounds.cx * S, -0.003, bounds.cz * S]}>
        <planeGeometry args={[gridSize + 2, gridSize + 2]} />
        <meshStandardMaterial color={previewStyle === "clean" ? "#0c0e18" : "#0e1c30"} roughness={1} />
      </mesh>
      <primitive object={grid} position={[bounds.cx * S, -0.001, bounds.cz * S]} />
    </>
  );
}

// ── 3D: camera ────────────────────────────────────────────────────────────────

function SceneCamera({ params, bounds }: { params: SceneParams; bounds: ReturnType<typeof layoutBounds> }) {
  const { camera } = useThree();
  const appliedMode = useRef<string | null>(null);
  useEffect(() => {
    const signature = `${bounds.minX}:${bounds.maxX}:${bounds.minZ}:${bounds.maxZ}:${params.wallHeight}`;
    if (appliedMode.current === signature) return;
    appliedMode.current = signature;
    const { wallHeight: H } = params;
    const diagDist = Math.max(bounds.width, bounds.depth, H) * S * 1.35;
    camera.position.set(bounds.cx * S + diagDist, H * S * 0.75, bounds.cz * S - diagDist);
    camera.lookAt(bounds.cx * S, H * S * 0.4, bounds.cz * S);
    (camera as THREE.PerspectiveCamera).updateProjectionMatrix();
  }, [camera, params, bounds]);
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

function ExportErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div style={{
      marginTop: 8, padding: "7px 9px", borderRadius: 7,
      background: "rgba(239,68,68,0.10)", border: "1px solid rgba(239,68,68,0.35)",
      color: "#fecaca", fontSize: 10, lineHeight: 1.55,
    }}>
      {message}
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

// ── Stress presets ────────────────────────────────────────────────────────────

interface StressPreset {
  name: string;
  desc: string;
  params: Partial<SceneParams>;
}

const STRESS_PRESETS: StressPreset[] = [
  {
    name: "Standard 90°",
    desc: "Baseline right-angle corner",
    params: { wallAWidth: 3000, wallBWidth: 2000, wallHeight: 2800,
               panelW: 1000, panelH: 600, edgeDepth: 30, gap: 6,
               cornerAngle: 90, protrusionWidth: 0, protrusionDepth: 0 },
  },
  {
    name: "Sharp 37°",
    desc: "Acute corner — bend verification needed",
    params: { wallAWidth: 2400, wallBWidth: 1800, wallHeight: 2800,
               panelW: 800, panelH: 600, edgeDepth: 30, cornerAngle: 37 },
  },
  {
    name: "Wide 113°",
    desc: "Obtuse corner — panels bow outward",
    params: { wallAWidth: 3600, wallBWidth: 2400, wallHeight: 3200,
               panelW: 1000, panelH: 700, edgeDepth: 25, cornerAngle: 113 },
  },
  {
    name: "Deep protrusion",
    desc: "Large protrusion — short leftover segments",
    params: { wallAWidth: 4000, wallBWidth: 3000, wallHeight: 3000,
               panelW: 1000, panelH: 600, edgeDepth: 40, gap: 6,
               protrusionPosition: 1500, protrusionWidth: 800, protrusionDepth: 400 },
  },
  {
    name: "Small panels",
    desc: "High panel count — return density stress",
    params: { wallAWidth: 2400, wallBWidth: 1800, wallHeight: 2400,
               panelW: 300, panelH: 200, edgeDepth: 20, gap: 4 },
  },
  {
    name: "Narrow wall",
    desc: "Wall narrower than panel — short segments",
    params: { wallAWidth: 700, wallBWidth: 500, wallHeight: 2800,
               panelW: 600, panelH: 600, edgeDepth: 30, gap: 6 },
  },
];

// ── Suggest best layout ───────────────────────────────────────────────────────

interface LayoutSuggestion {
  recommendedMode: "wrap" | "separate";
  warnings: string[];
  tips: string[];
  panelCount: number;
  efficiencyPct: number;
}

function suggestLayout(p: SceneParams): LayoutSuggestion {
  const { wallAWidth: WA, wallBWidth: WB, wallHeight: H,
          panelW, panelH, edgeDepth: d, gap, cornerAngle,
          protrusionWidth, protrusionDepth } = p;

  const warnings: string[] = [];
  const tips: string[] = [];

  // Columns per wall
  const nColsA = Math.ceil(WA / (panelW + gap));
  const nColsB = Math.ceil(WB / (panelW + gap));
  const nRows  = Math.ceil(H  / (panelH + gap));

  // Leftover widths (last column)
  const remA = WA - Math.floor(WA / (panelW + gap)) * (panelW + gap);
  const remB = WB - Math.floor(WB / (panelW + gap)) * (panelW + gap);

  if (remA > 0 && remA < panelW * 0.25)
    warnings.push(`Leftover column on Wall A is very narrow (${remA.toFixed(0)} mm). Consider adjusting panel width.`);
  if (remB > 0 && remB < panelW * 0.25)
    warnings.push(`Leftover column on Wall B is very narrow (${remB.toFixed(0)} mm). Consider adjusting panel width.`);

  if (panelW > Math.min(WA, WB) * 0.9)
    warnings.push("Panel width is close to wall width. This leaves very few columns per wall.");

  if (panelW < 200)
    warnings.push("Panels are very small. Handling and installation cost will be high.");
  if (panelW > 2000)
    warnings.push("Panels are very large. May be difficult to transport and handle safely.");

  if (d > panelW * 0.15)
    warnings.push(`Edge return depth (${d} mm) is large relative to panel width — check blank dimensions.`);

  if (cornerAngle < 60)
    warnings.push(`Angle ${cornerAngle}° is very acute. Wrap panels may not physically fold to this angle — verify with fabricator.`);
  else if (cornerAngle < 80)
    warnings.push(`Angle ${cornerAngle}° is sharp. Check bend allowance and minimum bend radius with material spec.`);

  if (protrusionWidth > 0 && protrusionDepth > 0) {
    const shortSeg = Math.min(protrusionWidth % (panelW + gap) || panelW, panelW);
    if (shortSeg < 150)
      warnings.push(`Protrusion creates a very short panel segment (~${shortSeg.toFixed(0)} mm). Consider adjusting protrusion width.`);
  }

  // Mode recommendation
  const recommendedMode: "wrap" | "separate" = cornerAngle < 100 ? "wrap" : "separate";
  if (recommendedMode === "wrap")
    tips.push("Use Wrap Corner mode for a seamless corner appearance with no exposed joint.");
  else
    tips.push("Separate panel mode is preferable for obtuse angles — wrap panels would be very wide.");

  if (nColsA === 1 || nColsB === 1)
    tips.push("Wall is only one panel wide — ensure corner returns are within material bend limits.");

  // Efficiency estimate (face area / blank area)
  const faceArea  = (WA + WB) * H;
  const blankArea = (nColsA * (panelW + 2 * d) + nColsB * (panelW + 2 * d)) * nRows * (panelH + 2 * d);
  const efficiencyPct = Math.min(99, Math.round(faceArea / blankArea * 100));

  tips.push(`Estimated layout efficiency: ${efficiencyPct}%.`);

  const panelCount = (nColsA + nColsB) * nRows;

  return { recommendedMode, warnings, tips, panelCount, efficiencyPct };
}

// ── Fix actions ───────────────────────────────────────────────────────────────

interface FixChange { label: string; before: string; after: string; }

interface FixResult {
  title: string;
  description: string;
  changes: FixChange[];
}

function fixNarrowLeftover(wallWidth: number, gap: number, currentPW: number): number {
  const n = Math.max(1, Math.round(wallWidth / (currentPW + gap)));
  return Math.max(100, Math.round(wallWidth / n - gap));
}

// ── Fix result card ───────────────────────────────────────────────────────────

function FixResultCard({ result, onDismiss }: { result: FixResult | null; onDismiss: () => void }) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (!result) { setShow(false); return; }
    const id = setTimeout(() => setShow(true), 16);
    return () => clearTimeout(id);
  }, [result]);
  if (!result) return null;
  return (
    <div style={{
      position: "absolute", bottom: 56, left: "50%",
      transform: `translateX(-50%) translateY(${show ? 0 : 12}px)`,
      opacity: show ? 1 : 0,
      transition: "opacity 0.35s ease, transform 0.35s ease",
      background: "rgba(5, 14, 26, 0.93)",
      border: "1px solid rgba(74, 222, 128, 0.38)",
      borderRadius: 12, padding: "12px 16px",
      minWidth: 262, maxWidth: 340,
      backdropFilter: "blur(14px)",
      boxShadow: "0 8px 32px rgba(0,0,0,0.55), 0 0 20px rgba(74,222,128,0.09)",
      zIndex: 10, pointerEvents: "all",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <div style={{
          width: 20, height: 20, borderRadius: "50%", flexShrink: 0,
          background: "rgba(74,222,128,0.15)", border: "1px solid rgba(74,222,128,0.45)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 11, color: "#4ade80",
        }}>✓</div>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#4ade80", flex: 1 }}>
          {result.title}
        </div>
        <button onClick={onDismiss} style={{
          background: "none", border: "none", cursor: "pointer", padding: 0, lineHeight: 1,
          color: "rgba(255,255,255,0.28)", fontSize: 16, fontFamily: "inherit",
        }}>×</button>
      </div>
      {result.description && (
        <div style={{ fontSize: 10, color: "var(--text-subtle)", marginBottom: 10, lineHeight: 1.6 }}>
          {result.description}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {result.changes.map((c, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "72px 1fr 14px 1fr", alignItems: "center", gap: 5 }}>
            <span style={{ fontSize: 9, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              {c.label}
            </span>
            <span style={{
              fontSize: 11, fontWeight: 700, color: "var(--text-muted)",
              background: "rgba(255,255,255,0.06)", borderRadius: 4, padding: "3px 7px",
              textAlign: "center", fontFamily: "monospace",
            }}>{c.before}</span>
            <span style={{ color: "var(--text-subtle)", textAlign: "center", fontSize: 11 }}>→</span>
            <span style={{
              fontSize: 11, fontWeight: 700, color: "#4ade80",
              background: "rgba(74,222,128,0.10)", borderRadius: 4, padding: "3px 7px",
              textAlign: "center", fontFamily: "monospace",
              border: "1px solid rgba(74,222,128,0.22)",
            }}>{c.after}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CornerTestPage() {
  const [params, setParams] = useState<SceneParams>({
    wallAWidth: 3000, wallBWidth: 2000, wallHeight: 2800,
    panelW: 1000, panelH: 600, edgeDepth: 30, gap: 6,
    cornerAngle: 90, protrusionWidth: 0, protrusionDepth: 0, protrusionPosition: 900,
  });
  const [mode,         setMode]         = useState<CornerMode>("outside");
  const [panelMode,    setPanelMode]    = useState<PanelMode>("separate");
  const [previewStyle, setPreviewStyle] = useState<PreviewStyle>("clean");
  const [bendSegments, setBendSegments] = useState(3);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [exporting, setExporting]   = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<LayoutSuggestion | null>(null);
  const [fixResult,  setFixResult]  = useState<FixResult | null>(null);
  const [pulseActive, setPulseActive] = useState(false);
  const pulseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const set = (k: keyof SceneParams) => (v: number) => setParams(p => ({ ...p, [k]: v }));

  const effectivePanelMode: PanelMode = panelMode;
  const buildingLayout = useMemo(() => computeBuildingLayout(params, effectivePanelMode), [params, effectivePanelMode]);
  const { walls, corners, regularPanels, wraps, multiWrapPanels, bounds } = buildingLayout;
  const wallById   = useMemo(() => Object.fromEntries(walls.map(w => [w.id, w]))   as Record<string, WallDef>,   [walls]);
  const cornerById = useMemo(() => Object.fromEntries(corners.map(c => [c.id, c])) as Record<string, CornerDef>, [corners]);

  // Deselect if the selected panel vanishes after a resize/mode change
  const allIds = useMemo(() => {
    return new Set([
      ...regularPanels.map(p => p.id),
      ...wraps.map(w => w.id),
      ...multiWrapPanels.map(m => m.id),
    ]);
  }, [regularPanels, wraps, multiWrapPanels]);
  useEffect(() => {
    if (selectedId && !allIds.has(selectedId)) setSelectedId(null);
  }, [allIds, selectedId]);

  const selectedRegular   = selectedId && !selectedId.startsWith("W-") && !selectedId.startsWith("MW-")
    ? regularPanels.find(p => p.id === selectedId) ?? null : null;
  const selectedWrap      = selectedId?.startsWith("W-")
    ? wraps.find(w => w.id === selectedId) ?? null : null;
  const selectedMultiWrap = selectedId?.startsWith("MW-")
    ? multiWrapPanels.find(m => m.id === selectedId) ?? null : null;
  const hasSelection = !!(selectedRegular || selectedWrap || selectedMultiWrap);

  const exportDxf = useCallback(async () => {
    if (!hasSelection) return;
    setExporting(true);
    setExportError(null);
    try {
      let url_path: string;
      let body: object;
      let fname: string;

      if (selectedMultiWrap) {
        url_path = `${BASE}/multi-wrap/dxf`;
        fname    = `multi-wrap-${selectedMultiWrap.id}.dxf`;
        body     = {
          face_widths:   selectedMultiWrap.wallSpans.map(s => s.length),
          corner_angles: selectedMultiWrap.corners.map(c => c.angleDeg),
          height:        selectedMultiWrap.visH,
          edge_depth:    params.edgeDepth,
          filename:      fname,
        };
      } else if (selectedWrap) {
        url_path = `${BASE}/corner-wrap/dxf`;
        fname    = `wrap-${selectedWrap.id}.dxf`;
        body     = {
          segA: selectedWrap.segA, segB: selectedWrap.segB,
          height: selectedWrap.visH, edge_depth: params.edgeDepth,
          filename: fname,
        };
      } else {
        url_path = `${BASE}/folded-board/dxf`;
        fname    = `panel-${selectedRegular!.id}.dxf`;
        body     = {
          width: selectedRegular!.visW, height: selectedRegular!.visH,
          edge_depth: params.edgeDepth, filename: fname,
        };
      }

      const res  = await fetch(url_path, { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) {
        let detail = "";
        try { detail = await res.text(); } catch {}
        throw new Error(detail ? `Backend returned ${res.status}: ${detail}` : `Backend returned ${res.status}`);
      }
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      Object.assign(document.createElement("a"), { href, download: fname }).click();
      URL.revokeObjectURL(href);
    } catch (e) {
      console.error(e);
      const detail = e instanceof Error ? e.message : "";
      setExportError(`Export failed — backend not reachable or endpoint missing.${detail ? ` ${detail}` : ""}`);
    } finally {
      setExporting(false);
    }
  }, [hasSelection, selectedMultiWrap, selectedWrap, selectedRegular, params.edgeDepth]);

  const triggerPulse = useCallback(() => {
    if (pulseTimerRef.current) clearTimeout(pulseTimerRef.current);
    setPulseActive(true);
    pulseTimerRef.current = setTimeout(() => setPulseActive(false), 2000);
  }, []);

  const applyFix = useCallback((changes: FixChange[], newParams: Partial<SceneParams>, title: string, description: string) => {
    setParams(p => ({ ...p, ...newParams }));
    setFixResult({ title, description, changes });
    triggerPulse();
  }, [triggerPulse]);

  const getWarningFix = useCallback((warning: string): (() => void) | null => {
    const { wallAWidth: WA, wallBWidth: WB, panelW, gap } = params;
    if (warning.includes("Leftover column on Wall A")) {
      const newPW = fixNarrowLeftover(WA, gap, panelW);
      if (newPW === panelW) return null;
      return () => applyFix(
        [{ label: "Panel W", before: `${panelW} mm`, after: `${newPW} mm` }],
        { panelW: newPW },
        "Layout improved",
        "Panel width adjusted to eliminate narrow leftover on Wall A.",
      );
    }
    if (warning.includes("Leftover column on Wall B")) {
      const newPW = fixNarrowLeftover(WB, gap, panelW);
      if (newPW === panelW) return null;
      return () => applyFix(
        [{ label: "Panel W", before: `${panelW} mm`, after: `${newPW} mm` }],
        { panelW: newPW },
        "Layout improved",
        "Panel width adjusted to eliminate narrow leftover on Wall B.",
      );
    }
    if (warning.includes("Panels are very small")) {
      const newPW = Math.max(200, panelW);
      return newPW === panelW ? null : () => applyFix(
        [{ label: "Panel W", before: `${panelW} mm`, after: `${newPW} mm` }],
        { panelW: newPW },
        "Panel size increased",
        "Panel width set to minimum recommended 200 mm.",
      );
    }
    if (warning.includes("Panels are very large")) {
      const newPW = Math.min(2000, panelW);
      return newPW === panelW ? null : () => applyFix(
        [{ label: "Panel W", before: `${panelW} mm`, after: `${newPW} mm` }],
        { panelW: newPW },
        "Panel size reduced",
        "Panel width capped at 2000 mm for transport.",
      );
    }
    return null;
  }, [params, applyFix]);

  const orbitTarget: [number, number, number] = [
    bounds.cx * S,
    params.wallHeight * 0.4 * S,
    bounds.cz * S,
  ];

  const modeColor  = mode === "outside" ? "#86efac" : "#fde68a";
  const modeBorder = mode === "outside" ? "rgba(34,197,94,0.25)" : "rgba(251,191,36,0.25)";

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
            Four-Wall{" "}
            <span style={{ background: "linear-gradient(135deg,#06b6d4,#7c3aed)",
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
              Building
            </span>
          </h1>
          <p style={{ fontSize: 10, color: "var(--text-subtle)", margin: 0, lineHeight: 1.55 }}>
            Folded panel cladding · variable-angle building test
          </p>
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 6 }}>
            Preview Style
          </div>
          <SegControl<PreviewStyle>
            value={previewStyle} onChange={setPreviewStyle}
            options={[
              { value: "clean",    label: "Clean" },
              { value: "detailed", label: "Detailed" },
            ]}
            colors={{
              clean:    "linear-gradient(135deg,#64748b,#0ea5e9)",
              detailed: "linear-gradient(135deg,#f59e0b,#ec4899)",
            }}
          />
        </div>

        {/* Corner mode toggle */}
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 6 }}>
            Corner Mode
          </div>
          <SegControl<CornerMode>
            value={mode} onChange={v => { setMode(v); setSelectedId(null); }}
            options={[
              { value: "outside", label: "↗ Outside" },
              { value: "inside",  label: "↙ Inside"  },
            ]}
            colors={{
              outside: "linear-gradient(135deg,#06b6d4,#3b82f6)",
              inside:  "linear-gradient(135deg,#f97316,#7c3aed)",
            }}
          />
        </div>

        {/* Panel style toggle */}
        <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase",
              letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 6 }}>
              Panel Style
            </div>
            <SegControl<PanelMode>
              value={panelMode} onChange={v => { setPanelMode(v); setSelectedId(null); }}
              options={[
                { value: "separate",   label: "Separate" },
                { value: "wrap",       label: "⌐ Wrap" },
                { value: "multi-wrap", label: "◱ Multi" },
              ]}
              colors={{
                separate:   "linear-gradient(135deg,#6366f1,#7c3aed)",
                wrap:       "linear-gradient(135deg,#ec4899,#7c3aed)",
                "multi-wrap": "linear-gradient(135deg,#a78bfa,#0ea5e9)",
              }}
            />
            {(panelMode === "wrap" || panelMode === "multi-wrap") && (
              <div style={{ marginTop: 6 }}>
                {panelMode === "wrap" && (
                  <div style={{ fontSize: 9, color: "var(--text-subtle)", lineHeight: 1.6,
                    padding: "6px 8px", marginBottom: 8,
                    background: "rgba(236,72,153,0.07)",
                    border: "1px solid rgba(236,72,153,0.18)", borderRadius: 6 }}>
                    One panel wraps across each building corner. DXF: 10-vertex flat blank with V-notch relief cuts.
                  </div>
                )}
                {panelMode === "multi-wrap" && (
                  <div style={{ fontSize: 9, color: "var(--text-subtle)", lineHeight: 1.6,
                    padding: "6px 8px", marginBottom: 8,
                    background: "rgba(167,139,250,0.07)",
                    border: "1px solid rgba(167,139,250,0.18)", borderRadius: 6 }}>
                    Panels span the full perimeter as a continuous strip — one panel can cross multiple corners. DXF includes a bend line at each corner crossed.
                  </div>
                )}
                <Num
                  label="Corner bend segments"
                  value={bendSegments} min={1} max={8} step={1}
                  onChange={setBendSegments}
                />
                <div style={{ fontSize: 9, color: "var(--text-subtle)", marginTop: -4,
                  marginBottom: 4, lineHeight: 1.5 }}>
                  More segments = smoother arc in 3D. DXF is unaffected.
                </div>
              </div>
            )}
        </div>

        <Card label="Wall dimensions">
          <Num label="Wall A/C width" value={params.wallAWidth} min={200} max={12000} step={100} unit="mm" onChange={set("wallAWidth")} />
          <Num label="Wall B/D depth" value={params.wallBWidth} min={200} max={12000} step={100} unit="mm" onChange={set("wallBWidth")} />
          <Num label="Wall height"  value={params.wallHeight} min={200} max={12000} step={100} unit="mm" onChange={set("wallHeight")} />
          <Num label="A to B angle" value={params.cornerAngle} min={35} max={160} step={1} unit="deg" onChange={set("cornerAngle")} />
        </Card>

        <Card label="Wall A protrusion">
          <Num label="Position" value={params.protrusionPosition} min={0} max={params.wallAWidth} step={50} unit="mm" onChange={set("protrusionPosition")} />
          <Num label="Width" value={params.protrusionWidth} min={0} max={params.wallAWidth} step={50} unit="mm" onChange={set("protrusionWidth")} />
          <Num label="Depth" value={params.protrusionDepth} min={0} max={1200} step={25} unit="mm" onChange={set("protrusionDepth")} />
        </Card>

        <Card label="Panel">
          <Num label="Panel width"   value={params.panelW}    min={100} max={5000} step={50}  unit="mm" onChange={set("panelW")} />
          <Num label="Panel height"  value={params.panelH}    min={100} max={5000} step={50}  unit="mm" onChange={set("panelH")} />
          <Num label="Edge / return" value={params.edgeDepth} min={0}   max={200}  step={5}   unit="mm" onChange={set("edgeDepth")} />
          <Num label="Joint gap"     value={params.gap}       min={0}   max={50}   step={1}   unit="mm" onChange={set("gap")} />
        </Card>

        <Card label="Scene">
          {effectivePanelMode === "multi-wrap" ? (
            <>
              <KV k="Multi-wrap panels" v={multiWrapPanels.length} />
              <KV k="Multi-corner"      v={multiWrapPanels.filter(m => m.corners.length > 1).length} />
              <KV k="Corners"          v={corners.length} />
              <KV k="A-B angle"        v={`${params.cornerAngle} deg`} mono />
            </>
          ) : effectivePanelMode === "wrap" ? (
            <>
              <KV k="Wrap panels"    v={wraps.length} />
              <KV k="Regular panels" v={regularPanels.length} />
              <KV k="Corners"        v={corners.length} />
              <KV k="A-B angle"      v={`${params.cornerAngle} deg`} mono />
            </>
          ) : (
            <>
              <KV k="Total panels"  v={regularPanels.length} />
              <KV k="Wall A"        v={regularPanels.filter(p => p.wall === "A").length} />
              <KV k="Wall B"        v={regularPanels.filter(p => p.wall === "B").length} />
              <KV k="Wall C"        v={regularPanels.filter(p => p.wall === "C").length} />
              <KV k="Wall D"        v={regularPanels.filter(p => p.wall === "D").length} />
              <KV k="A-B angle"     v={`${params.cornerAngle} deg`} mono />
            </>
          )}
        </Card>

        <Card label="Corner logic">
          <div style={{ fontSize: 10, color: "var(--text-subtle)", lineHeight: 1.75 }}>
            {mode === "outside" ? (
              <>
                <div>Wall A — face at <code>z=+d</code>, returns to <code>z=0</code></div>
                <div style={{ marginTop: 4 }}>Wall B — face at <code>x=+d</code>, returns to <code>x=0</code></div>
                <div style={{ marginTop: 8, color: "#86efac" }}>
                  Convex: cladding on outer faces. Returns fold inward.
                </div>
              </>
            ) : panelMode === "wrap" ? (
              <>
                <div>Wrap face A at <code>z=−d</code>, bend strip, face B at <code>x=−d</code></div>
                <div style={{ marginTop: 4 }}>Single 90° fold at corner edge <code>(0,y,0)</code></div>
                <div style={{ marginTop: 8, color: "#f9a8d4" }}>
                  Corner wrap: one panel crosses both walls. V-notch relief cuts at top/bottom.
                </div>
              </>
            ) : (
              <>
                <div>Wall A — face at <code>z=−d</code>, returns to <code>z=0</code></div>
                <div style={{ marginTop: 4 }}>Wall B — face at <code>x=−d</code>, returns to <code>x=0</code></div>
                <div style={{ marginTop: 8, color: "#fde68a" }}>
                  Concave: cladding on inner faces. Returns fold outward.
                </div>
              </>
            )}
          </div>
        </Card>

        {/* ── Stress test presets ── */}
        <div className="glass-sm" style={{ padding: "11px 13px", marginBottom: 10 }}>
          <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 7 }}>
            Stress Test Presets
          </div>
          <div style={{ fontSize: 9, color: "var(--text-subtle)", lineHeight: 1.6, marginBottom: 8,
            padding: "5px 7px", background: "rgba(255,255,255,0.03)", borderRadius: 5,
            border: "1px solid rgba(255,255,255,0.06)" }}>
            Use these presets to verify panel placement, wrap corners, and DXF export under difficult geometry.
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {STRESS_PRESETS.map(preset => (
              <button key={preset.name}
                onClick={() => {
                  setParams(p => ({ ...p, ...preset.params }));
                  setSelectedId(null);
                  setSuggestion(null);
                }}
                style={{
                  display: "flex", flexDirection: "column", alignItems: "flex-start",
                  padding: "7px 9px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.08)",
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
          onClick={() => setSuggestion(suggestLayout(params))}
          style={{
            width: "100%", padding: "10px 0", borderRadius: 9, border: "none",
            cursor: "pointer", background: "linear-gradient(135deg,#f59e0b,#f97316)",
            color: "#fff", fontSize: 12, fontWeight: 700, fontFamily: "inherit",
            marginBottom: suggestion ? 10 : 0,
          }}
        >
          ✦ Suggest Best Layout
        </button>

        {suggestion && (
          <div className="glass-sm" style={{ padding: "11px 13px", marginBottom: 10 }}>
            <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase",
              letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 8 }}>
              Layout Recommendation
            </div>

            {/* Mode recommendation */}
            <div style={{ marginBottom: 9, padding: "7px 9px", borderRadius: 6,
              background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.18)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 14 }}>⌐</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#6ee7b7" }}>
                    Use {suggestion.recommendedMode === "wrap" ? "Wrap Corner" : "Separate"} mode
                  </div>
                  <div style={{ fontSize: 9, color: "var(--text-subtle)", marginTop: 2 }}>
                    Estimated panels: {suggestion.panelCount} · Efficiency: {suggestion.efficiencyPct}%
                  </div>
                </div>
              </div>
              {suggestion.recommendedMode !== panelMode && (
                <button
                  onClick={() => {
                    const before = panelMode === "wrap" ? "Wrap Corner" : "Separate";
                    const after  = suggestion.recommendedMode === "wrap" ? "Wrap Corner" : "Separate";
                    setPanelMode(suggestion.recommendedMode);
                    setSelectedId(null);
                    applyFix(
                      [{ label: "Panel Style", before, after }],
                      {},
                      "Mode applied",
                      `Panel mode changed to ${after} as recommended.`,
                    );
                  }}
                  style={{
                    marginTop: 6, width: "100%", padding: "4px 0", borderRadius: 5,
                    border: "1px solid rgba(16,185,129,0.28)",
                    background: "rgba(16,185,129,0.10)",
                    color: "#6ee7b7", fontSize: 10, fontWeight: 700,
                    cursor: "pointer", fontFamily: "inherit",
                  }}
                >
                  Apply → {suggestion.recommendedMode === "wrap" ? "Wrap Corner" : "Separate"}
                </button>
              )}
            </div>

            {/* Tips */}
            {suggestion.tips.map((tip, i) => (
              <div key={i} style={{ fontSize: 10, color: "#a3e635", marginBottom: 5,
                lineHeight: 1.55, display: "flex", gap: 5 }}>
                <span style={{ flexShrink: 0, opacity: 0.7 }}>→</span>
                <span>{tip}</span>
              </div>
            ))}

            {/* Warnings */}
            {suggestion.warnings.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: "#fde68a",
                  textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 5 }}>
                  Warnings
                </div>
                {suggestion.warnings.map((w, i) => {
                  const doFix = getWarningFix(w);
                  return (
                    <div key={i} style={{ fontSize: 10, color: "#fde68a", marginBottom: 6, lineHeight: 1.55 }}>
                      <div style={{ display: "flex", gap: 5 }}>
                        <span style={{ flexShrink: 0 }}>⚠</span>
                        <span>{w}</span>
                      </div>
                      {doFix && (
                        <button
                          onClick={doFix}
                          style={{
                            marginTop: 3, marginLeft: 13,
                            fontSize: 9, fontWeight: 700, cursor: "pointer",
                            fontFamily: "inherit",
                            background: "rgba(251,191,36,0.12)",
                            border: "1px solid rgba(251,191,36,0.28)",
                            color: "#fde68a", padding: "2px 8px", borderRadius: 4,
                          }}
                        >
                          Fix →
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            <button onClick={() => setSuggestion(null)}
              style={{ marginTop: 8, fontSize: 10, color: "var(--text-subtle)",
                background: "none", border: "none", cursor: "pointer",
                fontFamily: "inherit", padding: 0 }}>
              Dismiss
            </button>
          </div>
        )}

      </div>

      {/* ── 3D canvas ── */}
      <div style={{ flex: 1, background: previewStyle === "clean" ? "#07070e" : "#0d1520", position: "relative" }}>
        <Canvas camera={{ fov: 45, near: 0.001, far: 500 }} gl={{ antialias: true }}
          style={{ width: "100%", height: "100%" }}
          onPointerMissed={() => setSelectedId(null)}>
          <color attach="background" args={[previewStyle === "clean" ? "#07070e" : "#0d1520"]} />
          <Suspense fallback={null}>
            <SceneCamera params={params} bounds={bounds} />

            <ambientLight intensity={0.65} />
            <directionalLight position={[4,  6,  5]} intensity={0.88} castShadow />
            <directionalLight position={[-3, 2, -4]} intensity={0.30} />
            <directionalLight position={[1, -2,  3]} intensity={0.16} />

            {previewStyle === "detailed" && (
              <BuildingWalls walls={walls} H={params.wallHeight} previewStyle={previewStyle} />
            )}
            {previewStyle === "detailed" && <WallLabels walls={walls} H={params.wallHeight} />}
            {previewStyle === "detailed" && (
              <DebugGeometryOverlay
                walls={walls}
                regularPanels={regularPanels}
                wraps={wraps}
                multiWrapPanels={multiWrapPanels}
                wallById={wallById}
                cornerById={cornerById}
                params={params}
                mode={mode}
                bendSegments={bendSegments}
              />
            )}
            {panelMode === "separate" && (
              <CornerSeamFillers
                corners={corners}
                wallHeight={params.wallHeight}
                edgeDepth={params.edgeDepth}
                mode={mode}
                previewStyle={previewStyle}
                bendSegments={bendSegments}
              />
            )}

            {/* Regular / separate panels */}
            {regularPanels.map(panel => (
              <BuildingPanelMesh key={panel.id} panel={panel} wall={wallById[panel.wallKey ?? panel.wall]}
                mode={mode} previewStyle={previewStyle} edgeDepth={params.edgeDepth}
                selected={panel.id === selectedId} hasSelection={hasSelection}
                pulseActive={pulseActive} onSelect={setSelectedId} />
            ))}

            {/* Wrap corner panels (inside + wrap mode) */}
            {wraps.map(wp => (
              <BuildingWrapPanelMesh key={wp.id} panel={wp} corner={cornerById[wp.corner!]}
                edgeDepth={params.edgeDepth} bendSegments={bendSegments} mode={mode}
                previewStyle={previewStyle}
                selected={wp.id === selectedId} hasSelection={hasSelection}
                pulseActive={pulseActive} onSelect={setSelectedId} />
            ))}

            {/* Multi-corner wrap panels */}
            {multiWrapPanels.map(mp => (
              <MultiWrapPanelMesh key={mp.id} panel={mp}
                edgeDepth={params.edgeDepth} mode={mode} bendSegments={bendSegments}
                previewStyle={previewStyle}
                selected={mp.id === selectedId} hasSelection={hasSelection}
                pulseActive={pulseActive} onSelect={setSelectedId} />
            ))}

            {/* Ground + grid */}
            <SceneGrid bounds={bounds} previewStyle={previewStyle} />

            <OrbitControls enableDamping dampingFactor={0.08} target={orbitTarget} makeDefault />
          </Suspense>
        </Canvas>

        {/* Corner mode + panel mode badge */}
        <div style={{ position: "absolute", top: 14, left: "50%", transform: "translateX(-50%)",
          display: "flex", gap: 6, pointerEvents: "none" }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
            color: previewStyle === "clean" ? "#bfdbfe" : "#fbbf24",
            background: "rgba(0,0,0,0.55)", padding: "4px 14px",
            borderRadius: 20, border: previewStyle === "clean" ? "1px solid rgba(147,197,253,0.28)" : "1px solid rgba(251,191,36,0.30)",
            whiteSpace: "nowrap" }}>
            {previewStyle === "clean" ? "Clean preview" : "Detailed preview"}
          </div>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
            color: modeColor, background: "rgba(0,0,0,0.55)", padding: "4px 14px",
            borderRadius: 20, border: `1px solid ${modeBorder}`, whiteSpace: "nowrap" }}>
            {mode === "outside" ? "Outside corner" : "Inside corner"}
          </div>
          {panelMode === "wrap" && (
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
              color: "#f9a8d4", background: "rgba(0,0,0,0.55)", padding: "4px 14px",
              borderRadius: 20, border: "1px solid rgba(236,72,153,0.30)", whiteSpace: "nowrap" }}>
              Wrap panels
            </div>
          )}
          {panelMode === "multi-wrap" && (
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
              color: "#c4b5fd", background: "rgba(0,0,0,0.55)", padding: "4px 14px",
              borderRadius: 20, border: "1px solid rgba(167,139,250,0.30)", whiteSpace: "nowrap" }}>
              Multi-wrap
            </div>
          )}
        </div>

        {/* Fix result overlay */}
        <FixResultCard result={fixResult} onDismiss={() => setFixResult(null)} />

        {/* Hint */}
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
          {selectedMultiWrap
            ? `Multi-wrap ${selectedMultiWrap.id}`
            : selectedWrap
              ? `Wrap panel ${selectedWrap.id}`
              : selectedRegular
                ? `Panel ${selectedRegular.id}`
                : "No panel selected"}
        </div>
        <div style={{ fontSize: 10, color: modeColor, marginBottom: 12,
          fontWeight: 600, letterSpacing: "0.04em" }}>
          {mode === "outside" ? "Outside corner" : "Inside corner"} · {panelMode}
        </div>

        {selectedMultiWrap ? (() => {
          const mw = selectedMultiWrap;
          const d  = params.edgeDepth;
          const arcLens = mw.corners.map(c => Math.PI / 180 * c.angleDeg * d);
          const flatW = d + mw.wallSpans.reduce((a, s) => a + s.length, 0) + arcLens.reduce((a, v) => a + v, 0) + d;
          const flatH = d + mw.visH + d;
          return (
            <>
              <Card label="Multi-wrap panel">
                <KV k="Row"           v={mw.row} />
                <KV k="Face count"    v={mw.wallSpans.length} />
                <KV k="Corners crossed" v={mw.corners.length} />
                <KV k="Total face W"  v={`${mw.totalWidth.toFixed(0)} mm`} mono />
                <KV k="Height"        v={`${mw.visH} mm`} mono />
                <KV k="Perimeter pos" v={`${mw.perimStart.toFixed(0)} mm`} mono />
              </Card>

              <Card label="Wall faces">
                {mw.wallSpans.map((s, i) => (
                  <KV key={i} k={`Face ${i + 1} — ${s.wall.label}`} v={`${s.length.toFixed(0)} mm`} mono />
                ))}
              </Card>

              {mw.corners.length > 0 && (
                <Card label="Corner bends">
                  {mw.corners.map((c, i) => (
                    <KV key={i}
                      k={`Bend ${i + 1} at ${c.distAlongPanel.toFixed(0)} mm`}
                      v={`${c.angleDeg.toFixed(1)}°`} mono />
                  ))}
                </Card>
              )}

              <Card label="Flat blank">
                <KV k="Flat width"  v={`${flatW.toFixed(0)} mm`} mono />
                <KV k="Flat height" v={`${flatH.toFixed(0)} mm`} mono />
                <KV k="Returns (d)" v={`${d} mm`} mono />
                {arcLens.map((al, i) => (
                  <KV key={i} k={`Arc ${i + 1} (${mw.corners[i].angleDeg.toFixed(0)}°)`}
                    v={`${al.toFixed(1)} mm`} mono />
                ))}
                <div style={{ marginTop: 8 }}>
                  {[
                    { color: "#22c55e", sym: "CUT",   desc: "Outer rectangle boundary" },
                    { color: "#f97316", sym: "BEND",  desc: "Return + corner fold lines" },
                    { color: "#9db8d8", sym: "FACE",  desc: "Face outlines" },
                    { color: "#a0a0c0", sym: "LABELS",desc: "Dimensions + angles" },
                  ].map(({ color, sym, desc }) => (
                    <div key={sym} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
                      <div style={{ width: 8, height: 8, borderRadius: 2, background: color, flexShrink: 0 }} />
                      <span style={{ fontWeight: 700, fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)" }}>{sym}</span>
                      <span style={{ fontSize: 10, color: "var(--text-subtle)" }}>{desc}</span>
                    </div>
                  ))}
                </div>
              </Card>

              <button onClick={exportDxf} disabled={exporting} style={{
                width: "100%", padding: "10px 0", borderRadius: 9, border: "none",
                cursor: exporting ? "default" : "pointer",
                background: "linear-gradient(135deg,#a78bfa,#0ea5e9)",
                color: "#fff", fontSize: 13, fontWeight: 700,
                opacity: exporting ? 0.6 : 1, fontFamily: "inherit",
                transition: "opacity 0.2s",
              }}>
                {exporting ? "Exporting…" : "↓ Export Multi-wrap DXF"}
              </button>
              <ExportErrorBanner message={exportError} />
              <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-subtle)", textAlign: "center" }}>
                Flat blank · {mw.wallSpans.length} face{mw.wallSpans.length > 1 ? "s" : ""} · {mw.corners.length} bend{mw.corners.length !== 1 ? "s" : ""}
              </div>
            </>
          );
        })() : selectedWrap ? (
          <>
            <Card label="Wrap panel">
              <KV k="Row"          v={selectedWrap.row} />
              <KV k="Corner"      v={selectedWrap.corner ?? "AB"} />
              <KV k="From wall"   v={`Wall ${selectedWrap.fromWall ?? "A"}: ${selectedWrap.segA} mm`} mono />
              <KV k="To wall"     v={`Wall ${selectedWrap.toWall ?? "B"}: ${selectedWrap.segB} mm`} mono />
              <KV k="Face height"  v={`${selectedWrap.visH} mm`} mono />
              <KV k="Edge depth"   v={`${params.edgeDepth} mm`} mono />
              <KV k="Bend angle"    v={`${cornerById[selectedWrap.corner ?? ""]?.angleDeg.toFixed(1) ?? "90.0"} deg`} />
              <KV k="Bend segments" v={bendSegments} />
            </Card>

            <Card label="Flat blank">
              <KV k="Blank width"  v={`${selectedWrap.segA + selectedWrap.segB + 2 * params.edgeDepth} mm`} mono />
              <KV k="Blank height" v={`${selectedWrap.visH + 2 * params.edgeDepth} mm`} mono />
              <KV k="Shape"        v="Rectangle + V-notch relief" />
              <KV k="Bend lines"   v="7 (corner + 6 returns)" />
              <div style={{ marginTop: 10 }}>
                {[
                  { color: "#22c55e", sym: "CUT",  desc: "10-vertex outer boundary" },
                  { color: "#f97316", sym: "BEND",  desc: "7 score lines" },
                  { color: "#9db8d8", sym: "FACE",  desc: "Wall A + B face outlines" },
                  { color: "#a0a0c0", sym: "LABELS",desc: "A, B, H, d dimensions" },
                ].map(({ color, sym, desc }) => (
                  <div key={sym} style={{ display: "flex", alignItems: "center",
                    gap: 8, marginBottom: 5, fontSize: 11 }}>
                    <div style={{ width: 8, height: 8, borderRadius: 2,
                      background: color, flexShrink: 0 }} />
                    <span style={{ fontWeight: 700, fontFamily: "monospace",
                      color: "var(--text-muted)" }}>{sym}</span>
                    <span style={{ fontSize: 10, color: "var(--text-subtle)" }}>{desc}</span>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 8, padding: "6px 8px", fontSize: 9,
                background: "rgba(236,72,153,0.07)", border: "1px solid rgba(236,72,153,0.18)",
                borderRadius: 5, color: "var(--text-subtle)", lineHeight: 1.6 }}>
                V-notch relief cuts at top/bottom of bend line prevent material
                collision when folding the 90° corner.
              </div>
            </Card>

            <button onClick={exportDxf} disabled={exporting} style={{
              width: "100%", padding: "10px 0", borderRadius: 9, border: "none",
              cursor: exporting ? "default" : "pointer",
              background: "linear-gradient(135deg,#ec4899,#7c3aed)",
              color: "#fff", fontSize: 13, fontWeight: 700,
              opacity: exporting ? 0.6 : 1, fontFamily: "inherit",
              transition: "opacity 0.2s",
            }}>
              {exporting ? "Exporting…" : "↓ Export Wrap DXF"}
            </button>
            <ExportErrorBanner message={exportError} />
            <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-subtle)", textAlign: "center" }}>
              Corner wrap blank · {params.edgeDepth}mm returns · {cornerById[selectedWrap?.corner ?? ""]?.angleDeg?.toFixed(0) ?? params.cornerAngle}° bend
            </div>
          </>
        ) : selectedRegular ? (
          <>
            <Card label="Panel info">
              <KV k="Wall"       v={`Wall ${selectedRegular.wall}`} />
              <KV k="Row"        v={selectedRegular.row} />
              <KV k="Column"     v={selectedRegular.col} />
              <KV k="Face size"  v={`${selectedRegular.visW} × ${selectedRegular.visH} mm`} mono />
              <KV k="Edge depth" v={`${params.edgeDepth} mm`} mono />
              <KV k="Blank size" v={`${selectedRegular.visW + 2 * params.edgeDepth} × ${selectedRegular.visH + 2 * params.edgeDepth} mm`} mono />
            </Card>

            <Card label="Corner position">
              {selectedRegular.wall === "A" && selectedRegular.col === 0 && (
                <div style={{ fontSize: 10, color: "#86efac", lineHeight: 1.65 }}>
                  ✓ Left return at x=0. Mates with Wall B front return at (0,y,0).
                </div>
              )}
              {selectedRegular.wall === "B" && selectedRegular.col === 0 && (
                <div style={{ fontSize: 10, color: "#86efac", lineHeight: 1.65 }}>
                  ✓ Front return at z=0. Mates with Wall A left return at (0,y,0).
                </div>
              )}
              {selectedRegular.col !== 0 && (
                <div style={{ fontSize: 10, color: "var(--text-subtle)", lineHeight: 1.65 }}>
                  Interior panel — no corner returns.
                </div>
              )}
            </Card>

            <Card label="Flat blank (DXF)">
              {[
                { color: "#22c55e", sym: "CUT",    desc: "Plus-shaped outer cut" },
                { color: "#f97316", sym: "BEND",   desc: "4 fold/groove lines" },
                { color: "#9db8d8", sym: "FACE",   desc: "Face outline" },
                { color: "#a0a0c0", sym: "LABELS", desc: "W, H, d dimensions" },
              ].map(({ color, sym, desc }) => (
                <div key={sym} style={{ display: "flex", alignItems: "center",
                  gap: 8, marginBottom: 5, fontSize: 11 }}>
                  <div style={{ width: 8, height: 8, borderRadius: 2,
                    background: color, flexShrink: 0 }} />
                  <span style={{ fontWeight: 700, fontFamily: "monospace",
                    color: "var(--text-muted)" }}>{sym}</span>
                  <span style={{ fontSize: 10, color: "var(--text-subtle)" }}>{desc}</span>
                </div>
              ))}
            </Card>

            <button onClick={exportDxf} disabled={exporting} style={{
              width: "100%", padding: "10px 0", borderRadius: 9, border: "none",
              cursor: exporting ? "default" : "pointer",
              background: "linear-gradient(135deg,#06b6d4,#7c3aed)",
              color: "#fff", fontSize: 13, fontWeight: 700,
              opacity: exporting ? 0.6 : 1, fontFamily: "inherit",
              transition: "opacity 0.2s",
            }}>
              {exporting ? "Exporting…" : "↓ Export Panel DXF"}
            </button>
            <ExportErrorBanner message={exportError} />
            <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-subtle)", textAlign: "center" }}>
              Plus-shaped flat blank · {params.edgeDepth}mm returns
            </div>
          </>
        ) : (
          <div style={{ fontSize: 12, color: "var(--text-subtle)", lineHeight: 1.7 }}>
            <p style={{ margin: "0 0 10px" }}>
              Click any panel in the 3D view to inspect it and export its flat-blank DXF.
            </p>
            <p style={{ margin: 0 }}>
              {effectivePanelMode === "wrap"
                ? "Click a wrap panel (corner) to export the 10-vertex corner wrap blank."
                : "Corner panels (col 0) show which return meets the 90° joint."}
            </p>
          </div>
        )}
      </div>

    </div>
  );
}
