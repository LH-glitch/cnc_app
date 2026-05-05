"use client";

import { useRef, useState, useCallback, useEffect, DragEvent, ChangeEvent } from "react";
import {
  tracePhoto, analyzePhoto, exportPhotoAsDXF,
  traceHalftone, exportHalftoneDXF,
  aiRecommend,
  TraceResult, TraceParams, AnalyzeResult, TraceMode,
  HalftoneParams, HalftoneResult, AiRecommendResult,
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

// ── Halftone SVG preview ──────────────────────────────────────────────────────

function HalftoneSVG({ halftoneResult }: { halftoneResult: HalftoneResult }) {
  const { circles, image_width: w, image_height: h } = halftoneResult;
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      style={{ width: "100%", height: "auto", borderRadius: 10, display: "block" }}
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect width={w} height={h} fill="#06060f" />
      {circles.map(([row, col, radius], i) => (
        <circle key={i} cx={col} cy={row} r={Math.max(0.5, radius)} fill="#fbbf24" opacity={0.85} />
      ))}
    </svg>
  );
}

// ── Scan animation ────────────────────────────────────────────────────────────

function ScanAnimation({ imageUrl, mode }: { imageUrl: string | null; mode: TraceMode }) {
  const isStroke    = mode === "stroke";
  const isArt       = mode === "contour_art";
  const isHalftone  = mode === "halftone";
  const scanColor   = isStroke ? "14,165,233" : isHalftone ? "245,158,11" : "236,72,153";
  const nodeColorA  = isStroke ? "#38bdf8" : isHalftone ? "#fbbf24" : "#ec4899";
  const nodeColorB  = isStroke ? "#0ea5e9" : isHalftone ? "#f59e0b" : "#a855f7";

  const statusText = isStroke ? "Reconstructing stroke paths…"
    : isHalftone ? "Building halftone dot grid…"
    : isArt ? "Mapping contour levels…"
    : "Detecting edges…";
  const subText = isStroke ? "bilateral denoise · Sauvola binarize · crossing disambiguation · global assembly"
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
          <span style={{ fontSize: 12, color: isStroke ? "rgba(186,230,253,0.95)" : "rgba(249,168,212,0.95)", letterSpacing: "0.05em" }}>
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
    : mode === "halftone"
    ? "linear-gradient(135deg, #f59e0b, #fbbf24)"
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
    setResult(null); setHalftoneResult(null); setErrorMsg(""); setAppState("idle");
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
    if (result || halftoneResult) { setResult(null); setHalftoneResult(null); setAppState("idle"); }
  }

  // ── Trace ──────────────────────────────────────────────────────────────────
  async function handleTrace() {
    if (!file) return;
    setAppState("tracing"); setResult(null); setHalftoneResult(null); setErrorMsg("");

    if (traceMode === "halftone") {
      const params: HalftoneParams = {
        density: halftoneDensity, min_radius: halftoneMinR, max_radius: halftoneMaxR,
        contrast: halftoneContrast, invert,
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
      if (traceMode === "halftone" && halftoneResult) {
        await exportHalftoneDXF(
          halftoneResult.circles, halftoneResult.image_width, halftoneResult.image_height,
          parseFloat(scale) || 1.0, "halftone.dxf",
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

  function resetToIdle() { setResult(null); setHalftoneResult(null); setAppState("idle"); setExportSuccess(false); }

  const activeImgW = result ? result.image_width : halftoneResult ? halftoneResult.image_width : null;
  const activeImgH = result ? result.image_height : halftoneResult ? halftoneResult.image_height : null;
  const dxfW = activeImgW ? (activeImgW * (parseFloat(scale) || 1)).toFixed(0) : "—";
  const dxfH = activeImgH ? (activeImgH * (parseFloat(scale) || 1)).toFixed(0) : "—";

  // Dynamic labels
  const step3Title = traceMode === "accurate" ? "Detect Edges"
    : traceMode === "contour_art" ? "Configure Levels"
    : traceMode === "halftone" ? "Dot Grid Settings"
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
    : "⊙  Trace Accurately";

  const modeChipLabel = traceMode === "stroke" ? "✏ Hi-Fi Stroke"
    : traceMode === "halftone" ? "◉ Halftone"
    : traceMode === "contour_art" ? "⊚ Contour Art" : "⊙ Accurate";

  const pageSubtitle = traceMode === "stroke"
    ? "Skeleton centerlines · junction merge · DXF export"
    : traceMode === "halftone"
    ? "Dot grid · brightness mapping · DXF circles export"
    : traceMode === "contour_art"
    ? "Iso-contour topographic art · RDP simplification · DXF export"
    : "Canny edge detection · RDP simplification · DXF export";

  const hasDoneResult = appState === "done" && (result !== null || halftoneResult !== null);

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
              {traceMode === "halftone" ? (
                <>
                  <SliderRow
                    label="Density" sub="dots across"
                    hint="Number of dot grid cells across the longer image axis. Higher = finer dot pattern."
                    min={10} max={150} step={5} value={halftoneDensity} onChange={setHalftoneDensity}
                    format={(v) => `${v}`}
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
              {traceMode !== "halftone" && (
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
              {traceMode !== "halftone" && (
                <SliderRow
                  label="Simplify" sub="path precision"
                  hint={traceMode === "stroke"
                    ? "RDP tolerance on the final skeleton paths. Higher = fewer, smoother anchor points."
                    : "Higher = fewer points, smoother paths. Lower = preserves fine detail."}
                  min={0} max={15} step={0.5} value={simplify} onChange={setSimplify}
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
          {appState !== "tracing" && !result && !halftoneResult && (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20, padding: "32px 0" }}>
              <PhotoIllustration />

              {file ? (
                <>
                  <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text-primary)" }}>
                    {traceMode === "stroke" ? "✏ Stroke Trace ready"
                      : traceMode === "halftone" ? "◉ Halftone Dots ready"
                      : traceMode === "contour_art" ? "⊚ Contour Art ready"
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
                      : "Adjust Edge Sensitivity for the right level of detail, then click Trace Accurately."}
                  </div>

                  <div className="glass-sm" style={{ padding: "10px 16px", width: "100%", maxWidth: 380 }}>
                    <div style={{ fontSize: 10, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 8 }}>
                      Tips for {traceMode === "stroke" ? "Stroke Trace" : traceMode === "halftone" ? "Halftone Dots" : traceMode === "contour_art" ? "Contour Art" : "Accurate Trace"}
                    </div>
                    {MODE_TIPS[traceMode].map((tip, i) => (
                      <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 5 }}>
                        <div style={{ width: 3, height: 3, borderRadius: "50%", flexShrink: 0, marginTop: 5,
                          background: traceMode === "stroke" ? "#38bdf8" : traceMode === "halftone" ? "#fbbf24" : "#ec4899" }} />
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
                  background: traceMode === "halftone"
                    ? "linear-gradient(135deg, rgba(245,158,11,0.55), rgba(251,191,36,0.55))"
                    : "linear-gradient(135deg, rgba(236,72,153,0.55), rgba(168,85,247,0.55))",
                  border: traceMode === "halftone" ? "1px solid rgba(245,158,11,0.45)" : "1px solid rgba(236,72,153,0.45)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 10, fontWeight: 700,
                  color: traceMode === "halftone" ? "#fde68a" : "#fbcfe8",
                }}>5</div>
                <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.09em" }}>
                  Preview &amp; Export
                </div>
                <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
                  <span className={`chip ${traceMode === "stroke" ? "chip-sky" : traceMode === "halftone" ? "chip-amber" : traceMode === "contour_art" ? "chip-red" : "chip-violet"}`}
                    style={traceMode === "halftone" ? { background: "rgba(245,158,11,0.18)", color: "#fbbf24", borderColor: "rgba(245,158,11,0.3)" } : {}}>
                    {modeChipLabel}
                  </span>
                  <span className="chip chip-green">✓ Done</span>
                </div>
              </div>

              {/* ── Halftone result stats ── */}
              {halftoneResult && (
                <>
                  <div style={{ display: "flex", gap: 10 }}>
                    <Stat label="Circles"  value={halftoneResult.n_circles.toLocaleString()} mode="halftone" />
                    <Stat label="Image"    value={`${halftoneResult.image_width}×${halftoneResult.image_height}`} mode="halftone" />
                    <Stat label="Density"  value={`${halftoneDensity}`} mode="halftone" />
                  </div>
                  <div style={{ borderRadius: 12, overflow: "hidden", background: "#06060f" }}>
                    {imageUrl && (
                      <div style={{ position: "relative" }}>
                        <img src={imageUrl} alt="original" style={{ width: "100%", height: "auto", display: "block", opacity: 0.12, filter: "grayscale(1)" }} />
                        <div style={{ position: "absolute", inset: 0 }}>
                          <HalftoneSVG halftoneResult={halftoneResult} />
                        </div>
                      </div>
                    )}
                    {!imageUrl && <HalftoneSVG halftoneResult={halftoneResult} />}
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
