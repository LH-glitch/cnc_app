"use client";

// ─────────────────────────────────────────────────────────────────────────────
// Folded Board — rectangle Alucobond sheet
//
// Workflow (3D first, then unfold):
//   1. Build the 3D folded board: face + 4 flaps at 90° inward
//   2. Compute corner miter lines in the flat pattern (45°)
//   3. Unfold each flap back into the 2D plane to get the flat pattern
//   4. Generate DXF from the unfolded geometry
//
// Coordinate system:
//   X = panel width direction
//   Y = panel height direction
//   Z = outward normal (face sits at Z=0, flaps fold toward −Z)
//
// All values in mm; multiply by S=0.001 for Three.js metres.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useMemo, useEffect, useCallback, Suspense } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Html } from "@react-three/drei";
import * as THREE from "three";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const S = 0.001;

// ── Types ─────────────────────────────────────────────────────────────────────

interface Pt2 { x: number; y: number; }
interface Pt3 { x: number; y: number; z: number; }

interface BoardParams {
  width: number;     // mm — visible face width
  height: number;    // mm — visible face height
  edgeDepth: number; // mm — return flap depth
}

// ── Board design — decorative groove lines on the visible face ────────────────

interface DesignLine { a: Pt2; b: Pt2 }

interface DesignOption {
  id:          string;
  name:        string;
  description: string;
  suggestedUse: string;
  lineAngle:   number;   // decorative groove bend angle (degrees, small)
  lines:       DesignLine[];
}

const DECORATIVE_RECOMMENDED_MAX = 5;
const DECORATIVE_CAUTION_MAX = 10;
const DECORATIVE_PREVIEW_MAX = 10;

function clampDecorativeAngle(angle: number): number {
  const limit = DECORATIVE_PREVIEW_MAX;
  return Math.sign(angle) * Math.min(Math.abs(angle), limit);
}

function decorativeAngleLevel(angle: number): "recommended" | "caution" | "unsafe" {
  const abs = Math.abs(angle);
  if (abs <= DECORATIVE_RECOMMENDED_MAX) return "recommended";
  if (abs <= DECORATIVE_CAUTION_MAX) return "caution";
  return "unsafe";
}

function generateDesigns(W: number, H: number): DesignOption[] {
  return [
    {
      id: "diagonal",
      name: "Single Crease",
      description: "One groove — face splits into two flat facets. Half stays flat, half rotates toward viewer.",
      suggestedUse: "Minimalist facade accent",
      lineAngle: 3,
      lines: [{ a: { x: -W/2, y: -H/3 }, b: { x: W/2, y: H/3 } }],
    },
    {
      id: "raised-ridge",
      name: "Raised Ridge",
      description: "Two vertical creases — outer strips fold inward (inside bend), centre band stands forward.",
      suggestedUse: "Horizontal accent band",
      // Negative angle = inside fold.  Outward normals: outer strips recess → centre appears raised.
      lineAngle: 4,
      lines: [
        // Bottom-to-top → normal (−1,0) points LEFT (outward from centre)
        { a: { x: -W/4, y: -H/2 }, b: { x: -W/4, y:  H/2 } },
        // Top-to-bottom → normal (+1,0) points RIGHT (outward from centre)
        { a: { x:  W/4, y:  H/2 }, b: { x:  W/4, y: -H/2 } },
      ],
    },
    {
      id: "valley",
      name: "Recessed Valley",
      description: "Two vertical creases — outer strips fold outward (outside bend), centre strip stays flat and appears recessed.",
      suggestedUse: "Recessed centre panel",
      lineAngle: -4,
      lines: [
        { a: { x: -W/4, y: -H/2 }, b: { x: -W/4, y:  H/2 } },
        { a: { x:  W/4, y:  H/2 }, b: { x:  W/4, y: -H/2 } },
      ],
    },
    {
      id: "v-shape",
      name: "V Groove",
      description: "Two lines fan from bottom-centre — prismatic wedge pops toward viewer between the two creases.",
      suggestedUse: "Decorative fascia or spandrel",
      lineAngle: 5,
      lines: [
        // Reversed so normals point toward the V interior → interior gets both contributions
        { a: {  x:     0, y: -H/2 }, b: { x: -W/2, y:  H/2 } },
        { a: {  x:  W/2,  y:  H/2 }, b: { x:     0, y: -H/2 } },
      ],
    },
    {
      id: "diamond",
      name: "Faceted Diamond",
      description: "Four creases outline a diamond — centre facet is on the positive side of all four lines and projects most toward viewer.",
      suggestedUse: "Feature or highlight panel",
      lineAngle: 5,
      lines: [
        // All normals point toward the diamond centre
        { a: { x:  0,    y:  H/2 }, b: { x: -W/3, y:    0 } },
        { a: { x: -W/3,  y:    0 }, b: { x:  0,   y: -H/2 } },
        { a: { x:  0,    y: -H/2 }, b: { x:  W/3, y:    0 } },
        { a: { x:  W/3,  y:    0 }, b: { x:  0,   y:  H/2 } },
      ],
    },
    {
      id: "double-diagonal",
      name: "X Groove",
      description: "Two crossing grooves create four triangular facets — each at a different angle to light.",
      suggestedUse: "Dynamic textured cladding",
      lineAngle: 4,
      lines: [
        { a: { x: -W/2, y: -H/2 }, b: { x:  W/2, y:  H/2 } },
        { a: { x: -W/2, y:  H/2 }, b: { x:  W/2, y: -H/2 } },
      ],
    },
  ];
}

// ── Developed-blank computation ────────────────────────────────────────────────
//
// A decorative groove bends the face at angle θ. Each side tilts by θ/2 from flat.
// The developed (flat) extent perpendicular to the groove = projected_extent / cos(θ/2).
//
// Algorithm: for each groove, transform every face corner by scaling its signed
// perpendicular distance from the groove axis by 1/cos(θ/2). This is exact for one
// groove and a sequential approximation for multiple grooves (error < 0.5% at ≤ 20°).

interface DevInfo {
  devPoly:    Pt2[];    // developed face polygon (4 corners, slightly expanded from W×H)
  devW:       number;   // mm — bounding width
  devH:       number;   // mm — bounding height
  devArea:    number;   // mm²
  visArea:    number;   // mm²
  stretchPct: number;   // % area increase vs visible face
  perGroove:  {
    perpSpan:    number;  // mm — total face span perpendicular to this groove
    devPerpSpan: number;  // mm — developed span (perpSpan / cos(θ/2))
    stretchMm:   number;  // mm extra material in that direction
  }[];
}

function computeDesignDevelopment(W: number, H: number, lines: DesignLine[], lineAngle: number): DevInfo {
  const cosHalf = Math.cos((Math.abs(lineAngle) / 2) * (Math.PI / 180));

  let poly: Pt2[] = [
    { x: -W/2, y: -H/2 }, { x: W/2, y: -H/2 },
    { x:  W/2, y:  H/2 }, { x: -W/2, y:  H/2 },
  ];

  const perGroove: DevInfo["perGroove"] = [];

  for (const dl of lines) {
    const dx = dl.b.x - dl.a.x, dy = dl.b.y - dl.a.y;
    const len = Math.sqrt(dx * dx + dy * dy);
    if (len < 1e-6) continue;
    const tgx = dx / len, tgy = dy / len;  // unit tangent along groove
    const nx  = -tgy,     ny  = tgx;       // unit normal (90° CCW from tangent)

    // Total perpendicular span of the current polygon before development
    const perps = poly.map(p => (p.x - dl.a.x) * nx + (p.y - dl.a.y) * ny);
    const perpSpan    = Math.max(...perps) - Math.min(...perps);
    const devPerpSpan = perpSpan / cosHalf;
    perGroove.push({ perpSpan, devPerpSpan, stretchMm: devPerpSpan - perpSpan });

    // Apply development: scale each corner's perpendicular distance by 1/cosHalf.
    // Points on the groove axis (perp=0) stay fixed; points on either side expand outward.
    poly = poly.map(P => {
      const vx   = P.x - dl.a.x,  vy   = P.y - dl.a.y;
      const par  = vx * tgx + vy * tgy;
      const perp = vx * nx  + vy * ny;
      return {
        x: dl.a.x + par * tgx + (perp / cosHalf) * nx,
        y: dl.a.y + par * tgy + (perp / cosHalf) * ny,
      };
    });
  }

  const xs = poly.map(p => p.x), ys = poly.map(p => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);

  // Shoelace area of the (possibly non-rectangular) developed polygon
  let area2 = 0;
  for (let i = 0; i < poly.length; i++) {
    const j = (i + 1) % poly.length;
    area2 += poly[i].x * poly[j].y - poly[j].x * poly[i].y;
  }
  const devArea = Math.abs(area2) / 2;
  const visArea = W * H;

  return {
    devPoly: poly,
    devW:    maxX - minX,
    devH:    maxY - minY,
    devArea,
    visArea,
    stretchPct: (devArea / visArea - 1) * 100,
    perGroove,
  };
}

