"use client";

import { useRef, useState, useCallback, useEffect, DragEvent, ChangeEvent } from "react";
import {
  tracePhoto, analyzePhoto, exportPhotoAsDXF,
  traceHalftone, exportHalftoneDXF,
  traceOneLine, exportOneLineDXF,
  generateAiPattern, exportAiPatternDXF,
  aiRecommend,
  TraceResult, TraceParams, AnalyzeResult, TraceMode,
  HalftoneParams, HalftoneResult, AiRecommendResult,
  OneLineParams, OneLineResult,
  AiPatternResult, PatternType, PatternStyle, PanelShape,
} from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const IMAGE_TYPE_LABELS: Record<string, string> = {
  line_art:   "Line Art",
  silhouette: "Silhouette",
  logo:       "Logo / Graphic",
  photo:      "Photo / Portrait",
};

const NODE_POSITIONS = [
  [18, 30], [72, 15], [45, 60], [85, 42], [30, 78],
  [60, 88], [12, 55], [90, 70], [50, 25], [25, 92],
  [78, 55], [40, 40], [65, 72], [15, 10], [55, 10],
];

type HalftonePlacementMode = "organic_density" | "hex_packing" | "flow_field";

const HALFTONE_PLACEMENT_LABELS: Record<HalftonePlacementMode, string> = {
  organic_density: "Organic Density",
  hex_packing: "Hex Packing",
  flow_field: "Flow Field",
};

// ── Shared primitives ─────────────────────────────────────────────────────────

function Spinner({ size = 14 }: { size?: number }) {
  return (
    <span style={{
      display: "inline-block", width: size, height: size, flexShrink: 0,
      border: `${size <= 14 ? 2 : 3}px solid rgba(255,255,255,0.18)`,
      borderTopColor: "#fff", borderRadius: "50%",
      animation: "spin 0.7s linear infinite",
    }} />
  );
}

function StepSection({ step, title, done, children }: {
  step: number; title: string; done?: boolean; children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", gap: 13, alignItems: "flex-start" }}>
      <div style={{
        width: 22, height: 22, borderRadius: "50%", flexShrink: 0, marginTop: 1,
        background: done
          ? "linear-gradient(135deg, rgba(34,197,94,0.7), rgba(16,163,74,0.7))"
          : "linear-gradient(135deg, rgba(236,72,153,0.55), rgba(168,85,247,0.55))",
        border: done ? "1px solid rgba(34,197,94,0.5)" : "1px solid rgba(236,72,153,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 10, fontWeight: 700, color: done ? "#bbf7d0" : "#fbcfe8",
      }}>
        {done ? "✓" : step}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 10, fontWeight: 700, color: "var(--text-subtle)",
          textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 12, paddingTop: 3,
        }}>
          {title}
        </div>
        {children}
      </div>
    </div>
  );
}

function StepConnector() {
  return (
    <div style={{ display: "flex", gap: 13 }}>
      <div style={{ width: 22, flexShrink: 0, display: "flex", justifyContent: "center" }}>
        <div style={{ width: 1, height: 14, background: "rgba(255,255,255,0.09)" }} />
      </div>
    </div>
  );
}

function SliderRow({ label, sub, hint, min, max, step, value, onChange, format }: {
  label: string; sub?: string; hint?: string;
  min: number; max: number; step: number;
  value: number; onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  const display = format ? format(value) : String(value);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{label}</span>
          {sub && <span style={{ fontSize: 10, color: "var(--text-subtle)", marginLeft: 6 }}>{sub}</span>}
        </div>
        <span style={{
          fontSize: 12, fontWeight: 600, color: "var(--text-primary)",
          fontFamily: "var(--font-geist-mono), monospace",
          background: "rgba(255,255,255,0.06)", padding: "2px 7px", borderRadius: 5,
        }}>
          {display}
        </span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        className="range-dark"
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
      {hint && <div style={{ fontSize: 10, color: "var(--text-subtle)", lineHeight: 1.4 }}>{hint}</div>}
    </div>
  );
}

function Toggle({ label, sub, value, onChange }: {
  label: string; sub?: string; value: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <div>
        <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{label}</div>
        {sub && <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 1 }}>{sub}</div>}
      </div>
      <button
        type="button" onClick={() => onChange(!value)} aria-pressed={value}
        style={{
          width: 44, height: 24, borderRadius: 9999, border: "none", cursor: "pointer",
          position: "relative", flexShrink: 0, transition: "background 0.2s",
          background: value ? "linear-gradient(135deg, #ec4899, #a855f7)" : "rgba(255,255,255,0.10)",
        }}
      >
        <span style={{
          position: "absolute", top: 2, width: 20, height: 20, borderRadius: "50%",
          background: "#fff", transition: "left 0.2s", boxShadow: "0 1px 4px rgba(0,0,0,0.4)",
          left: value ? 22 : 2,
        }} />
      </button>
    </div>
  );
}

