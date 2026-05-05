"use client";

import Link from "next/link";
import ToolCard, { Tool } from "../components/ToolCard";
import { FadeIn, FadeInGroup, FadeInItem } from "../components/FadeIn";

// ── Tool registry ─────────────────────────────────────────────────────────────

const AVAILABLE: Tool[] = [
  {
    href: "/slicer",
    icon: "≡",
    name: "Stacked Slicer",
    tagline: "STL → stackable board profiles",
    description:
      "Upload any 3D mesh and slice it into flat board profiles ready for CNC cutting. Choose stacking axis, board thickness, quality preset, and alignment hole pattern — then export DXF.",
    capabilities: [
      "Envelope & best-sample profile modes",
      "Fast / Accurate quality presets",
      "Dowel alignment hole patterns",
    ],
    status: "live",
    accentFrom: "#7c3aed",
    accentTo: "#0ea5e9",
  },
  {
    href: "/photo-to-dxf",
    icon: "⊙",
    name: "Photo → DXF",
    tagline: "Vectorize images for CNC",
    description:
      "Turn photographs and raster artwork into clean DXF vector files. Adjust threshold, blur, and path simplification — then inspect the traced contours before exporting.",
    capabilities: [
      "Threshold + blur contour detection",
      "Ramer–Douglas–Peucker path simplification",
      "Scale calibration — mm per pixel export",
    ],
    status: "live",
    accentFrom: "#ec4899",
    accentTo: "#a855f7",
  },
  {
    href: "/dxf-generator",
    icon: "◇",
    name: "DXF Generator",
    tagline: "Parametric shape generator",
    description:
      "Generate precise DXF files from parametric shape templates. Configure dimensions, kerf compensation, and holes — then export instantly.",
    capabilities: [
      "Rectangle, circle, slot, L/T bracket",
      "Corner radius & kerf compensation",
      "Live SVG preview before export",
    ],
    status: "live",
    accentFrom: "#10b981",
    accentTo: "#06b6d4",
  },
  {
    href: "/sheet-layout",
    icon: "⊞",
    name: "Sheet Layout",
    tagline: "Nesting & material optimisation",
    description:
      "Pack cut parts onto sheets with minimal waste. Multi-sheet support, efficiency reporting, and DXF export per sheet.",
    capabilities: [
      "Shelf-packing nesting algorithm",
      "Multi-sheet with efficiency stats",
      "DXF export with part labels",
    ],
    status: "live",
    accentFrom: "#6366f1",
    accentTo: "#8b5cf6",
  },
  {
    href: "/panels",
    icon: "⬡",
    name: "3D Panels",
    tagline: "Sculptural panel design",
    description:
      "Design parametric panel grids for furniture, walls, and installations. Diamond, hexagon, chevron, and brick patterns with live preview and DXF export.",
    capabilities: [
      "Diamond, hexagon, chevron, brick patterns",
      "Bevel inset & assembly tab generation",
      "Live preview — updates as you adjust",
    ],
    status: "beta",
    accentFrom: "#06b6d4",
    accentTo: "#3b82f6",
  },
  {
    href: "/alucobond",
    icon: "⬡",
    name: "Alucobond Facade",
    tagline: "3D cladding skin generator",
    description:
      "Place an Alucobond cladding skin on any rectangular building at a configurable offset. Panelize the skin with joint gaps and fold returns, then export each panel as a flat DXF blank ready for cutting.",
    capabilities: [
      "Offset skin from structure — configurable gap",
      "Horizontal, vertical, and brick panel patterns",
      "Per-panel flat DXF with fold lines + cut marks",
    ],
    status: "live",
    accentFrom: "#06b6d4",
    accentTo: "#7c3aed",
  },
  {
    href: "/folded-board",
    icon: "◈",
    name: "Folded Board",
    tagline: "Triangle fold geometry test",
    description:
      "Define a triangular Alucobond board with edge returns. See the flat-blank cut pattern with bend, cut, and relief layers — then preview the 3D folded result and export DXF.",
    capabilities: [
      "Equilateral, isosceles, and right triangle presets",
      "Bend lines, cut lines, corner relief cuts",
      "3D folded preview — 90° edge returns",
    ],
    status: "beta",
    accentFrom: "#f97316",
    accentTo: "#7c3aed",
  },
  {
    href: "/corner-test",
    icon: "⌐",
    name: "Corner Test",
    tagline: "Two-wall folded panel test",
    description:
      "Clad a 90° building corner with folded Alucobond panels. Verify that returns from Wall A and Wall B meet cleanly before scaling to a full facade.",
    capabilities: [
      "Two perpendicular walls with configurable dimensions",
      "Click any panel to inspect and export its flat-blank DXF",
      "Plus-shaped DXF with fold lines — same geometry as Folded Board",
    ],
    status: "beta",
    accentFrom: "#06b6d4",
    accentTo: "#10b981",
  },
  {
    href: "/editor",
    icon: "✎",
    name: "DXF Editor",
    tagline: "Geometry inspector & viewer",
    description:
      "Load DXF files and inspect every contour. Pan, zoom, toggle layer visibility, measure bounding boxes, and prepare geometry for export.",
    capabilities: [
      "Loads DXF LINE & LWPOLYLINE entities",
      "Pan, zoom, per-layer visibility",
      "Bounding box inspector per contour",
    ],
    status: "beta",
    accentFrom: "#f59e0b",
    accentTo: "#ef4444",
  },
];