// ── Geometry — computed once, drives both 3D and 2D ──────────────────────────
//
// 3D folded board:
//   Main face lies in the Z=0 plane, centred at origin.
//   Each flap folds 90° inward → outer edge at Z = −edgeDepth.
//
// Unfolding (inverse of 90° fold):
//   Top flap    → rotate −90° around fold line y=+H/2  → lands above main face
//   Bottom flap → rotate +90° around fold line y=−H/2  → lands below main face
//   Left flap   → rotate +90° around fold line x=−W/2  → lands left of main face
//   Right flap  → rotate −90° around fold line x=+W/2  → lands right of main face
//
// Corner treatment (45° miter):
//   Adjacent flaps share a corner edge in 3D.  In 2D, their unfolded areas
//   would overlap at the corner square (d×d).  A 45° miter cut removes that
//   square as a triangle, giving clean mitered corners when folded.
//
interface BoardGeometry {
  W: number; H: number; d: number;

  // ── 3D folded positions ────────────────────────────────────────────────────
  face3:   [Pt3, Pt3, Pt3, Pt3]; // CCW from bottom-left, viewed from +Z
  top3:    [Pt3, Pt3, Pt3, Pt3];
  bottom3: [Pt3, Pt3, Pt3, Pt3];
  left3:   [Pt3, Pt3, Pt3, Pt3];
  right3:  [Pt3, Pt3, Pt3, Pt3];

  // fold lines in 3D (on the face surface, Z=0)
  foldLines3: { a: Pt3; b: Pt3; label: string }[];

  // ── 2D unfolded positions (flat pattern) ──────────────────────────────────
  face2:   [Pt2, Pt2, Pt2, Pt2];
  top2:    [Pt2, Pt2, Pt2, Pt2];
  bottom2: [Pt2, Pt2, Pt2, Pt2];
  left2:   [Pt2, Pt2, Pt2, Pt2];
  right2:  [Pt2, Pt2, Pt2, Pt2];

  // fold lines in 2D (shared edges between face and flaps)
  foldLines2: { a: Pt2; b: Pt2; label: string }[];

  // outer cut boundary — plus / cross shape, 12 vertices (CUT layer)
  outline: Pt2[];
}

function computeBoard({ width: W, height: H, edgeDepth: d }: BoardParams): BoardGeometry {
  // ── 3D ────────────────────────────────────────────────────────────────────
  //
  // Main face: 4 corners at Z=0
  const face3: BoardGeometry["face3"] = [
    { x: -W/2, y: -H/2, z: 0 },  // BL
    { x:  W/2, y: -H/2, z: 0 },  // BR
    { x:  W/2, y:  H/2, z: 0 },  // TR
    { x: -W/2, y:  H/2, z: 0 },  // TL
  ];

  // Each flap: fold line stays at Z=0, outer edge drops to Z=−d.
  // Vertices ordered: [fold-line-start, fold-line-end, outer-end, outer-start]

  // Top flap — folds around y=+H/2
  const top3: BoardGeometry["top3"] = [
    { x: -W/2, y:  H/2, z:  0 },
    { x:  W/2, y:  H/2, z:  0 },
    { x:  W/2, y:  H/2, z: -d },
    { x: -W/2, y:  H/2, z: -d },
  ];
  // Bottom flap — folds around y=−H/2
  const bottom3: BoardGeometry["bottom3"] = [
    { x:  W/2, y: -H/2, z:  0 },
    { x: -W/2, y: -H/2, z:  0 },
    { x: -W/2, y: -H/2, z: -d },
    { x:  W/2, y: -H/2, z: -d },
  ];
  // Left flap — folds around x=−W/2
  const left3: BoardGeometry["left3"] = [
    { x: -W/2, y:  H/2, z:  0 },
    { x: -W/2, y: -H/2, z:  0 },
    { x: -W/2, y: -H/2, z: -d },
    { x: -W/2, y:  H/2, z: -d },
  ];
  // Right flap — folds around x=+W/2
  const right3: BoardGeometry["right3"] = [
    { x:  W/2, y: -H/2, z:  0 },
    { x:  W/2, y:  H/2, z:  0 },
    { x:  W/2, y:  H/2, z: -d },
    { x:  W/2, y: -H/2, z: -d },
  ];

  const foldLines3: BoardGeometry["foldLines3"] = [
    { a: { x: -W/2, y:  H/2, z: 0.001 }, b: { x:  W/2, y:  H/2, z: 0.001 }, label: "T" },
    { a: { x: -W/2, y: -H/2, z: 0.001 }, b: { x:  W/2, y: -H/2, z: 0.001 }, label: "B" },
    { a: { x: -W/2, y: -H/2, z: 0.001 }, b: { x: -W/2, y:  H/2, z: 0.001 }, label: "L" },
    { a: { x:  W/2, y: -H/2, z: 0.001 }, b: { x:  W/2, y:  H/2, z: 0.001 }, label: "R" },
  ];

  // ── 2D unfolded ───────────────────────────────────────────────────────────
  //
  // Main face: stays put in the XY plane
  const face2: BoardGeometry["face2"] = [
    { x: -W/2, y: -H/2 },
    { x:  W/2, y: -H/2 },
    { x:  W/2, y:  H/2 },
    { x: -W/2, y:  H/2 },
  ];

  // Top flap: unfold by rotating −90° around y=+H/2.
  //   A point (x, H/2, −z) → (x, H/2+z, 0)
  const top2: BoardGeometry["top2"] = [
    { x: -W/2, y:  H/2   },  // fold-line corner (unchanged)
    { x:  W/2, y:  H/2   },
    { x:  W/2, y:  H/2+d },  // outer edge unfolds outward in +Y
    { x: -W/2, y:  H/2+d },
  ];

  // Bottom flap: unfold by rotating +90° around y=−H/2.
  //   A point (x, −H/2, −z) → (x, −H/2−z, 0)
  const bottom2: BoardGeometry["bottom2"] = [
    { x:  W/2, y: -H/2   },
    { x: -W/2, y: -H/2   },
    { x: -W/2, y: -(H/2+d) },
    { x:  W/2, y: -(H/2+d) },
  ];

  // Left flap: unfold by rotating +90° around x=−W/2.
  //   A point (−W/2, y, −z) → (−W/2−z, y, 0)
  const left2: BoardGeometry["left2"] = [
    { x:  -W/2,    y:  H/2 },
    { x:  -W/2,    y: -H/2 },
    { x: -(W/2+d), y: -H/2 },
    { x: -(W/2+d), y:  H/2 },
  ];

  // Right flap: unfold by rotating −90° around x=+W/2.
  //   A point (W/2, y, −z) → (W/2+z, y, 0)
  const right2: BoardGeometry["right2"] = [
    { x:  W/2,    y: -H/2 },
    { x:  W/2,    y:  H/2 },
    { x:  W/2+d,  y:  H/2 },
    { x:  W/2+d,  y: -H/2 },
  ];

  const foldLines2: BoardGeometry["foldLines2"] = [
    { a: { x: -W/2, y:  H/2 }, b: { x:  W/2, y:  H/2 }, label: "Top fold" },
    { a: { x: -W/2, y: -H/2 }, b: { x:  W/2, y: -H/2 }, label: "Bottom fold" },
    { a: { x: -W/2, y: -H/2 }, b: { x: -W/2, y:  H/2 }, label: "Left fold" },
    { a: { x:  W/2, y: -H/2 }, b: { x:  W/2, y:  H/2 }, label: "Right fold" },
  ];

  // Outer cut boundary — plus / cross shape, 12 vertices, clockwise from top-left of top flap.
  // The inner corners are right-angle notches that separate adjacent flaps.
  const outline: Pt2[] = [
    { x: -W/2,    y:  H/2+d   },  // top flap — outer left
    { x:  W/2,    y:  H/2+d   },  // top flap — outer right
    { x:  W/2,    y:  H/2     },  // inner notch — top-right
    { x:  W/2+d,  y:  H/2     },  // right flap — outer top
    { x:  W/2+d,  y: -H/2     },  // right flap — outer bottom
    { x:  W/2,    y: -H/2     },  // inner notch — bottom-right
    { x:  W/2,    y: -(H/2+d) },  // bottom flap — outer right
    { x: -W/2,    y: -(H/2+d) },  // bottom flap — outer left
    { x: -W/2,    y: -H/2     },  // inner notch — bottom-left
    { x: -(W/2+d),y: -H/2     },  // left flap — outer bottom
    { x: -(W/2+d),y:  H/2     },  // left flap — outer top
    { x: -W/2,    y:  H/2     },  // inner notch — top-left
  ];

  return {
    W, H, d,
    face3, top3, bottom3, left3, right3, foldLines3,
    face2, top2, bottom2, left2, right2, foldLines2,
    outline,
  };
}