function formatBytes(b: number) {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1048576).toFixed(2)} MB`;
}

// ── Mode selector ─────────────────────────────────────────────────────────────

function ModeCard({ mode, selected, onSelect, recommended }: {
  mode: "accurate" | "contour_art"; selected: boolean; onSelect: () => void; recommended?: boolean;
}) {
  const isArt  = mode === "contour_art";
  const accent  = isArt ? "#ec4899" : "#a855f7";
  const accentA = isArt ? "rgba(236,72,153," : "rgba(168,85,247,";
  return (
    <div onClick={onSelect} style={{
      flex: 1, padding: "11px 12px", borderRadius: 10, cursor: "pointer",
      position: "relative", userSelect: "none",
      border: selected ? `1px solid ${accentA}0.45)` : "1px solid rgba(255,255,255,0.08)",
      background: selected ? `${accentA}0.09)` : "rgba(255,255,255,0.02)",
      transition: "all 0.15s",
    }}>
      {recommended && (
        <div style={{
          position: "absolute", top: -8, right: 7,
          background: "linear-gradient(90deg, #ec4899, #a855f7)",
          borderRadius: 9999, padding: "2px 8px",
          fontSize: 9, fontWeight: 700, color: "#fff",
        }}>✦ Recommended</div>
      )}
      <div style={{ fontSize: 15, marginBottom: 4, lineHeight: 1 }}>{isArt ? "⊚" : "⊙"}</div>
      <div style={{ fontSize: 12, fontWeight: 700, color: selected ? accent : "var(--text-muted)", transition: "color 0.15s" }}>
        {isArt ? "Contour Art" : "Accurate Trace"}
      </div>
      <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 2, lineHeight: 1.4 }}>
        {isArt ? "Topographic bands" : "Canny edges · Precision"}
      </div>
    </div>
  );
}

function StrokeCard({ selected, onSelect, recommended }: {
  selected: boolean; onSelect: () => void; recommended?: boolean;
}) {
  return (
    <div onClick={onSelect} style={{
      padding: "11px 14px", borderRadius: 10, cursor: "pointer",
      position: "relative", userSelect: "none",
      border: selected ? "1px solid rgba(14,165,233,0.5)" : "1px solid rgba(255,255,255,0.08)",
      background: selected ? "rgba(14,165,233,0.09)" : "rgba(255,255,255,0.02)",
      transition: "all 0.15s",
      display: "flex", alignItems: "center", gap: 12,
    }}>
      {recommended && (
        <div style={{
          position: "absolute", top: -8, right: 7,
          background: "linear-gradient(90deg, #0ea5e9, #38bdf8)",
          borderRadius: 9999, padding: "2px 8px",
          fontSize: 9, fontWeight: 700, color: "#fff",
        }}>✦ Recommended</div>
      )}
      <div style={{ fontSize: 18, lineHeight: 1, flexShrink: 0 }}>✏</div>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: selected ? "#38bdf8" : "var(--text-muted)", transition: "color 0.15s" }}>
            High-Fidelity Stroke
          </span>
          <span style={{
            fontSize: 9, fontWeight: 700, color: "#38bdf8",
            background: "rgba(14,165,233,0.15)", border: "1px solid rgba(14,165,233,0.3)",
            padding: "1px 6px", borderRadius: 9999,
          }}>New</span>
        </div>
        <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 2 }}>
          Portraits · flowing ink · overlapping lines · maximum fidelity
        </div>
      </div>
    </div>
  );
}

function HalftoneCard({ selected, onSelect, recommended }: {
  selected: boolean; onSelect: () => void; recommended?: boolean;
}) {
  return (
    <div onClick={onSelect} style={{
      padding: "11px 14px", borderRadius: 10, cursor: "pointer",
      position: "relative", userSelect: "none",
      border: selected ? "1px solid rgba(245,158,11,0.5)" : "1px solid rgba(255,255,255,0.08)",
      background: selected ? "rgba(245,158,11,0.09)" : "rgba(255,255,255,0.02)",
      transition: "all 0.15s",
      display: "flex", alignItems: "center", gap: 12,
    }}>
      {recommended && (
        <div style={{
          position: "absolute", top: -8, right: 7,
          background: "linear-gradient(90deg, #f59e0b, #fbbf24)",
          borderRadius: 9999, padding: "2px 8px",
          fontSize: 9, fontWeight: 700, color: "#fff",
        }}>✦ Recommended</div>
      )}
      <div style={{ fontSize: 18, lineHeight: 1, flexShrink: 0 }}>◉</div>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: selected ? "#fbbf24" : "var(--text-muted)", transition: "color 0.15s" }}>
            Halftone / Dot
          </span>
          <span style={{
            fontSize: 9, fontWeight: 700, color: "#f59e0b",
            background: "rgba(245,158,11,0.15)", border: "1px solid rgba(245,158,11,0.3)",
            padding: "1px 6px", borderRadius: 9999,
          }}>New</span>
        </div>
        <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 2 }}>
          Drill dots · stipple · tonal portraits · CNC engraving
        </div>
      </div>
    </div>
  );
}

function OneLineCard({ selected, onSelect }: { selected: boolean; onSelect: () => void }) {
  return (
    <div onClick={onSelect} style={{
      padding: "11px 14px", borderRadius: 10, cursor: "pointer",
      position: "relative", userSelect: "none",
      border: selected ? "1px solid rgba(34,211,238,0.5)" : "1px solid rgba(255,255,255,0.08)",
      background: selected ? "rgba(34,211,238,0.08)" : "rgba(255,255,255,0.02)",
      transition: "all 0.15s",
      display: "flex", alignItems: "center", gap: 12,
    }}>
      <div style={{ fontSize: 18, lineHeight: 1, flexShrink: 0 }}>∾</div>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: selected ? "#22d3ee" : "var(--text-muted)", transition: "color 0.15s" }}>
            One-Line Drawing
          </span>
          <span style={{
            fontSize: 9, fontWeight: 700, color: "#22d3ee",
            background: "rgba(34,211,238,0.12)", border: "1px solid rgba(34,211,238,0.28)",
            padding: "1px 6px", borderRadius: 9999,
          }}>New</span>
        </div>
        <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 2 }}>
          Single continuous path · plotter-style CNC engraving · artistic line work
        </div>
      </div>
    </div>
  );
}

function AiPatternCard({ selected, onSelect }: { selected: boolean; onSelect: () => void }) {
  return (
    <div onClick={onSelect} style={{
      padding: "11px 14px", borderRadius: 10, cursor: "pointer",
      position: "relative", userSelect: "none",
      border: selected ? "1px solid rgba(245,158,11,0.5)" : "1px solid rgba(255,255,255,0.08)",
      background: selected ? "rgba(245,158,11,0.08)" : "rgba(255,255,255,0.02)",
      transition: "all 0.15s",
      display: "flex", alignItems: "center", gap: 12,
    }}>
      <div style={{ fontSize: 18, lineHeight: 1, flexShrink: 0 }}>◈</div>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: selected ? "#fbbf24" : "var(--text-muted)", transition: "color 0.15s" }}>
            AI Pattern Maker
          </span>
          <span style={{
            fontSize: 9, fontWeight: 700, color: "#f59e0b",
            background: "rgba(245,158,11,0.15)", border: "1px solid rgba(245,158,11,0.3)",
            padding: "1px 6px", borderRadius: 9999,
          }}>New</span>
        </div>
        <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 2 }}>
          Photo → interpreted decorative pattern → CNC-ready DXF
        </div>
      </div>
    </div>
  );
}

// ── One-line SVG preview (animated draw) ──────────────────────────────────────

function OneLineSVG({ result, showJumps }: { result: OneLineResult; showJumps: boolean }) {
  const { path, image_width: w, image_height: h, jump_indices } = result;
  const realRef = useRef<SVGPathElement>(null);

  // Split flat path into real-segment subpaths and jump connector subpaths.
  const jumpSet = new Set(jump_indices);
  let realD = "", jumpD = "", cur = "";
  for (let i = 0; i < path.length; i++) {
    const [r, c] = path[i];
    if (i === 0) { cur = `M${c.toFixed(1)},${r.toFixed(1)}`; continue; }
    const [pr, pc] = path[i - 1];
    if (jumpSet.has(i - 1)) {
      // Segment i-1 → i is a jump connector
      if (cur) { realD += (realD ? " " : "") + cur; cur = ""; }
      jumpD += (jumpD ? " " : "") + `M${pc.toFixed(1)},${pr.toFixed(1)} L${c.toFixed(1)},${r.toFixed(1)}`;
      cur = `M${c.toFixed(1)},${r.toFixed(1)}`;
    } else {
      cur += ` L${c.toFixed(1)},${r.toFixed(1)}`;
    }
  }
  if (cur) realD += (realD ? " " : "") + cur;

  // Animate real path on mount / new result
  useEffect(() => {
    const el = realRef.current;
    if (!el || !realD) return;
    const len = el.getTotalLength();
    el.style.strokeDasharray = String(len);
    el.style.strokeDashoffset = String(len);
    el.style.transition = "none";
    void el.getBoundingClientRect();
    const duration = Math.min(6, Math.max(1.5, len / 2000));
    el.style.transition = `stroke-dashoffset ${duration}s linear`;
    el.style.strokeDashoffset = "0";
  }, [realD]);

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      style={{ width: "100%", height: "auto", display: "block", borderRadius: 10 }}
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect width={w} height={h} fill="#06060f" />
      <defs>
        <pattern id="olgrid" width="32" height="32" patternUnits="userSpaceOnUse">
          <path d="M 32 0 L 0 0 0 32" fill="none" stroke="rgba(255,255,255,0.025)" strokeWidth="0.5" />
        </pattern>
      </defs>
      <rect width={w} height={h} fill="url(#olgrid)" />
      {/* Jump connectors — dashed orange travel lines */}
      {showJumps && jumpD && (
        <path
          d={jumpD}
          fill="none"
          stroke="rgba(251,146,60,0.50)"
          strokeWidth={1}
          strokeLinecap="round"
          strokeDasharray="3,7"
        />
      )}
      {/* Real drawing path — animated */}
      {realD && (
        <path
          ref={realRef}
          d={realD}
          fill="none"
          stroke="#22d3ee"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity={0.92}
        />
      )}
    </svg>
  );
}

// ── Halftone SVG preview ──────────────────────────────────────────────────────

function HalftoneSVG({ halftoneResult, showHeatmap = false }: { halftoneResult: HalftoneResult; showHeatmap?: boolean }) {
  const { circles, image_width: w, image_height: h } = halftoneResult;
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      style={{ width: "100%", height: "auto", borderRadius: 10, display: "block" }}
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect width={w} height={h} fill="#d6d0c2" />
      <rect width={w} height={h} fill="rgba(38,32,24,0.10)" />
      {showHeatmap && halftoneResult.density_heatmap && (
        <image href={halftoneResult.density_heatmap} width={w} height={h} opacity={0.42} preserveAspectRatio="none" />
      )}
      {circles.map(([row, col, radius], i) => (
        <circle key={i} cx={col} cy={row} r={Math.max(0.5, radius)} fill="#090806" opacity={0.92} />
      ))}
    </svg>
  );
}

// ── Scan animation ────────────────────────────────────────────────────────────

function ScanAnimation({ imageUrl, mode }: { imageUrl: string | null; mode: TraceMode }) {
  const isStroke    = mode === "stroke";
  const isArt       = mode === "contour_art";
  const isHalftone  = mode === "halftone";
  const isOneLine   = mode === "one_line";
  const isAiPattern = mode === "ai_pattern";
  const scanColor   = isStroke ? "14,165,233" : isOneLine ? "34,211,238" : isHalftone || isAiPattern ? "245,158,11" : "236,72,153";
  const nodeColorA  = isStroke ? "#38bdf8" : isOneLine ? "#22d3ee" : isHalftone ? "#fbbf24" : "#ec4899";
  const nodeColorB  = isStroke ? "#0ea5e9" : isOneLine ? "#06b6d4" : isHalftone ? "#f59e0b" : "#a855f7";

  const statusText = isStroke ? "Reconstructing stroke paths…"
    : isOneLine ? "Building one-line path…"
    : isHalftone ? "Building halftone dot grid…"
    : isArt ? "Mapping contour levels…"
    : "Detecting edges…";
  const subText = isStroke ? "bilateral denoise · Sauvola binarize · crossing disambiguation · global assembly"
    : isOneLine ? "skeletonize · chain tracing · greedy nearest-neighbor tour · RDP simplify"
    : isHalftone ? "brightness sampling · radius mapping · circle generation"
    : isArt ? "iso-contours · RDP simplification"
    : "Canny · dilation · RDP simplification";

  return (
    <div style={{ position: "relative", borderRadius: 12, overflow: "hidden", background: "#06060f", minHeight: 340 }}>
      {imageUrl && (
        <img src={imageUrl} alt="" style={{ width: "100%", display: "block", opacity: 0.07, filter: "grayscale(1) contrast(1.3)" }} />
      )}
      <div style={{
        position: "absolute", inset: 0,
        backgroundImage: `radial-gradient(circle, rgba(${scanColor},0.18) 1px, transparent 1px)`,
        backgroundSize: "26px 26px",
      }} />
      <div style={{
        position: "absolute", left: 0, right: 0, height: "9%", top: 0,
        background: `linear-gradient(180deg, transparent, rgba(${scanColor},0.55) 50%, transparent)`,
        animation: "scanDown 2.1s linear infinite",
        boxShadow: `0 0 32px rgba(${scanColor},0.6), 0 0 80px rgba(${scanColor},0.15)`,
      }} />
      {NODE_POSITIONS.map(([top, left], i) => (
        <div key={i} style={{
          position: "absolute", top: `${top}%`, left: `${left}%`,
          width: 5, height: 5, borderRadius: "50%",
          background: i % 2 === 0 ? nodeColorA : nodeColorB,
          boxShadow: `0 0 6px ${i % 2 === 0 ? nodeColorA : nodeColorB}`,
          animation: `nodeFlicker ${1.2 + (i * 0.17) % 1.3}s ease-in-out infinite`,
          animationDelay: `${(i * 0.23) % 1.1}s`,
        }} />
      ))}
      <div style={{
        position: "absolute", bottom: 20, left: 0, right: 0,
        display: "flex", flexDirection: "column", alignItems: "center", gap: 8,
      }}>
        <div style={{
          background: "rgba(6,6,15,0.80)", backdropFilter: "blur(8px)",
          border: `1px solid rgba(${scanColor},0.22)`,
          borderRadius: 9, padding: "8px 20px",
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <Spinner size={11} />
          <span style={{ fontSize: 12, color: (isStroke || isOneLine) ? "rgba(186,230,253,0.95)" : "rgba(249,168,212,0.95)", letterSpacing: "0.05em" }}>
            {statusText}
          </span>
        </div>
        <div style={{ fontSize: 10, color: "rgba(255,255,255,0.15)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
          {subText}
        </div>
      </div>
    </div>
  );
}

// ── Idle illustration ─────────────────────────────────────────────────────────

function PhotoIllustration() {
  return (
    <svg viewBox="0 0 220 170" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ width: 180, opacity: 0.65 }}>
      <rect x="10" y="18" width="88" height="70" rx="7" fill="rgba(236,72,153,0.07)" stroke="rgba(236,72,153,0.38)" strokeWidth="1.5" />
      <ellipse cx="54" cy="40" rx="11" ry="11" fill="rgba(236,72,153,0.14)" stroke="rgba(236,72,153,0.42)" strokeWidth="1.2" />
      <path d="M30 76 Q54 60 78 76" stroke="rgba(236,72,153,0.42)" strokeWidth="1.2" fill="none" />
      <line x1="108" y1="52" x2="130" y2="52" stroke="rgba(168,85,247,0.6)" strokeWidth="1.5" />
      <polygon points="130,48 138,52 130,56" fill="rgba(168,85,247,0.6)" />
      <rect x="140" y="18" width="70" height="70" rx="5" fill="rgba(168,85,247,0.06)" stroke="rgba(168,85,247,0.38)" strokeWidth="1.5" />
      <ellipse cx="175" cy="38" rx="9" ry="9" fill="none" stroke="rgba(168,85,247,0.7)" strokeWidth="1.4" strokeDasharray="3,2" />
      <path d="M148 72 Q175 56 202 72" fill="none" stroke="rgba(168,85,247,0.7)" strokeWidth="1.4" strokeDasharray="3,2" />
      <circle cx="148" cy="72" r="2.5" fill="#a855f7" />
      <circle cx="202" cy="72" r="2.5" fill="#a855f7" />
      <circle cx="175" cy="29" r="2.5" fill="#ec4899" />
      {["Upload", "Mode", "Tune", "Trace", "Export"].map((s, i) => (
        <g key={s}>
          <rect x={10 + i * 42} y={104} width={36} height={14} rx="3" fill="rgba(255,255,255,0.04)" stroke="rgba(255,255,255,0.08)" strokeWidth="0.8" />
          <text x={28 + i * 42} y={114} textAnchor="middle" fill="rgba(255,255,255,0.22)" fontSize="6" fontFamily="system-ui">{s}</text>
          {i < 4 && <line x1={46 + i * 42} y1={111} x2={52 + i * 42} y2={111} stroke="rgba(255,255,255,0.10)" strokeWidth="0.8" />}
        </g>
      ))}
    </svg>
  );
}

// ── Vector contour preview ────────────────────────────────────────────────────

const ART_COLORS   = ["#ef4444","#f97316","#eab308","#22c55e","#06b6d4","#6366f1","#ec4899","#a855f7"];
const TRACE_COLORS = ["#ec4899","#a855f7","#7dd3fc"];

function ContourSVG({ result, mode }: { result: TraceResult; mode: TraceMode }) {
  const { contours, image_width: w, image_height: h } = result;
  const isArt    = mode === "contour_art";
  const isStroke = mode === "stroke";

  // For stroke mode: single cyan color, opacity encodes relative length
  const maxLen = isStroke ? Math.max(1, ...contours.map((c) => c.length)) : 1;

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      style={{ width: "100%", height: "auto", borderRadius: 10, display: "block" }}
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect width={w} height={h} fill="#06060f" />
      <defs>
        <pattern id="vgrid" width="32" height="32" patternUnits="userSpaceOnUse">
          <path d="M 32 0 L 0 0 0 32" fill="none" stroke="rgba(255,255,255,0.03)" strokeWidth="0.5" />
        </pattern>
      </defs>
      <rect width={w} height={h} fill="url(#vgrid)" />
      {contours.map((contour, i) => {
        const pts = contour.map(([r, c]) => `${c.toFixed(1)},${r.toFixed(1)}`).join(" ");
        const color   = isStroke ? "#38bdf8"
          : isArt ? ART_COLORS[i % ART_COLORS.length]
          : TRACE_COLORS[i % TRACE_COLORS.length];
        const opacity = isStroke ? 0.35 + (contour.length / maxLen) * 0.65
          : isArt ? 0.65 : 0.82;
        const sw      = isStroke ? 1.8 : isArt ? 1.0 : 1.5;
        return (
          <polyline
            key={i} points={pts} fill="none" stroke={color}
            strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"
            opacity={opacity}
          />
        );
      })}
    </svg>
  );
}

// ── Stat pill ─────────────────────────────────────────────────────────────────

function Stat({ label, value, mode }: { label: string; value: string; mode: TraceMode }) {
  const gradient = mode === "stroke"
    ? "linear-gradient(135deg, #0ea5e9, #38bdf8)"
    : mode === "halftone" || mode === "ai_pattern"
    ? "linear-gradient(135deg, #f59e0b, #fbbf24)"
    : mode === "one_line"
    ? "linear-gradient(135deg, #06b6d4, #22d3ee)"
    : "linear-gradient(135deg, #ec4899, #a855f7)";
  return (
    <div className="glass-sm" style={{ padding: "9px 14px", textAlign: "center", flex: 1 }}>
      <div style={{
        fontSize: 17, fontWeight: 700, lineHeight: 1.2,
        backgroundImage: gradient,
        WebkitBackgroundClip: "text", color: "transparent",
      }}>{value}</div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
    </div>
  );
}

// ── Analysis card ─────────────────────────────────────────────────────────────

function AnalysisCard({ analysis, analyzing, traceMode, onApply }: {
  analysis: AnalyzeResult | null; analyzing: boolean;
  traceMode: TraceMode; onApply: (m: TraceMode) => void;
}) {
  if (!analyzing && !analysis) return null;
  return (
    <div className="glass-sm" style={{ padding: "14px 16px" }}>
      {analyzing ? (
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Spinner size={12} />
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Analysing image…</span>
        </div>
      ) : analysis && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
            <span className={`chip ${analysis.image_type === "photo" ? "chip-violet" : analysis.image_type === "line_art" ? "chip-sky" : "chip-sky"}`}>
              {IMAGE_TYPE_LABELS[analysis.image_type] ?? analysis.image_type}
            </span>
            <span style={{ fontSize: 11, color: "var(--text-muted)", flex: 1, lineHeight: 1.4 }}>
              {analysis.description}
            </span>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <div style={{
              width: 2, minHeight: 36, flexShrink: 0, borderRadius: 9999, alignSelf: "stretch",
              background: analysis.recommended_mode === "stroke"
                ? "rgba(14,165,233,0.5)"
                : analysis.recommended_mode === "halftone"
                  ? "rgba(245,158,11,0.5)"
                  : analysis.recommended_mode === "contour_art"
                    ? "rgba(236,72,153,0.5)" : "rgba(168,85,247,0.5)",
            }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)", marginBottom: 4 }}>
                {analysis.recommended_mode === "stroke" ? "✏ Stroke Trace"
                  : analysis.recommended_mode === "halftone" ? "◉ Halftone / Dot"
                  : analysis.recommended_mode === "contour_art" ? "⊚ Contour Art"
                  : "⊙ Accurate Trace"} recommended
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>
                {analysis.recommendation}
              </div>
              {traceMode !== analysis.recommended_mode && (
                <button
                  className="btn-ghost"
                  onClick={() => onApply(analysis.recommended_mode as TraceMode)}
                  style={{ marginTop: 8, padding: "4px 10px", fontSize: 11 }}
                >
                  Apply recommendation
                </button>
              )}
            </div>
          </div>
          {(traceMode === "contour_art" || traceMode === "stroke") && (
            <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid rgba(255,255,255,0.05)", fontSize: 11, color: "var(--text-subtle)", lineHeight: 1.5 }}>
              ✦ {analysis.artistic_description}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── AI Copilot card ───────────────────────────────────────────────────────────

const CONFIDENCE_COLOR = (c: number) =>
  c >= 0.8 ? "#86efac" : c >= 0.55 ? "#fde68a" : "#fca5a5";

function AiCopilotCard({ ai, aiLoading, traceMode, onApply }: {
  ai: AiRecommendResult | null;
  aiLoading: boolean;
  traceMode: TraceMode;
  onApply: (m: TraceMode) => void;
}) {
  if (!aiLoading && (!ai || ai.source === "none")) return null;
  return (
    <div className="glass-sm" style={{
      padding: "14px 16px", marginTop: 8,
      border: "1px solid rgba(124,58,237,0.22)",
      background: "rgba(124,58,237,0.05)",
    }}>
      {aiLoading ? (
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Spinner size={12} />
          <span style={{ fontSize: 12, color: "#c4b5fd" }}>◆ AI Copilot analyzing…</span>
        </div>
      ) : ai && ai.source === "ai" && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
            <span style={{
              fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
              background: "rgba(124,58,237,0.18)", color: "#c4b5fd",
              border: "1px solid rgba(124,58,237,0.30)",
              textTransform: "uppercase", letterSpacing: "0.06em",
            }}>◆ AI Copilot</span>
            {ai.confidence != null && (
              <span style={{ fontSize: 10, color: CONFIDENCE_COLOR(ai.confidence) }}>
                {Math.round(ai.confidence * 100)}% confidence
              </span>
            )}
          </div>

          {ai.reasoning && (
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 8, lineHeight: 1.5 }}>
              {ai.reasoning}
            </div>
          )}

          {ai.recommended_mode && (
            <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: ai.explanation ? 8 : 0 }}>
              <div style={{
                width: 2, minHeight: 30, flexShrink: 0, borderRadius: 9999, alignSelf: "stretch",
                background: "rgba(124,58,237,0.6)",
              }} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)", marginBottom: 3 }}>
                  {ai.recommended_mode === "stroke" ? "✏ Stroke Trace"
                    : ai.recommended_mode === "halftone" ? "◉ Halftone / Dot"
                    : ai.recommended_mode === "contour_art" ? "⊚ Contour Art"
                    : "⊙ Accurate Trace"} suggested by AI
                </div>
                {ai.explanation && (
                  <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>
                    {ai.explanation}
                  </div>
                )}
                {traceMode !== ai.recommended_mode && (
                  <button
                    className="btn-ghost"
                    onClick={() => onApply(ai.recommended_mode as TraceMode)}
                    style={{ marginTop: 8, padding: "4px 10px", fontSize: 11,
                      borderColor: "rgba(124,58,237,0.35)", color: "#c4b5fd" }}
                  >
                    Apply AI recommendation
                  </button>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Mode tips ─────────────────────────────────────────────────────────────────

const MODE_TIPS: Record<TraceMode, string[]> = {
  ai_pattern: [
    "Contour Relief: topographic iso-lines ideal for wall art and engraving",
    "Groove: brightness-driven scan-line grooves — great for Alucobond and wood engraving",
    "Perforation: brightness → hole size grid — ready for CNC drilling",
    "Facade: geometric tile pattern (hex/triangle/diamond/wave) for architectural panels",
    "Style controls how cells are selected: clean=binary threshold, organic=variable size",
  ],
  one_line: [
    "Creates a single continuous path — no pen lifts, like a plotter drawing",
    "Lower Detail (1–3) for bold simplified silhouettes",
    "Higher Detail (8–10) to trace fine texture and structure",
    "Higher Jump Penalty keeps the path flowing forward, reducing backtracking",
    "Enable Invert for light drawings on a dark background",
  ],
  stroke: [
    "Best for sketches, portraits, and pen/ink line art",
    "Enable Invert for light strokes on dark background",
    "Raise Sensitivity to capture faint or thin strokes",
    "Lower Min Path to keep short connecting curves",
    "Higher Simplify gives smoother, fewer-point paths",
  ],
  contour_art: [
    "Works beautifully on portraits and landscape photos",
    "More levels = finer topographic detail",
    "Enable Invert to flip highlight / shadow layers",
    "Raise Min Path to remove tiny disconnected curves",
  ],
  accurate: [
    "Best for logos, silhouettes, and bold line art",
    "Enable Invert for dark lines on white background",
    "Lower Sensitivity = only the strongest outlines",
    "Raise Min Path to remove noise dots",
  ],
  halftone: [
    "Works on portraits, gradients, and tonal images",
    "Higher Density = more, smaller dots for fine detail",
    "Max Circle controls the darkest-area dot size",
    "Enable Invert to flip dark/light (holes vs pits)",
    "Contrast boost sharpens the brightness→size mapping",
  ],
};

// ── Main page ─────────────────────────────────────────────────────────────────

type AppState = "idle" | "tracing" | "done" | "error";

export default function PhotoToDXFPage() {
  const [file,     setFile]     = useState<File | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const [traceMode, setTraceMode] = useState<TraceMode>("accurate");
  const [analysis,    setAnalysis]    = useState<AnalyzeResult | null>(null);
  const [analyzing,   setAnalyzing]   = useState(false);
  const [aiAnalysis,  setAiAnalysis]  = useState<AiRecommendResult | null>(null);
  const [aiLoading,   setAiLoading]   = useState(false);

  const [blur,        setBlur]        = useState(1.5);
  const [invert,      setInvert]      = useState(false);
  const [sensitivity, setSensitivity] = useState(5);
  const [minLength,   setMinLength]   = useState(15);
  const [simplify,    setSimplify]    = useState(2.5);

  const [appState, setAppState] = useState<AppState>("idle");
  const [result,   setResult]   = useState<TraceResult | null>(null);
  const [errorMsg, setErrorMsg] = useState("");

  // ── Halftone state ──────────────────────────────────────────────────────────
  const [halftoneResult,   setHalftoneResult]   = useState<HalftoneResult | null>(null);
  const [halftoneDensity,  setHalftoneDensity]  = useState(60);
  const [halftoneMinR,     setHalftoneMinR]     = useState(0.5);
  const [halftoneMaxR,     setHalftoneMaxR]     = useState(8);
  const [halftoneContrast, setHalftoneContrast] = useState(1.2);
  const [halftonePlacement, setHalftonePlacement] = useState<HalftonePlacementMode>("organic_density");
  const [halftoneRandomness, setHalftoneRandomness] = useState(0.55);
  const [halftoneDensitySensitivity, setHalftoneDensitySensitivity] = useState(1.25);
  const [showHalftoneHeatmap, setShowHalftoneHeatmap] = useState(false);

  // ── One-line state ──────────────────────────────────────────────────────────
  const [oneLineResult,  setOneLineResult]  = useState<OneLineResult | null>(null);
  const [olDetail,       setOlDetail]       = useState(5.0);
  const [olSimplify,     setOlSimplify]     = useState(3.0);
  const [olJumpPenalty,  setOlJumpPenalty]  = useState(0.5);
  const [olPreviewMode,  setOlPreviewMode]  = useState<"original" | "enhanced" | "skeleton" | "oneline">("oneline");
  const [showJumps,      setShowJumps]      = useState(true);

  // ── AI Pattern state ────────────────────────────────────────────────────────
  const [aiPatternResult, setAiPatternResult] = useState<AiPatternResult | null>(null);
  const [apPatternType,   setApPatternType]   = useState<PatternType>("contour_relief");
  const [apStyle,         setApStyle]         = useState<PatternStyle>("clean");
  const [apDetail,        setApDetail]        = useState(5.0);
  const [apMinSpacing,    setApMinSpacing]    = useState(8.0);
  const [apMinHoleSize,   setApMinHoleSize]   = useState(4.0);
  const [apMaxElements,   setApMaxElements]   = useState(1500);
  const [apPanelShape,    setApPanelShape]    = useState<PanelShape>("hexagon");
  const [apPreviewMode,   setApPreviewMode]   = useState<"original" | "analysis" | "pattern">("pattern");

  // ── AI prompt state ─────────────────────────────────────────────────────────
  const [prompt, setPrompt] = useState("");
  const promptTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [scale,         setScale]         = useState("1.0");
  const [exportBusy,    setExportBusy]    = useState(false);
  const [exportSuccess, setExportSuccess] = useState(false);

  const [previewMode, setPreviewMode] = useState<"original" | "cleaned" | "edges" | "binary" | "segments" | "merged" | "vector">("vector");

  useEffect(() => () => { if (imageUrl) URL.revokeObjectURL(imageUrl); }, [imageUrl]);

  // ── File handling ──────────────────────────────────────────────────────────
  const onDragOver  = useCallback((e: DragEvent) => { e.preventDefault(); setDragging(true); }, []);
  const onDragLeave = useCallback(() => setDragging(false), []);
  const onDrop      = useCallback((e: DragEvent) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files[0]; if (f) acceptFile(f);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; if (f) acceptFile(f);
  };

  function fireAiRecommend(a: AnalyzeResult, userPrompt: string) {
    setAiAnalysis(null); setAiLoading(true);
    aiRecommend(a.image_type, a.edge_density, a.contrast, userPrompt)
      .then(setAiAnalysis)
      .catch(() => setAiAnalysis({ source: "none" }))
      .finally(() => setAiLoading(false));
  }

  async function acceptFile(f: File) {
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    setFile(f); setImageUrl(URL.createObjectURL(f));
    setResult(null); setHalftoneResult(null); setOneLineResult(null); setErrorMsg(""); setAppState("idle");
    setAnalysis(null); setAiAnalysis(null); setAiLoading(false);

    setAnalyzing(true);
    try {
      const a = await analyzePhoto(f, prompt);
      setAnalysis(a);
      setTraceMode(a.recommended_mode as TraceMode);
      if (a.param_hints) {
        if (a.param_hints.sensitivity != null) setSensitivity(a.param_hints.sensitivity);
        if (a.param_hints.simplify    != null) setSimplify(a.param_hints.simplify);
        if (a.param_hints.min_length  != null) setMinLength(a.param_hints.min_length);
      }
      fireAiRecommend(a, prompt);
    } catch { /* non-critical */ } finally {
      setAnalyzing(false);
    }
  }

  function handlePromptChange(text: string) {
    setPrompt(text);
    if (!file) return;
    if (promptTimerRef.current) clearTimeout(promptTimerRef.current);
    promptTimerRef.current = setTimeout(async () => {
      setAnalyzing(true);
      try {
        const a = await analyzePhoto(file, text);
        setAnalysis(a);
        setTraceMode(a.recommended_mode as TraceMode);
        if (a.param_hints) {
          if (a.param_hints.sensitivity != null) setSensitivity(a.param_hints.sensitivity);
          if (a.param_hints.simplify    != null) setSimplify(a.param_hints.simplify);
          if (a.param_hints.min_length  != null) setMinLength(a.param_hints.min_length);
        }
        fireAiRecommend(a, text);
      } catch { /* non-critical */ } finally {
        setAnalyzing(false);
      }
    }, 650);
  }

  function selectMode(m: TraceMode) {
    setTraceMode(m);
    if (result || halftoneResult || oneLineResult || aiPatternResult) { setResult(null); setHalftoneResult(null); setOneLineResult(null); setAiPatternResult(null); setAppState("idle"); }
  }

  // ── Trace ──────────────────────────────────────────────────────────────────
  async function handleTrace() {
    if (!file) return;
    setAppState("tracing"); setResult(null); setHalftoneResult(null); setOneLineResult(null); setAiPatternResult(null); setErrorMsg("");

    if (traceMode === "ai_pattern") {
      try {
        const r = await generateAiPattern(
          file,
          { pattern_type: apPatternType, style: apStyle, detail: apDetail,
            min_spacing: apMinSpacing, min_hole_size: apMinHoleSize,
            max_elements: apMaxElements, panel_shape: apPanelShape },
          blur, invert, parseFloat(scale) || 1.0,
        );
        setAiPatternResult(r); setAppState("done"); setApPreviewMode("pattern");
      } catch (err: unknown) {
        setErrorMsg(err instanceof Error ? err.message : String(err));
        setAppState("error");
      }
      return;
    }

    if (traceMode === "one_line") {
      const params: OneLineParams = { detail: olDetail, simplify: olSimplify, jump_penalty: olJumpPenalty, blur, invert };
      try {
        const r = await traceOneLine(file, params);
        setOneLineResult(r); setAppState("done"); setOlPreviewMode("oneline");
      } catch (err: unknown) {
        setErrorMsg(err instanceof Error ? err.message : String(err));
        setAppState("error");
      }
      return;
    }

    if (traceMode === "halftone") {
      const params: HalftoneParams = {
        density: halftoneDensity, min_radius: halftoneMinR, max_radius: halftoneMaxR,
        contrast: halftoneContrast, invert,
        placement_mode: halftonePlacement,
        randomness: halftoneRandomness,
        density_sensitivity: halftoneDensitySensitivity,
      };
      try {
        const r = await traceHalftone(file, params);
        setHalftoneResult(r); setAppState("done");
      } catch (err: unknown) {
        setErrorMsg(err instanceof Error ? err.message : String(err));
        setAppState("error");
      }
      return;
    }

    const params: TraceParams = { mode: traceMode, blur, sensitivity, simplify, min_length: minLength, invert };
    try {
      const r = await tracePhoto(file, params);
      setResult(r); setAppState("done"); setPreviewMode("vector");
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setAppState("error");
    }
  }

  // ── Export ─────────────────────────────────────────────────────────────────
  async function handleExport() {
    setExportBusy(true); setExportSuccess(false);
    try {
      if (traceMode === "ai_pattern" && aiPatternResult) {
        await exportAiPatternDXF(aiPatternResult, parseFloat(scale) || 1.0, "pattern.dxf");
      } else if (traceMode === "halftone" && halftoneResult) {
        await exportHalftoneDXF(
          halftoneResult.circles, halftoneResult.image_width, halftoneResult.image_height,
          parseFloat(scale) || 1.0, "halftone.dxf",
        );
      } else if (traceMode === "one_line" && oneLineResult) {
        await exportOneLineDXF(
          oneLineResult.path, oneLineResult.image_width, oneLineResult.image_height,
          parseFloat(scale) || 1.0, "one-line.dxf",
        );
      } else if (result) {
        await exportPhotoAsDXF(result.contours, result.image_width, result.image_height, parseFloat(scale) || 1.0);
      }
      setExportSuccess(true);
      setTimeout(() => setExportSuccess(false), 2500);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setExportBusy(false);
    }
  }

  function resetToIdle() { setResult(null); setHalftoneResult(null); setOneLineResult(null); setAiPatternResult(null); setAppState("idle"); setExportSuccess(false); }

  const activeImgW = result ? result.image_width : halftoneResult ? halftoneResult.image_width : oneLineResult ? oneLineResult.image_width : aiPatternResult ? aiPatternResult.image_width : null;
  const activeImgH = result ? result.image_height : halftoneResult ? halftoneResult.image_height : oneLineResult ? oneLineResult.image_height : aiPatternResult ? aiPatternResult.image_height : null;
  const dxfW = activeImgW ? (activeImgW * (parseFloat(scale) || 1)).toFixed(0) : "—";
  const dxfH = activeImgH ? (activeImgH * (parseFloat(scale) || 1)).toFixed(0) : "—";

  // Dynamic labels
  const step3Title = traceMode === "accurate" ? "Detect Edges"
    : traceMode === "contour_art" ? "Configure Levels"
    : traceMode === "halftone" ? "Dot Placement"
    : traceMode === "one_line" ? "Path Settings"
    : traceMode === "ai_pattern" ? "Pattern Design"
    : "Threshold & Clean";

  const edgesTabLabel = traceMode === "stroke" ? "Skeleton"
    : traceMode === "contour_art" ? "Levels" : "Edges";

  const edgesTabHint = traceMode === "stroke"
    ? "Skeletonized centerlines — each drawn stroke reduced to a 1-pixel wide spine."
    : traceMode === "contour_art"
    ? "Posterized brightness bands — each band becomes one contour level."
    : "Raw Canny edge map. Adjust Sensitivity if edges look too sparse or too noisy.";

  const traceButtonLabel = traceMode === "stroke" ? "✏  Trace High-Fidelity"
    : traceMode === "halftone" ? "◉  Generate Dots"
    : traceMode === "contour_art" ? "⊚  Trace Contour Art"
    : traceMode === "one_line" ? "∾  Draw One Line"
    : traceMode === "ai_pattern" ? "◈  Generate Pattern"
    : "⊙  Trace Accurately";

  const modeChipLabel = traceMode === "stroke" ? "✏ Hi-Fi Stroke"
    : traceMode === "halftone" ? "◉ Halftone"
    : traceMode === "one_line" ? "∾ One-Line"
    : traceMode === "contour_art" ? "⊚ Contour Art"
    : traceMode === "ai_pattern" ? "◈ AI Pattern"
    : "⊙ Accurate";

  const pageSubtitle = traceMode === "stroke"
    ? "Skeleton centerlines · junction merge · DXF export"
    : traceMode === "halftone"
    ? "Dot grid · brightness mapping · DXF circles export"
    : traceMode === "contour_art"
    ? "Iso-contour topographic art · RDP simplification · DXF export"
    : traceMode === "one_line"
    ? "Single continuous path · plotter-style · DXF export"
    : traceMode === "ai_pattern"
    ? "Image analysis · decorative pattern generation · CNC-ready DXF"
    : "Canny edge detection · RDP simplification · DXF export";

  const hasDoneResult = appState === "done" && (result !== null || halftoneResult !== null || oneLineResult !== null || aiPatternResult !== null);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>

      <div style={{ padding: "28px 32px 0", display: "flex", alignItems: "baseline", gap: 14, flexShrink: 0, flexWrap: "wrap" }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.02em", margin: 0 }}>
          Photo → DXF
        </h1>
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{pageSubtitle}</span>
        <span className="chip chip-violet" style={{ marginLeft: "auto" }}>Beta</span>
      </div>

      <div className="two-col" style={{ flex: 1, display: "flex", gap: 20, padding: "20px 32px 40px", alignItems: "flex-start" }}>

        {/* ── LEFT PANEL ── */}
        <div className="glass" style={{ width: 360, flexShrink: 0, padding: "22px 22px", display: "flex", flexDirection: "column", gap: 0 }}>

          {/* ── Mode Selector ── */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 10 }}>
              Tracing Mode
            </div>
            {/* Row 1: Accurate + Contour Art */}
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <ModeCard
                mode="accurate" selected={traceMode === "accurate"}
                onSelect={() => selectMode("accurate")}
                recommended={analysis?.recommended_mode === "accurate"}
              />
              <ModeCard
                mode="contour_art" selected={traceMode === "contour_art"}
                onSelect={() => selectMode("contour_art")}
                recommended={analysis?.recommended_mode === "contour_art"}
              />
            </div>
            {/* Row 2: Stroke Trace — full width */}
            <StrokeCard
              selected={traceMode === "stroke"}
              onSelect={() => selectMode("stroke")}
              recommended={analysis?.recommended_mode === "stroke"}
            />
            {/* Row 3: Halftone — full width */}
            <div style={{ marginTop: 8 }}>
              <HalftoneCard
                selected={traceMode === "halftone"}
                onSelect={() => selectMode("halftone")}
                recommended={analysis?.recommended_mode === "halftone"}
              />
            </div>
            {/* Row 4: One-Line Drawing — full width */}
            <div style={{ marginTop: 8 }}>
              <OneLineCard
                selected={traceMode === "one_line"}
                onSelect={() => selectMode("one_line")}
              />
            </div>
            {/* Row 5: AI Pattern Maker — full width */}
            <div style={{ marginTop: 8 }}>
              <AiPatternCard
                selected={traceMode === "ai_pattern"}
                onSelect={() => selectMode("ai_pattern")}
              />
            </div>
          </div>

          {/* AI Prompt Box */}
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
              <span>AI Copilot</span>
              <span style={{ fontSize: 9, background: "linear-gradient(90deg,#ec4899,#a855f7)", color: "#fff", padding: "1px 6px", borderRadius: 9999, fontWeight: 700 }}>optional</span>
            </div>
            <textarea
              rows={2}
              placeholder={'Describe your image or intent — e.g. "pen sketch of a face" or "make it dot style for CNC drilling"'}
              value={prompt}
              onChange={(e) => handlePromptChange(e.target.value)}
              style={{
                width: "100%", boxSizing: "border-box", resize: "none",
                background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.09)",
                borderRadius: 9, padding: "9px 11px", fontSize: 11, color: "var(--text-muted)",
                lineHeight: 1.5, outline: "none", fontFamily: "inherit",
              }}
            />
            {analyzing && file && (
              <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 5, display: "flex", gap: 5, alignItems: "center" }}>
                <Spinner size={9} /> Re-analysing with your description…
              </div>
            )}
          </div>

          <div style={{ height: 1, background: "rgba(255,255,255,0.06)", marginBottom: 18 }} />

          {/* Step 1 */}
          <StepSection step={1} title="Upload Image" done={!!file}>
            <div
              className={`dropzone${dragging ? " over" : ""}`}
              style={{ padding: file ? "12px 14px" : "28px 14px", display: "flex", flexDirection: "column", alignItems: "center", gap: 8, cursor: "pointer" }}
              onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}
              onClick={() => fileRef.current?.click()}
            >
              <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={onFileChange} />
              {file ? (
                <div style={{ display: "flex", alignItems: "center", gap: 10, width: "100%" }}>
                  {imageUrl && <img src={imageUrl} alt="" style={{ width: 48, height: 48, borderRadius: 8, objectFit: "cover", border: "1px solid rgba(236,72,153,0.3)", flexShrink: 0 }} />}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-primary)" }}>{file.name}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>{formatBytes(file.size)} · click to replace</div>
                  </div>
                  <span className="chip chip-green">Ready</span>
                </div>
              ) : (
                <>
                  <div style={{ fontSize: 26, opacity: 0.4, lineHeight: 1 }}>⊙</div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-muted)", textAlign: "center" }}>Drop image here or click to browse</div>
                  <div style={{ fontSize: 11, color: "var(--text-subtle)" }}>JPG · PNG · BMP · WebP — up to 20 MB</div>
                </>
              )}
            </div>
          </StepSection>

          <StepConnector />

          {/* Step 2 */}
          <StepSection step={2} title="Clean Image">
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <SliderRow
                label="Denoise" sub="pre-blur"
                hint={traceMode === "stroke"
                  ? "Critical for stroke tracing — 1–2 smooths texture without losing stroke edges."
                  : "Higher = smoother input. Reduces noise but softens fine detail."}
                min={0} max={5} step={0.5} value={blur} onChange={setBlur}
                format={(v) => v === 0 ? "Off" : v.toFixed(1)}
              />
              <Toggle
                label="Invert"
                sub={traceMode === "stroke"
                  ? "Enable for light/white strokes on dark background"
                  : "Enable for dark lines on white background"}
                value={invert} onChange={setInvert}
              />
            </div>
          </StepSection>

          <StepConnector />

          {/* Step 3 — mode-specific */}
          <StepSection step={3} title={step3Title}>
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {traceMode === "ai_pattern" ? (
                <>
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>Pattern Type</div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                      {([
                        { id: "contour_relief" as PatternType, label: "Contour Relief", desc: "Topographic layers" },
                        { id: "groove"         as PatternType, label: "Groove",         desc: "Brightness scan lines" },
                        { id: "perforation"    as PatternType, label: "Perforation",    desc: "Drill hole grid" },
                        { id: "facade"         as PatternType, label: "Facade Panels",  desc: "Geometric tiling" },
                      ]).map(({ id, label, desc }) => (
                        <button key={id} type="button" onClick={() => setApPatternType(id)}
                          style={{
                            padding: "8px 10px", borderRadius: 8, cursor: "pointer", textAlign: "left",
                            border: apPatternType === id ? "1px solid rgba(245,158,11,0.5)" : "1px solid rgba(255,255,255,0.08)",
                            background: apPatternType === id ? "rgba(245,158,11,0.1)" : "rgba(255,255,255,0.02)",
                            transition: "all 0.15s",
                          }}>
                          <div style={{ fontSize: 11, fontWeight: 700, color: apPatternType === id ? "#fbbf24" : "var(--text-muted)" }}>{label}</div>
                          <div style={{ fontSize: 9, color: "var(--text-subtle)", marginTop: 1 }}>{desc}</div>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>Style</div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5 }}>
                      {([
                        { id: "clean"     as PatternStyle, label: "Clean",    hint: "Binary threshold, sharp edges" },
                        { id: "organic"   as PatternStyle, label: "Organic",   hint: "Variable size, flowing forms" },
                        { id: "geometric" as PatternStyle, label: "Geometric", hint: "Structured, regular grid" },
                        { id: "facade"    as PatternStyle, label: "Facade",    hint: "Modulated by brightness" },
                      ]).map(({ id, label, hint }) => (
                        <button key={id} type="button" onClick={() => setApStyle(id)} title={hint}
                          style={{
                            padding: "5px 8px", borderRadius: 6, cursor: "pointer",
                            border: apStyle === id ? "1px solid rgba(245,158,11,0.45)" : "1px solid rgba(255,255,255,0.08)",
                            background: apStyle === id ? "rgba(245,158,11,0.1)" : "rgba(255,255,255,0.02)",
                            fontSize: 11, fontWeight: 600,
                            color: apStyle === id ? "#fbbf24" : "var(--text-subtle)",
                            transition: "all 0.15s",
                          }}>
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <SliderRow
                    label="Detail" sub="pattern density"
                    hint="Higher = more contour levels / denser lines / finer geometry."
                    min={1} max={10} step={0.5} value={apDetail} onChange={setApDetail}
                    format={(v) => v.toFixed(1)}
                  />
                  <SliderRow
                    label="Min Spacing" sub="px"
                    hint="Minimum gap between elements. Keeps parts manufacturable."
                    min={3} max={30} step={0.5} value={apMinSpacing} onChange={setApMinSpacing}
                    format={(v) => `${v.toFixed(1)} px`}
                  />

                  {apPatternType === "perforation" && (
                    <SliderRow
                      label="Min Hole Size" sub="px diameter"
                      hint="Smallest drillable hole. Prevents too-small holes."
                      min={1} max={20} step={0.5} value={apMinHoleSize} onChange={setApMinHoleSize}
                      format={(v) => `${v.toFixed(1)} px`}
                    />
                  )}

                  {apPatternType === "facade" && (
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>Panel Shape</div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5 }}>
                        {([
                          { id: "hexagon"  as PanelShape, label: "Hexagon"  },
                          { id: "triangle" as PanelShape, label: "Triangle" },
                          { id: "diamond"  as PanelShape, label: "Diamond"  },
                          { id: "wave"     as PanelShape, label: "Wave"     },
                        ]).map(({ id, label }) => (
                          <button key={id} type="button" onClick={() => setApPanelShape(id)}
                            style={{
                              padding: "5px 8px", borderRadius: 6, cursor: "pointer",
                              border: apPanelShape === id ? "1px solid rgba(245,158,11,0.45)" : "1px solid rgba(255,255,255,0.08)",
                              background: apPanelShape === id ? "rgba(245,158,11,0.1)" : "rgba(255,255,255,0.02)",
                              fontSize: 11, fontWeight: 600,
                              color: apPanelShape === id ? "#fbbf24" : "var(--text-subtle)",
                              transition: "all 0.15s",
                            }}>
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  <SliderRow
                    label="Max Elements" sub="limit"
                    hint="Cap on total pattern elements. Higher = more detail but slower export."
                    min={100} max={5000} step={100} value={apMaxElements} onChange={setApMaxElements}
                    format={(v) => v.toLocaleString()}
                  />
                </>
              ) : traceMode === "one_line" ? (
                <>
                  <SliderRow
                    label="Detail" sub="skeleton density"
                    hint="Higher = captures finer structure. Lower = bold simplified silhouette."
                    min={1} max={10} step={0.5} value={olDetail} onChange={setOlDetail}
                    format={(v) => v.toFixed(1)}
                  />
                  <SliderRow
                    label="Jump Penalty" sub="continuity"
                    hint="Higher = path prefers to continue forward rather than backtrack. Reduces cross-jumps."
                    min={0} max={1} step={0.05} value={olJumpPenalty} onChange={setOlJumpPenalty}
                    format={(v) => v.toFixed(2)}
                  />
                  <div className="glass-sm" style={{ padding: "10px 12px", borderRadius: 8 }}>
                    <div style={{ fontSize: 10, color: "var(--text-subtle)", lineHeight: 1.6 }}>
                      Creates a single continuous path that approximates the image, useful for plotter-style CNC engraving or artistic line work.
                    </div>
                  </div>
                </>
              ) : traceMode === "halftone" ? (
                <>
                  <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                      <span style={{ fontSize: 13, color: "var(--text-muted)" }}>Placement Mode</span>
                      <span style={{ fontSize: 10, color: "var(--text-subtle)" }}>{HALFTONE_PLACEMENT_LABELS[halftonePlacement]}</span>
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6 }}>
                      {(["organic_density", "hex_packing", "flow_field"] as HalftonePlacementMode[]).map((mode) => {
                        const active = halftonePlacement === mode;
                        return (
                          <button
                            key={mode}
                            type="button"
                            onClick={() => setHalftonePlacement(mode)}
                            style={{
                              minHeight: 34, borderRadius: 7, cursor: "pointer",
                              border: active ? "1px solid rgba(251,191,36,0.55)" : "1px solid rgba(255,255,255,0.08)",
                              background: active ? "rgba(245,158,11,0.14)" : "rgba(255,255,255,0.035)",
                              color: active ? "#fde68a" : "var(--text-muted)",
                              fontSize: 10, fontWeight: 700,
                            }}
                          >
                            {HALFTONE_PLACEMENT_LABELS[mode]}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <SliderRow
                    label="Density" sub="dots across"
                    hint="Overall candidate density across the longer image axis. Dark regions still pack more tightly than highlights."
                    min={10} max={150} step={5} value={halftoneDensity} onChange={setHalftoneDensity}
                    format={(v) => `${v}`}
                  />
                  <SliderRow
                    label="Organic randomness" sub="placement"
                    hint="Controls jitter and natural variation. Hex mode uses a lighter amount so rows stay manufacturable."
                    min={0} max={1} step={0.05} value={halftoneRandomness} onChange={setHalftoneRandomness}
                    format={(v) => v.toFixed(2)}
                  />
                  <SliderRow
                    label="Density sensitivity" sub="brightness"
                    hint="Higher values make dark areas pack much denser while bright areas open up faster."
                    min={0.35} max={3} step={0.05} value={halftoneDensitySensitivity} onChange={setHalftoneDensitySensitivity}
                    format={(v) => v.toFixed(2)}
                  />
                  <SliderRow
                    label="Min circle" sub="px radius"
                    hint="Smallest dot (for near-white areas). Keep low so highlights stay subtle."
                    min={0.5} max={5} step={0.5} value={halftoneMinR} onChange={setHalftoneMinR}
                    format={(v) => v.toFixed(1)}
                  />
                  <SliderRow
                    label="Max circle" sub="px radius"
                    hint="Largest dot (for darkest areas). Must be less than half the cell size."
                    min={1} max={20} step={0.5} value={halftoneMaxR} onChange={setHalftoneMaxR}
                    format={(v) => v.toFixed(1)}
                  />
                  <SliderRow
                    label="Contrast" sub="boost"
                    hint="Amplifies the brightness→dot-size mapping. 1.0 = linear, higher = punchier."
                    min={0.5} max={3} step={0.1} value={halftoneContrast} onChange={setHalftoneContrast}
                    format={(v) => v.toFixed(1)}
                  />
                </>
              ) : traceMode === "stroke" ? (
                <SliderRow
                  label="Stroke Sensitivity" sub="threshold"
                  hint="Higher = includes fainter, thinner strokes. Lower = only bold, strong strokes."
                  min={1} max={10} step={0.5} value={sensitivity} onChange={setSensitivity}
                  format={(v) => v.toFixed(1)}
                />
              ) : traceMode === "accurate" ? (
                <SliderRow
                  label="Sensitivity" sub="edge strength"
                  hint="Higher = detects finer, weaker edges. Lower = only strong outlines."
                  min={1} max={10} step={0.5} value={sensitivity} onChange={setSensitivity}
                  format={(v) => v.toFixed(1)}
                />
              ) : (
                <SliderRow
                  label="Contour Levels" sub="bands"
                  hint="Number of iso-contour bands. More levels = finer tonal detail, denser output."
                  min={1} max={10} step={0.5} value={sensitivity} onChange={setSensitivity}
                  format={(v) => `${Math.max(3, Math.min(15, Math.round(v * 1.3)))} bands`}
                />
              )}
              {traceMode !== "halftone" && traceMode !== "one_line" && (
                <SliderRow
                  label={traceMode === "stroke" ? "Min stroke length" : "Min path"}
                  sub="pixels"
                  hint={traceMode === "stroke"
                    ? "Filters out short skeleton fragments. Lower = keep small connecting curves."
                    : "Removes short noisy segments. Raise if result looks cluttered."}
                  min={5} max={80} step={5} value={minLength} onChange={setMinLength}
                />
              )}
            </div>
          </StepSection>

          <StepConnector />

          {/* Step 4 */}
          <StepSection step={4} title="Trace & Simplify" done={hasDoneResult}>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {traceMode !== "halftone" && traceMode !== "ai_pattern" && (
                <SliderRow
                  label="Simplify" sub="path precision"
                  hint={traceMode === "stroke"
                    ? "RDP tolerance on the final skeleton paths. Higher = fewer, smoother anchor points."
                    : traceMode === "one_line"
                    ? "RDP tolerance on the one-line path. Higher = fewer points, smoother curves."
                    : "Higher = fewer points, smoother paths. Lower = preserves fine detail."}
                  min={0} max={15} step={0.5}
                  value={traceMode === "one_line" ? olSimplify : simplify}
                  onChange={traceMode === "one_line" ? setOlSimplify : setSimplify}
                  format={(v) => v === 0 ? "None" : v.toFixed(1)}
                />
              )}
              <button
                className="btn-glow-pink"
                onClick={handleTrace}
                disabled={!file || appState === "tracing"}
                style={{ padding: "13px 20px", fontSize: 14, width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}
              >
                {appState === "tracing" ? <><Spinner />Processing…</> : traceButtonLabel}
              </button>

              {appState === "error" && (
                <div className="glass-sm" style={{ padding: "11px 14px", display: "flex", flexDirection: "column", gap: 8, borderColor: "rgba(248,113,113,0.25)" }}>
                  <div style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
                    <span style={{ fontSize: 14, flexShrink: 0, marginTop: 1 }}>⚠</span>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "#fca5a5" }}>Failed</div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2, wordBreak: "break-word" }}>{errorMsg}</div>
                    </div>
                  </div>
                  <button className="btn-ghost" onClick={handleTrace} disabled={!file}
                    style={{ padding: "6px 14px", fontSize: 12, width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                    ↺ Try again
                  </button>
                </div>
              )}

              {hasDoneResult && (
                <div style={{ fontSize: 11, color: "var(--text-subtle)", textAlign: "center" }}>
                  {halftoneResult
                    ? `${halftoneResult.n_circles.toLocaleString()} circles`
                    : oneLineResult
                      ? `${oneLineResult.n_points.toLocaleString()} pts · ${oneLineResult.n_jumps} jumps`
                      : aiPatternResult
                        ? `${aiPatternResult.n_elements.toLocaleString()} elements`
                        : result
                          ? `${result.n_contours} ${traceMode === "stroke" ? "stroke" : "contour"}${result.n_contours !== 1 ? "s" : ""} · ${result.total_points.toLocaleString()} points`
                          : ""}
                </div>
              )}
            </div>
          </StepSection>

        </div>

        {/* ── RIGHT PANEL ── */}
        <div className="glass" style={{ flex: 1, minWidth: 0, padding: "22px 24px", display: "flex", flexDirection: "column", gap: 20, minHeight: 560 }}>

          {/* ── Idle ── */}
          {appState !== "tracing" && !result && !halftoneResult && !oneLineResult && !aiPatternResult && (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20, padding: "32px 0" }}>
              <PhotoIllustration />

              {file ? (
                <>
                  <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text-primary)" }}>
                    {traceMode === "stroke" ? "✏ Stroke Trace ready"
                      : traceMode === "halftone" ? "◉ Halftone Dots ready"
                      : traceMode === "contour_art" ? "⊚ Contour Art ready"
                      : traceMode === "one_line" ? "∾ One-Line Drawing ready"
                      : traceMode === "ai_pattern" ? "◈ AI Pattern Maker ready"
                      : "⊙ Accurate Trace ready"}
                  </div>

                  <div style={{ width: "100%", maxWidth: 420 }}>
                    <AnalysisCard analysis={analysis} analyzing={analyzing} traceMode={traceMode} onApply={selectMode} />
                    <AiCopilotCard ai={aiAnalysis} aiLoading={aiLoading} traceMode={traceMode} onApply={selectMode} />
                  </div>

                  <div style={{ fontSize: 13, color: "var(--text-muted)", textAlign: "center", maxWidth: 360, lineHeight: 1.65 }}>
                    {traceMode === "stroke"
                      ? "Adjust Sensitivity to capture all strokes, then click Trace High-Fidelity."
                      : traceMode === "halftone"
                      ? "Adjust Density and circle sizes, then click Generate Dots."
                      : traceMode === "contour_art"
                      ? "Adjust Contour Levels for tonal density, then click Trace Contour Art."
                      : traceMode === "one_line"
                      ? "Adjust Detail and Jump Penalty, then click Draw One Line."
                      : traceMode === "ai_pattern"
                      ? "Choose a pattern type and style, then click Generate Pattern."
                      : "Adjust Edge Sensitivity for the right level of detail, then click Trace Accurately."}
                  </div>

                  <div className="glass-sm" style={{ padding: "10px 16px", width: "100%", maxWidth: 380 }}>
                    <div style={{ fontSize: 10, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 8 }}>
                      Tips for {traceMode === "stroke" ? "Stroke Trace" : traceMode === "halftone" ? "Halftone Dots" : traceMode === "contour_art" ? "Contour Art" : traceMode === "one_line" ? "One-Line Drawing" : traceMode === "ai_pattern" ? "AI Pattern Maker" : "Accurate Trace"}
                    </div>
                    {MODE_TIPS[traceMode].map((tip, i) => (
                      <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 5 }}>
                        <div style={{ width: 3, height: 3, borderRadius: "50%", flexShrink: 0, marginTop: 5,
                          background: traceMode === "stroke" ? "#38bdf8" : traceMode === "halftone" || traceMode === "ai_pattern" ? "#fbbf24" : traceMode === "one_line" ? "#22d3ee" : "#ec4899" }} />
                        <span style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>{tip}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text-primary)" }}>Upload an image to get started</div>
                  <div style={{ fontSize: 13, color: "var(--text-muted)", textAlign: "center", maxWidth: 340, lineHeight: 1.7 }}>
                    Choose a mode, then upload any photo, scan, or line art. The tool will analyse the image and suggest the best mode automatically.
                  </div>
                  <div className="glass-sm" style={{ padding: "12px 16px", width: "100%", maxWidth: 400 }}>
                    <div style={{ display: "flex", gap: 10, flexDirection: "column" }}>
                      {([
                        { icon: "⊙", label: "Accurate Trace",   color: "#a855f7", desc: "Canny edges. Best for logos, silhouettes, high-contrast images." },
                        { icon: "⊚", label: "Contour Art",      color: "#ec4899", desc: "Topographic iso-contour bands. Best for portraits and photos." },
                        { icon: "✏", label: "Stroke Trace",     color: "#38bdf8", desc: "Skeleton centerlines. Best for sketches, pen drawings, line art." },
                        { icon: "◉", label: "Halftone / Dot",   color: "#fbbf24", desc: "Dot grid from brightness. Best for CNC drilling, stipple art." },
                        { icon: "∾", label: "One-Line Drawing", color: "#22d3ee", desc: "Single continuous path. Best for plotter engraving and artistic line work." },
                        { icon: "◈", label: "AI Pattern Maker", color: "#fbbf24", desc: "Photo → decorative pattern. Contour relief, grooves, perforations, or geometric tile panels." },
                      ] as const).map(({ icon, label, color, desc }) => (
                        <div key={label} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                          <div style={{ fontSize: 14, color, flexShrink: 0, paddingTop: 1 }}>{icon}</div>
                          <div>
                            <div style={{ fontSize: 11, fontWeight: 700, color }}>{label}</div>
                            <div style={{ fontSize: 11, color: "var(--text-subtle)", lineHeight: 1.4, marginTop: 2 }}>{desc}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── Tracing ── */}
          {appState === "tracing" && <ScanAnimation imageUrl={imageUrl} mode={traceMode} />}

          {/* ── Results ── */}
          {hasDoneResult && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{
                  width: 22, height: 22, borderRadius: "50%", flexShrink: 0,
                  background: traceMode === "halftone" || traceMode === "ai_pattern"
                    ? "linear-gradient(135deg, rgba(245,158,11,0.55), rgba(251,191,36,0.55))"
                    : "linear-gradient(135deg, rgba(236,72,153,0.55), rgba(168,85,247,0.55))",
                  border: traceMode === "halftone" || traceMode === "ai_pattern" ? "1px solid rgba(245,158,11,0.45)" : "1px solid rgba(236,72,153,0.45)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 10, fontWeight: 700,
                  color: traceMode === "halftone" || traceMode === "ai_pattern" ? "#fde68a" : "#fbcfe8",
                }}>5</div>
                <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.09em" }}>
                  Preview &amp; Export
                </div>
                <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
                  <span className={`chip ${traceMode === "stroke" ? "chip-sky" : traceMode === "halftone" || traceMode === "ai_pattern" ? "chip-amber" : traceMode === "one_line" ? "chip-sky" : traceMode === "contour_art" ? "chip-red" : "chip-violet"}`}
                    style={traceMode === "halftone" || traceMode === "ai_pattern" ? { background: "rgba(245,158,11,0.18)", color: "#fbbf24", borderColor: "rgba(245,158,11,0.3)" }
                      : traceMode === "one_line" ? { background: "rgba(34,211,238,0.12)", color: "#22d3ee", borderColor: "rgba(34,211,238,0.3)" } : {}}>
                    {modeChipLabel}
                  </span>
                  <span className="chip chip-green">✓ Done</span>
                </div>
              </div>

              {/* ── AI Pattern result ── */}
              {aiPatternResult && (
                <>
                  <div style={{ display: "flex", gap: 10 }}>
                    <Stat label="Elements" value={aiPatternResult.n_elements.toLocaleString()} mode="ai_pattern" />
                    <Stat label="Type"     value={aiPatternResult.pattern_type.replace(/_/g, " ")} mode="ai_pattern" />
                    <Stat label="Image"    value={`${aiPatternResult.image_width}×${aiPatternResult.image_height}`} mode="ai_pattern" />
                  </div>

                  <div className="glass-sm" style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
                      Pattern analysis
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                      {[
                        { label: "Edge density",   value: `${(aiPatternResult.analysis.edge_density * 100).toFixed(1)}%` },
                        { label: "Contrast",       value: aiPatternResult.analysis.contrast.toFixed(3) },
                        { label: "Dominant angle", value: `${aiPatternResult.analysis.dominant_angle_deg.toFixed(1)}°` },
                        ...Object.entries(aiPatternResult.n_by_layer).map(([layer, count]) => ({
                          label: layer.replace("PATTERN_", "").replace(/_/g, " ").toLowerCase(),
                          value: (count as number).toLocaleString(),
                        })),
                      ].map(({ label, value }) => (
                        <div key={label} style={{ background: "rgba(245,158,11,0.06)", borderRadius: 7, padding: "7px 10px", border: "1px solid rgba(245,158,11,0.15)" }}>
                          <div style={{ fontSize: 9, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
                          <div style={{ fontSize: 13, fontWeight: 700, color: "#fbbf24", marginTop: 2 }}>{value}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* CNC Readiness panel */}
                  {(() => {
                    const fab = aiPatternResult.fabrication;
                    const worst = fab.checks.reduce<"ok"|"warning"|"error">((acc, c) => {
                      if (c.severity === "error")   return "error";
                      if (c.severity === "warning" && acc !== "error") return "warning";
                      return acc;
                    }, "ok");
                    const statusColor   = worst === "error" ? "#f87171" : worst === "warning" ? "#fb923c" : "#4ade80";
                    const statusBg      = worst === "error" ? "rgba(239,68,68,0.12)" : worst === "warning" ? "rgba(251,146,60,0.12)" : "rgba(74,222,128,0.1)";
                    const statusBorder  = worst === "error" ? "rgba(239,68,68,0.3)"  : worst === "warning" ? "rgba(251,146,60,0.3)"  : "rgba(74,222,128,0.2)";
                    const statusLabel   = worst === "error" ? "Issues found" : worst === "warning" ? "Warnings" : "CNC-ready";
                    const severityIcon  = (s: string) => s === "error" ? "✗" : s === "warning" ? "⚠" : "✓";
                    const severityClr   = (s: string) => s === "error" ? "#f87171" : s === "warning" ? "#fb923c" : "#4ade80";
                    return (
                      <div className="glass-sm" style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 8, borderColor: statusBorder }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                          <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
                            CNC readiness
                          </div>
                          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                            <span style={{ fontSize: 10, fontWeight: 700, color: statusColor, background: statusBg, border: `1px solid ${statusBorder}`, borderRadius: 5, padding: "2px 7px" }}>
                              {statusLabel}
                            </span>
                          </div>
                        </div>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                          <div style={{ background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.18)", borderRadius: 7, padding: "5px 10px", flex: 1, minWidth: 130 }}>
                            <div style={{ fontSize: 9, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Operation</div>
                            <div style={{ fontSize: 12, fontWeight: 700, color: "#fbbf24", marginTop: 2 }}>{fab.operation_type}</div>
                            <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: 1 }}>{fab.operation_label}</div>
                          </div>
                          <div style={{ background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.18)", borderRadius: 7, padding: "5px 10px", flex: 1, minWidth: 80 }}>
                            <div style={{ fontSize: 9, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Est. time</div>
                            <div style={{ fontSize: 12, fontWeight: 700, color: "#fbbf24", marginTop: 2 }}>
                              {fab.estimated_time_min >= 60
                                ? `${Math.floor(fab.estimated_time_min / 60)}h ${Math.round(fab.estimated_time_min % 60)}m`
                                : `${fab.estimated_time_min} min`}
                            </div>
                          </div>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          {fab.checks.map((chk, i) => (
                            <div key={i} style={{ display: "flex", gap: 7, alignItems: "flex-start" }}>
                              <span style={{ fontSize: 12, color: severityClr(chk.severity), flexShrink: 0, lineHeight: 1.4 }}>{severityIcon(chk.severity)}</span>
                              <span style={{ fontSize: 11, color: chk.severity === "ok" ? "var(--text-muted)" : severityClr(chk.severity), lineHeight: 1.4 }}>{chk.message}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })()}

                  {aiPatternResult.warnings.length > 0 && (
                    <div className="glass-sm" style={{ padding: "9px 12px", borderColor: "rgba(251,146,60,0.3)" }}>
                      {aiPatternResult.warnings.map((w, i) => (
                        <div key={i} style={{ fontSize: 11, color: "#fb923c", display: "flex", gap: 6 }}>
                          <span>⚠</span><span>{w}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>Preview</span>
                    <div className="seg-control" style={{ padding: 2 }}>
                      {[
                        { key: "original", label: "Original" },
                        { key: "analysis", label: "Analysis" },
                        { key: "pattern",  label: "Pattern"  },
                      ].map(({ key, label }) => (
                        <button key={key} className={`seg-btn${apPreviewMode === key ? " active" : ""}`}
                          onClick={() => setApPreviewMode(key as typeof apPreviewMode)} type="button"
                          style={{ padding: "4px 10px", fontSize: 11 }}>
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div style={{ borderRadius: 12, overflow: "hidden", background: "#06060f" }}>
                    {apPreviewMode === "original" && imageUrl && (
                      <img src={imageUrl} alt="original" style={{ width: "100%", height: "auto", display: "block" }} />
                    )}
                    {apPreviewMode === "analysis" && (
                      <img src={aiPatternResult.analysis.brightness_map} alt="brightness map" style={{ width: "100%", height: "auto", display: "block", filter: "sepia(0.6) hue-rotate(10deg)" }} />
                    )}
                    {apPreviewMode === "pattern" && (
                      <img src={aiPatternResult.preview_image} alt="pattern" style={{ width: "100%", height: "auto", display: "block" }} />
                    )}
                  </div>
                </>
              )}

              {/* ── Halftone result stats ── */}
              {halftoneResult && (
                <>
                  <div style={{ display: "flex", gap: 10 }}>
                    <Stat label="Circles"  value={halftoneResult.n_circles.toLocaleString()} mode="halftone" />
                    <Stat label="Image"    value={`${halftoneResult.image_width}×${halftoneResult.image_height}`} mode="halftone" />
                    <Stat label="Open Area" value={`${(halftoneResult.open_area_pct ?? 0).toFixed(1)}%`} mode="halftone" />
                  </div>
                  <div style={{ display: "flex", gap: 10 }}>
                    <Stat label="Strength" value={`${halftoneResult.strength_label ?? "n/a"} ${halftoneResult.strength_score ?? 0}%`} mode="halftone" />
                    <Stat label="Bridge" value={`${(halftoneResult.min_bridge_px ?? 0).toFixed(1)} px`} mode="halftone" />
                    <Stat label="Mode" value={HALFTONE_PLACEMENT_LABELS[(halftoneResult.placement_mode as HalftonePlacementMode) || halftonePlacement] ?? HALFTONE_PLACEMENT_LABELS[halftonePlacement]} mode="halftone" />
                  </div>
                  <div className="glass-sm" style={{ padding: "9px 12px", borderRadius: 8 }}>
                    <Toggle
                      label="Density heatmap"
                      sub="overlay brightness-driven placement pressure"
                      value={showHalftoneHeatmap}
                      onChange={setShowHalftoneHeatmap}
                    />
                  </div>
                  <div style={{ borderRadius: 12, overflow: "hidden", background: "#06060f" }}>
                    {imageUrl && (
                      <div style={{ position: "relative" }}>
                        <img src={imageUrl} alt="original" style={{ width: "100%", height: "auto", display: "block", opacity: 0.12, filter: "grayscale(1)" }} />
                        <div style={{ position: "absolute", inset: 0 }}>
                          <HalftoneSVG halftoneResult={halftoneResult} showHeatmap={showHalftoneHeatmap} />
                        </div>
                      </div>
                    )}
                    {!imageUrl && <HalftoneSVG halftoneResult={halftoneResult} showHeatmap={showHalftoneHeatmap} />}
                  </div>
                </>
              )}

              {/* ── One-line result ── */}
              {oneLineResult && (
                <>
                  <div style={{ display: "flex", gap: 10 }}>
                    <Stat label="Points"  value={oneLineResult.n_points.toLocaleString()} mode="one_line" />
                    <Stat label="Jumps"   value={String(oneLineResult.n_jumps)} mode="one_line" />
                    <Stat label="Image"   value={`${oneLineResult.image_width}×${oneLineResult.image_height}`} mode="one_line" />
                  </div>

                  <div className="glass-sm" style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
                      One-line path metrics
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6 }}>
                      {[
                        { label: "Total length",  value: `${oneLineResult.total_length_px.toLocaleString()} px` },
                        { label: "Jump count",    value: `${oneLineResult.n_jumps} connector${oneLineResult.n_jumps !== 1 ? "s" : ""}` },
                        { label: "Longest jump",  value: `${oneLineResult.longest_jump.toFixed(0)} px` },
                      ].map(({ label, value }) => (
                        <div key={label} style={{ background: "rgba(34,211,238,0.06)", borderRadius: 7, padding: "7px 10px", border: "1px solid rgba(34,211,238,0.15)" }}>
                          <div style={{ fontSize: 9, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
                          <div style={{ fontSize: 13, fontWeight: 700, color: "#22d3ee", marginTop: 2 }}>{value}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>Preview stages</span>
                    <div className="seg-control" style={{ padding: 2 }}>
                      {[
                        { key: "original", label: "Original" },
                        { key: "enhanced", label: "Enhanced" },
                        { key: "skeleton", label: "Skeleton" },
                        { key: "oneline",  label: "One Line" },
                      ].map(({ key, label }) => (
                        <button key={key} className={`seg-btn${olPreviewMode === key ? " active" : ""}`}
                          onClick={() => setOlPreviewMode(key as typeof olPreviewMode)} type="button"
                          style={{ padding: "4px 10px", fontSize: 11 }}>
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {olPreviewMode === "oneline" && (
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>Show connection jumps</span>
                      <button
                        type="button"
                        onClick={() => setShowJumps(v => !v)}
                        style={{
                          padding: "3px 12px", fontSize: 11, borderRadius: 6, cursor: "pointer",
                          border: showJumps ? "1px solid rgba(251,146,60,0.55)" : "1px solid rgba(255,255,255,0.12)",
                          background: showJumps ? "rgba(251,146,60,0.15)" : "rgba(255,255,255,0.04)",
                          color: showJumps ? "#fb923c" : "var(--text-subtle)",
                          fontWeight: 600, transition: "all 0.15s",
                        }}
                      >
                        {showJumps ? "On" : "Off"}
                      </button>
                    </div>
                  )}

                  {olPreviewMode === "oneline" && (
                    <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: -10 }}>
                      Animated one-line path — the complete image redrawn as a single continuous stroke.
                    </div>
                  )}
                  {olPreviewMode === "skeleton" && (
                    <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: -10 }}>
                      Skeletonized centerlines — 1-pixel wide spines from which the path is built.
                    </div>
                  )}

                  <div style={{ borderRadius: 12, overflow: "hidden", background: "#06060f" }}>
                    {olPreviewMode === "original" && imageUrl && (
                      <img src={imageUrl} alt="original" style={{ width: "100%", height: "auto", display: "block" }} />
                    )}
                    {olPreviewMode === "enhanced" && (
                      <img src={oneLineResult.cleaned_image} alt="enhanced" style={{ width: "100%", height: "auto", display: "block" }} />
                    )}
                    {olPreviewMode === "skeleton" && (
                      <img src={oneLineResult.skeleton_image} alt="skeleton" style={{ width: "100%", height: "auto", display: "block" }} />
                    )}
                    {olPreviewMode === "oneline" && <OneLineSVG result={oneLineResult} showJumps={showJumps} />}
                  </div>
                </>
              )}

              {/* ── Trace result stats + tabs ── */}
              {result && (
                <>
                  <div style={{ display: "flex", gap: 10 }}>
                    <Stat label={traceMode === "stroke" ? "Strokes" : "Contours"} value={String(result.n_contours)} mode={traceMode} />
                    <Stat label="Points" value={result.total_points.toLocaleString()} mode={traceMode} />
                    <Stat label="Image"  value={`${result.image_width}×${result.image_height}`} mode={traceMode} />
                  </div>

                  {traceMode === "stroke" && result.coverage_pct != null && (
                    <div className="glass-sm" style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
                        Stroke reconstruction metrics
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6 }}>
                        {[
                          { label: "Coverage",     value: `${result.coverage_pct}%` },
                          { label: "Avg length",   value: `${result.avg_stroke_len} px` },
                          { label: "Skeleton px",  value: result.total_skel_px?.toLocaleString() ?? "—" },
                          { label: "Raw segments", value: String(result.n_raw_segments ?? "—") },
                          { label: "Crossings",    value: String(result.n_crossings ?? "—") },
                          { label: "Merges",       value: String(result.n_merges ?? "—") },
                          { label: "Bridges",      value: String(result.n_bridges ?? "—") },
                          { label: "Discarded",    value: String(result.n_discarded ?? "—") },
                        ].map(({ label, value }) => (
                          <div key={label} style={{ background: "rgba(56,189,248,0.06)", borderRadius: 7, padding: "7px 10px", border: "1px solid rgba(56,189,248,0.15)" }}>
                            <div style={{ fontSize: 9, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
                            <div style={{ fontSize: 14, fontWeight: 700, color: "#38bdf8", marginTop: 2 }}>{value}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>Inspect each processing stage</span>
                    <div className="seg-control" style={{ padding: 2, flexWrap: "wrap" }}>
                      {(traceMode === "stroke"
                        ? [
                            { key: "original", label: "Original" },
                            { key: "cleaned",  label: "Enhanced" },
                            { key: "binary",   label: "Binary"   },
                            { key: "edges",    label: "Skeleton" },
                            { key: "segments", label: "Segments" },
                            { key: "merged",   label: "Merged"   },
                            { key: "vector",   label: "Vector"   },
                          ]
                        : [
                            { key: "original", label: "Original"    },
                            { key: "cleaned",  label: "Cleaned"     },
                            { key: "edges",    label: edgesTabLabel },
                            { key: "vector",   label: "Vector"      },
                          ]
                      ).map(({ key, label }) => (
                        <button key={key} className={`seg-btn${previewMode === key ? " active" : ""}`}
                          onClick={() => setPreviewMode(key as typeof previewMode)} type="button"
                          style={{ padding: "4px 10px", fontSize: 11 }}>
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {previewMode === "cleaned" && (
                    <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: -10 }}>
                      {traceMode === "stroke" ? "CLAHE contrast-enhanced view — faint strokes amplified before binarization."
                        : "Grayscale + blur applied. Adjust Denoise in Step 2 if you see too much noise or lost detail."}
                    </div>
                  )}
                  {previewMode === "binary" && (
                    <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: -10 }}>
                      Sauvola ∪ Otsu binarization — local adaptive threshold captures faint strokes that global threshold misses.
                    </div>
                  )}
                  {previewMode === "edges" && <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: -10 }}>{edgesTabHint}</div>}
                  {previewMode === "segments" && (
                    <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: -10 }}>
                      Raw pixel-graph segments before merging — each color is a distinct segment.
                    </div>
                  )}
                  {previewMode === "merged" && (
                    <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: -10 }}>
                      After junction merging and gap bridging — collinear segments fused into longer continuous strokes.
                    </div>
                  )}
                  {previewMode === "vector" && (
                    <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: -10 }}>
                      {traceMode === "stroke" ? "Final stroke paths — brighter = longer, more important strokes."
                        : "Final simplified vector paths — this is what will be exported as DXF."}
                    </div>
                  )}

                  <div style={{ borderRadius: 12, overflow: "hidden", background: "#06060f" }}>
                    {previewMode === "original" && imageUrl && <img src={imageUrl} alt="original" style={{ width: "100%", height: "auto", display: "block" }} />}
                    {previewMode === "cleaned" && <img src={result.cleaned_image} alt="cleaned" style={{ width: "100%", height: "auto", display: "block" }} />}
                    {previewMode === "binary" && result.binary && <img src={result.binary} alt="binary" style={{ width: "100%", height: "auto", display: "block" }} />}
                    {previewMode === "edges" && <img src={result.edges_image} alt={edgesTabLabel.toLowerCase()} style={{ width: "100%", height: "auto", display: "block" }} />}
                    {previewMode === "segments" && result.segments && <img src={result.segments} alt="segments" style={{ width: "100%", height: "auto", display: "block" }} />}
                    {previewMode === "merged" && result.merged && <img src={result.merged} alt="merged" style={{ width: "100%", height: "auto", display: "block" }} />}
                    {previewMode === "vector" && <ContourSVG result={result} mode={traceMode} />}
                  </div>
                </>
              )}

              <div className="glass-sm" style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
                  DXF Export settings
                </div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div>
                    <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
                      {traceMode === "halftone" ? "Scale — mm per pixel (circle radii scaled)" : "Scale — mm per pixel"}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: 2 }}>Output: {dxfW} × {dxfH} mm</div>
                  </div>
                  <input
                    type="number" min={0.01} max={100} step={0.1} value={scale}
                    onChange={(e) => setScale(e.target.value)}
                    className="input-dark"
                    style={{ width: 76, padding: "6px 10px", fontSize: 14, textAlign: "right" }}
                  />
                </div>
              </div>

              <button
                className={exportSuccess ? "btn-success" : "btn-glow-pink"}
                onClick={handleExport} disabled={exportBusy}
                style={{ padding: "13px 20px", fontSize: 14, width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}
              >
                {exportSuccess ? "✓ Downloaded" : exportBusy ? <><Spinner />Exporting…</> : "⬇  Download DXF"}
              </button>

              <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 16 }}>
                <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>
                  Adjust settings and run again for a different result.
                </span>
                <button className="btn-ghost" onClick={resetToIdle} style={{ padding: "4px 11px", fontSize: 11, flexShrink: 0 }}>
                  ↺ New image
                </button>
              </div>
            </>
          )}

        </div>

      </div>
    </div>
  );
}
