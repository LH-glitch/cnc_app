"use client";

/**
 * Board3DViewer — react-three-fiber 3D visualisation of stacked CNC boards.
 *
 * Each board is rendered as an extruded slab whose cross-section comes from
 * the 2-D contour produced by the slicer.  Boards are stacked along the
 * slicing axis.  The viewer supports orbit/zoom/pan and highlights the
 * currently-selected board.
 */

import { memo, useMemo, useRef, useEffect } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { SliceResult, BoardSlice } from "@/lib/api";

// ── Color palette ─────────────────────────────────────────────────────────────

const C_FROM = new THREE.Color("#7c3aed"); // violet
const C_TO   = new THREE.Color("#0ea5e9"); // sky
const C_SEL  = new THREE.Color("#f0e6ff"); // bright selection tint

function boardColor(t: number, selected: boolean): THREE.Color {
  const c = new THREE.Color().lerpColors(C_FROM, C_TO, t);
  if (selected) c.lerp(C_SEL, 0.45);
  return c;
}

// ── Geometry builder ──────────────────────────────────────────────────────────

/**
 * Build an ExtrudeGeometry from contour data.
 * The longest contour is used as the outer shape; shorter ones become holes
 * (useful for alignment holes, etc.).
 *
 * The shape lives in the XY plane; depth is extruded along +Z.
 * Callers rotate the mesh to align with the stacking axis.
 */
function buildBoardGeometry(
  contours: Array<Array<[number, number]>>,
  depth: number
): THREE.ExtrudeGeometry | null {
  // Sort by length — longest is outer shape
  const sorted = [...contours].sort((a, b) => b.length - a.length);
  const outer = sorted[0];
  if (!outer || outer.length < 3) return null;

  const shape = new THREE.Shape();
  shape.moveTo(outer[0][0], outer[0][1]);
  for (let i = 1; i < outer.length; i++) shape.lineTo(outer[i][0], outer[i][1]);

  // Remaining contours are holes (e.g. dowel holes)
  for (let h = 1; h < sorted.length; h++) {
    const pts = sorted[h];
    if (pts.length < 3) continue;
    const hole = new THREE.Path();
    hole.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) hole.lineTo(pts[i][0], pts[i][1]);
    shape.holes.push(hole);
  }

  return new THREE.ExtrudeGeometry(shape, {
    depth,
    bevelEnabled: false,
    steps: 1,
  });
}

// ── Axis helpers ──────────────────────────────────────────────────────────────

/**
 * Returns the Euler rotation and world-space position for a board mesh so
 * that the extrusion (local +Z) aligns with the model's stacking axis.
 *
 * The ExtrudeGeometry is built in the local XY plane, extruded along local Z.
 * Rotation.x = +π/2  → local XY  becomes world XZ, local +Z becomes world +Y
 * Rotation.y = -π/2  → local XY  becomes world YZ, local +Z becomes world +X
 * No rotation        → local XY  stays   world XY, local +Z stays   world +Z
 */
function boardTransform(
  axis: string,
  yMin: number,
  elevate: number
): { rotation: [number, number, number]; position: [number, number, number] } {
  switch (axis) {
    case "x":
      return {
        rotation: [0, -Math.PI / 2, 0],
        position: [yMin + elevate, 0, 0],
      };
    case "z":
      return {
        rotation: [0, 0, 0],
        position: [0, 0, yMin + elevate],
      };
    default: // "y"
      return {
        rotation: [Math.PI / 2, 0, 0],
        position: [0, yMin + elevate, 0],
      };
  }
}

// ── Board mesh ────────────────────────────────────────────────────────────────

interface BoardMeshProps {
  slice: BoardSlice;
  boardDepth: number;
  colorT: number;
  selected: boolean;
  stackingAxis: string;
  onSelect: () => void;
}

const BoardMesh = memo(function BoardMesh({
  slice,
  boardDepth,
  colorT,
  selected,
  stackingAxis,
  onSelect,
}: BoardMeshProps) {
  const geoRef = useRef<THREE.ExtrudeGeometry | null>(null);

  const geo = useMemo(() => {
    geoRef.current?.dispose();
    const g = buildBoardGeometry(slice.contours, boardDepth);
    geoRef.current = g;
    return g;
  }, [slice, boardDepth]);

  // Cleanup on unmount
  useEffect(() => () => { geoRef.current?.dispose(); }, []);

  const color   = useMemo(() => boardColor(colorT, selected), [colorT, selected]);
  const emissive = useMemo(() => boardColor(colorT, false).multiplyScalar(selected ? 0.32 : 0.06), [colorT, selected]);

  const elevate = selected ? boardDepth * 0.12 : 0;
  const { rotation, position } = useMemo(
    () => boardTransform(stackingAxis, slice.y_min, elevate),
    [stackingAxis, slice.y_min, elevate]
  );

  if (!geo) return null;

  return (
    <mesh
      geometry={geo}
      rotation={rotation}
      position={position}
      onClick={(e) => { e.stopPropagation(); onSelect(); }}
      onPointerOver={(e) => { e.stopPropagation(); document.body.style.cursor = "pointer"; }}
      onPointerOut={() => { document.body.style.cursor = "auto"; }}
    >
      <meshStandardMaterial
        color={color}
        emissive={emissive}
        emissiveIntensity={1}
        roughness={selected ? 0.35 : 0.62}
        metalness={0.12}
        transparent
        opacity={selected ? 1.0 : 0.80}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
});

// ── Camera setup ──────────────────────────────────────────────────────────────

/**
 * Positions the camera once (on first mount) so the full stack is in view.
 */
function CameraSetup({
  target,
  distance,
}: {
  target: THREE.Vector3;
  distance: number;
}) {
  const { camera } = useThree();
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    camera.position.set(
      target.x + distance * 0.55,
      target.y + distance * 0.45,
      target.z + distance * 0.9
    );
    camera.lookAt(target);
  }, [camera, target, distance]);

  return null;
}