// ── Three.js geometry builders ────────────────────────────────────────────────

function quad3(verts: Pt3[]): THREE.BufferGeometry {
  // verts = [v0, v1, v2, v3] — quad split into two triangles (0,1,2) and (0,2,3)
  const pos = new Float32Array([
    verts[0].x*S, verts[0].y*S, verts[0].z*S,
    verts[1].x*S, verts[1].y*S, verts[1].z*S,
    verts[2].x*S, verts[2].y*S, verts[2].z*S,
    verts[3].x*S, verts[3].y*S, verts[3].z*S,
  ]);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setIndex([0, 1, 2,  0, 2, 3]);
  g.computeVertexNormals();
  return g;
}

function lines3(pairs: { a: Pt3; b: Pt3 }[]): THREE.BufferGeometry {
  const pts: THREE.Vector3[] = [];
  for (const { a, b } of pairs) {
    pts.push(new THREE.Vector3(a.x*S, a.y*S, a.z*S));
    pts.push(new THREE.Vector3(b.x*S, b.y*S, b.z*S));
  }
  return new THREE.BufferGeometry().setFromPoints(pts);
}

// ── Polygon clipping helper ───────────────────────────────────────────────────
// Sutherland-Hodgman half-plane clip: returns vertices on each side of the
// line through (ax,ay) with unit normal (nx,ny).

function clipPolyByLine(
  poly: Pt2[], ax: number, ay: number, nx: number, ny: number,
): { pos: Pt2[]; neg: Pt2[] } {
  const EPS = 1e-7;
  const dist = (p: Pt2) => (p.x - ax) * nx + (p.y - ay) * ny;
  const pos: Pt2[] = [], neg: Pt2[] = [];
  const addUnique = (arr: Pt2[], p: Pt2) => {
    const last = arr[arr.length - 1];
    if (!last || Math.hypot(last.x - p.x, last.y - p.y) > EPS) arr.push(p);
  };

  for (let i = 0; i < poly.length; i++) {
    const j = (i + 1) % poly.length;
    const pi = poly[i], pj = poly[j];
    const di = dist(pi), dj = dist(pj);

    if (di >= -EPS) addUnique(pos, pi);
    if (di <=  EPS) addUnique(neg, pi);

    if ((di > EPS && dj < -EPS) || (di < -EPS && dj > EPS)) {
      const t  = di / (di - dj);
      const ip = { x: pi.x + t * (pj.x - pi.x), y: pi.y + t * (pj.y - pi.y) };
      addUnique(pos, ip);
      addUnique(neg, ip);
    }
  }

  const clean = (arr: Pt2[]): Pt2[] => {
    if (arr.length > 1 && Math.hypot(arr[0].x - arr[arr.length - 1].x, arr[0].y - arr[arr.length - 1].y) <= EPS) {
      arr.pop();
    }
    return arr;
  };

  return { pos: clean(pos), neg: clean(neg) };
}

function polyArea(poly: Pt2[]): number {
  let twiceArea = 0;
  for (let i = 0; i < poly.length; i++) {
    const j = (i + 1) % poly.length;
    twiceArea += poly[i].x * poly[j].y - poly[j].x * poly[i].y;
  }
  return Math.abs(twiceArea) / 2;
}

// ── Per-region facet geometry — one BufferGeometry per clipped polygon ─────────
//
// Polygon clipping (Sutherland-Hodgman) divides the face into ≤2^N regions.
// Each region is returned as its own BufferGeometry so that:
//   • every facet has a single flat normal (flatShading per mesh, not averaged)
//   • crease lines are hard geometric edges between adjacent meshes
//   • lighting reads each tilted panel as a distinct surface, like real folds
//
// Vertex positions use sequential Rodrigues axis-angle rotation around each
// groove line (hinge). No taper, no back-plane clamp — the geometry shows the
// true folded shape. Groove-line vertices (d≈0) stay at z=0 naturally.

