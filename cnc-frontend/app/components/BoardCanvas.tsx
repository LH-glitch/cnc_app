"use client";

import { useMemo } from "react";
import type { BoardSlice } from "@/lib/api";

// SVG logical viewport size (will scale to container via viewBox)
const VW = 520;
const VH = 360;
const PAD = 40; // padding inside the drawing area

function buildPaths(slice: BoardSlice) {
  const flat = slice.contours.filter((c) => c.length >= 2);
  if (!flat.length) return null;

  // Bounding box across all contours
  let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  for (const c of flat) {
    for (const [x, z] of c) {
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (z < z0) z0 = z;
      if (z > z1) z1 = z;
    }
  }

  const rangeX = x1 - x0 || 1;
  const rangeZ = z1 - z0 || 1;
  const drawW = VW - PAD * 2;
  const drawH = VH - PAD * 2;
  const scale = Math.min(drawW / rangeX, drawH / rangeZ) * 0.86;
  const midX = (x0 + x1) / 2;
  const midZ = (z0 + z1) / 2;

  const toSvg = (x: number, z: number) =>
    `${(VW / 2 + (x - midX) * scale).toFixed(2)},${(VH / 2 - (z - midZ) * scale).toFixed(2)}`;

  return {
    paths: flat.map((c, i) => ({
      key: i,
      d: c.map((pt, j) => `${j === 0 ? "M" : "L"}${toSvg(pt[0], pt[1])}`).join(" ") + " Z",
    })),
    dimW: rangeX.toFixed(1),
    dimH: rangeZ.toFixed(1),
  };
}

export default function BoardCanvas({ slice }: { slice: BoardSlice }) {
  const geo = useMemo(() => buildPaths(slice), [slice]);
  const u = `bc${slice.index}`; // unique id prefix for SVG defs

  return (
    <svg
      viewBox={`0 0 ${VW} ${VH}`}
      style={{ width: "100%", height: "auto", display: "block" }}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        {/* Dot grid background pattern */}
        <pattern id={`${u}g`} width="24" height="24" patternUnits="userSpaceOnUse">
          <circle cx="0.5" cy="0.5" r="0.75" fill="rgba(255,255,255,0.055)" />
        </pattern>
        {/* Contour fill gradient */}
        <linearGradient id={`${u}f`} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#7c3aed" stopOpacity="0.20" />
          <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0.12" />
        </linearGradient>
        {/* Contour stroke gradient */}
        <linearGradient id={`${u}s`} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#a78bfa" />
          <stop offset="100%" stopColor="#38bdf8" />
        </linearGradient>
        {/* Glow filter */}
        <filter id={`${u}glow`} x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="3.5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Canvas background */}
      <rect width={VW} height={VH} fill="rgba(0,0,0,0.25)" rx="10" />
      <rect width={VW} height={VH} fill={`url(#${u}g)`} rx="10" />
      {/* Border */}
      <rect width={VW} height={VH} rx="10" fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="1" />

      {/* Crosshair center reference */}
      <line x1={VW / 2} y1={PAD / 2} x2={VW / 2} y2={VH - PAD / 2} stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
      <line x1={PAD / 2} y1={VH / 2} x2={VW - PAD / 2} y2={VH / 2} stroke="rgba(255,255,255,0.04)" strokeWidth="1" />

      {geo ? (
        <>
          {geo.paths.map(({ d, key }) => (
            <path
              key={key}
              d={d}
              fill={`url(#${u}f)`}
              stroke={`url(#${u}s)`}
              strokeWidth="1.8"
              strokeLinejoin="round"
              filter={`url(#${u}glow)`}
            />
          ))}
          {/* Dimension label */}
          <text
            x={VW / 2}
            y={VH - 11}
            textAnchor="middle"
            fill="rgba(255,255,255,0.28)"
            fontSize="11"
            fontFamily="var(--font-geist-mono), monospace"
          >
            {geo.dimW} × {geo.dimH} mm
          </text>
        </>
      ) : (
        <text
          x={VW / 2}
          y={VH / 2}
          textAnchor="middle"
          dominantBaseline="middle"
          fill="rgba(255,255,255,0.2)"
          fontSize="13"
          fontFamily="var(--font-geist-sans), sans-serif"
        >
          No contour data
        </text>
      )}
    </svg>
  );
}