// ── Orbit loop (keeps damping alive) ─────────────────────────────────────────

function DampingLoop({ controlsRef }: { controlsRef: React.RefObject<import("three-stdlib").OrbitControls | null> }) {
  useFrame(() => controlsRef.current?.update());
  return null;
}

// ── Scene (renders inside <Canvas>) ──────────────────────────────────────────

function Scene({
  result,
  selectedBoard,
  onSelectBoard,
}: {
  result: SliceResult;
  selectedBoard: number;
  onSelectBoard: (i: number) => void;
}) {
  const controlsRef = useRef<import("three-stdlib").OrbitControls>(null);

  const { target, distance } = useMemo(() => {
    const { slices, model_span, stacking_axis } = result;
    const y0 = slices[0]?.y_min ?? 0;
    const y1 = slices[slices.length - 1]?.y_max ?? model_span;
    const mid = (y0 + y1) / 2;

    // Estimate cross-section extent from first contour
    let maxR = 80;
    const c0 = slices[0]?.contours[0];
    if (c0?.length) {
      let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
      for (const [x, z] of c0) {
        if (x < x0) x0 = x; if (x > x1) x1 = x;
        if (z < z0) z0 = z; if (z > z1) z1 = z;
      }
      maxR = Math.max(x1 - x0, z1 - z0) * 0.6;
    }

    const tgt = new THREE.Vector3(
      stacking_axis === "x" ? mid : 0,
      stacking_axis === "y" ? mid : 0,
      stacking_axis === "z" ? mid : 0
    );
    const dist = Math.max(model_span * 1.1, maxR * 3, 200);
    return { target: tgt, distance: dist };
  }, [result]);

  const orbitTarget = useMemo<[number, number, number]>(
    () => [target.x, target.y, target.z],
    [target]
  );

  return (
    <>
      {/* Lighting */}
      <ambientLight intensity={0.55} />
      <directionalLight position={[1, 2.5, 1.5]} intensity={1.1} />
      <directionalLight position={[-1.5, -1, -1]} intensity={0.22} color="#6060b0" />
      <pointLight
        position={[target.x, target.y + distance * 0.4, target.z]}
        intensity={0.5}
        color="#9d6fce"
        distance={distance * 3}
        decay={1.5}
      />

      {/* Subtle depth fog */}
      <fog attach="fog" args={["#04040f", distance * 2, distance * 6]} />

      {/* Camera + controls */}
      <CameraSetup target={target} distance={distance} />
      <OrbitControls
        ref={controlsRef}
        target={orbitTarget}
        enableDamping
        dampingFactor={0.06}
        zoomSpeed={1.1}
        rotateSpeed={0.75}
        panSpeed={0.85}
        minDistance={distance * 0.08}
        maxDistance={distance * 8}
      />
      <DampingLoop controlsRef={controlsRef} />

      {/* Board meshes */}
      {result.slices.map((slice, i) => (
        <BoardMesh
          key={slice.index}
          slice={slice}
          boardDepth={result.board_thickness}
          colorT={result.slices.length > 1 ? i / (result.slices.length - 1) : 0.5}
          selected={i === selectedBoard}
          stackingAxis={result.stacking_axis}
          onSelect={() => onSelectBoard(i)}
        />
      ))}
    </>
  );
}

// ── Public component ──────────────────────────────────────────────────────────

export default function Board3DViewer({
  result,
  selectedBoard,
  onSelectBoard,
}: {
  result: SliceResult;
  selectedBoard: number;
  onSelectBoard: (i: number) => void;
}) {
  return (
    <div
      style={{
        width: "100%",
        height: 380,
        background: "rgba(2,2,12,0.6)",
        borderRadius: 12,
        overflow: "hidden",
        position: "relative",
      }}
    >
      <Canvas
        frameloop="always"
        camera={{ fov: 45, near: 0.5, far: 200000 }}
        gl={{ antialias: true, alpha: true }}
        style={{ background: "transparent" }}
      >
        <Scene
          result={result}
          selectedBoard={selectedBoard}
          onSelectBoard={onSelectBoard}
        />
      </Canvas>

      {/* Usage hint */}
      <div
        style={{
          position: "absolute",
          bottom: 10,
          right: 14,
          fontSize: 10,
          color: "rgba(255,255,255,0.22)",
          pointerEvents: "none",
          fontFamily: "var(--font-geist-mono), monospace",
        }}
      >
        drag · scroll · shift+drag
      </div>
    </div>
  );
}