function facetGeometry(poly: Pt3[]): THREE.BufferGeometry {
  const posArr: number[] = [];
  for (let j = 1; j < poly.length - 1; j++) {
    for (const p of [poly[0], poly[j], poly[j + 1]]) {
      posArr.push(p.x * S, p.y * S, p.z * S);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(posArr, 3));
  g.computeVertexNormals();
  return g;
}

function buildDesignFacetRegions(
  W: number, H: number,
  designId: string | undefined,
  designLines: DesignLine[],
  lineAngle: number,
): THREE.BufferGeometry[] {
  const sinHalfAbs = Math.sin((Math.abs(lineAngle) / 2) * (Math.PI / 180));
  const basePop = Math.sign(lineAngle || 1) * Math.min(180, Math.min(W, H) * 0.32) * sinHalfAbs;
  const outwardPop = Math.abs(basePop);
  const inwardPop = -Math.abs(basePop);
  const pop = designId === "valley" ? inwardPop : outwardPop;
  const Z0 = 0;

  const p3 = (x: number, y: number, z = Z0): Pt3 => ({ x, y, z });
  const BL = p3(-W/2, -H/2), BR = p3(W/2, -H/2), TR = p3(W/2, H/2), TL = p3(-W/2, H/2);

  if (designId === "raised-ridge" || designId === "valley") {
    const x1 = -W / 4, x2 = W / 4;
    const x1B = p3(x1, -H/2, pop), x1T = p3(x1, H/2, pop);
    const x2B = p3(x2, -H/2, pop), x2T = p3(x2, H/2, pop);
    return [
      facetGeometry([BL, x1B, x1T, TL]),
      facetGeometry([x1B, x2B, x2T, x1T]),
      facetGeometry([x2B, BR, TR, x2T]),
    ];
  }

  if (designId === "v-shape") {
    const A = p3(0, -H/2, pop), L = p3(-W/2, H/2, pop), R = p3(W/2, H/2, pop);
    return [
      facetGeometry([A, R, L]),
      facetGeometry([BL, A, L, TL]),
      facetGeometry([A, BR, TR, R]),
    ];
  }

  if (designId === "diamond") {
    const T = p3(0, H * 0.34, pop);
    const R = p3(W * 0.28, 0, pop);
    const B = p3(0, -H * 0.34, pop);
    const L = p3(-W * 0.28, 0, pop);
    return [
      facetGeometry([T, R, B, L]),
      facetGeometry([TL, TR, R, T, L]),
      facetGeometry([TR, BR, B, R]),
      facetGeometry([BR, BL, L, B]),
      facetGeometry([BL, TL, T, L]),
    ];
  }

  if (designId === "double-diagonal") {
    const C = p3(0, 0, Z0);
    const topPop = p3(0, H/2, pop);
    const rightPop = p3(W/2, 0, -pop * 0.55);
    const bottomPop = p3(0, -H/2, pop * 0.55);
    const leftPop = p3(-W/2, 0, -pop);
    return [
      facetGeometry([C, TL, topPop, TR]),
      facetGeometry([C, TR, rightPop, BR]),
      facetGeometry([C, BR, bottomPop, BL]),
      facetGeometry([C, BL, leftPop, TL]),
    ];
  }

  const dl = designLines[0];
  if (dl) {
    const dx = dl.b.x - dl.a.x, dy = dl.b.y - dl.a.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const nx = -dy / len, ny = dx / len;
    const project = (p: Pt2): Pt3 => {
      const d = (p.x - dl.a.x) * nx + (p.y - dl.a.y) * ny;
      return p3(p.x, p.y, -d * Math.sin((lineAngle / 2) * (Math.PI / 180)));
    };
    const { pos, neg } = clipPolyByLine([{ x: -W/2, y: -H/2 }, { x: W/2, y: -H/2 }, { x: W/2, y: H/2 }, { x: -W/2, y: H/2 }], dl.a.x, dl.a.y, nx, ny);
    return [pos, neg].filter(poly => poly.length >= 3 && polyArea(poly) > 1e-4).map(poly => facetGeometry(poly.map(project)));
  }

  return [facetGeometry([BL, BR, TR, TL])];
}

// ── Back-plane safety: max inward displacement (mm) ──────────────────────────
// Only OUT designs (positive lineAngle) push flanks toward the wall (−z).
// Samples a 30×30 grid to find the worst-case displacement.

function computeMaxInwardDisp(
  W: number, H: number,
  designLines: DesignLine[],
  lineAngle: number,
): number {
  if (lineAngle === 0) return 0;

  const sinHalf = Math.sin((lineAngle / 2) * (Math.PI / 180));

  type LN = { ax: number; ay: number; tx: number; ty: number; nx: number; ny: number };
  const lns: LN[] = designLines
    .map(dl => {
      const dx = dl.b.x - dl.a.x, dy = dl.b.y - dl.a.y;
      const len = Math.sqrt(dx * dx + dy * dy);
      if (len < 1e-6) return null;
      const tx = dx / len, ty = dy / len;
      return { ax: dl.a.x, ay: dl.a.y, tx, ty, nx: -ty, ny: tx };
    })
    .filter((v): v is LN => v !== null);

  if (lns.length === 0) return 0;

  const MARGIN = 8;
  const STEPS  = 30;
  let maxInward = 0;

  for (let xi = 0; xi <= STEPS; xi++) {
    for (let yi = 0; yi <= STEPS; yi++) {
      const px = -W / 2 + xi * W / STEPS;
      const py = -H / 2 + yi * H / STEPS;

      let vz = 0;
      for (const { ax, ay, nx, ny } of lns) {
        const d = (px - ax) * nx + (py - ay) * ny;
        if (Math.abs(d) < 1e-9) continue;
        vz += -d * sinHalf;
      }

      const wx = Math.min(1, (W / 2 - Math.abs(px)) / MARGIN);
      const wy = Math.min(1, (H / 2 - Math.abs(py)) / MARGIN);
      const zt = vz * Math.max(0, Math.min(wx, wy));
      if (zt < 0) maxInward = Math.max(maxInward, -zt);
    }
  }

  return maxInward;
}

// ── Direction-arrow geometry ───────────────────────────────────────────────────
// Tick marks along each groove line pointing in the peak direction:
//   OUT (+): arrow tips point toward +z (viewer) — groove is the raised ridge
//   IN  (−): arrow tips point toward −z (wall)   — groove is the recessed valley

function buildDirectionArrowsGeo(
  W: number,
  H: number,
  designLines: DesignLine[],
  lineAngle: number,
): THREE.BufferGeometry {
  const sinHalfAbs = Math.sin((Math.abs(lineAngle) / 2) * (Math.PI / 180));
  const sampleDist = Math.min(160, Math.max(35, Math.min(W, H) * 0.14));
  const ARROW_LEN  = 11;  // mm — stem length
  const HEAD_BACK  =  5;  // mm — from tip back to arrowhead base
  const HEAD_SPREAD = 3;  // mm — lateral fin spread
  const N          =  4;  // tick marks per groove line
  const zDir       = Math.sign(lineAngle || 1);

  const pts: THREE.Vector3[] = [];
  const add = (ax: number, ay: number, az: number, bx: number, by: number, bz: number) => {
    pts.push(new THREE.Vector3(ax, ay, az));
    pts.push(new THREE.Vector3(bx, by, bz));
  };

  for (const dl of designLines) {
    const dx = dl.b.x - dl.a.x, dy = dl.b.y - dl.a.y;
    const len = Math.sqrt(dx * dx + dy * dy);
    if (len < 1e-6) continue;
    const tx = dx / len, ty = dy / len;
    const nx = -ty, ny = tx;

    for (let i = 1; i <= N; i++) {
      const t = i / (N + 1);
      const mx = (dl.a.x + t * (dl.b.x - dl.a.x) + nx * sampleDist) * S;
      const my = (dl.a.y + t * (dl.b.y - dl.a.y) + ny * sampleDist) * S;
      const popDistance = zDir * sampleDist * sinHalfAbs;

      const baseZ = 0.5 * S;
      const tipZ  = baseZ + popDistance * S;
      const hdZ   = baseZ + (popDistance - zDir * HEAD_BACK) * S;
      const hr    = HEAD_SPREAD * S;

      add(mx, my, baseZ, mx, my, tipZ);                          // stem
      add(mx, my, tipZ, mx + tx * hr, my + ty * hr, hdZ);       // fin A
      add(mx, my, tipZ, mx - tx * hr, my - ty * hr, hdZ);       // fin B
    }
  }

  return new THREE.BufferGeometry().setFromPoints(pts);
}

// ── 3D scene ──────────────────────────────────────────────────────────────────

function Board3D({ geo, designId, designLines, lineAngle = 10, lightMode = "realistic" }: {
  geo: BoardGeometry;
  designId?: string;
  designLines?: DesignLine[];
  lineAngle?: number;
  lightMode?: "realistic" | "technical";
}) {
  const hasDesign    = Boolean(designLines?.length);

  const flatFaceGeo  = useMemo(() => quad3(geo.face3), [geo]);
  const facetRegions = useMemo(() => {
    if (!hasDesign || !designLines?.length) return null;
    return buildDesignFacetRegions(geo.W, geo.H, designId, designLines, lineAngle);
  }, [geo, hasDesign, designId, designLines, lineAngle]);

  const topGeo    = useMemo(() => quad3(geo.top3),    [geo]);
  const bottomGeo = useMemo(() => quad3(geo.bottom3), [geo]);
  const leftGeo   = useMemo(() => quad3(geo.left3),   [geo]);
  const rightGeo  = useMemo(() => quad3(geo.right3),  [geo]);
  const foldGeo   = useMemo(() => lines3(geo.foldLines3.map(fl => ({ a: fl.a, b: fl.b }))), [geo]);
  const arrowsGeo = useMemo(() => {
    if (!designLines?.length) return null;
    return buildDirectionArrowsGeo(geo.W, geo.H, designLines, lineAngle);
  }, [geo, designLines, lineAngle]);

  // Realistic: brushed-aluminium feel — wide diffuse spread, no harsh hot spots.
  // Technical: tighter specular so groove curvature reads more distinctly.
  const metalness = !hasDesign ? 0.65
    : lightMode === "technical" ? 0.80
    : 0.68;
  const roughness = !hasDesign ? 0.28
    : lightMode === "technical" ? 0.18
    : 0.32;
  const popSampleDist = Math.min(160, Math.max(35, Math.min(geo.W, geo.H) * 0.14));
  const popSampleMm = Math.sign(lineAngle || 1) * popSampleDist * Math.sin((Math.abs(lineAngle) / 2) * (Math.PI / 180));
  const faceMat = (
    <meshStandardMaterial
      color="#9db8d8"
      metalness={metalness}
      roughness={roughness}
      side={THREE.FrontSide}
    />
  );
  const flapMat = <meshStandardMaterial color="#7090b8" metalness={0.55} roughness={0.35} side={THREE.FrontSide} />;
  const backMat = <meshStandardMaterial color="#3a5470" metalness={0.4}  roughness={0.5}  side={THREE.BackSide}  />;

  return (
    <group>
      {hasDesign && (
        <mesh geometry={flatFaceGeo}>
          <meshBasicMaterial color="#dbeafe" transparent opacity={0.14} side={THREE.DoubleSide} />
        </mesh>
      )}
      {/* Main face — flat quad when no design; separate mesh per facet when design active */}
      {facetRegions
        ? facetRegions.map((fg, i) => (
            <group key={i}>
              <mesh geometry={fg}>
                <meshStandardMaterial
                  color="#9db8d8"
                  metalness={metalness}
                  roughness={roughness}
                  side={THREE.FrontSide}
                  flatShading
                />
              </mesh>
              <mesh geometry={fg}>{backMat}</mesh>
            </group>
          ))
        : (
          <>
            <mesh geometry={flatFaceGeo}>{faceMat}</mesh>
            <mesh geometry={flatFaceGeo}>{backMat}</mesh>
          </>
        )
      }

      {[topGeo, bottomGeo, leftGeo, rightGeo].map((g, i) => (
        <group key={i}>
          <mesh geometry={g}>{flapMat}</mesh>
          <mesh geometry={g}>{backMat}</mesh>
        </group>
      ))}

      {/* Fold lines — orange */}
      <lineSegments geometry={foldGeo}>
        <lineBasicMaterial color="#f97316" linewidth={1} />
      </lineSegments>

      {/* Groove crease lines — drawn from the design line definitions */}
      {hasDesign && designLines && (() => {
        const pts: THREE.Vector3[] = [];
        for (const dl of designLines) {
          pts.push(new THREE.Vector3(dl.a.x * S, dl.a.y * S, 1.5 * S));
          pts.push(new THREE.Vector3(dl.b.x * S, dl.b.y * S, 1.5 * S));
        }
        const g = new THREE.BufferGeometry().setFromPoints(pts);
        return (
          <lineSegments geometry={g}>
            <lineBasicMaterial color={lineAngle > 0 ? "#86efac" : "#fb923c"} />
          </lineSegments>
        );
      })()}
      {/* Direction arrows — ▲ toward viewer (OUT) or ▼ into panel (IN) */}
      {arrowsGeo && (
        <lineSegments geometry={arrowsGeo}>
          <lineBasicMaterial color={lineAngle > 0 ? "#86efac" : "#fb923c"} />
        </lineSegments>
      )}
      {/* Angle labels — one per groove at its midpoint, 18mm above face */}
      {hasDesign && designLines?.map((dl, i) => {
        const dx = dl.b.x - dl.a.x, dy = dl.b.y - dl.a.y;
        const len = Math.sqrt(dx * dx + dy * dy) || 1;
        const nx = -dy / len, ny = dx / len;
        const mx = ((dl.a.x + dl.b.x) / 2 + nx * popSampleDist) * S;
        const my = ((dl.a.y + dl.b.y) / 2 + ny * popSampleDist) * S;
        const color = lineAngle > 0 ? "#86efac" : "#fb923c";
        return (
          <Html key={`pop-${i}`} position={[mx, my, (popSampleMm + 12) * S]} center zIndexRange={[10, 10]}>
            <div style={{
              fontSize: "9px", fontWeight: 700, fontFamily: "monospace",
              color, background: "rgba(4,4,18,0.80)",
              padding: "1px 6px", borderRadius: 3, whiteSpace: "nowrap",
              border: `1px solid ${color}55`,
              pointerEvents: "none", userSelect: "none",
            }}>
              pop {popSampleMm >= 0 ? "+" : ""}{popSampleMm.toFixed(1)} mm
            </div>
          </Html>
        );
      })}
      {hasDesign && designLines?.map((dl, i) => {
        const mx = ((dl.a.x + dl.b.x) / 2) * S;
        const my = ((dl.a.y + dl.b.y) / 2) * S;
        const color = lineAngle > 0 ? "#86efac" : "#fb923c";
        const label = lineAngle > 0 ? `+${lineAngle}° OUT` : `${lineAngle}° IN`;
        return (
          <Html key={i} position={[mx, my, 18 * S]} center zIndexRange={[10, 10]}>
            <div style={{
              fontSize: "9px", fontWeight: 700, fontFamily: "monospace",
              color, background: "rgba(4,4,18,0.80)",
              padding: "1px 6px", borderRadius: 3, whiteSpace: "nowrap",
              border: `1px solid ${color}55`,
              pointerEvents: "none", userSelect: "none",
            }}>
              {label}
            </div>
          </Html>
        );
      })}
    </group>
  );
}

function Camera3D({ geo }: { geo: BoardGeometry }) {
  const { camera } = useThree();
  useEffect(() => {
    const diag = Math.sqrt(geo.W ** 2 + geo.H ** 2) * S;
    camera.position.set(geo.W * S * 0.55, geo.H * S * 0.55, diag * 1.6);
    (camera as THREE.PerspectiveCamera).lookAt(0, 0, -geo.d * S * 0.4);
  }, [geo, camera]);
  return null;
}

// ── 2D SVG flat pattern ───────────────────────────────────────────────────────

function FlatPatternSVG({ geo, size = 480, designLines, devInfo }: { geo: BoardGeometry; size?: number; designLines?: DesignLine[]; devInfo?: DevInfo | null }) {
  const pad = 42;
  const fabW = devInfo ? devInfo.devW : geo.W;
  const fabH = devInfo ? devInfo.devH : geo.H;
  const d    = geo.d;
  const fabOutline: Pt2[] = [
    { x: -fabW/2,      y:  fabH/2+d   },
    { x:  fabW/2,      y:  fabH/2+d   },
    { x:  fabW/2,      y:  fabH/2     },
    { x:  fabW/2+d,    y:  fabH/2     },
    { x:  fabW/2+d,    y: -fabH/2     },
    { x:  fabW/2,      y: -fabH/2     },
    { x:  fabW/2,      y: -(fabH/2+d) },
    { x: -fabW/2,      y: -(fabH/2+d) },
    { x: -fabW/2,      y: -fabH/2     },
    { x: -(fabW/2+d),  y: -fabH/2     },
    { x: -(fabW/2+d),  y:  fabH/2     },
    { x: -fabW/2,      y:  fabH/2     },
  ];
  const fabFolds: { a: Pt2; b: Pt2 }[] = [
    { a: { x: -fabW/2, y:  fabH/2 }, b: { x:  fabW/2, y:  fabH/2 } },
    { a: { x: -fabW/2, y: -fabH/2 }, b: { x:  fabW/2, y: -fabH/2 } },
    { a: { x: -fabW/2, y: -fabH/2 }, b: { x: -fabW/2, y:  fabH/2 } },
    { a: { x:  fabW/2, y: -fabH/2 }, b: { x:  fabW/2, y:  fabH/2 } },
  ];
  const all = fabOutline;
  const minX = Math.min(...all.map(p => p.x));
  const maxX = Math.max(...all.map(p => p.x));
  const minY = Math.min(...all.map(p => p.y));
  const maxY = Math.max(...all.map(p => p.y));
  const sc = Math.min((size - 2*pad) / (maxX-minX), (size - 2*pad) / (maxY-minY));
  const ox = (size - (maxX-minX)*sc) / 2;
  const oy = (size - (maxY-minY)*sc) / 2;

  // Y-axis flip: SVG Y goes down, geometry Y goes up
  const tx = (p: Pt2): Pt2 => ({
    x: (p.x - minX) * sc + ox,
    y: size - ((p.y - minY) * sc + oy),
  });

  const pts = (arr: Pt2[]): string =>
    arr.map(p => { const t = tx(p); return `${t.x.toFixed(1)},${t.y.toFixed(1)}`; }).join(" ");

  // Dimension helpers
  const dimText = (a: Pt2, b: Pt2, label: string, offset: number) => {
    const ta = tx(a), tb = tx(b);
    const mx = (ta.x + tb.x) / 2, my = (ta.y + tb.y) / 2;
    // perpendicular direction for label offset
    const dx = tb.x - ta.x, dy = tb.y - ta.y;
    const len = Math.sqrt(dx*dx + dy*dy) || 1;
    const nx = -dy/len, ny = dx/len;
    return (
      <text
        x={mx + nx * offset} y={my + ny * offset}
        textAnchor="middle" dominantBaseline="central"
        fontSize={11} fill="#6080a0" fontFamily="monospace"
      >
        {label}
      </text>
    );
  };

  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}
      style={{ display: "block", background: "#07071a", borderRadius: 10 }}>

      <defs>
        <filter id="cutGlow" x="-15%" y="-15%" width="130%" height="130%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="2.5" result="blur" />
          <feColorMatrix in="blur" type="matrix"
            values="1 0 0 0 0.6  0 0 0 0 0.05  0 0 0 0 0.05  0 0 0 0.5 0"
            result="glow" />
          <feMerge>
            <feMergeNode in="glow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* ── Blank fill — fabrication plus/cross shape (CUT material) ── */}
      <polygon points={pts(fabOutline)} fill="rgba(70,95,165,0.30)" stroke="none" />

      {/* ── Face area ── */}
      {devInfo ? (
        <>
          {/* Projected (original visible) face — faint dashed reference */}
          <polygon points={pts(geo.face2)} fill="rgba(130,170,230,0.08)" stroke="rgba(130,170,230,0.28)" strokeWidth="1" strokeDasharray="5,3" />
          {/* Developed (fabrication) face — primary teal fill */}
          <polygon points={pts(devInfo.devPoly)} fill="rgba(6,182,212,0.15)" stroke="none" />
        </>
      ) : (
        <polygon points={pts(geo.face2)} fill="rgba(130,170,230,0.20)" stroke="none" />
      )}

      {/* ── BEND: fold lines at developed face boundary ── */}
      {fabFolds.map((fl, i) => {
        const ta = tx(fl.a), tb = tx(fl.b);
        return (
          <line key={i}
            x1={ta.x} y1={ta.y} x2={tb.x} y2={tb.y}
            stroke="#f97316" strokeWidth="1.7" strokeDasharray="9,5"
          />
        );
      })}

      {/* ── DESIGN_GROOVE: decorative groove lines — purple dashed ── */}
      {designLines?.map((dl, i) => {
        const ta = tx(dl.a), tb = tx(dl.b);
        return (
          <line key={i}
            x1={ta.x} y1={ta.y} x2={tb.x} y2={tb.y}
            stroke="#a78bfa" strokeWidth="1.5" strokeDasharray="5,3"
          />
        );
      })}

      {/* ── CUT: fabrication blank boundary ── */}
      <polygon points={pts(fabOutline)} fill="none"
        stroke="#ef4444" strokeWidth="2.8" strokeLinejoin="round"
        filter="url(#cutGlow)" />

      {/* ── Fold corner marks (at face corners = bend origins) ── */}
      {(devInfo ? devInfo.devPoly : geo.face2).map((p, i) => {
        const t = tx(p);
        return <circle key={i} cx={t.x} cy={t.y} r={3} fill="#f97316" />;
      })}

      {devInfo && (
        <text
          x={tx({ x: 0, y: 0 }).x} y={tx({ x: 0, y: 0 }).y + 14}
          textAnchor="middle" fontSize={8.5} fill="rgba(130,170,230,0.45)" fontFamily="sans-serif"
        >
          projected face
        </text>
      )}

      {/* ── Dimension labels ── */}
      {dimText({ x: -fabW/2, y: 0 }, { x: fabW/2, y: 0 }, devInfo ? `fabW = ${fabW.toFixed(1)}` : `W = ${geo.W}`, -18)}
      {dimText({ x: 0, y: -fabH/2 }, { x: 0, y: fabH/2 }, devInfo ? `fabH = ${fabH.toFixed(1)}` : `H = ${geo.H}`, -18)}
      {dimText({ x: fabW/2, y: fabH/2 }, { x: fabW/2, y: fabH/2 + d }, `d=${d}`, 14)}
      {dimText({ x: fabW/2, y: 0 }, { x: fabW/2 + d, y: 0 }, `d=${d}`, -14)}

      {/* ── Legend ── */}
      {[
        { color: "#ef4444", dash: "",    rect: false, label: devInfo ? "CUT — developed blank boundary" : "CUT — outer blank boundary (cut through)" },
        { color: "#f97316", dash: "8,5", rect: false, label: "BEND — fold/groove line (90°)" },
        ...(designLines?.length ? [{ color: "#a78bfa", dash: "5,3", rect: false, label: "DESIGN_GROOVE — decorative groove" }] : [] as { color: string; dash: string; rect: boolean; label: string }[]),
        ...(devInfo ? [{ color: "#06b6d4", dash: "",    rect: true,  label: "FACE — developed (fabrication)" }] : [] as { color: string; dash: string; rect: boolean; label: string }[]),
      ].map(({ color, dash, rect, label }, i) => {
        const y = 14 + i * 16;
        return (
          <g key={label}>
            {rect
              ? <rect x={8} y={y - 5} width={22} height={10} fill={color} fillOpacity={0.3} stroke={color} strokeWidth={1} rx={2} />
              : <line x1={8} y1={y} x2={30} y2={y} stroke={color} strokeWidth={1.8} strokeDasharray={dash} />
            }
            <text x={35} y={y} dominantBaseline="central" fontSize={9.5} fill="#6080a8" fontFamily="sans-serif">
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ── UI atoms ──────────────────────────────────────────────────────────────────

function Num({ label, value, min, max, step, unit, onChange }: {
  label: string; value: number; min?: number; max?: number;
  step?: number; unit?: string; onChange: (v: number) => void;
}) {
  return (
    <div style={{ marginBottom: 9 }}>
      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 3 }}>
        {label}{unit && <span style={{ opacity: 0.5 }}> ({unit})</span>}
      </div>
      <input type="number" value={value} min={min} max={max} step={step ?? 1}
        onChange={e => onChange(Number(e.target.value))}
        style={{
          width: "100%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)",
          borderRadius: 6, color: "var(--text-primary)", padding: "5px 9px", fontSize: 13,
          outline: "none", boxSizing: "border-box", fontFamily: "inherit",
        }} />
    </div>
  );
}

function Card({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="glass-sm" style={{ padding: "11px 13px", marginBottom: 10 }}>
      <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.10em", color: "var(--text-subtle)", marginBottom: 9 }}>
        {label}
      </div>
      {children}
    </div>
  );
}

function KV({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 5, fontSize: 12 }}>
      <span style={{ color: "var(--text-subtle)" }}>{k}</span>
      <span style={{ color: "var(--text-primary)", fontWeight: 600, fontFamily: mono ? "monospace" : "inherit", fontSize: mono ? 11 : 12 }}>{v}</span>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function FoldedBoardPage() {
  const [params, setParams] = useState<BoardParams>({ width: 1200, height: 600, edgeDepth: 30 });
  const [view, setView] = useState<"2d" | "3d" | "split">("split");
  const [lightMode, setLightMode] = useState<"realistic" | "technical">("realistic");
  const [exporting, setExporting] = useState(false);
  const [showDesigns, setShowDesigns] = useState(false);
  const [selectedDesignId, setSelectedDesignId] = useState<string | null>(null);

  const set = (k: keyof BoardParams) => (v: number) => setParams(p => ({ ...p, [k]: v }));

  const geo = useMemo(() => computeBoard(params), [params]);

  const activeDesign = useMemo(
    () => !selectedDesignId ? null : generateDesigns(params.width, params.height).find(d => d.id === selectedDesignId) ?? null,
    [selectedDesignId, params.width, params.height],
  );
  const activePreviewAngle = activeDesign ? clampDecorativeAngle(activeDesign.lineAngle) : 0;
  const activeAngleLevel = activeDesign ? decorativeAngleLevel(activeDesign.lineAngle) : "recommended";
  const activeAngleClamped = activeDesign ? Math.abs(activeDesign.lineAngle) > DECORATIVE_PREVIEW_MAX : false;

  const devInfo = useMemo<DevInfo | null>(
    () => activeDesign?.lines.length
      ? computeDesignDevelopment(params.width, params.height, activeDesign.lines, activePreviewAngle)
      : null,
    [activeDesign, activePreviewAngle, params.width, params.height],
  );

  // Max inward displacement for the active design (mm) — used for wall-safety warning
  const maxInwardDisp = useMemo(
    () => activeDesign
      ? computeMaxInwardDisp(params.width, params.height, activeDesign.lines, activePreviewAngle)
      : 0,
    [activeDesign, activePreviewAngle, params.width, params.height],
  );
  const wallClamped = maxInwardDisp > params.edgeDepth - 2;

  // Per-design max inward displacement — shown as a warning on each card
  const designMaxDisps = useMemo(() => {
    const result: Record<string, number> = {};
    for (const d of generateDesigns(params.width, params.height)) {
      result[d.id] = computeMaxInwardDisp(params.width, params.height, d.lines, clampDecorativeAngle(d.lineAngle));
    }
    return result;
  }, [params.width, params.height]);

  const blankW  = params.width  + 2 * params.edgeDepth;
  const blankH  = params.height + 2 * params.edgeDepth;
  const faceArea  = (params.width  * params.height) / 1e6;
  // Octagon area: full rectangle minus 4 corner triangles (each d×d/2)
  const blankArea = (blankW * blankH - 4 * (params.edgeDepth * params.edgeDepth / 2)) / 1e6;

  const exportDxf = useCallback(async () => {
    setExporting(true);
    try {
      const res = await fetch(`${BASE}/folded-board/dxf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          width: params.width,
          height: params.height,
          edge_depth: params.edgeDepth,
          filename: "folded_board.dxf",
          design_lines: activeDesign?.lines.map(dl => ({
            x1: dl.a.x, y1: dl.a.y, x2: dl.b.x, y2: dl.b.y,
          })) ?? [],
          developed_polygon: devInfo?.devPoly.map(p => [p.x, p.y]) ?? [],
          design_angle: activeDesign?.lineAngle ?? 0,
        }),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      Object.assign(document.createElement("a"), { href: url, download: "folded_board.dxf" }).click();
      URL.revokeObjectURL(url);
    } catch (e) { console.error(e); }
    finally { setExporting(false); }
  }, [params, activeDesign, devInfo]);

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: "var(--bg-primary)" }}>

      {/* ── Left: controls ── */}
      <div style={{ width: 240, flexShrink: 0, overflowY: "auto", padding: "18px 14px", borderRight: "1px solid var(--glass-border)" }}>
        <div style={{ marginBottom: 14 }}>
          <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--text-subtle)" }}>
            Folded Board
          </span>
          <h1 style={{ fontSize: 17, fontWeight: 800, margin: "4px 0 4px", letterSpacing: "-0.02em" }}>
            Rectangle{" "}
            <span style={{ background: "linear-gradient(135deg,#06b6d4,#7c3aed)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
              Panel
            </span>
          </h1>
          <p style={{ fontSize: 10, color: "var(--text-subtle)", margin: 0, lineHeight: 1.55 }}>
            3D model → unfold → flat pattern → DXF
          </p>
        </div>

        <Card label="Panel dimensions">
          <Num label="Face width"    value={params.width}     min={100} max={6000} step={10} unit="mm" onChange={set("width")}     />
          <Num label="Face height"   value={params.height}    min={100} max={6000} step={10} unit="mm" onChange={set("height")}    />
          <Num label="Edge / return" value={params.edgeDepth} min={5}   max={200}  step={5}  unit="mm" onChange={set("edgeDepth")} />
        </Card>

        <Card label="Fabrication sequence">
          {[
            { color: "#9db8d8", sym: "①", label: "3D model",   desc: "Define the folded board geometry first" },
            { color: "#f97316", sym: "②", label: "BEND lines", desc: "Fold/groove lines along every face edge" },
            { color: "#ef4444", sym: "③", label: "CUT line",   desc: "Plus-shaped blank boundary — inner corners separate each flap" },
          ].map(({ color, sym, label, desc }) => (
            <div key={sym} style={{ display: "flex", gap: 9, marginBottom: 8, alignItems: "flex-start" }}>
              <div style={{ fontSize: 13, color, flexShrink: 0, lineHeight: 1 }}>{sym}</div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)" }}>{label}</div>
                <div style={{ fontSize: 10, color: "var(--text-subtle)", lineHeight: 1.45 }}>{desc}</div>
              </div>
            </div>
          ))}
        </Card>

        <Card label="Corner logic (45° miter)">
          <div style={{ fontSize: 10, color: "var(--text-subtle)", lineHeight: 1.7 }}>
            Each corner square (d × d) is cut at 45°. This means adjacent flap edges in 3D share a clean corner edge — no gap, no overlap.
          </div>
          <div style={{ marginTop: 10, fontFamily: "monospace", fontSize: 10, color: "var(--text-muted)", lineHeight: 1.8 }}>
            <div>d = {params.edgeDepth} mm</div>
            <div>corner cut = {params.edgeDepth}×{params.edgeDepth} mm²</div>
          </div>
        </Card>

        <Card label="Board-to-board joint">
          <div style={{ fontSize: 10, color: "var(--text-subtle)", lineHeight: 1.7 }}>
            Two boards edge-to-edge: each contributes a 90° return. Together they form a 180° flat joint — both returns press against the wall or backing.
          </div>
        </Card>
      </div>

      {/* ── Centre: views ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>

        {/* Toggle bar */}
        <div style={{ padding: "9px 16px", borderBottom: "1px solid var(--glass-border)", display: "flex", gap: 6, alignItems: "center" }}>
          {(["split", "3d", "2d"] as const).map(v => (
            <button key={v} onClick={() => setView(v)} style={{
              padding: "4px 14px", borderRadius: 6, border: "none", fontSize: 11,
              fontWeight: view === v ? 700 : 500, cursor: "pointer", fontFamily: "inherit",
              background: view === v ? "rgba(124,58,237,0.25)" : "rgba(255,255,255,0.05)",
              color: view === v ? "#c4b5fd" : "var(--text-subtle)",
            }}>
              {v === "split" ? "Split" : v === "3d" ? "3D Folded" : "2D Pattern"}
            </button>
          ))}

          {/* Lighting mode toggle — only shown when a design is active in 3D */}
          {activeDesign && view !== "2d" && (
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ fontSize: 9, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.08em", marginRight: 2 }}>
                Lighting
              </span>
              {(["realistic", "technical"] as const).map(mode => (
                <button key={mode} onClick={() => setLightMode(mode)} style={{
                  padding: "3px 10px", borderRadius: 5, border: "none", fontSize: 10,
                  fontWeight: lightMode === mode ? 700 : 400, cursor: "pointer", fontFamily: "inherit",
                  background: lightMode === mode ? "rgba(6,182,212,0.18)" : "rgba(255,255,255,0.04)",
                  color: lightMode === mode ? "#67e8f9" : "var(--text-subtle)",
                  transition: "background 0.15s, color 0.15s",
                }}>
                  {mode === "realistic" ? "Realistic" : "Technical"}
                </button>
              ))}
            </div>
          )}
        </div>

        <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

          {/* 3D panel */}
          {(view === "3d" || view === "split") && (
            <div style={{ flex: 1, background: "#07070e", borderRight: view === "split" ? "1px solid var(--glass-border)" : "none" }}>
              <Canvas camera={{ fov: 45, near: 0.001, far: 500 }} gl={{ antialias: true }}
                style={{ width: "100%", height: "100%" }}>
                <Suspense fallback={null}>
                  <Camera3D geo={geo} />
                  <ambientLight intensity={0.48} />
                  <directionalLight position={[3, 4, 5]}   intensity={0.85} />
                  <directionalLight position={[-3, 1, -3]} intensity={0.22} />
                  <directionalLight position={[0, -3, 2]}  intensity={0.12} />
                  {/* Single diagonal grazing light — reveals groove curvature without
                      creating a cross-highlight pattern that mimics fake groove lines.
                      Realistic: soft/low; Technical: slightly stronger. */}
                  {activeDesign && (
                    <directionalLight
                      position={[-2.5, -0.8, 1.8]}
                      intensity={lightMode === "technical" ? 0.38 : 0.22}
                    />
                  )}
                  <Board3D geo={geo} designId={activeDesign?.id} designLines={activeDesign?.lines} lineAngle={activePreviewAngle} lightMode={lightMode} />
                  <gridHelper args={[3, 24, "#111128", "#111128"]} position={[0, 0, -geo.d*S - 0.01]} rotation={[Math.PI/2, 0, 0]} />
                  <OrbitControls enableDamping dampingFactor={0.08} makeDefault />
                </Suspense>
              </Canvas>
            </div>
          )}

          {/* 2D panel */}
          {(view === "2d" || view === "split") && (
            <div style={{
              flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
              background: "#06060f", overflow: "auto", padding: 16,
            }}>
              <FlatPatternSVG geo={geo} size={480} designLines={activeDesign?.lines} devInfo={devInfo} />
            </div>
          )}
        </div>
      </div>

      {/* ── Right: info + export ── */}
      <div style={{ width: 256, flexShrink: 0, overflowY: "auto", padding: "18px 14px", borderLeft: "1px solid var(--glass-border)" }}>

        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)", marginBottom: 12 }}>Geometry</div>

        <Card label="3D folded board">
          <KV k="Face"   v={`${params.width} × ${params.height} mm`} />
          <KV k="Return" v={`${params.edgeDepth} mm (all 4 sides)`} />
          <KV k="Depth (folded)" v={`${params.edgeDepth} mm`} />
          <KV k="Bend angle"     v="90° inward" />
        </Card>

        <Card label="Flat blank (unfolded)">
          <KV k="Total W" v={`${blankW} mm`} mono />
          <KV k="Total H" v={`${blankH} mm`} mono />
          <KV k="Formula" v={`W+2d × H+2d`} mono />
          <div style={{ height: 1, background: "rgba(255,255,255,0.07)", margin: "6px 0" }} />
          <KV k="Face area"  v={`${faceArea.toFixed(4)} m²`} />
          <KV k="Blank area" v={`${blankArea.toFixed(4)} m²`} />
          <KV k="Corner cut (×4)" v={`${(params.edgeDepth * params.edgeDepth / 2 / 1e6).toFixed(5)} m²`} />
        </Card>

        {activeDesign && devInfo && (
          <Card label="Actual fabrication size">
            <KV k="Groove angle" v={`Requested: ${activeDesign.lineAngle}°`} mono />
            <KV k="Preview angle" v={activeAngleClamped ? `${activePreviewAngle}° max safe` : `${activePreviewAngle}°`} mono />
            {activeAngleLevel === "caution" && (
              <div style={{ marginTop: 8, padding: "6px 8px", borderRadius: 6, background: "rgba(251,191,36,0.07)", border: "1px solid rgba(251,191,36,0.24)", fontSize: 9, color: "#fcd34d", lineHeight: 1.7 }}>
                Caution: decorative face groove angles above 5° may be difficult to fabricate cleanly.
              </div>
            )}
            {activeAngleClamped && (
              <div style={{ marginTop: 8, padding: "6px 8px", borderRadius: 6, background: "rgba(251,191,36,0.09)", border: "1px solid rgba(251,191,36,0.32)", fontSize: 9, color: "#fcd34d", lineHeight: 1.7 }}>
                Angle too high for decorative face groove. Preview clamped to {DECORATIVE_PREVIEW_MAX}°.
              </div>
            )}
            <div style={{ height: 1, background: "rgba(255,255,255,0.07)", margin: "8px 0" }} />
            <KV k="Visible W"   v={`${params.width} mm`} mono />
            <KV k="Developed W" v={`${devInfo.devW.toFixed(2)} mm`} mono />
            <KV k="Visible H"   v={`${params.height} mm`} mono />
            <KV k="Developed H" v={`${devInfo.devH.toFixed(2)} mm`} mono />
            <div style={{ height: 1, background: "rgba(255,255,255,0.07)", margin: "6px 0" }} />
            <KV k="Visible area"   v={`${(devInfo.visArea/1e6).toFixed(4)} m²`} />
            <KV k="Developed area" v={`${(devInfo.devArea/1e6).toFixed(4)} m²`} mono />
            <KV k="Area stretch"   v={`+${devInfo.stretchPct.toFixed(3)}%`} />
            {devInfo.perGroove.map((g, i) => (
              <div key={i}>
                <div style={{ height: 1, background: "rgba(255,255,255,0.07)", margin: "6px 0" }} />
                <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 4 }}>
                  Groove {i + 1} — {activeDesign.lineAngle}° bend
                </div>
                <KV k="Perp span"  v={`${g.perpSpan.toFixed(1)} mm`} mono />
                <KV k="Dev'd span" v={`${g.devPerpSpan.toFixed(1)} mm`} mono />
                <KV k="Extra ↑"   v={`+${g.stretchMm.toFixed(2)} mm`} />
              </div>
            ))}
            <div style={{ marginTop: 8, padding: "5px 8px", borderRadius: 6, background: "rgba(6,182,212,0.07)", border: "1px solid rgba(6,182,212,0.18)", fontSize: 9, color: "#67e8f9", lineHeight: 1.65 }}>
              ⓘ Approx. (sequential unfolding). Exact for 1 groove, ≤ 0.5% error for multiple at ≤ 20°.
            </div>
            {wallClamped && (
              <div style={{ marginTop: 8, padding: "6px 8px", borderRadius: 6, background: "rgba(251,191,36,0.07)", border: "1px solid rgba(251,191,36,0.28)", fontSize: 9, color: "#fcd34d", lineHeight: 1.7 }}>
                ⚠ Flank displacement ({maxInwardDisp.toFixed(1)} mm) exceeds return depth ({params.edgeDepth} mm).
                3D preview clamped — groove flanks limited to wall plane.
              </div>
            )}
          </Card>
        )}

        <Card label="Corner miter">
          <KV k="Cut type"     v="45° diagonal" />
          <KV k="Corner size"  v={`${params.edgeDepth} × ${params.edgeDepth} mm`} />
          <KV k="Material saved" v={`${(4 * params.edgeDepth**2 / 2 / 1e6).toFixed(5)} m²`} />
          <div style={{ marginTop: 8, fontSize: 10, color: "var(--text-subtle)", lineHeight: 1.6 }}>
            The miter diagonal connects the outer corner of one flap to the outer corner of the adjacent flap. In 3D, the two flap edges meet cleanly.
          </div>
        </Card>

        {/* ── AI Board Design ── */}
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)", marginBottom: 10, marginTop: 4 }}>
          AI Board Design
        </div>

        <Card label="Generate Design Ideas">
          <div style={{ fontSize: 10, color: "var(--text-subtle)", lineHeight: 1.55, marginBottom: 9 }}>
            Apply a decorative groove pattern to the face. Selected design exports on the DESIGN_GROOVE layer.
          </div>
          <button
            onClick={() => setShowDesigns(true)}
            style={{
              width: "100%", padding: "8px 0", borderRadius: 7, border: "none",
              cursor: "pointer", fontFamily: "inherit", fontSize: 12, fontWeight: 700,
              background: "linear-gradient(135deg,#a78bfa,#38bdf8)", color: "#fff",
            }}
          >
            ✦ Generate Design Ideas
          </button>
        </Card>

        {showDesigns && (
          <div style={{ marginBottom: 10 }}>
            {generateDesigns(params.width, params.height).map(opt => (
              <div
                key={opt.id}
                onClick={() => setSelectedDesignId(prev => prev === opt.id ? null : opt.id)}
                style={{
                  cursor: "pointer", padding: "9px 11px", borderRadius: 8, marginBottom: 6,
                  border: `1px solid ${selectedDesignId === opt.id ? "rgba(167,139,250,0.6)" : "rgba(255,255,255,0.08)"}`,
                  background: selectedDesignId === opt.id ? "rgba(167,139,250,0.12)" : "rgba(255,255,255,0.03)",
                  transition: "border-color 0.15s, background 0.15s",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 3 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: selectedDesignId === opt.id ? "#c4b5fd" : "var(--text-primary)" }}>
                    {opt.name}
                  </span>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2, flexShrink: 0, marginLeft: 6 }}>
                    {/* Direction badge */}
                    <span style={{
                      fontSize: 9, fontWeight: 700, fontFamily: "monospace",
                      padding: "1px 5px", borderRadius: 4,
                      background: opt.lineAngle > 0 ? "rgba(134,239,172,0.14)" : "rgba(251,146,60,0.14)",
                      color: opt.lineAngle > 0 ? "#86efac" : "#fb923c",
                      border: `1px solid ${opt.lineAngle > 0 ? "rgba(134,239,172,0.32)" : "rgba(251,146,60,0.32)"}`,
                      whiteSpace: "nowrap",
                    }}>
                      {opt.lineAngle > 0 ? "▲ OUT" : "▼ IN"}&nbsp;{Math.abs(opt.lineAngle)}°
                    </span>
                    {decorativeAngleLevel(opt.lineAngle) !== "recommended" && (
                      <span style={{ fontSize: 8, color: "#fbbf24", letterSpacing: "0.03em", fontWeight: 600 }}>
                        {decorativeAngleLevel(opt.lineAngle) === "unsafe" ? "angle clamp" : "caution"}
                      </span>
                    )}
                    {/* Wall-plane warning */}
                    {(designMaxDisps[opt.id] ?? 0) > params.edgeDepth - 2 && (
                      <span style={{ fontSize: 8, color: "#fbbf24", letterSpacing: "0.03em", fontWeight: 600 }}>
                        ⚠ wall
                      </span>
                    )}
                  </div>
                </div>
                <div style={{ fontSize: 10, color: "var(--text-subtle)", lineHeight: 1.45, marginBottom: 3 }}>
                  {opt.description}
                </div>
                <div style={{ fontSize: 9, color: "#7c6bba", fontStyle: "italic" }}>
                  {opt.suggestedUse}
                </div>
                {decorativeAngleLevel(opt.lineAngle) === "unsafe" && (
                  <div style={{ marginTop: 6, padding: "5px 7px", borderRadius: 6, background: "rgba(251,191,36,0.08)", border: "1px solid rgba(251,191,36,0.25)", color: "#fcd34d", fontSize: 9, lineHeight: 1.5 }}>
                    Angle too high for decorative face groove. Preview clamped to {DECORATIVE_PREVIEW_MAX}°.
                    <br />Requested: {opt.lineAngle}° · Preview: {clampDecorativeAngle(opt.lineAngle)}° max safe
                  </div>
                )}
              </div>
            ))}
            {selectedDesignId && (
              <button
                onClick={() => setSelectedDesignId(null)}
                style={{
                  width: "100%", padding: "5px 0", borderRadius: 6, cursor: "pointer",
                  border: "1px solid rgba(255,255,255,0.10)", background: "transparent",
                  color: "var(--text-subtle)", fontSize: 10, fontFamily: "inherit",
                }}
              >
                Clear selection
              </button>
            )}
          </div>
        )}

        <Card label="DXF layers">
          {[
            { color: "#ef4444", sym: "CUT",    desc: "Plus-shaped outer blank boundary" },
            { color: "#f97316", sym: "BEND",   desc: "4 fold/groove lines" },
            { color: "#9db8d8", sym: "FACE",   desc: "Visible face outline" },
            { color: "#a0a0c0", sym: "LABELS", desc: "W, H, d dimensions" },
            ...(activeDesign ? [{ color: "#a78bfa", sym: "DESIGN_GROOVE", desc: `${activeDesign.name} — ${activeDesign.lineAngle > 0 ? "+" : ""}${activeDesign.lineAngle}° ${activeDesign.lineAngle < 0 ? "inside" : "outside"}` }] : []),
            ...(devInfo ? [{ color: "#06b6d4", sym: "DEVELOPED", desc: "Original face reference (developed size approx.)" }] : []),
          ].map(({ color, sym, desc }) => (
            <div key={sym} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5, fontSize: 11 }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: color, flexShrink: 0 }} />
              <span style={{ fontWeight: 700, fontFamily: "monospace", color: "var(--text-muted)" }}>{sym}</span>
              <span style={{ fontSize: 10, color: "var(--text-subtle)" }}>{desc}</span>
            </div>
          ))}
        </Card>

        <button onClick={exportDxf} disabled={exporting} style={{
          width: "100%", padding: "10px 0", borderRadius: 9, border: "none",
          cursor: exporting ? "default" : "pointer",
          background: "linear-gradient(135deg,#7c3aed,#06b6d4)",
          color: "#fff", fontSize: 13, fontWeight: 700,
          opacity: exporting ? 0.6 : 1, fontFamily: "inherit", transition: "opacity 0.2s",
        }}>
          {exporting ? "Exporting…" : "↓ Export Flat-Blank DXF"}
        </button>
        <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-subtle)", textAlign: "center", lineHeight: 1.5 }}>
          Edge bends exact · Decorative groove DXF — developed size approximate
        </div>
      </div>

    </div>
  );
}