const ROADMAP: Tool[] = [];

// ── Section label ─────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 700, letterSpacing: "0.08em",
      textTransform: "uppercase", color: "var(--text-subtle)", marginBottom: 16,
    }}>
      {children}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Dashboard() {
  return (
    <main style={{ padding: "48px 40px 80px", maxWidth: 1080, margin: "0 auto" }}>

      {/* ── Hero ── */}
      <FadeIn style={{ marginBottom: 52 }}>
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: "0.12em",
          textTransform: "uppercase", color: "var(--text-subtle)",
          display: "inline-block", marginBottom: 12,
        }}>
          CNC Fabrication Platform
        </span>

        <h1 style={{
          fontSize: 38, fontWeight: 800, color: "var(--text-primary)",
          letterSpacing: "-0.03em", margin: "0 0 14px", lineHeight: 1.15,
        }}>
          Industrial-grade tools{" "}
          <span style={{
            background: "linear-gradient(135deg, #a78bfa, #38bdf8)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}>
            for digital fabrication
          </span>
        </h1>

        <p style={{ fontSize: 16, color: "var(--text-muted)", margin: "0 0 24px", maxWidth: 560, lineHeight: 1.65 }}>
          Slice 3D models, vectorize images, nest parts onto sheets —
          and take your designs from screen to CNC, all in one platform.
        </p>

        {/* Stats + primary CTA row */}
        <div style={{ display: "flex", alignItems: "center", gap: 28, flexWrap: "wrap", marginBottom: 28 }}>
          {[
            { label: "Tools", value: "9",  color: "var(--text-primary)" },
            { label: "Live",  value: "5",  color: "#86efac" },
            { label: "Beta",  value: "4",  color: "#fde68a" },
          ].map((s) => (
            <div key={s.label} style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
              <span style={{ fontSize: 22, fontWeight: 700, color: s.color, letterSpacing: "-0.02em" }}>
                {s.value}
              </span>
              <span style={{ fontSize: 12, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                {s.label}
              </span>
            </div>
          ))}

          <div style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
            <Link
              href="/slicer"
              style={{
                display: "inline-flex", alignItems: "center", gap: 8,
                padding: "10px 20px", borderRadius: 10, fontSize: 13, fontWeight: 600,
                background: "linear-gradient(135deg, #7c3aed, #0ea5e9)",
                color: "#fff", textDecoration: "none",
                boxShadow: "0 0 20px rgba(124,58,237,0.35)",
              }}
            >
              ≡ Open Slicer →
            </Link>
            <Link
              href="/photo-to-dxf"
              style={{
                display: "inline-flex", alignItems: "center", gap: 8,
                padding: "10px 20px", borderRadius: 10, fontSize: 13, fontWeight: 600,
                background: "rgba(255,255,255,0.05)",
                border: "1px solid rgba(236,72,153,0.30)",
                color: "#f9a8d4", textDecoration: "none",
              }}
            >
              ⊙ Photo → DXF
            </Link>
          </div>
        </div>

        {/* Workflow strip */}
        <div style={{
          display: "flex", alignItems: "center",
          padding: "13px 20px",
          background: "rgba(255,255,255,0.03)",
          border: "1px solid var(--glass-border)",
          borderRadius: 12, overflowX: "auto",
        }}>
          {(["3D Model ◈", "Slice ≡", "Profiles ◫", "DXF ◇", "Nest ⊞", "Cut ✂"] as const).map((label, i, arr) => (
            <div key={i} style={{ display: "flex", alignItems: "center", flexShrink: 0 }}>
              <span style={{ fontSize: 12, color: "var(--text-subtle)", padding: "0 16px", letterSpacing: "0.02em" }}>
                {label}
              </span>
              {i < arr.length - 1 && (
                <div style={{ width: 20, height: 1, background: "rgba(255,255,255,0.10)" }} />
              )}
            </div>
          ))}
        </div>
      </FadeIn>

      {/* ── Available Now ── */}
      <FadeIn delay={0.10} style={{ marginBottom: 48 }}>
        <SectionLabel>Available Now</SectionLabel>
        <FadeInGroup style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
          gap: 16,
        }}>
          {AVAILABLE.map((tool) => (
            <FadeInItem key={tool.href}>
              <ToolCard tool={tool} />
            </FadeInItem>
          ))}
        </FadeInGroup>
      </FadeIn>

      {ROADMAP.length > 0 && (
        <FadeIn delay={0.18}>
          <SectionLabel>Roadmap</SectionLabel>
          <FadeInGroup style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12 }}>
            {ROADMAP.map((tool) => (
              <FadeInItem key={tool.href}>
                <ToolCard tool={tool} />
              </FadeInItem>
            ))}
          </FadeInGroup>
        </FadeIn>
      )}

    </main>
  );
}
